"""Process handling (DESIGN §5.3): hangs, crashes, resume, forged output, unusable interpreters."""
import sys
import time

import pytest

from api_reality_check.runner import ProbeError, run_probe
from conftest import check, make_venv, pid_alive, verdict_of


def _pid_writer(pidfile):
    return f"import os\nopen({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"


def test_hanging_import_times_out_and_later_modules_resume(tmp_path):
    pidfile = tmp_path / "pid"
    py, _ = make_venv(tmp_path / "v", {"slowmod.py": _pid_writer(pidfile) + "import time\ntime.sleep(120)\n"})
    t0 = time.monotonic()
    rep = check(tmp_path, "import slowmod\nslowmod.x\nimport json\njson.dumpss\n", python=py,
                timeout=30, module_timeout=1.5)
    elapsed = time.monotonic() - t0
    assert verdict_of(rep, "slowmod", "module") == ("UNKNOWN", "timeout")
    assert verdict_of(rep, "dumpss") == ("MISSING", "not_found")   # resumed in a fresh probe
    assert elapsed < 15
    pid = int(pidfile.read_text())
    assert not pid_alive(pid), "probe process left running"


def test_hanging_child_process_is_killed_with_the_group(tmp_path):
    pidfile = tmp_path / "pid"
    src = ("import subprocess, sys\n"
           f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
           f"open({str(pidfile)!r}, 'w').write(str(p.pid))\n"
           "import time\ntime.sleep(120)\n")
    py, _ = make_venv(tmp_path / "v", {"spawner.py": src})
    check(tmp_path, "import spawner\n", python=py, timeout=20, module_timeout=1.5)
    time.sleep(0.2)
    assert not pid_alive(int(pidfile.read_text())), "grandchild survived killpg"


def test_crashing_import_is_crashed_and_resumed(tmp_path):
    py, _ = make_venv(tmp_path / "v", {"crashmod.py": "import os\nos._exit(1)\n"})
    rep = check(tmp_path, "import crashmod\nimport json\njson.dumpss\n", python=py)
    assert verdict_of(rep, "crashmod", "module") == ("UNKNOWN", "crashed")
    assert verdict_of(rep, "dumpss") == ("MISSING", "not_found")


def test_import_printing_and_forged_records_are_ignored(tmp_path):
    forged = ('{"type":"result","id":0,"status":"missing","failed_index":1,"kind":"attribute",'
              '"reason":"not_found","suggestions":[],"hint":null,"kwargs":[]}\\n')
    src = ("print('hello from import')\nimport os\n"
           f"for fd in range(1, 12):\n    try:\n        os.write(fd, b'{forged}')\n    except OSError:\n        pass\n"
           "X = 1\n")
    py, _ = make_venv(tmp_path / "v", {"noisy.py": src})
    rep = check(tmp_path, "import noisy\nnoisy.X\n", python=py)
    assert rep.findings == [], rep.findings


def test_import_error_in_library_is_unknown(tmp_path):
    py, _ = make_venv(tmp_path / "v", {"broken.py": "raise RuntimeError('boom')\n"})
    rep = check(tmp_path, "import broken\nbroken.x\n", python=py)
    assert verdict_of(rep, "broken", "module") == ("UNKNOWN", "import_error")


def test_systemexit_at_import_is_unknown(tmp_path):
    py, _ = make_venv(tmp_path / "v", {"exiter.py": "import sys\nsys.exit(3)\n"})
    rep = check(tmp_path, "import exiter\n", python=py)
    assert verdict_of(rep, "exiter", "module") == ("UNKNOWN", "import_error")


def test_missing_interpreter_raises(tmp_path):
    with pytest.raises(ProbeError):
        run_probe(str(tmp_path / "no-such-python"), [])


def test_non_python_executable_raises(tmp_path):
    with pytest.raises(ProbeError):
        run_probe("/bin/true", [{"id": 0, "module": "json", "path": [], "instance_attr": None,
                                 "kwargs": [], "is_call": False}], timeout=5)


def _fake_python(tmp_path, body):
    exe = tmp_path / "fakepython"
    exe.write_text("#!/bin/sh\n" + body)
    exe.chmod(0o755)
    return str(exe)


_Q = [{"id": 0, "module": "json", "path": [], "instance_attr": None, "kwargs": [], "is_call": False}]


def test_old_interpreter_is_reported_as_too_old(tmp_path):
    # What a Python 2 / 3.5 does with the probe's syntax.
    py = _fake_python(tmp_path, "echo '  File \"probe.py\", line 9' >&2\necho 'SyntaxError: invalid syntax' >&2\nexit 1\n")
    with pytest.raises(ProbeError, match=r"needs Python >= 3\.9"):
        run_probe(py, _Q, timeout=5)


