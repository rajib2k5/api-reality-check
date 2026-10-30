"""One analysis run: extract every file, one batched probe, resolve (DESIGN §3)."""
from __future__ import annotations

import os
import time
from collections import Counter
from dataclasses import dataclass, field

from .extract import MAX_BYTES, extract
from .models import FileAnalysis, Finding
from .resolve import MAX_MODULES, MAX_QUERIES, Policy, plan, resolve, stdlib_names
from .runner import ProbeOutcome, run_probe


@dataclass
class Report:
    target: dict
    files: list[FileAnalysis]
    findings: list[Finding]
    ok: int
    warnings: list[str] = field(default_factory=list)
    stderr: str = ""
    protocol_errors: int = 0

    def counts(self) -> dict:
        c = Counter(f.verdict for f in self.findings)
        return {"ok": self.ok, "missing": c["MISSING"], "suspect": c["SUSPECT"], "unknown": c["UNKNOWN"],
                "by_reason": {v: dict(sorted(Counter(f.reason for f in self.findings if f.verdict == v).items()))
                              for v in ("MISSING", "SUSPECT", "UNKNOWN")}}


def read_file(path: str) -> FileAnalysis:
    try:
        size = os.path.getsize(path)
        if size > MAX_BYTES:
            return FileAnalysis(path, "too_large", notes=[f"file larger than {MAX_BYTES} bytes"])
        with open(path, "rb") as f:
            data = f.read(MAX_BYTES + 1)
    except OSError as e:
        return FileAnalysis(path, "unreadable", notes=[f"{type(e).__name__}: {e.strerror or ''}"])
    return extract(path, data)


def analyze(paths: list[str], python: str, timeout: float = 30.0, module_timeout: float = 10.0,
            policy: Policy | None = None) -> Report:
    """`timeout` is one wall-clock deadline for the whole run: reading, extraction, planning and the
    probe (F4). Raises runner.ProbeError when the target interpreter is unusable."""
    deadline = time.monotonic() + timeout
    policy = policy or Policy()
    analyses = []
    for p in paths:
        if time.monotonic() >= deadline:
            analyses.append(FileAnalysis(p, "timeout", notes=["the deadline was reached before this file was read"]))
        else:
            analyses.append(read_file(p))
    pl = plan(analyses, deadline)
    remaining = deadline - time.monotonic()
    if remaining <= 0.05:
        outcome = ProbeOutcome(failed={q["id"]: "timeout" for q in pl.queries}, deadline_hit=bool(pl.queries))
    else:
        outcome = run_probe(python, pl.queries, timeout=remaining, module_timeout=module_timeout,
                            cross_modules=pl.cross_modules)
    res = resolve(analyses, pl, outcome, policy)
    warnings = []
    if pl.capped:
        warnings.append(f"{pl.capped} reference(s) not checked (cap_exceeded): more than {MAX_MODULES} modules "
                        f"or {MAX_QUERIES} distinct references in one run")
    if outcome.module_timeouts:
        n = outcome.module_timeouts
        warnings.append(f"the per-module timeout ({module_timeout:g} s, --module-timeout) was reached for {n} "
                        f"module{'s' if n != 1 else ''}; their references are UNKNOWN (timeout)")
    if pl.timed_out or outcome.deadline_hit:
        warnings.append(f"the {timeout:g} s deadline was reached; references not checked in time are UNKNOWN (timeout)")
    third_party = {t for t in res.not_installed_tops if t not in stdlib_names()}
    if len(third_party) >= 3:
        warnings.append(f"{len(third_party)} third-party modules are not installed in the target "
                        f"interpreter ({', '.join(sorted(third_party)[:5])}); target env may be wrong")
    return Report(target=outcome.hello or {}, files=analyses, findings=res.findings, ok=res.ok,
                  warnings=warnings, stderr=outcome.stderr, protocol_errors=outcome.protocol_errors)
