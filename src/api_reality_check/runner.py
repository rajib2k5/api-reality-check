"""Spawn the probe in the target interpreter (DESIGN §5.3, §6, §14 A6).

One batched subprocess per run, ``python -I -S probe.py`` with an empty private cwd, an allowlisted
environment and its own process group. A module that hangs or crashes is marked UNKNOWN and the
remaining modules are resumed in a fresh probe (at most two resumes).
"""
from __future__ import annotations

import json
import os
import queue
import re
import secrets
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import PROTOCOL
from .models import PROBE_REASONS

PROBE_PATH = str(Path(__file__).with_name("probe.py"))
ENV_ALLOW = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "SYSTEMROOT")
MAX_LINE = 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024
MAX_STDERR = 64 * 1024
MAX_RESUMES = 2
MAX_REQUEST = 4 * 1024 * 1024   # same limit as probe.MAX_REQUEST
# probe.py exit codes before it says hello
EXIT_TOO_LARGE, EXIT_BAD_REQUEST, EXIT_TOO_OLD = 3, 4, 5
_STATUSES = frozenset({"ok", "missing", "suspect", "unknown"})
# Free-text channels into Claude's context (F3 residual): dist names and versions must look like
# package metadata, and a suggestion must be a short (dotted) identifier. Anything else is dropped.
_DIST = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,59}")
_DIST_VERSION = re.compile(r"[A-Za-z0-9.+!_-]{1,40}")
MAX_SUGGESTION = 60
_DOWNGRADE = "optional_dep_outside_env"


class ProbeError(Exception):
    """The target interpreter is unusable (missing, not executable, never said hello)."""


@dataclass
class ProbeOutcome:
    hello: dict | None = None
    results: dict[int, dict] = field(default_factory=dict)
    suggestions: dict[int, list[str]] = field(default_factory=dict)
    failed: dict[int, str] = field(default_factory=dict)    # query id -> timeout|crashed|protocol_error
    stderr: str = ""
    protocol_errors: int = 0
    attempts: int = 0
    module_timeouts: int = 0       # groups killed by the per-module timeout
    deadline_hit: bool = False     # the overall deadline stopped the probe or left references unchecked
    start_failure: tuple[str, int | None] | None = None   # (how the attempt ended, exit code) without hello


def probe_env(tmpdir: str) -> dict[str, str]:
    env = {k: os.environ[k] for k in ENV_ALLOW if k in os.environ}
    env.update({
        "TMPDIR": tmpdir, "PYTHONDONTWRITEBYTECODE": "1",
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    })
    return env


def _is_ident(s) -> bool:
    return isinstance(s, str) and len(s) <= 200 and all(p.isidentifier() for p in s.split("."))


def _clean_suggestions(value) -> list[str] | None:
    """The suggestions that are dotted identifiers of at most MAX_SUGGESTION chars; None if not a list."""
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    return [s for s in value if _is_ident(s) and len(s) <= MAX_SUGGESTION]


def _reason_ok(status, reason) -> bool:
    return isinstance(reason, (str, type(None))) and reason in PROBE_REASONS.get(status, ())


def _valid_result(rec: dict, ids: set[int]) -> bool:
    """Schema and enum check (F3): code inside the probe can write records, so status, kind and reason must
    each be one of the fixed values, and the reason must fit the status."""
    if rec.get("id") not in ids or rec.get("status") not in _STATUSES:
        return False
    if not _reason_ok(rec["status"], rec.get("reason")):
        return False
    fi = rec.get("failed_index")
    if fi is not None and (not isinstance(fi, int) or isinstance(fi, bool)):
        return False
    if rec.get("kind") not in ("module", "attribute"):
        return False
    if rec["status"] != "ok" and (fi is None or (rec["kind"] == "module") != (fi == 0)):
        return False
    sugg = _clean_suggestions(rec.get("suggestions", []))
    if sugg is None:
        return False
    rec["suggestions"] = sugg
    kws = rec.get("kwargs", [])
    if not isinstance(kws, list):
        return False
    for k in kws:
        if not isinstance(k, dict) or k.get("status") not in _STATUSES or not _is_ident(k.get("name")):
            return False
        if not _reason_ok(k["status"], k.get("reason")):
            return False
        ks = _clean_suggestions(k.get("suggestions", []))
        if ks is None:
            return False
        k["suggestions"] = ks
    for key in ("reason", "hint", "dist", "dist_version"):
        if rec.get(key) is not None and not isinstance(rec.get(key), str):
            return False
    for key, pattern in (("dist", _DIST), ("dist_version", _DIST_VERSION)):
        if rec.get(key) is not None and not pattern.fullmatch(rec[key]):
            rec[key] = None
    return True


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _reader(stream, q: queue.Queue, tag: str) -> None:
    try:
        while True:
            line = stream.readline(MAX_LINE + 1)
            if not line:
                break
            q.put((tag, line))
    except (OSError, ValueError):
        pass
    finally:
        q.put((tag, None))