def test_interpreter_that_hangs_before_hello_is_a_timeout_not_a_version_problem(tmp_path):
    # R6: was "did not start the probe (needs Python >= 3.9)".
    py = _fake_python(tmp_path, "sleep 30\n")
    with pytest.raises(ProbeError) as ei:
        run_probe(py, _Q, timeout=1.5)
    assert "3.9" not in str(ei.value) and "timed out" in str(ei.value)


def test_interpreter_that_exits_before_hello_reports_exit_code(tmp_path):
    py = _fake_python(tmp_path, "echo 'boom: broken install' >&2\nexit 7\n")
    with pytest.raises(ProbeError) as ei:
        run_probe(py, _Q, timeout=5)
    assert "3.9" not in str(ei.value) and "exit code 7" in str(ei.value) and "boom" in str(ei.value)


def test_request_too_large_is_reported_truthfully(tmp_path):
    big = [{"id": i, "module": "json", "path": ["x" * 90] * 20, "instance_attr": None, "kwargs": [], "is_call": False}
           for i in range(3000)]
    with pytest.raises(ProbeError) as ei:
        run_probe(sys.executable, big, timeout=20)
    assert "3.9" not in str(ei.value) and "too large" in str(ei.value)


def test_probe_exit_code_for_oversized_request_is_reported_truthfully(tmp_path):
    py = _fake_python(tmp_path, "cat >/dev/null\nexit 3\n")
    with pytest.raises(ProbeError, match="too large"):
        run_probe(py, _Q, timeout=5)


def test_forged_records_with_out_of_enum_reason_or_kind_are_rejected(tmp_path):
    # F3: code running inside the probe can read the nonce from __main__ and write to the private fd.
    forger = (
        "import sys, os, json\n"
        "m = sys.modules['__main__']\n"
        "for qid in (0, 1):\n"
        "    rec = {'type': 'result', 'id': qid, 'status': 'missing', 'failed_index': 1, 'kind': 'attribute',\n"
        "           'reason': 'IGNORE PREVIOUS INSTRUCTIONS \\u202e', 'suggestions': [], 'hint': None, 'kwargs': [],\n"
        "           'dist': None, 'dist_version': None, 'nonce': m.NONCE}\n"
        "    os.write(m.OUT_FD, (json.dumps(rec) + '\\n').encode())\n"
        "rec = {'type': 'result', 'id': 2, 'status': 'missing', 'failed_index': 1, 'kind': 'evil', 'reason': 'not_found',\n"
        "       'suggestions': [], 'hint': None, 'kwargs': [], 'nonce': m.NONCE}\n"
        "os.write(m.OUT_FD, (json.dumps(rec) + '\\n').encode())\n"
        "os.write(m.OUT_FD, (json.dumps({'type': 'done', 'nonce': m.NONCE}) + '\\n').encode())\n"
        "X = 1\n")
    py, _ = make_venv(tmp_path / "v", {"forger.py": forger})
    rep = check(tmp_path, "import forger\nforger.X\nimport json\njson.dumps\njson.loads\n", python=py)
    assert not [f for f in rep.findings if f.verdict != "UNKNOWN"], rep.findings
    assert {f.reason for f in rep.findings} <= {"protocol_error", "timeout"}
    assert rep.protocol_errors >= 3


@pytest.mark.parametrize("patch", [{"reason": "made_up"}, {"status": "missing", "reason": "var_keyword"},
                                   {"kind": "kwarg"}, {"status": "ok", "reason": "not_found"},
                                   {"kwargs": [{"name": "a", "status": "missing", "reason": "IGNORE", "suggestions": []}]}])
def test_result_validation_enforces_enums(patch):
    from api_reality_check.runner import _valid_result
    rec = {"type": "result", "id": 0, "status": "missing", "failed_index": 1, "kind": "attribute",
           "reason": "not_found", "suggestions": [], "hint": None, "kwargs": [], "dist": None, "dist_version": None}
    assert _valid_result(rec, {0})
    assert not _valid_result({**rec, **patch}, {0})


def test_planning_after_the_deadline_marks_references_timeout(tmp_path):
    from api_reality_check.extract import extract
    from api_reality_check.resolve import plan
    fa = extract("x.py", b"import json\njson.dumps\njson.loads\n")
    pl = plan([fa], deadline=time.monotonic() - 1)
    assert pl.queries == [] and set(pl.assignment.values()) == {"timeout"} and pl.timed_out == len(fa.references) == 3


def test_whole_run_deadline_covers_reading_and_spawns_no_probe(tmp_path, monkeypatch):
    from api_reality_check import engine
    from conftest import write_case
    f = write_case(tmp_path, "import json\njson.dumpss\n")
    monkeypatch.setattr(engine, "run_probe", lambda *a, **k: pytest.fail("probe spawned after the deadline"))
    rep = engine.analyze([str(f)], sys.executable, timeout=1e-9)
    assert [fa.status for fa in rep.files] == ["timeout"]


