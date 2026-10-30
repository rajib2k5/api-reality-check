"""Metric and gate arithmetic of eval/run_eval.py on a tiny synthetic manifest (not the real fixtures)."""
import importlib.util
import json
import sys

import pytest

from conftest import REPO

spec = importlib.util.spec_from_file_location("run_eval", REPO / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(spec)
sys.modules["run_eval"] = run_eval
spec.loader.exec_module(run_eval)


def L(file, line, name, kind="attribute", hallucination=True, expected="MISSING", category="misspelled", **kw):
    d = {"file": file, "line": line, "name": name, "kind": kind, "category": category,
         "hallucination": hallucination, "expected": expected}
    d.update(kw)
    return d


def F(file, line, name, verdict="MISSING", kind="attribute", col=0):
    return {"file": file, "line": line, "col": col, "name": name, "kind": kind, "verdict": verdict}


MANIFEST = {
    "version": 1,
    "labels": [
        L("c/a_seeded.py", 3, "linspce"),                                    # TP
        L("c/a_seeded.py", 4, "numm", kind="kwarg", category="invented_kwarg", expected="SUSPECT"),  # caught as SUSPECT
        L("c/a_seeded.py", 5, "bogus", kind="kwarg", category="invented_kwarg", expected="UNKNOWN"),  # FN
        L("c/a_seeded.py", 6, "headers", hallucination=False, expected="UNKNOWN"),  # must not flag
    ],
    "clean_files": ["c/a_clean.py"],
}
FINDINGS = [
    F("c/a_seeded.py", 3, "linspce"),
    F("c/a_seeded.py", 4, "numm", "SUSPECT", "kwarg"),
    F("c/a_seeded.py", 6, "headers", "MISSING"),          # FP: label says it exists
    F("c/a_clean.py", 9, "rolling", "MISSING"),           # FP: clean file
    F("c/a_clean.py", 10, "plot", "SUSPECT"),             # FP only for MISSING|SUSPECT
]


def test_missing_only_counts():
    m = run_eval.compute_metrics(MANIFEST, FINDINGS)["missing"]
    assert (m["tp"], m["fp"], m["fn"]) == (1, 2, 2)
    assert m["precision"] == pytest.approx(1 / 3) and m["recall"] == pytest.approx(1 / 3)


def test_missing_or_suspect_counts():
    m = run_eval.compute_metrics(MANIFEST, FINDINGS)["missing_or_suspect"]
    assert (m["tp"], m["fp"], m["fn"]) == (2, 3, 1)
    assert m["precision"] == pytest.approx(2 / 5) and m["recall"] == pytest.approx(2 / 3)


def test_label_matches_at_most_one_finding():
    man = {"version": 1, "labels": [L("x.py", 1, "a")], "clean_files": []}
    m = run_eval.compute_metrics(man, [F("x.py", 1, "a", col=0), F("x.py", 1, "a", col=5)])["missing"]
    assert (m["tp"], m["fp"], m["fn"]) == (1, 1, 0)


def test_col_disambiguates_when_present():
    man = {"version": 1, "labels": [L("x.py", 1, "a", col=5)], "clean_files": []}
    m = run_eval.compute_metrics(man, [F("x.py", 1, "a", col=0)])["missing"]
    assert (m["tp"], m["fp"]) == (0, 1)


def test_kind_must_match():
    man = {"version": 1, "labels": [L("x.py", 1, "a", kind="module")], "clean_files": []}
    m = run_eval.compute_metrics(man, [F("x.py", 1, "a", kind="attribute")])["missing"]
    assert (m["tp"], m["fp"], m["fn"]) == (0, 1, 1)


def test_conformance_against_expected():
    c = run_eval.compute_metrics(MANIFEST, FINDINGS)["conformance"]
    assert c["total"] == 4 and c["conforming"] == 2   # bogus: NOT_CHECKED != UNKNOWN; headers: MISSING != UNKNOWN
    by = {(r["line"], r["name"]): r for r in c["labels"]}
    assert by[(5, "bogus")]["actual"] == "NOT_CHECKED" and by[(5, "bogus")]["conforms"] is False
    assert by[(6, "headers")]["actual"] == "MISSING"


def test_label_without_any_finding_is_not_checked_not_ok():
    man = {"version": 1, "labels": [L("x.py", 1, "a", hallucination=False, expected="UNKNOWN"),
                                    L("x.py", 2, "b", hallucination=False, expected="UNKNOWN")],
           "clean_files": []}
    c = run_eval.compute_metrics(man, [F("x.py", 2, "b", "OK")])["conformance"]
    by = {r["name"]: r["actual"] for r in c["labels"]}
    assert by == {"a": "NOT_CHECKED", "b": "OK"}      # an explicit OK finding stays distinct
    assert c["matrix"] == {"UNKNOWN->NOT_CHECKED": 1, "UNKNOWN->OK": 1}


def test_not_checked_is_rendered_in_the_markdown_report():
    man = {"version": 1, "labels": [L("x.py", 1, "a", hallucination=False, expected="UNKNOWN")], "clean_files": []}
    res = {"timestamp": "t", "python": "p", "gate_failures": [],
           "metrics": run_eval.compute_metrics(man, [])}
    assert "expected UNKNOWN, got NOT_CHECKED" in run_eval.render_md(res)


def test_no_findings_at_all_has_undefined_precision_and_fails_gate():
    metrics = run_eval.compute_metrics(MANIFEST, [])
    assert metrics["missing"]["precision"] is None
    assert any("TP+FP" in r for r in run_eval.gate(metrics, {}))


def test_gate_fails_on_any_false_missing():
    metrics = run_eval.compute_metrics(MANIFEST, FINDINGS)
    assert any("precision" in r for r in run_eval.gate(metrics, {}))


def test_gate_passes_perfect_precision_and_checks_recall_floor():
    findings = [F("c/a_seeded.py", 3, "linspce")]
    metrics = run_eval.compute_metrics(MANIFEST, findings)
    assert run_eval.gate(metrics, {}) == []
    assert run_eval.gate(metrics, {"missing_recall_floor": 0.30}) == []
    assert any("recall" in r for r in run_eval.gate(metrics, {"missing_recall_floor": 0.5}))


def test_line_drift_detected(tmp_path):
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "f.py").write_text("import numpy as np\nnp.linspce\n")
    man = {"version": 1, "labels": [L("c/f.py", 2, "linspce"), L("c/f.py", 1, "linspce")], "clean_files": []}
    drift = run_eval.line_drift(man, tmp_path)
    assert len(drift) == 1 and "c/f.py:1" in drift[0]


def test_end_to_end_on_synthetic_stdlib_manifest(tmp_path):
    cases = tmp_path / "fixtures" / "cases"
    cases.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("")
    (cases / "std_seeded.py").write_text("import json\njson.dumpss({})\nimport collections\ncollections.deque()\n")
    (cases / "std_clean.py").write_text("import json\njson.dumps({})\n")
    man = {"version": 1, "labels": [L("fixtures/cases/std_seeded.py", 2, "dumpss")],
           "clean_files": ["fixtures/cases/std_clean.py"]}
    (tmp_path / "fixtures" / "manifest.json").write_text(json.dumps(man))
    out = tmp_path / "out"
    code = run_eval.main(["--root", str(tmp_path), "--python", sys.executable, "--out-dir", str(out),
                          "--no-socket-guard"])
    res = json.loads((out / "results.json").read_text())
    assert code == 0, res.get("gate_failures")
    assert res["metrics"]["missing"]["tp"] == 1 and res["metrics"]["missing"]["precision"] == 1.0
    assert (out / "RESULTS.md").read_text().startswith("# ")