def _is_downgrade(old: dict, new: dict) -> bool:
    """A30: the first record for an id wins. The only allowed second record is the probe's downgrade of a
    MISSING (the record or its kwargs) to UNKNOWN optional_dep_outside_env after a later refusal (A21)."""
    def same_or_down(a: dict, b: dict) -> bool:
        if (a.get("status"), a.get("reason")) == (b.get("status"), b.get("reason")):
            return True
        return a.get("status") == "missing" and (b.get("status"), b.get("reason")) == ("unknown", _DOWNGRADE)

    if any(old.get(k) != new.get(k) for k in ("kind", "failed_index", "suggestions", "dist", "dist_version")):
        return False
    if not same_or_down(old, new):
        return False
    ok, nk = old.get("kwargs") or [], new.get("kwargs") or []
    if [(k.get("name"), k.get("suggestions")) for k in ok] != [(k.get("name"), k.get("suggestions")) for k in nk]:
        return False
    if not all(same_or_down(a, b) for a, b in zip(ok, nk)):
        return False
    return new.get("status") != old.get("status") or any(a.get("status") != b.get("status") for a, b in zip(ok, nk))


def _attempt(python: str, request: dict, deadline: float, module_timeout: float, out: ProbeOutcome,
             ids: set[int], tops_order: list[str],
             group_ids: dict[str, set[int]]) -> tuple[str | None, set[str], str]:
    """Run one probe process. Returns (in-flight module or None, modules completed, how it ended:
    'done' | 'timeout' | 'crashed' | 'nohello')."""
    tmpdir = tempfile.mkdtemp(prefix="arc-")
    completed: set[str] = set()
    current: str | None = None
    try:
        try:
            proc = subprocess.Popen(
                [python, "-I", "-S", PROBE_PATH], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, cwd=tmpdir, env=probe_env(tmpdir), start_new_session=True)
        except OSError as e:
            raise ProbeError(f"cannot execute {python}: {e.strerror or e}") from None
        q: queue.Queue = queue.Queue()
        threads = [threading.Thread(target=_reader, args=(proc.stdout, q, "out"), daemon=True),
                   threading.Thread(target=_reader, args=(proc.stderr, q, "err"), daemon=True)]
        for t in threads:
            t.start()
        try:
            proc.stdin.write(json.dumps(request).encode())
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        total = 0
        stderr_parts: list[bytes] = []
        stderr_len = 0
        eof = set()
        began_at = time.monotonic()
        ended = "crashed"
        nonce = request["nonce"]
        saw_hello = out.hello is not None
        saw_hello_here = False
        pending = [t for t in tops_order if t not in request.get("skip_modules", ())]
        begun: set[str] = set()
        while len(eof) < 2:
            now = time.monotonic()
            limit = deadline
            if current is not None:
                limit = min(limit, began_at + module_timeout)
            if now >= limit:
                ended = "timeout"
                if current is not None and began_at + module_timeout < deadline:
                    out.module_timeouts += 1
                else:
                    out.deadline_hit = True
                break
            try:
                tag, line = q.get(timeout=min(0.1, max(0.0, limit - now)))
            except queue.Empty:
                continue
            if line is None:
                eof.add(tag)
                continue
            if tag == "err":
                if stderr_len < MAX_STDERR:
                    stderr_parts.append(line[: MAX_STDERR - stderr_len])
                    stderr_len += len(stderr_parts[-1])
                continue
            total += len(line)
            if len(line) > MAX_LINE or total > MAX_TOTAL:
                out.protocol_errors += 1
                if total > MAX_TOTAL:
                    ended = "crashed"
                    break
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict) or rec.get("nonce") != nonce:
                continue
            typ = rec.get("type")
            if typ == "hello":
                if rec.get("protocol") == PROTOCOL:
                    saw_hello_here = True
                    if out.hello is None:
                        out.hello = {k: rec.get(k) for k in ("python", "executable", "prefix", "user_site_added")}
            elif typ == "begin":
                m = rec.get("module")
                if m in tops_order:
                    # Strict order: one begin per group, in request order, none while a group is open.
                    if current is not None or m in begun or len(begun) >= len(pending) or m != pending[len(begun)]:
                        out.protocol_errors += 1
                        ended = "crashed"
                        break
                    begun.add(m)
                    current, began_at = m, time.monotonic()
            elif typ == "end":
                if rec.get("module") != current:
                    out.protocol_errors += 1
                    ended = "crashed"
                    break
                completed.add(current)
                current = None
            elif typ == "result":
                if _valid_result(rec, ids):
                    rid = rec["id"]
                    if current is None or rid not in group_ids.get(current, ()):
                        out.protocol_errors += 1      # A30: a record only counts during its own group
                    elif rid not in out.results:
                        out.results[rid] = rec
                    elif _is_downgrade(out.results[rid], rec):
                        out.results[rid] = rec
                    else:
                        out.protocol_errors += 1
                else:
                    out.protocol_errors += 1
                    if rec.get("id") in ids:
                        out.failed[rec["id"]] = "protocol_error"
            elif typ == "suggest":
                s = _clean_suggestions(rec.get("suggestions"))
                if rec.get("id") in ids and s:
                    out.suggestions[rec["id"]] = s[:3]
            elif typ == "done":
                ended = "done"
                break
        if ended != "done":
            _kill(proc)
        else:
            try:
                proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                _kill(proc)
        out.stderr += b"".join(stderr_parts).decode("utf-8", "replace")
        if not saw_hello and not saw_hello_here:
            out.start_failure = (ended, proc.returncode)
            return current, completed, "nohello"
        if ended == "crashed" and current is None:
            # Died between modules: blame the first module not yet completed.
            pass
        return current, completed, ended
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def start_failure_message(python: str, out: ProbeOutcome) -> str:
    """The real reason the probe never said hello (R6): only a version failure says "needs Python >= 3.9"."""
    how, code = out.start_failure or ("crashed", None)
    tail = " ".join(out.stderr.strip().splitlines()[-1:])[:200]
    if code == EXIT_TOO_LARGE:
        return f"probe request too large (limit {MAX_REQUEST} bytes)"
    if code == EXIT_BAD_REQUEST:
        return f"interpreter {python} rejected the probe request (protocol mismatch)"
    if code == EXIT_TOO_OLD or (code not in (None, 0) and "SyntaxError" in out.stderr):
        return f"interpreter {python} cannot run the probe: it needs Python >= 3.9. {tail}".strip()
    if how == "timeout":
        return f"interpreter {python} timed out before the probe started"
    return f"interpreter {python} did not start the probe (exit code {code}). {tail}".strip()


