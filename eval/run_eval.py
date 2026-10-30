"""Fixture evaluation (DESIGN §9, §14 A9).

Runs the CLI with ``--json --python fixtures/.venv/bin/python`` over every labelled and clean
fixture file, then scores MISSING findings against ``fixtures/manifest.json``:

* a MISSING finding is a TP iff an unmatched label has the same file, line, name and kind and
  ``hallucination: true`` (and the same col, when the label gives one); each label matches at most
  one finding; every other MISSING is an FP; unmatched hallucination labels are FNs;
* the same scoring is reported for MISSING ∪ SUSPECT;
* conformance compares each label's actual verdict (MISSING/SUSPECT/UNKNOWN/OK) with ``expected``.

Exit status is non-zero if TP+FP == 0, if MISSING precision < 1.0, if MISSING recall is below the
floor in eval/thresholds.json (when that file exists), on label line drift, if the CLI fails, or
if importing yfinance attempts a network connection. Fixture files are only ever parsed.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("module", "attribute", "kwarg")
VERDICTS = ("MISSING", "SUSPECT", "UNKNOWN", "OK", "NOT_CHECKED")
_RANK = {"MISSING": 3, "SUSPECT": 2, "UNKNOWN": 1, "OK": 0}


def _norm(path: str, root: Path) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(root.resolve())
        except ValueError:
            pass
    return p.as_posix()


def _score(labels: list[dict], findings: list[dict], verdicts: set[str]) -> dict:
    used: set[int] = set()
    tp, fp = [], []
    for f in findings:
        if f.get("verdict") not in verdicts:
            continue
        hit = None
        for i, lab in enumerate(labels):
            if i in used or not lab.get("hallucination"):
                continue
            if (lab["file"], lab["line"], lab["name"], lab["kind"]) != (f["file"], f["line"], f["name"], f["kind"]):
                continue
            if "col" in lab and lab["col"] != f.get("col"):
                continue
            hit = i
            break
        if hit is None:
            fp.append(f)
        else:
            used.add(hit)
            tp.append((labels[hit], f))
    fn = [lab for i, lab in enumerate(labels) if lab.get("hallucination") and i not in used]
    n_tp, n_fp, n_fn = len(tp), len(fp), len(fn)
    by_cat: dict[str, dict] = {}
    for lab in labels:
        if lab.get("hallucination"):
            by_cat.setdefault(lab.get("category", "?"), {"tp": 0, "fn": 0})
    for lab, _ in tp:
        by_cat[lab.get("category", "?")]["tp"] += 1
    for lab in fn:
        by_cat[lab.get("category", "?")]["fn"] += 1
    for c in by_cat.values():
        c["recall"] = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else None
    return {
        "tp": n_tp, "fp": n_fp, "fn": n_fn,
        "precision": n_tp / (n_tp + n_fp) if n_tp + n_fp else None,
        "recall": n_tp / (n_tp + n_fn) if n_tp + n_fn else None,
        "false_positives": [{k: f.get(k) for k in ("file", "line", "col", "name", "kind", "verdict", "reason")}
                            for f in fp],
        "false_negatives": [{k: lab.get(k) for k in ("file", "line", "name", "kind", "category", "expected")}
                            for lab in fn],
        "by_category": by_cat,
    }


def _actual(lab: dict, findings: list[dict]) -> tuple[str, str | None]:
    """No finding at all for a label means the tool reported nothing for that reference (it was not
    extracted or not checked): NOT_CHECKED, distinct from an explicit OK finding."""
    best = ("NOT_CHECKED", None)
    for f in findings:
        if (lab["file"], lab["line"], lab["name"], lab["kind"]) != (f["file"], f["line"], f["name"], f["kind"]):
            continue
        if "col" in lab and lab["col"] != f.get("col"):
            continue
        if best[0] == "NOT_CHECKED" or _RANK[f["verdict"]] > _RANK[best[0]]:
            best = (f["verdict"], f.get("reason"))
    return best


def compute_metrics(manifest: dict, findings: list[dict]) -> dict:
    labels = manifest.get("labels", [])
    rows = []
    for lab in labels:
        actual, reason = _actual(lab, findings)
        rows.append({"file": lab["file"], "line": lab["line"], "name": lab["name"], "kind": lab["kind"],
                     "category": lab.get("category"), "hallucination": lab.get("hallucination"),
                     "expected": lab.get("expected"), "actual": actual, "reason": reason,
                     "conforms": actual == lab.get("expected")})
    matrix = Counter((r["expected"], r["actual"]) for r in rows)
    return {
        "missing": _score(labels, findings, {"MISSING"}),
        "missing_or_suspect": _score(labels, findings, {"MISSING", "SUSPECT"}),
        "conformance": {
            "total": len(rows), "conforming": sum(r["conforms"] for r in rows),
            "matrix": {f"{e}->{a}": n for (e, a), n in sorted(matrix.items(), key=str)},
            "labels": rows,
        },
    }


def gate(metrics: dict, thresholds: dict) -> list[str]:
    m = metrics["missing"]
    out = []
    if m["tp"] + m["fp"] == 0:
        out.append("no MISSING findings at all (TP+FP == 0): the eval measured nothing")
    if m["precision"] is not None and m["precision"] < 1.0:
        out.append(f"MISSING precision {m['precision']:.3f} < 1.0 ({m['fp']} false MISSING)")
    floor = thresholds.get("missing_recall_floor")
    if floor is not None and (m["recall"] is None or m["recall"] < float(floor)):
        out.append(f"MISSING recall {m['recall']} < floor {floor} (eval/thresholds.json)")
    return out


def line_drift(manifest: dict, root: Path) -> list[str]:
    out = []
    cache: dict[str, list[str]] = {}
    for lab in manifest.get("labels", []):
        f = lab["file"]
        if f not in cache:
            try:
                cache[f] = (root / f).read_text(encoding="utf-8").splitlines()
            except OSError as e:
                cache[f] = []
                out.append(f"{f}: unreadable ({e.strerror})")
        lines = cache[f]
        ok = 1 <= lab["line"] <= len(lines) and lab["name"] in lines[lab["line"] - 1]
        if not ok:
            out.append(f"{f}:{lab['line']}: label name {lab['name']!r} not on that line")
    return out


def bad_kinds(manifest: dict) -> list[str]:
    return [f"{lab['file']}:{lab['line']}: kind {lab.get('kind')!r} not in {KINDS}"
            for lab in manifest.get("labels", []) if lab.get("kind") not in KINDS]


SOCKET_GUARD = r"""
import socket, sys, json
calls = []
def deny(name):
    def f(*a, **k):
        calls.append(name)
        raise OSError("network blocked by eval socket guard")
    return f
