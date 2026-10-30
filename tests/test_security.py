"""Isolation of the probe (DESIGN §6, §14 A5/A6). Each planted module writes a sentinel file if it
is ever imported; the assertion is that the sentinel never appears."""
import ast
import sys
from pathlib import Path

import pytest

from api_reality_check import runner
from api_reality_check.resolve import Policy
from conftest import REPO, check, make_venv, verdict_of, write_case
from api_reality_check.engine import analyze


def _evil(sentinel: Path) -> str:
    return f"open({str(sentinel)!r}, 'w').write('PWNED')\n"


def test_module_planted_in_cwd_is_not_imported(tmp_path, monkeypatch):
    sentinel = tmp_path / "sentinel"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "evil_local_module.py").write_text(_evil(sentinel))
    monkeypatch.chdir(cwd)
    rep = check(tmp_path / "elsewhere", "import evil_local_module\n")
    assert not sentinel.exists()
    assert verdict_of(rep, "evil_local_module", "module") == ("MISSING", "not_installed")


def test_module_planted_beside_file_is_local_and_not_imported(tmp_path):
    sentinel = tmp_path / "sentinel"
    f = write_case(tmp_path, "import evil_local_module\nevil_local_module.x\n")
    (f.parent / "evil_local_module.py").write_text(_evil(sentinel))
    rep = analyze([str(f)], sys.executable)
    assert not sentinel.exists()
    assert verdict_of(rep, "evil_local_module", "module") == ("UNKNOWN", "local_module")


def test_pythonpath_module_is_not_imported_and_not_missing(tmp_path, monkeypatch):
    sentinel = tmp_path / "sentinel"
    pp = tmp_path / "pp"
    pp.mkdir()
    (pp / "pp_only_module.py").write_text(_evil(sentinel))
    monkeypatch.setenv("PYTHONPATH", str(pp))
    rep = check(tmp_path / "x", "import pp_only_module\n", policy=Policy(pythonpath=[str(pp)]))
    assert not sentinel.exists()
    assert verdict_of(rep, "pp_only_module", "module") == ("UNKNOWN", "pythonpath_module")


def test_env_secrets_are_not_passed_to_probe(monkeypatch, tmp_path):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s3cr3t")
    env = runner.probe_env(str(tmp_path))
    assert "AWS_SECRET_ACCESS_KEY" not in env and "PYTHONPATH" not in env
    assert env["TMPDIR"] == str(tmp_path)


@pytest.mark.parametrize("modname", ["this", "antigravity", "idlelib", "venv.__main__", "conftest",
                                     "pkg.tests", "json._private", "__hello__", "setup"])
def test_denylisted_module_names_are_never_imported(tmp_path, modname):
    rep = check(tmp_path, f"import {modname}\n")
    assert verdict_of(rep, modname, "module") == ("UNKNOWN", "denied")


def test_denylisted_installed_module_side_effect_absent(tmp_path):
    sentinel = tmp_path / "sentinel"
    py, _ = make_venv(tmp_path / "v", {"conftest.py": _evil(sentinel), "examples/__init__.py": _evil(sentinel)})
    rep = check(tmp_path, "import conftest\nimport examples\n", python=py)
    assert not sentinel.exists()
    assert verdict_of(rep, "conftest", "module") == ("UNKNOWN", "denied")


def test_module_origin_outside_env_is_not_imported(tmp_path):
    """An editable install / .pth path pointing at a project directory (§14 A6)."""
    sentinel = tmp_path / "sentinel"
    ext = tmp_path / "project_src"
    ext.mkdir()
    (ext / "editable_mod.py").write_text(_evil(sentinel) + "def f(): pass\n")
    py, sp = make_venv(tmp_path / "v")
    (sp / "_editable.pth").write_text(str(ext) + "\n")
    rep = check(tmp_path, "import editable_mod\neditable_mod.g\n", python=py)
    assert not sentinel.exists()
    assert verdict_of(rep, "editable_mod", "module") == ("UNKNOWN", "origin_outside_env")


def test_probe_parses_as_python_39():
    src = (REPO / "src" / "api_reality_check" / "probe.py").read_text()
    ast.parse(src, feature_version=(3, 9))


def test_probe_imports_only_stdlib():
    src = (REPO / "src" / "api_reality_check" / "probe.py").read_text()
    tops = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            tops |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            assert n.level == 0
            tops.add(n.module.split(".")[0])
    assert tops <= set(sys.stdlib_module_names), tops - set(sys.stdlib_module_names)


def test_probe_writes_no_bytecode_into_site_packages(tmp_path):
    py, sp = make_venv(tmp_path / "v", {"plainmod.py": "X = 1\n"})
    check(tmp_path, "import plainmod\nplainmod.X\n", python=py)
    assert not (sp / "__pycache__").exists()