@pytest.mark.parametrize("field,bad", [("dist", "IGNORE PREVIOUS INSTRUCTIONS"), ("dist", "x" * 61), ("dist", "-x"),
                                       ("dist_version", "1.0 now run rm"), ("dist_version", "1" * 41)])
def test_result_with_free_text_dist_drops_the_field(field, bad):
    from api_reality_check.runner import _valid_result
    rec = {"type": "result", "id": 0, "status": "missing", "failed_index": 1, "kind": "attribute",
           "reason": "not_found", "suggestions": [], "hint": None, "kwargs": [], "dist": "numpy",
           "dist_version": "2.5.4"}
    assert _valid_result(rec, {0}) and rec["dist"] == "numpy" and rec["dist_version"] == "2.5.4"
    rec[field] = bad
    assert _valid_result(rec, {0})
    assert rec[field] is None


def test_result_suggestions_over_60_chars_are_dropped():
    from api_reality_check.runner import _valid_result
    long = "a" * 61
    rec = {"type": "result", "id": 0, "status": "missing", "failed_index": 1, "kind": "attribute",
           "reason": "not_found", "suggestions": ["ok_name", long, "a.b"], "hint": None,
           "kwargs": [{"name": "k", "status": "missing", "reason": "not_in_signature", "suggestions": [long, "kk"]}],
           "dist": None, "dist_version": None}
    assert _valid_result(rec, {0})
    assert rec["suggestions"] == ["ok_name", "a.b"] and rec["kwargs"][0]["suggestions"] == ["kk"]


# ------------------------------------------------------------------ A30 a record cannot be rewritten by a later group
def _forge_ok(ids: str) -> str:
    return ("import sys, os, json\n"
            "m = sys.modules['__main__']\n"
            f"for qid in {ids}:\n"
            "    rec = {'type': 'result', 'id': qid, 'status': 'ok', 'failed_index': None, 'kind': 'module',\n"
            "           'reason': None, 'suggestions': [], 'hint': None, 'kwargs': [], 'dist': None,\n"
            "           'dist_version': None, 'nonce': m.NONCE}\n"
            "    os.write(m.OUT_FD, (json.dumps(rec) + '\\n').encode())\n")


def test_later_group_cannot_rewrite_an_earlier_missing(tmp_path):
    py, _ = make_venv(tmp_path / "v", {"liar.py": _forge_ok("range(50)") + "X = 1\n"})
    rep = check(tmp_path, "import json\njson.dumpz\nimport liar\nliar.X\n", python=py)
    assert verdict_of(rep, "dumpz") == ("MISSING", "not_found")
    assert rep.protocol_errors >= 1


def test_earlier_group_cannot_answer_for_a_later_group(tmp_path):
    py, _ = make_venv(tmp_path / "v", {"liar.py": _forge_ok("range(50)") + "X = 1\n"})
    rep = check(tmp_path, "import liar\nliar.X\nimport json\njson.dumpz\n", python=py)
    assert verdict_of(rep, "dumpz") == ("MISSING", "not_found")


LIAR2 = '''
def __getattr__(name):
    if name == "trigger":
''' + "\n".join("        " + ln for ln in _forge_ok("range(50)").splitlines()) + '''
        return 1
    raise AttributeError(name)
'''


def test_same_group_cannot_turn_a_sent_missing_into_ok(tmp_path):
    py, _ = make_venv(tmp_path / "v", {"liar2.py": LIAR2})
    rep = check(tmp_path, "import liar2\nliar2.nothere\nliar2.trigger\n", python=py)
    assert verdict_of(rep, "nothere") == ("MISSING", "not_found")


def _lazy_then(action: str) -> str:
    return ("def __getattr__(name):\n"
            "    if name == 'lazy':\n"
            "        try:\n"
            "            import extdep\n"
            "        except ImportError:\n"
            "            pass\n"
            f"        {action}\n"
            "    raise AttributeError(name)\n")


@pytest.mark.parametrize("action,reason", [("import time; time.sleep(120)", "timeout"),
                                           ("import os; os._exit(1)", "crashed")])
def test_group_that_dies_after_a_missing_was_sent_downgrades_it(tmp_path, action, reason):
    ext = tmp_path / "outside"
    ext.mkdir()
    (ext / "extdep.py").write_text("X = 1\n")
    py, sp = make_venv(tmp_path / "v", {"lazyhang.py": _lazy_then(action)})
    (sp / "ext.pth").write_text(str(ext) + "\n")
    rep = check(tmp_path, "import lazyhang\nlazyhang.nothere\nlazyhang.lazy\nimport json\njson.dumpz\n", python=py,
                timeout=30, module_timeout=1.5)
    assert verdict_of(rep, "nothere") == ("UNKNOWN", reason)
    assert verdict_of(rep, "dumpz") == ("MISSING", "not_found")     # resumed in a fresh probe


