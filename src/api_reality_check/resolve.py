"""Plan queries and map probe results to findings (DESIGN §4.5, §14 A1/A3/A5).

Invariant: MISSING only on evidence that cannot lie. Every downgrade rule below moves a verdict
toward UNKNOWN; nothing here can turn a probe "ok/unknown/suspect" into MISSING.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

from .locality import Locality, pythonpath_has_module
from .models import FileAnalysis, Finding, Reference

MAX_MODULES = 500
MAX_QUERIES = 5000
MAX_KWARGS = 50

_RANK = {"UNKNOWN": 0, "SUSPECT": 1, "MISSING": 2}


@dataclass
class Policy:
    # Hook running on its own fallback interpreter: "not installed" may just be the wrong env.
    downgrade_not_installed: bool = False
    pythonpath: list[str] = field(default_factory=list)


@dataclass
class Plan:
    queries: list[dict]
    # (file index, reference index) -> query id, or an UNKNOWN reason decided without probing
    assignment: dict[tuple[int, int], int | str]
    # Per file, the top-level modules it imports (sent once per request; a query names its file by index).
    cross_modules: list[list[str]] = field(default_factory=list)
    capped: int = 0          # references not checked because of MAX_MODULES / MAX_QUERIES
    timed_out: int = 0       # references not checked because the deadline passed while planning


def _query_key(ref: Reference) -> tuple:
    return (ref.module, ref.path, ref.instance_attr, ref.is_call,
            tuple(sorted({k.name for k in ref.kwargs[:MAX_KWARGS]})))


def plan(analyses: list[FileAnalysis], deadline: float | None = None) -> Plan:
    """The module cap is applied before the locality check, so a file with thousands of distinct imports
    costs at most MAX_MODULES locality checks (F4). Past `deadline` the remaining references are UNKNOWN
    `timeout`."""
    queries: list[dict] = []
    by_key: dict[tuple, int] = {}
    tops: set[str] = set()           # every top-level module looked at (local or probed), for the cap
    assignment: dict[tuple[int, int], int | str] = {}
    local_cache: dict[tuple[str, str], bool] = {}
    loc = Locality()
    pl = Plan(queries, assignment, [list(fa.imported_tops[:MAX_MODULES]) for fa in analyses])
    for fi, fa in enumerate(analyses):
        for ri, ref in enumerate(fa.references):
            if ref.skip_reason:
                assignment[(fi, ri)] = ref.skip_reason
                continue
            if deadline is not None and time.monotonic() >= deadline:
                assignment[(fi, ri)] = "timeout"
                pl.timed_out += 1
                continue
            top = ref.module.split(".")[0]
            if top not in tops and len(tops) >= MAX_MODULES:
                assignment[(fi, ri)] = "cap_exceeded"
                pl.capped += 1
                continue
            tops.add(top)
            ck = (top, fa.path)
            if ck not in local_cache:
                local_cache[ck] = loc.is_local_module(top, fa.path)
            if local_cache[ck]:
                assignment[(fi, ri)] = "local_module"
                fa.skipped_local.add(top)
                continue
            key = _query_key(ref)
            if key in by_key:
                assignment[(fi, ri)] = by_key[key]
                continue
            if len(queries) >= MAX_QUERIES:
                assignment[(fi, ri)] = "cap_exceeded"
                pl.capped += 1
                continue
            qid = len(queries)
            by_key[key] = qid
            queries.append({
                "id": qid, "module": ref.module, "path": list(ref.path), "instance_attr": ref.instance_attr,
                "kwargs": list(key[4]), "is_call": ref.is_call, "file": fi,
            })
            assignment[(fi, ri)] = qid
    return pl


def _qualname(ref: Reference, upto: int) -> str:
    elems = ref.elements()[: upto + 1]
    text = ".".join(elems[: 1 + len(ref.path)])
    if ref.instance_attr is not None and upto > len(ref.path):
        text += "()." + ref.instance_attr
    return text


def _finding(ref, idx, verdict, reason, suggestions=(), hint=None, rec=None) -> Finding:
    loc = ref.element_loc(idx)
    kind = "module" if idx == 0 else "attribute"
    name = ref.module_as_written if idx == 0 else ref.elements()[idx]
    return Finding(ref.file, loc.line, loc.col, verdict, kind, name, _qualname(ref, idx), reason,
                   tuple(suggestions)[:3], hint, (rec or {}).get("dist"), (rec or {}).get("dist_version"))


def _kw_finding(ref, kw, verdict, reason, suggestions=(), rec=None) -> Finding:
    callee = _qualname(ref, len(ref.elements()) - 1)
    if ref.instance_attr is None and not ref.path:
        callee = ref.module
    return Finding(ref.file, kw.loc.line, kw.loc.col, verdict, "kwarg", kw.name, f"{callee}({kw.name}=)",
                   reason, tuple(suggestions)[:3], None, (rec or {}).get("dist"), (rec or {}).get("dist_version"))


@dataclass
class Resolution:
    findings: list[Finding]
    ok: int
    not_installed_tops: set[str]


def resolve(analyses: list[FileAnalysis], pl: Plan, outcome, policy: Policy) -> Resolution:
    findings: list[Finding] = []
    ok = 0
    not_installed: set[str] = set()
    results = outcome.results if outcome is not None else {}
    failed = outcome.failed if outcome is not None else {}
    extra_sugg = outcome.suggestions if outcome is not None else {}
    for fi, fa in enumerate(analyses):
        for ri, ref in enumerate(fa.references):
            a = pl.assignment.get((fi, ri))
            if a is None:
                continue
            if isinstance(a, str):
                if ref.owned == 0:
                    findings.append(_finding(ref, 0, "UNKNOWN", a))
                elif a != "local_module":
                    idx = min(ref.owned, len(ref.elements()) - 1)
                    findings.append(_finding(ref, idx, "UNKNOWN", a))
                continue
            if a in failed and a not in results:
                findings.append(_finding(ref, min(ref.owned, len(ref.elements()) - 1), "UNKNOWN", failed[a]))
                continue
            rec = results.get(a)
            if rec is None:
                findings.append(_finding(ref, min(ref.owned, len(ref.elements()) - 1), "UNKNOWN", "protocol_error"))
                continue
            status = rec["status"]
            if status != "ok":
                idx = rec.get("failed_index")
                if not isinstance(idx, int) or idx < 0 or idx >= len(ref.elements()):
                    findings.append(_finding(ref, 0, "UNKNOWN", "protocol_error"))
                    continue
                if idx < ref.owned:
                    continue  # reported by the import reference
                sugg = rec.get("suggestions") or extra_sugg.get(a, [])
                verdict, reason = _map(ref, fa, idx, status, rec.get("reason") or "", policy)
                if reason == "not_installed" and verdict == "MISSING":
                    not_installed.add(ref.module.split(".")[0])
                findings.append(_finding(ref, idx, verdict, reason, sugg, rec.get("hint"), rec))
                continue
            ok += 1
            by_name = {k.get("name"): k for k in rec.get("kwargs") or []}
            for n, kw in enumerate(ref.kwargs):
                if n >= MAX_KWARGS:
                    findings.append(_kw_finding(ref, kw, "UNKNOWN", "cap_exceeded", rec=rec))
                    continue
                kr = by_name.get(kw.name)
                if kr is None:
                    if ref.is_call:
                        findings.append(_kw_finding(ref, kw, "UNKNOWN", "protocol_error", rec=rec))
                    continue
                st = kr.get("status")
                if st == "ok":
                    ok += 1
                    continue
                guarded = ref.guard or kw.name in fa.string_tokens
                reason = kr.get("reason") or ""
                if st == "missing":
                    if guarded:
                        v, reason = "UNKNOWN", "guarded"
                    elif ref.caller_star_kwargs:
                        v, reason = "SUSPECT", "star_kwargs_call"
                    else:
                        v = "MISSING"
                elif st == "suspect":
                    v, reason = ("UNKNOWN", "guarded") if guarded else ("SUSPECT", reason)
                else:
                    v = "UNKNOWN"
                findings.append(_kw_finding(ref, kw, v, reason, kr.get("suggestions") or (), rec))
    return Resolution(_dedupe(findings), ok, not_installed)


def _map(ref: Reference, fa: FileAnalysis, idx: int, status: str, reason: str, policy: Policy):
    name = ref.elements()[idx]
    guarded = ref.guard or (idx > 0 and name in fa.string_tokens)
    if status == "missing":
        if guarded:
            return "UNKNOWN", "guarded"
        if idx == 0 and ref.optional_import:
            return "UNKNOWN", "optional_import"
        if reason == "not_installed":
            top = ref.module.split(".")[0]
            if pythonpath_has_module(top, policy.pythonpath):
                return "UNKNOWN", "pythonpath_module"
            if policy.downgrade_not_installed:
                return "UNKNOWN", "unconfigured_interpreter"
        return "MISSING", reason
    if status == "suspect":
        return ("UNKNOWN", "guarded") if guarded else ("SUSPECT", reason)
    return "UNKNOWN", reason or "unknown"


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """Duplicate (file, line, name, kind) collapse to one; the weakest verdict wins."""
    best: dict[tuple, Finding] = {}
    for f in findings:
        key = (f.file, f.line, f.name, f.kind)
        cur = best.get(key)
        if cur is None or _RANK[f.verdict] < _RANK[cur.verdict]:
            best[key] = f
    return sorted(best.values(), key=lambda f: (f.file, f.line, f.col, f.name))


def stdlib_names() -> frozenset[str]:
    return frozenset(getattr(sys, "stdlib_module_names", ()))
