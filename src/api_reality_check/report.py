"""Text / JSON output and the hook's context text (DESIGN §6, §8, §14 A8).

Everything that reaches Claude's context or a terminal is either an identifier (escaped and
truncated) or a library message (sanitized, capped and labelled untrusted).
"""
from __future__ import annotations

import json
import re

from . import PROTOCOL, __version__

HINT_CHARS = 200
NAME_CHARS = 100
HOOK_CAP = 8000
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-_]")


def sanitize(text: str | None, limit: int = HINT_CHARS) -> str:
    if not text:
        return ""
    text = _ANSI.sub(" ", str(text))
    text = "".join(ch if ch.isprintable() else " " for ch in text)
    text = " ".join(text.split())
    return text[:limit]


def show_name(name: str) -> str:
    """repr-style escaping, truncated, in backticks."""
    s = repr(str(name))[1:-1].replace("`", "'")
    if len(s) > NAME_CHARS:
        s = s[:NAME_CHARS] + "..."
    return f"`{s}`"


def _dist(f) -> str:
    if f.dist and f.dist_version:
        return f" [{sanitize(f.dist, 60)} {sanitize(f.dist_version, 40)}]"
    return ""


def _did_you_mean(f) -> str:
    if not f.suggestions:
        return ""
    return " — did you mean " + " or ".join(show_name(s) for s in f.suggestions) + "?"


def finding_line(f) -> str:
    return (f"{sanitize(f.file, 300)}:{f.line}:{f.col}: {f.verdict} {f.kind} {show_name(f.qualname)}"
            f"{_did_you_mean(f)}{_dist(f)}" + ("" if f.verdict == "MISSING" else f" ({sanitize(f.reason, 40)})"))


def header(rep) -> str:
    t = rep.target or {}
    return (f"api-reality-check {__version__}: target {sanitize(t.get('executable'), 300)} "
            f"(Python {sanitize(t.get('python'), 20)}, prefix {sanitize(t.get('prefix'), 300)})")


def summary_line(rep) -> str:
    c = rep.counts()

    def part(label, verdict):
        reasons = ", ".join(f"{sanitize(k, 40)}={v}" for k, v in c["by_reason"][verdict].items())
        return f"{label} {c[label.lower()]}" + (f" ({reasons})" if reasons else "")

    return f"OK {c['ok']} · " + " · ".join(part(v, v) for v in ("MISSING", "SUSPECT", "UNKNOWN"))


def to_text(rep, show_unknown: bool = False) -> str:
    lines = [header(rep)]
    for w in rep.warnings:
        lines.append(f"warning: {sanitize(w, 300)}")
    for fa in rep.files:
        if fa.status != "analysed":
            lines.append(f"{fa.path}: {fa.status}" + (f" ({sanitize(fa.notes[0])})" if fa.notes else ""))
    for f in rep.findings:
        if f.verdict == "UNKNOWN" and not show_unknown:
            continue
        lines.append(finding_line(f))
        if f.hint and f.verdict != "UNKNOWN":
            lines.append(f"    library message (untrusted): \"{sanitize(f.hint)}\"")
    lines.append(summary_line(rep))
    return "\n".join(lines) + "\n"


def to_json(rep) -> str:
    t = rep.target or {}
    doc = {
        "tool": "api-reality-check", "version": __version__, "protocol": PROTOCOL,
        "target": {"python": t.get("python"), "executable": t.get("executable"), "prefix": t.get("prefix")},
        "files": [{"path": fa.path, "status": fa.status} for fa in rep.files],
        "findings": [f.to_json() for f in rep.findings],
        "summary": rep.counts(),
        "warnings": rep.warnings,
        "diagnostics": {"protocol_errors": rep.protocol_errors, "stderr": rep.stderr[-4000:]},
    }
    return json.dumps(doc, indent=2)


def hook_text(rep) -> str:
    """additionalContext for Claude (§14 A8). Empty when there is nothing actionable."""
    shown = [f for f in rep.findings if f.verdict in ("MISSING", "SUSPECT")]
    if not shown:
        return ""
    n_missing = sum(f.verdict == "MISSING" for f in shown)
    t = rep.target or {}
    head = (f"api-reality-check: {n_missing} API(s) not found and {len(shown) - n_missing} suspect "
            f"in {sanitize(t.get('executable'), 200)} (Python {sanitize(t.get('python'), 20)}). "
            "MISSING = the name does not exist in the installed version; SUSPECT = probably wrong, verify "
            "before changing.")
    out = [head]
    used = len(head)
    for i, f in enumerate(shown):
        line = (f"{sanitize(f.file, 300)}:{int(f.line)} {sanitize(f.verdict, 10)} {show_name(f.qualname)} "
                f"({sanitize(f.reason, 40)}){_did_you_mean(f)}{_dist(f)}")
        if f.hint:
            line += f" library message (untrusted): \"{sanitize(f.hint)}\""
        more = f"+{len(shown) - i} more"
        if used + len(line) + 1 + len(more) + 1 > HOOK_CAP:
            out.append(more)
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)[:HOOK_CAP]