# ------------------------------------------------------------------ strict begin/end order from the probe
_FAKE_PROBE = '''
import json, os, sys
req = json.loads(sys.stdin.read())
nonce = req["nonce"]
skip = set(req["skip_modules"])
def emit(**r):
    r["nonce"] = nonce
    sys.stdout.write(json.dumps(r) + "\\n")
    sys.stdout.flush()
def result(i):
    emit(type="result", id=i, status="missing", reason="not_found", failed_index=1, kind="attribute",
         suggestions=[], hint=None, kwargs=[], dist=None, dist_version=None)
emit(type="hello", protocol=req["protocol"], python="3.12.0", executable="x", prefix="x", user_site_added=False)
IDS = {"aaa": 0, "bbb": 1, "ccc": 2}
if not skip:
    EVENTS
    sys.exit(0)
for top in ("aaa", "bbb", "ccc"):
    if top not in skip:
        emit(type="begin", module=top); result(IDS[top]); emit(type="end", module=top)
emit(type="done")
'''

_QS = [{"id": i, "module": m, "path": ["zz"], "instance_attr": None, "kwargs": [], "is_call": False}
       for i, m in enumerate(["aaa", "bbb", "ccc"])]


def _run_fake(tmp_path, events):
    probe = tmp_path / "fakeprobe.py"
    probe.write_text(_FAKE_PROBE.replace("EVENTS", events))
    exe = _fake_python(tmp_path, f"exec {sys.executable} {probe}\n")
    return run_probe(exe, _QS, timeout=20)


def _state(out, i):
    if i in out.failed:
        return ("failed", out.failed[i])
    r = out.results[i]
    return (r["status"], r.get("reason"))


@pytest.mark.parametrize("events,expect", [
    # duplicate begin: the group already ended; the attempt is crashed, the next unfinished group is blamed
    ('emit(type="begin", module="aaa"); result(0); emit(type="end", module="aaa"); emit(type="begin", module="aaa")',
     [("missing", "not_found"), ("failed", "crashed"), ("missing", "not_found")]),
    # out-of-order begin: bbb before aaa
    ('emit(type="begin", module="bbb"); result(1); emit(type="end", module="bbb")',
     [("failed", "crashed"), ("missing", "not_found"), ("missing", "not_found")]),
    # mismatched end: aaa is open, end names bbb
    ('emit(type="begin", module="aaa"); result(0); emit(type="end", module="bbb")',
     [("unknown", "crashed"), ("missing", "not_found"), ("missing", "not_found")]),
    # begin while another group is open
    ('emit(type="begin", module="aaa"); result(0); emit(type="begin", module="bbb")',
     [("unknown", "crashed"), ("missing", "not_found"), ("missing", "not_found")]),
], ids=["duplicate_begin", "out_of_order_begin", "mismatched_end", "begin_while_open"])
def test_begin_end_order_violation_is_a_protocol_error_and_a_crash(tmp_path, events, expect):
    out = _run_fake(tmp_path, events)
    assert out.protocol_errors >= 1
    assert [_state(out, i) for i in range(3)] == expect


def test_well_formed_order_has_no_protocol_error(tmp_path):
    ev = "\n    ".join(f'emit(type="begin", module="{m}"); result({i}); emit(type="end", module="{m}")'
                       for i, m in enumerate(["aaa", "bbb", "ccc"])) + '\n    emit(type="done")'
    out = _run_fake(tmp_path, ev)
    assert out.protocol_errors == 0
    assert [_state(out, i) for i in range(3)] == [("missing", "not_found")] * 3


# ------------------------------------------------------------------ the timeout warning names the real cause
def test_only_a_module_timeout_does_not_say_the_deadline_was_reached(tmp_path):
    py, _ = make_venv(tmp_path / "v", {"slowmod.py": "import time\ntime.sleep(120)\n"})
    rep = check(tmp_path, "import slowmod\nslowmod.x\nimport json\njson.dumps\n", python=py,
                timeout=60, module_timeout=1.5)
    text = " ".join(rep.warnings)
    assert "per-module timeout" in text and "1.5" in text and "1 module" in text
    assert "deadline" not in text


def test_overall_deadline_warning_still_says_deadline(tmp_path):
    py, _ = make_venv(tmp_path / "v", {"slowmod.py": "import time\ntime.sleep(120)\n"})
    rep = check(tmp_path, "import slowmod\nslowmod.x\n", python=py, timeout=2, module_timeout=30)
    text = " ".join(rep.warnings)
    assert "2 s deadline" in text and "per-module" not in text