def _downgrade_missing(rec: dict, reason: str) -> None:
    """A30: the group died before its end, so a later refusal could not downgrade what was already sent.
    Its MISSING record and kwargs become UNKNOWN with the reason the group ended (timeout or crashed)."""
    if rec.get("status") == "missing":
        rec["status"], rec["reason"] = "unknown", reason
    for k in rec.get("kwargs") or []:
        if k.get("status") == "missing":
            k["status"], k["reason"] = "unknown", reason


def run_probe(python: str, queries: list[dict], timeout: float = 30.0, module_timeout: float = 10.0,
              limits: dict | None = None, cross_modules: list[list[str]] | None = None) -> ProbeOutcome:
    out = ProbeOutcome()
    ids = {q["id"] for q in queries}
    tops_order: list[str] = []
    by_top: dict[str, list[int]] = {}
    for q in queries:
        top = q["module"].split(".")[0]
        if top not in by_top:
            by_top[top] = []
            tops_order.append(top)
        by_top[top].append(q["id"])
    deadline = time.monotonic() + timeout
    skip: set[str] = set()
    resumes = 0
    cross_modules = cross_modules or []
    size = len(json.dumps({"queries": queries, "cross_modules": cross_modules}))
    if size > MAX_REQUEST:
        raise ProbeError(f"probe request too large: {size} bytes (limit {MAX_REQUEST}); "
                         "the file has too many distinct references")
    while True:
        request = {"protocol": PROTOCOL, "nonce": secrets.token_hex(16),
                   "limits": limits or {"suggestions": 3, "hint_chars": 200},
                   "queries": queries, "cross_modules": cross_modules, "skip_modules": sorted(skip)}
        out.attempts += 1
        current, completed, ended = _attempt(python, request, deadline, module_timeout, out, ids, tops_order,
                                             {t: set(v) for t, v in by_top.items()})
        if ended == "nohello":
            if out.hello is None:
                raise ProbeError(start_failure_message(python, out))
            ended = "crashed"
        skip |= completed
        if ended == "done":
            break
        reason = "timeout" if ended == "timeout" else "crashed"
        if current is None:
            remaining = [t for t in tops_order if t not in skip]
            current = remaining[0] if remaining else None
        if current is not None:
            for qid in by_top[current]:
                if qid not in out.results:
                    out.failed[qid] = reason
                else:
                    _downgrade_missing(out.results[qid], reason)
            skip.add(current)
        if resumes >= MAX_RESUMES or time.monotonic() >= deadline or all(t in skip for t in tops_order):
            break
        resumes += 1
    for top in tops_order:
        for qid in by_top[top]:
            if qid not in out.results and qid not in out.failed:
                out.failed[qid] = "timeout"
                out.deadline_hit = True
    return out