socket.socket.connect = deny("connect")
socket.socket.connect_ex = deny("connect_ex")
socket.socket.sendto = deny("sendto")
socket.create_connection = deny("create_connection")
socket.getaddrinfo = deny("getaddrinfo")
import importlib.util
ok = importlib.util.find_spec("yfinance") is not None
if ok:
    import yfinance
print(json.dumps({"installed": ok, "calls": calls}))
"""


def socket_guard(python: str) -> tuple[bool, str]:
    """M15 re-check: importing yfinance must not attempt any connection."""
    try:
        p = subprocess.run([python, "-I", "-c", SOCKET_GUARD], capture_output=True, text=True, timeout=120,
                           cwd=str(ROOT / "eval"))
        doc = json.loads(p.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as e:
        return False, f"socket guard could not run: {type(e).__name__}"
    if not doc["installed"]:
        return True, "yfinance not installed; skipped"
    return (not doc["calls"]), f"network calls during import yfinance: {doc['calls']}"


def dist_versions(python: str) -> dict:
    code = ("import json, importlib.metadata as m\nout = {}\n"
            "for d in ('numpy', 'pandas', 'requests', 'yfinance'):\n"
            "    try:\n        out[d] = m.version(d)\n    except Exception:\n        out[d] = None\n"
            "import sys\nout['python'] = sys.version.split()[0]\nprint(json.dumps(out))")
    try:
        p = subprocess.run([python, "-I", "-c", code], capture_output=True, text=True, timeout=60)
        return json.loads(p.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def run_cli(python: str, files: list[str], root: Path, timeout: float) -> tuple[int, dict, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env.pop("VIRTUAL_ENV", None)
    p = subprocess.run([sys.executable, "-m", "api_reality_check", "--json", "--python", python,
                        "--timeout", str(timeout), *files],
                       capture_output=True, text=True, cwd=str(root), env=env, timeout=timeout + 60)
    try:
        doc = json.loads(p.stdout)
    except ValueError:
        doc = {}
    return p.returncode, doc, p.stderr


def _fmt(x) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def render_md(res: dict) -> str:
    m, ms, c = res["metrics"]["missing"], res["metrics"]["missing_or_suspect"], res["metrics"]["conformance"]
    v = res.get("versions", {})
    lines = [
        "# api-reality-check fixture eval",
        "",
        f"Generated {res['timestamp']} by `eval/run_eval.py`. Target: `{res['python']}` "
        f"(Python {v.get('python')}; numpy {v.get('numpy')}, pandas {v.get('pandas')}, "
        f"requests {v.get('requests')}, yfinance {v.get('yfinance')}).",
        "",
        f"Gate: **{'PASS' if not res['gate_failures'] else 'FAIL'}**"
        + ("" if not res["gate_failures"] else " — " + "; ".join(res["gate_failures"])),
        "",
        "| Verdicts scored | TP | FP | FN | Precision | Recall |",
        "|---|---|---|---|---|---|",
        f"| MISSING | {m['tp']} | {m['fp']} | {m['fn']} | {_fmt(m['precision'])} | {_fmt(m['recall'])} |",
        f"| MISSING ∪ SUSPECT | {ms['tp']} | {ms['fp']} | {ms['fn']} | {_fmt(ms['precision'])} | {_fmt(ms['recall'])} |",
        "",
        "## Recall of MISSING by category",
        "",
        "| Category | TP | FN | Recall |",
        "|---|---|---|---|",
    ]
    for cat, d in sorted(m["by_category"].items()):
        lines.append(f"| {cat} | {d['tp']} | {d['fn']} | {_fmt(d['recall'])} |")
    lines += ["", f"## Conformance with designed verdicts: {c['conforming']} / {c['total']}", "",
              "| expected -> actual | labels |", "|---|---|"]
    for k, n in c["matrix"].items():
        lines.append(f"| {k} | {n} |")
    if m["false_positives"]:
        lines += ["", "## False MISSING", ""]
        for f in m["false_positives"]:
            lines.append(f"- `{f['file']}:{f['line']}` {f['kind']} `{f['name']}` ({f.get('reason')})")
    nonconf = [r for r in c["labels"] if not r["conforms"]]
    if nonconf:
        lines += ["", "## Labels not matching their designed verdict", ""]
        for r in nonconf:
            lines.append(f"- `{r['file']}:{r['line']}` {r['kind']} `{r['name']}`: expected {r['expected']}, "
                         f"got {r['actual']} ({r['reason']})")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT), help="directory the manifest paths are relative to")
    ap.add_argument("--manifest", default=None, help="default: <root>/fixtures/manifest.json")
    ap.add_argument("--python", default=None, help="default: <root>/fixtures/.venv/bin/python")
    ap.add_argument("--out-dir", default=None, help="default: <root>/eval")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--no-socket-guard", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    manifest_path = Path(args.manifest) if args.manifest else root / "fixtures" / "manifest.json"
    python = args.python or str(root / "fixtures" / ".venv" / "bin" / "python")
    out_dir = Path(args.out_dir) if args.out_dir else root / "eval"
    manifest = json.loads(manifest_path.read_text())
    files = sorted({lab["file"] for lab in manifest.get("labels", [])} | set(manifest.get("clean_files", [])))

    failures = []
    failures += line_drift(manifest, root)
    failures += bad_kinds(manifest)
    code, doc, stderr = run_cli(python, files, root, args.timeout)
    if code not in (0, 1) or not doc:
        failures.append(f"CLI exited {code}: {stderr.strip()[-500:]}")
    bad_files = [f for f in doc.get("files", []) if f.get("status") != "analysed"]
    if bad_files:
        failures.append(f"files not analysed: {bad_files}")
    findings = []
    for f in doc.get("findings", []):
        f = dict(f)
        f["file"] = _norm(f["file"], root)
        findings.append(f)
    metrics = compute_metrics(manifest, findings)
    thresholds_path = root / "eval" / "thresholds.json"
    thresholds = json.loads(thresholds_path.read_text()) if thresholds_path.exists() else {}
    failures += gate(metrics, thresholds)
    sg_detail = "skipped"
    if not args.no_socket_guard:
        sg_ok, sg_detail = socket_guard(python)
        if not sg_ok:
            failures.append(sg_detail)

    res = {
        "timestamp": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": python, "versions": dist_versions(python), "tool_target": doc.get("target"),
        "cli_exit": code, "files": files, "thresholds": thresholds, "metrics": metrics,
        "summary": doc.get("summary"), "socket_guard": sg_detail, "gate_failures": failures,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(res, indent=2) + "\n")
    (out_dir / "RESULTS.md").write_text(render_md(res))
    m = metrics["missing"]
    print(f"MISSING: TP {m['tp']} FP {m['fp']} FN {m['fn']} precision {_fmt(m['precision'])} "
          f"recall {_fmt(m['recall'])}; conformance {metrics['conformance']['conforming']}/"
          f"{metrics['conformance']['total']}")
    for f in failures:
        print(f"FAIL: {f}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
