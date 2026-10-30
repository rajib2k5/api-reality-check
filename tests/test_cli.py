import json
import os
import subprocess
import sys

from conftest import REPO, make_venv, write_case


def run_cli(*args, env_extra=None, cwd=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "src")
    env.pop("VIRTUAL_ENV", None)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-m", "api_reality_check", *args], capture_output=True, text=True,
                          env=env, timeout=120, cwd=cwd)


def test_exit_1_and_text_on_missing(tmp_path):
    f = write_case(tmp_path, "import collections\ncollections.OrderedDictt\n")
    p = run_cli(str(f), "--python", sys.executable)
    assert p.returncode == 1, p.stderr
    assert "MISSING attribute `collections.OrderedDictt`" in p.stdout and sys.executable in p.stdout


def test_exit_0_on_clean_and_suspect_does_not_fail(tmp_path):
    f = write_case(tmp_path, "import collections\nd = collections.deque()\nd.appendd(1)\ncollections.OrderedDict\n")
    p = run_cli(str(f), "--python", sys.executable)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "SUSPECT" in p.stdout


def test_json_output(tmp_path):
    f = write_case(tmp_path, "import json\njson.dumpss\n")
    p = run_cli(str(f), "--json", "--python", sys.executable)
    doc = json.loads(p.stdout)
    assert p.returncode == 1
    assert doc["findings"][0]["name"] == "dumpss" and doc["target"]["executable"]
    assert doc["summary"]["missing"] == 1


def test_exit_2_on_syntax_error_file(tmp_path):
    good = write_case(tmp_path, "import json\n", "good.py")
    bad = write_case(tmp_path, "def (:\n", "bad.py")
    p = run_cli(str(good), str(bad), "--python", sys.executable)
    assert p.returncode == 2 and "syntax_error" in p.stdout


def test_exit_2_on_unusable_interpreter(tmp_path):
    f = write_case(tmp_path, "import json\n")
    p = run_cli(str(f), "--python", str(tmp_path / "nope"))
    assert p.returncode == 2 and "nope" in p.stderr


def test_exit_2_on_usage_error():
    assert run_cli().returncode == 2


def test_virtual_env_is_default_interpreter(tmp_path):
    f = write_case(tmp_path, "import json\n")
    venv = os.path.dirname(os.path.dirname(sys.executable))
    p = run_cli(str(f), env_extra={"VIRTUAL_ENV": venv})
    assert p.returncode == 0 and venv in p.stdout


def test_relative_python_path_is_resolved_against_callers_cwd(tmp_path):
    # The probe runs in a private temp cwd, so a relative interpreter path must be made absolute first,
    # and by abspath (not realpath): a venv python is a symlink and resolving it drops the venv's site-packages.
    make_venv(tmp_path / "envs", {"relmod.py": "def real(): pass\n"})
    f = write_case(tmp_path, "import relmod\nrelmod.real()\nrelmod.fake()\n")
    p = run_cli(str(f), "--json", "--python", "envs/venv/bin/python", cwd=str(tmp_path))
    assert p.returncode == 1, p.stdout + p.stderr
    doc = json.loads(p.stdout)
    assert [(x["name"], x["verdict"]) for x in doc["findings"]] == [("fake", "MISSING")]


import pytest  # noqa: E402


@pytest.mark.parametrize("flag,value", [("--timeout", "0"), ("--timeout", "-1"), ("--module-timeout", "0"),
                                        ("--module-timeout", "-5"), ("--timeout", "nan")])
def test_non_positive_timeouts_are_usage_errors(tmp_path, flag, value):
    f = write_case(tmp_path, "import json\n")
    p = run_cli(str(f), "--python", sys.executable, flag, value)
    assert p.returncode == 2 and "must be > 0" in p.stderr, p.stderr