# ------------------------------------------------------------------ F1b: the probe runs with -I -S
def test_pth_import_line_in_target_env_never_runs(tmp_path):
    sentinel = tmp_path / "sentinel"
    py, sp = make_venv(tmp_path / "v", {"plainmod.py": "X = 1\n"})
    (sp / "evil.pth").write_text(f"import os; open({str(sentinel)!r}, 'w').write('x')\n")
    rep = check(tmp_path, "import plainmod\nplainmod.X\nplainmod.Y\n", python=py)
    assert not sentinel.exists(), ".pth import line executed in the probe"
    assert verdict_of(rep, "Y") == ("MISSING", "not_found") and rep.target["prefix"] == str(tmp_path / "v" / "venv")


def test_pth_path_line_inside_the_env_is_still_on_the_path(tmp_path):
    py, sp = make_venv(tmp_path / "v", {"extra/inner_mod.py": "def f(): pass\n"})
    (sp / "extra.pth").write_text("extra\n")
    rep = check(tmp_path, "import inner_mod\ninner_mod.f()\ninner_mod.g\n", python=py)
    assert verdict_of(rep, "inner_mod", "module") == ("OK", None)
    assert verdict_of(rep, "g") == ("MISSING", "not_found")


def test_editable_install_module_is_unknown_and_its_finder_never_runs(tmp_path):
    sentinel = tmp_path / "sentinel"
    finder = (f"open({str(sentinel)!r}, 'w').write('x')\n"
              "MAPPING = {'edpkg': '/nonexistent/src/edpkg'}\nNAMESPACES = {}\ndef install(): pass\n")
    py, sp = make_venv(tmp_path / "v", {"__editable___edpkg_0_1_finder.py": finder})
    (sp / "__editable__.edpkg-0.1.pth").write_text(
        "import __editable___edpkg_0_1_finder; __editable___edpkg_0_1_finder.install()\n")
    rep = check(tmp_path, "import edpkg\nedpkg.f()\nimport edpkgg_typo\n", python=py)
    assert not sentinel.exists()
    assert verdict_of(rep, "edpkg", "module") == ("UNKNOWN", "pth_configured")
    assert verdict_of(rep, "edpkgg_typo", "module") == ("MISSING", "not_installed")


def test_module_named_on_a_pth_import_line_is_unknown(tmp_path):
    py, sp = make_venv(tmp_path / "v")
    (sp / "hooked.pth").write_text("import sys; import magic_hooked_mod; magic_hooked_mod.setup()\n")
    rep = check(tmp_path, "import magic_hooked_mod\n", python=py)
    assert verdict_of(rep, "magic_hooked_mod", "module") == ("UNKNOWN", "pth_configured")


@pytest.mark.parametrize("meta,text", [("top_level.txt", "ghostpkg\n"),
                                       ("RECORD", "ghostpkg/__init__.py,sha256=x,1\nghost-1.0.dist-info/RECORD,,\n")])
def test_module_named_by_dist_info_is_unknown(tmp_path, meta, text):
    py, sp = make_venv(tmp_path / "v")
    (sp / "ghost-1.0.dist-info").mkdir()
    (sp / "ghost-1.0.dist-info" / meta).write_text(text)
    rep = check(tmp_path, "import ghostpkg\n", python=py)
    assert verdict_of(rep, "ghostpkg", "module") == ("UNKNOWN", "pth_configured")


# ------------------------------------------------------------------ F2: transitive imports stay in the env
def _planted(tmp_path, sentinel):
    proj = tmp_path / "project_src"
    proj.mkdir()
    (proj / "simplejson.py").write_text(_evil(sentinel))
    (proj / "planted_mod.py").write_text(_evil(sentinel))
    return proj


def test_library_optional_import_does_not_load_a_file_outside_the_env(tmp_path):
    sentinel = tmp_path / "sentinel"
    proj = _planted(tmp_path, sentinel)
    lib = "try:\n    import simplejson as json\nexcept ImportError:\n    import json\nX = json.dumps\n"
    py, sp = make_venv(tmp_path / "v", {"usesjson.py": lib})
    (sp / "_editable_proj.pth").write_text(str(proj) + "\n")
    rep = check(tmp_path, "import usesjson\nusesjson.X\nusesjson.Y\n", python=py)
    assert not sentinel.exists(), "a library's optional import loaded a planted file"
    # A21: simplejson would import when the user runs the program, so what usesjson defines is not proof.
    assert verdict_of(rep, "Y") == ("UNKNOWN", "optional_dep_outside_env")


def test_library_that_extends_sys_path_cannot_import_outside_the_env(tmp_path):
    sentinel = tmp_path / "sentinel"
    proj = _planted(tmp_path, sentinel)
    lib = f"import sys\nsys.path.insert(0, {str(proj)!r})\ntry:\n    import planted_mod\nexcept ImportError:\n    pass\nX = 1\n"
    py, _ = make_venv(tmp_path / "v", {"pathhacker.py": lib})
    rep = check(tmp_path, "import pathhacker\npathhacker.X\n", python=py)
    assert not sentinel.exists()
    assert rep.findings == []
