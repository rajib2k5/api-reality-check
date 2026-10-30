"""Import machinery the probe does not run (DESIGN §15 A19-A21). The probe reads `.pth` files as text
and never adds paths outside the environment, so a not-found there is MISSING only when nothing we
skipped could provide the name. Each case was a false MISSING for code that runs."""
import importlib.machinery
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import check, make_venv, verdict_of

SETUPTOOLS_PTH = ("import os; var = 'SETUPTOOLS_USE_DISTUTILS'; enabled = os.environ.get(var, 'local') == 'local'; "
                  "enabled and __import__('_distutils_hack').add_shim(); \n")
DISTUTILS_HACK = '''
import sys, os
class DistutilsMetaFinder:
    def find_spec(self, fullname, path, target=None):
        if path is not None:
            return None
        method_name = 'spec_for_{fullname}'.format(**locals())
        method = getattr(self, method_name, lambda: None)
        return method()
    def spec_for_distutils(self):
        import importlib
        mod = importlib.import_module('setuptools._distutils')
        return None
DISTUTILS_FINDER = DistutilsMetaFinder()
def add_shim():
    DISTUTILS_FINDER in sys.meta_path or sys.meta_path.insert(0, DISTUTILS_FINDER)
'''


def _sentinel_src(sentinel: Path) -> str:
    return f"open({str(sentinel)!r}, 'w').write('PWNED')\n"


# ------------------------------------------------------------------ (a) setuptools' distutils shim
@pytest.mark.skipif(sys.version_info < (3, 12), reason="distutils is still in the stdlib before Python 3.12")
def test_distutils_provided_by_setuptools_pth_shim_is_not_missing(tmp_path):
    py, sp = make_venv(tmp_path / "v", {"_distutils_hack/__init__.py": DISTUTILS_HACK})
    (sp / "distutils-precedence.pth").write_text(SETUPTOOLS_PTH)
    rep = check(tmp_path, "from distutils.version import LooseVersion\nimport distutilz_typo\n", python=py)
    assert verdict_of(rep, "distutils.version", "module") == ("UNKNOWN", "pth_configured")
    # The shim's source was parsed, so a real typo is still MISSING (no backstop).
    assert verdict_of(rep, "distutilz_typo", "module") == ("MISSING", "not_installed")


@pytest.mark.skipif(sys.version_info < (3, 12), reason="distutils is still in the stdlib before Python 3.12")
def test_distutils_hack_alias_without_a_distutils_string(tmp_path):
    py, sp = make_venv(tmp_path / "v", {"_distutils_hack/__init__.py": "def add_shim():\n    pass\n"})
    (sp / "distutils-precedence.pth").write_text(SETUPTOOLS_PTH)
    rep = check(tmp_path, "import distutils\n", python=py)
    assert verdict_of(rep, "distutils", "module") == ("UNKNOWN", "pth_configured")


@pytest.mark.skipif(not (os.path.exists("/usr/lib/python3/dist-packages/distutils-precedence.pth")
                         and os.path.exists("/usr/bin/python3")), reason="needs Debian python3 with setuptools")
def test_distutils_on_system_python_is_not_missing(tmp_path):
    ran = subprocess.run(["/usr/bin/python3", "-c", "from distutils.version import LooseVersion"],
                         capture_output=True, cwd=tmp_path)
    if ran.returncode != 0:
        pytest.skip("distutils is really absent from /usr/bin/python3")
    rep = check(tmp_path, "from distutils.version import LooseVersion\n", python="/usr/bin/python3")
    assert verdict_of(rep, "distutils.version", "module")[0] != "MISSING"


# ------------------------------------------------------------------ (b) hatchling / editables editable install
EDITABLES_IMPL = ("from editables.redirector import RedirectingFinder as F\nF.install()\n"
                  "F.map_module('tinyh', '/nonexistent/tinyh_proj/src/tinyh/__init__.py')")


def test_editables_redirector_module_is_not_missing(tmp_path):
    sentinel = tmp_path / "sentinel"
    py, sp = make_venv(tmp_path / "v", {"_editable_impl_tinyh.py": _sentinel_src(sentinel) + EDITABLES_IMPL})
    (sp / "_editable_impl_tinyh.pth").write_text("import _editable_impl_tinyh")
    rep = check(tmp_path, "import tinyh\ntinyh.f()\nimport tinyhh_typo\n", python=py)
    assert not sentinel.exists()
    assert verdict_of(rep, "tinyh", "module") == ("UNKNOWN", "pth_configured")
    assert verdict_of(rep, "tinyhh_typo", "module") == ("MISSING", "not_installed")


def test_real_hatchling_editable_install_is_not_missing(tmp_path):
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv not on PATH")
    proj = tmp_path / "tinyh_proj"
    (proj / "src" / "tinyh").mkdir(parents=True)
    (proj / "src" / "tinyh" / "__init__.py").write_text("def f():\n    pass\n")
    (proj / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
        '[project]\nname = "tinyh"\nversion = "0.1"\n'
        '[tool.hatch.build.targets.wheel]\npackages = ["src/tinyh"]\n'
        '[tool.hatch.build]\ndev-mode-exact = true\n')
    py, sp = make_venv(tmp_path / "v")
    inst = subprocess.run([uv, "pip", "install", "--offline", "--no-deps", "--python", py, "-e", str(proj)],
                          capture_output=True, text=True, timeout=180)
    if inst.returncode != 0:
        pytest.skip(f"hatchling not resolvable offline: {inst.stderr[-300:]}")
    assert (sp / "_editable_impl_tinyh.pth").exists(), sorted(os.listdir(sp))
    rep = check(tmp_path, "import tinyh\ntinyh.f()\n", python=py)
    assert verdict_of(rep, "tinyh", "module") == ("UNKNOWN", "pth_configured")


# ------------------------------------------------------------------ backstop: .pth code we cannot read
@pytest.mark.parametrize("files", [{}, {"opaque_hook.pyc": ""},
                                   {"opaque_hook" + importlib.machinery.EXTENSION_SUFFIXES[0]: ""}])
def test_pth_import_of_unreadable_module_makes_every_not_found_unknown(tmp_path, files):
    py, sp = make_venv(tmp_path / "v", files)
    (sp / "hook.pth").write_text("import opaque_hook; opaque_hook.install()\n")
    rep = check(tmp_path, "import anything_at_all\n", python=py)
    assert verdict_of(rep, "anything_at_all", "module") == ("UNKNOWN", "pth_configured")


def test_pth_import_of_stdlib_module_only_does_not_trigger_backstop(tmp_path):
    py, sp = make_venv(tmp_path / "v")
    (sp / "std.pth").write_text("import os, sys; import importlib.util\n")
    rep = check(tmp_path, "import anything_at_all\n", python=py)
    assert verdict_of(rep, "anything_at_all", "module") == ("MISSING", "not_installed")


# ------------------------------------------------------------------ (c, d) PEP 420 namespace split across a .pth path
@pytest.mark.parametrize("form", ["dir", "py", "ext"])
def test_namespace_portion_outside_the_env_is_not_missing(tmp_path, form):
    sentinel = tmp_path / "sentinel"
    ext = tmp_path / "outside"
    (ext / "nsx").mkdir(parents=True)
    if form == "dir":
        (ext / "nsx" / "b").mkdir()
        (ext / "nsx" / "b" / "__init__.py").write_text(_sentinel_src(sentinel))
    elif form == "py":
        (ext / "nsx" / "b.py").write_text(_sentinel_src(sentinel))
    else:
        (ext / "nsx" / ("b" + importlib.machinery.EXTENSION_SUFFIXES[0])).write_text("")
    py, sp = make_venv(tmp_path / "v", {"nsx/a.py": "X = 1\n"})
    (sp / "nsx_outside.pth").write_text(str(ext) + "\n")
    rep = check(tmp_path, "import nsx.b\nimport nsx.a\nnsx.a.X\nimport nsx.zzz\n", python=py)
    assert not sentinel.exists()
    assert verdict_of(rep, "nsx.b", "module") == ("UNKNOWN", "origin_outside_env")
    assert verdict_of(rep, "nsx.zzz", "module") == ("MISSING", "not_found")


def test_namespace_portion_outside_the_env_as_attribute_is_not_missing(tmp_path):
    ext = tmp_path / "outside"
    (ext / "nsx").mkdir(parents=True)
    (ext / "nsx" / "b.py").write_text("Y = 1\n")
    py, sp = make_venv(tmp_path / "v", {"nsx/a.py": "X = 1\n"})
    (sp / "nsx_outside.pth").write_text(str(ext) + "\n")
    rep = check(tmp_path, "from nsx import b\nfrom nsx import zzz\n", python=py)
    assert verdict_of(rep, "b", "attribute") == ("UNKNOWN", "origin_outside_env")
    assert verdict_of(rep, "zzz", "attribute") == ("MISSING", "not_found")


# ------------------------------------------------------------------ (e) optional dependency outside the env
OPTLIB = '''
try:
    import extdep
except ImportError:
    extdep = None
if extdep is not None:
    def feature():
        pass
    def run(x, fast=False):
        pass
else:
    def run(x):
        pass
def base():
    pass
'''


def test_optional_dependency_outside_the_env_downgrades_its_group(tmp_path):
    sentinel = tmp_path / "sentinel"
    ext = tmp_path / "outside"
    ext.mkdir()
    (ext / "extdep.py").write_text(_sentinel_src(sentinel))
    py, sp = make_venv(tmp_path / "v", {"optlib.py": OPTLIB})
    (sp / "ext.pth").write_text(str(ext) + "\n")
    src = "import optlib\noptlib.feature()\noptlib.run(1, fast=True)\nimport json\njson.dumpz\n"
    rep = check(tmp_path, src, python=py)
    assert not sentinel.exists()
    assert verdict_of(rep, "feature", "attribute") == ("UNKNOWN", "optional_dep_outside_env")
    assert verdict_of(rep, "fast", "kwarg") == ("UNKNOWN", "optional_dep_outside_env")
    # Another group, with no refusal while it was imported, keeps its MISSING.
    assert verdict_of(rep, "dumpz", "attribute") == ("MISSING", "not_found")


def test_optional_import_refused_by_root_guard_downgrades_its_group(tmp_path):
    sentinel = tmp_path / "sentinel"
    ext = tmp_path / "outside"
    ext.mkdir()
    (ext / "planted_dep.py").write_text(_sentinel_src(sentinel))
    lib = (f"import sys\nsys.path.insert(0, {str(ext)!r})\ntry:\n    import planted_dep\n"
           "    def feature():\n        pass\nexcept ImportError:\n    pass\n")
    py, _ = make_venv(tmp_path / "v", {"pathlib_hacker.py": lib})
    rep = check(tmp_path, "import pathlib_hacker\npathlib_hacker.feature\n", python=py)
    assert not sentinel.exists()
    assert verdict_of(rep, "feature", "attribute") == ("UNKNOWN", "optional_dep_outside_env")


LAZYLIB = '''
def __getattr__(name):
    if name == "lazy":
        try:
            import extdep
        except ImportError:
            raise AttributeError(name)
        return extdep
    raise AttributeError(name)
'''


def test_refusal_in_a_later_query_downgrades_records_already_sent(tmp_path):
    ext = tmp_path / "outside"
    ext.mkdir()
    (ext / "extdep.py").write_text("X = 1\n")
    py, sp = make_venv(tmp_path / "v", {"lazylib.py": LAZYLIB})
    (sp / "ext.pth").write_text(str(ext) + "\n")
    rep = check(tmp_path, "import lazylib\nlazylib.nothere\nlazylib.lazy\n", python=py)
    assert verdict_of(rep, "nothere") == ("UNKNOWN", "optional_dep_outside_env")
    assert verdict_of(rep, "lazy") == ("UNKNOWN", "optional_dep_outside_env")


# ------------------------------------------------------------------ R1 origin check for modules already in sys.modules
def test_module_put_in_sys_modules_from_outside_the_env_is_unknown(tmp_path):
    ext = tmp_path / "outside"
    ext.mkdir()
    (ext / "sideloaded.py").write_text("def f():\n    pass\n")
    loader = ("import importlib.util, sys\n"
              f"spec = importlib.util.spec_from_file_location('sideloaded', {str(ext / 'sideloaded.py')!r})\n"
              "m = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(m)\nsys.modules['sideloaded'] = m\n")
    py, _ = make_venv(tmp_path / "v", {"sideloader.py": loader})
    rep = check(tmp_path, "import sideloader\nimport sideloaded\nsideloaded.g\n", python=py)
    assert verdict_of(rep, "sideloaded", "module") == ("UNKNOWN", "origin_outside_env")
    assert verdict_of(rep, "g")[0] != "MISSING"


# ------------------------------------------------------------------ sys.path is restricted to ROOTS
def test_pth_path_outside_the_env_is_not_on_sys_path(tmp_path):
    ext = tmp_path / "outside_marker_dir"
    ext.mkdir()
    lib = "import sys\nif any('outside_marker_dir' in p for p in sys.path):\n    LEAKED = True\nOK = 1\n"
    py, sp = make_venv(tmp_path / "v", {"pathspy.py": lib})
    (sp / "ext.pth").write_text(str(ext) + "\n")
    rep = check(tmp_path, "import pathspy\npathspy.OK\npathspy.LEAKED\n", python=py)
    assert verdict_of(rep, "LEAKED") == ("MISSING", "not_found")


# ------------------------------------------------------------------ (f) `testing` is a public API name
def test_testing_submodule_is_checked_not_denied(tmp_path):
    py, _ = make_venv(tmp_path / "v", {"pubpkg/__init__.py": "", "pubpkg/testing.py": "def assert_equal(a, b):\n    pass\n"})
    rep = check(tmp_path, "import pubpkg.testing\npubpkg.testing.assert_equal\npubpkg.testing.assert_equals\n",
                python=py)
    assert verdict_of(rep, "pubpkg.testing", "module") == ("OK", None)
    assert verdict_of(rep, "assert_equals") == ("MISSING", "not_found")


# ------------------------------------------------------------------ A25 .pth code that changes sys.path (fourth review)
def _runs(py: str, src: str, cwd: Path) -> bool:
    """Ground truth: the user code imports in the venv's own python, with its .pth files run."""
    return subprocess.run([py, "-c", src], cwd=cwd, capture_output=True).returncode == 0


@pytest.mark.parametrize("line", ["import site; site.addsitedir({d!r})\n",
                                  "import sys; sys.path.append({d!r})\n",
                                  "import sys; sys.path.insert(0, {d!r})\n",
                                  "import sys; sys.path.extend([{d!r}])\n"])
def test_pth_line_adding_a_constant_outside_dir_is_not_missing(tmp_path, line):
    sentinel = tmp_path / "sentinel"
    ext = tmp_path / "outside"
    ext.mkdir()
    (ext / "extmod.py").write_text(_sentinel_src(sentinel) + "def f():\n    pass\n")
    py, sp = make_venv(tmp_path / "v")
    (sp / "grow.pth").write_text(line.format(d=str(ext)))
    assert _runs(py, "import extmod; extmod.f()", tmp_path)
    sentinel.unlink()
    rep = check(tmp_path, "import extmod\nextmod.f()\nimport extmod_typo\n", python=py)
    assert not sentinel.exists()
    assert verdict_of(rep, "extmod", "module") == ("UNKNOWN", "origin_outside_env")
    # The added directory is known, so a name that is not in it is still MISSING.
    assert verdict_of(rep, "extmod_typo", "module") == ("MISSING", "not_installed")


def test_pth_line_adding_a_constant_dir_inside_the_env_is_searched(tmp_path):
    py, sp = make_venv(tmp_path / "v", {"extra_dir/inmod.py": "def f():\n    pass\n"})
    (sp / "grow.pth").write_text(f"import sys; sys.path.append({str(sp / 'extra_dir')!r})\n")
    assert _runs(py, "import inmod; inmod.f()", tmp_path)
    rep = check(tmp_path, "import inmod\ninmod.f()\ninmod.g_typo\n", python=py)
    assert verdict_of(rep, "inmod", "module") == ("OK", None)
    assert verdict_of(rep, "g_typo") == ("MISSING", "not_found")


def test_addsitedir_runs_the_pth_files_of_the_added_dir(tmp_path):
    ext, ext2 = tmp_path / "outside", tmp_path / "outside2"
    ext.mkdir()
    ext2.mkdir()
    (ext2 / "deepmod.py").write_text("X = 1\n")
    (ext / "inner.pth").write_text(str(ext2) + "\n")
    py, sp = make_venv(tmp_path / "v")
    (sp / "grow.pth").write_text(f"import site; site.addsitedir({str(ext)!r})\n")
    assert _runs(py, "import deepmod", tmp_path)
    rep = check(tmp_path, "import deepmod\nimport deepmod_typo\n", python=py)
    assert verdict_of(rep, "deepmod", "module") == ("UNKNOWN", "origin_outside_env")
    assert verdict_of(rep, "deepmod_typo", "module") == ("MISSING", "not_installed")


def test_pth_line_putting_an_outside_dir_first_shadows_the_installed_module(tmp_path):
    ext = tmp_path / "outside"
    ext.mkdir()
    (ext / "shadowed.py").write_text("def new():\n    pass\n")
    py, sp = make_venv(tmp_path / "v", {"shadowed.py": "def old():\n    pass\n"})
    (sp / "grow.pth").write_text(f"import sys; sys.path.insert(0, {str(ext)!r})\n")
    assert _runs(py, "import shadowed; shadowed.new()", tmp_path)
    rep = check(tmp_path, "import shadowed\nshadowed.new()\n", python=py)
    assert verdict_of(rep, "shadowed", "module") == ("UNKNOWN", "origin_outside_env")
    assert verdict_of(rep, "new")[0] != "MISSING"


COMPUTED = "os.path.join(sys.prefix, 'extra')"


@pytest.mark.parametrize("line", [
    "import os, sys; sys.path.append(" + COMPUTED + ")\n",
    "import os, sys; sys.path.insert(0, " + COMPUTED + ")\n",
    "import os, sys; sys.path.extend([" + COMPUTED + "])\n",
    "import os, sys; sys.path += [" + COMPUTED + "]\n",
    "import os, sys; sys.path[:0] = [" + COMPUTED + "]\n",
    "import os, sys; sys.path = sys.path + [" + COMPUTED + "]\n",
    "import os, sys, site; site.addsitedir(" + COMPUTED + ")\n",
    "import os, sys; from sys import path; path.append(" + COMPUTED + ")\n",
    "import os, sys; p = sys.path; p.append(" + COMPUTED + ")\n",
    "import os, sys; from sys import path; path += [" + COMPUTED + "]\n",
    "import os, sys; sys.path.append('extra')\n",          # relative: depends on the cwd at run time
])
def test_pth_line_adding_a_computed_dir_makes_not_found_unknown(tmp_path, line):
    py, sp = make_venv(tmp_path / "v")
    extra = Path(py).parent.parent / "extra"
    extra.mkdir()
    (extra / "cmod.py").write_text("X = 1\n")
    (sp / "grow.pth").write_text(line)
    if "'extra')" not in line:
        assert _runs(py, "import cmod", tmp_path)
    rep = check(tmp_path, "import cmod\n", python=py)
    assert verdict_of(rep, "cmod", "module") == ("UNKNOWN", "pth_configured")


BASEHOOK_COMPUTED = "import os, sys\nsys.path.append(os.path.join(os.path.dirname(__file__), 'hooked'))\n"


def test_module_run_by_pth_that_adds_a_computed_dir_makes_not_found_unknown(tmp_path):
    py, sp = make_venv(tmp_path / "v", {"basehook.py": BASEHOOK_COMPUTED, "hooked/hmod.py": "X = 1\n"})
    (sp / "basehook.pth").write_text("import basehook\n")
    assert _runs(py, "import hmod", tmp_path)
    rep = check(tmp_path, "import hmod\n", python=py)
    assert verdict_of(rep, "hmod", "module") == ("UNKNOWN", "pth_configured")


def test_module_run_by_pth_that_adds_a_constant_outside_dir_keeps_recall(tmp_path):
    ext = tmp_path / "outside"
    ext.mkdir()
    (ext / "hmod.py").write_text("X = 1\n")
    py, sp = make_venv(tmp_path / "v", {"basehook.py": f"import sys\nsys.path.append({str(ext)!r})\n"})
    (sp / "basehook.pth").write_text("import basehook\n")
    assert _runs(py, "import hmod", tmp_path)
    rep = check(tmp_path, "import hmod\nimport hmod_typo\n", python=py)
    assert verdict_of(rep, "hmod", "module") == ("UNKNOWN", "origin_outside_env")
    assert verdict_of(rep, "hmod_typo", "module") == ("MISSING", "not_installed")


# ------------------------------------------------------------------ A26 exec of a constant string in a .pth line
PYTEST_COV_PTH = ("import os, sys;exec('if \\'COV_CORE_SOURCE\\' in os.environ:\\n try:\\n  from pytest_cov.embed "
                  "import init\\n  init()\\n except Exception as exc:\\n  sys.stderr.write(\\n    \"pytest-cov: "
                  "Failed to setup subprocess coverage. \"\\n    \"Exception: {0!r}\\\\n\".format(exc)\\n  )')\n")


def test_pytest_cov_style_exec_pth_keeps_top_level_missing(tmp_path):
    py, sp = make_venv(tmp_path / "v", {"pytest_cov/__init__.py": "", "pytest_cov/embed.py": "def init():\n    pass\n"})
    (sp / "pytest-cov.pth").write_text(PYTEST_COV_PTH)
    assert _runs(py, "import json", tmp_path)       # the .pth line is valid Python
    rep = check(tmp_path, "import pandaz\n", python=py)
    assert verdict_of(rep, "pandaz", "module") == ("MISSING", "not_installed")


@pytest.mark.parametrize("line", ["import os; exec(os.environ.get('X', ''))\n",
                                  "import sys; exec('import sys; sys.path.append(sys.prefix)')\n",
                                  "import sys; exec('exec(sys.argv[0])')\n"])
def test_exec_of_code_we_cannot_name_in_pth_makes_not_found_unknown(tmp_path, line):
    py, sp = make_venv(tmp_path / "v")
    (sp / "x.pth").write_text(line)
    rep = check(tmp_path, "import anything_at_all\n", python=py)
    assert verdict_of(rep, "anything_at_all", "module") == ("UNKNOWN", "pth_configured")


def test_exec_constant_that_imports_an_unreadable_module_makes_not_found_unknown(tmp_path):
    py, sp = make_venv(tmp_path / "v")
    (sp / "x.pth").write_text("import sys; exec('import opaque_hook')\n")
    rep = check(tmp_path, "import anything_at_all\n", python=py)
    assert verdict_of(rep, "anything_at_all", "module") == ("UNKNOWN", "pth_configured")


# ------------------------------------------------------------------ A27 zip or egg file on an outside .pth path line
def _make_egg(path: Path, files: dict[str, str]) -> None:
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        for name, src in files.items():
            z.writestr(name, src)


def test_zipped_egg_on_an_outside_pth_path_is_not_missing(tmp_path):
    sentinel = tmp_path / "sentinel"
    ext = tmp_path / "outside"
    ext.mkdir()
    egg = ext / "zlib_demo-1.0-py3.egg"
    _make_egg(egg, {"zmod.py": _sentinel_src(sentinel) + "X = 1\n", "zpkg/__init__.py": "", "zpkg/sub.py": "Y = 1\n",
                    "zns/b.py": "Z = 1\n"})
    py, sp = make_venv(tmp_path / "v", {"zns/a.py": "A = 1\n"})
    (sp / "egg.pth").write_text(str(egg) + "\n")
    assert _runs(py, "import zmod, zpkg.sub, zns.a", tmp_path)
    sentinel.unlink()
    rep = check(tmp_path, "import zmod\nimport zpkg.sub\nimport zns.b\nimport zns.a\nimport zmod_typo\nimport zns.zzz\n",
                python=py)
    assert not sentinel.exists()
    assert verdict_of(rep, "zmod", "module") == ("UNKNOWN", "origin_outside_env")
    assert verdict_of(rep, "zpkg.sub", "module") == ("UNKNOWN", "origin_outside_env")
    assert verdict_of(rep, "zns.b", "module") == ("UNKNOWN", "origin_outside_env")
    assert verdict_of(rep, "zmod_typo", "module") == ("MISSING", "not_installed")
    assert verdict_of(rep, "zns.zzz", "module") == ("MISSING", "not_found")


# ------------------------------------------------------------------ A28 a module tainted by a refusal in an earlier group
LIBFOO = '''
try:
    import fastjson
except ImportError:
    fastjson = None
if fastjson is not None:
    def fast(x):
        return x
'''


def test_module_imported_in_an_earlier_group_with_a_refusal_is_downgraded(tmp_path):
    ext = tmp_path / "outside"
    ext.mkdir()
    (ext / "fastjson.py").write_text("X = 1\n")
    py, sp = make_venv(tmp_path / "v", {"libfoo.py": LIBFOO, "libbar.py": "import libfoo\n"})
    (sp / "ext.pth").write_text(str(ext) + "\n")
    src = "import libbar\nimport libfoo\nlibfoo.fast(1)\nimport json\njson.dumpz\n"
    assert _runs(py, "import libbar, libfoo; libfoo.fast(1)", tmp_path)
    rep = check(tmp_path, src, python=py)
    assert verdict_of(rep, "fast", "attribute") == ("UNKNOWN", "optional_dep_outside_env")
    assert verdict_of(rep, "dumpz", "attribute") == ("MISSING", "not_found")


# ------------------------------------------------------------------ A29 package metadata outside the env
LIBMETA = {
    "version": "import importlib.metadata as md\ntry:\n    md.version('fastjson')\n    def fast():\n        pass\n"
               "except md.PackageNotFoundError:\n    pass\n",
    "distributions": "import importlib.metadata as md\nif 'fastjson' in {d.metadata['Name'] for d in md.distributions()}:\n"
                     "    def fast():\n        pass\n",
}
MPKG = "import importlib.metadata as md\ntry:\n    md.version('fastjson')\nexcept md.PackageNotFoundError:\n    pass\n"


def _outside_meta(tmp_path: Path, form: str) -> Path:
    ext = tmp_path / "outside"
    meta = "Metadata-Version: 2.1\nName: fastjson\nVersion: 1.0\n"
    if form == "dist-info":
        (ext / "fastjson-1.0.dist-info").mkdir(parents=True)
        (ext / "fastjson-1.0.dist-info" / "METADATA").write_text(meta)
        return ext
    ext.mkdir()
    egg = ext / "fastjson-1.0-py3.egg"
    _make_egg(egg, {"EGG-INFO/PKG-INFO": meta, "fastjson.py": "X = 1\n"})
    return egg


@pytest.mark.parametrize("form,lookup", [("dist-info", "version"), ("egg", "version"), ("dist-info", "distributions")])
def test_metadata_look_up_that_finds_outside_metadata_downgrades_its_group(tmp_path, form, lookup):
    entry = _outside_meta(tmp_path, form)
    py, sp = make_venv(tmp_path / "v", {"libmeta.py": LIBMETA[lookup], "mpkg/__init__.py": MPKG})
    (sp / "ext.pth").write_text(str(entry) + "\n")
    assert _runs(py, "import libmeta; libmeta.fast()", tmp_path)
    rep = check(tmp_path, "import libmeta\nlibmeta.fast()\nimport mpkg.zzz\nimport json\njson.dumpz\nimport pandaz\n",
                python=py)
    assert verdict_of(rep, "fast", "attribute") == ("UNKNOWN", "optional_dep_outside_env")
    assert verdict_of(rep, "mpkg.zzz", "module") == ("UNKNOWN", "optional_dep_outside_env")
    # A group with no look-up keeps its MISSING, and no metadata can create a top-level module file.
    assert verdict_of(rep, "dumpz", "attribute") == ("MISSING", "not_found")
    assert verdict_of(rep, "pandaz", "module") == ("MISSING", "not_installed")


def test_metadata_look_up_for_a_name_that_is_nowhere_keeps_missing(tmp_path):
    entry = _outside_meta(tmp_path, "dist-info")
    lib = LIBMETA["version"].replace("fastjson", "notthere")
    py, sp = make_venv(tmp_path / "v", {"libmeta.py": lib})
    (sp / "ext.pth").write_text(str(entry) + "\n")
    rep = check(tmp_path, "import libmeta\nlibmeta.fast()\n", python=py)
    assert verdict_of(rep, "fast", "attribute") == ("MISSING", "not_found")


def test_pkg_resources_with_outside_metadata_downgrades_later_groups(tmp_path):
    entry = _outside_meta(tmp_path, "dist-info")
    py, sp = make_venv(tmp_path / "v", {"pkg_resources/__init__.py": "def get_distribution(name):\n    return name\n",
                                         "usespr.py": "import pkg_resources\nX = 1\n"})
    (sp / "ext.pth").write_text(str(entry) + "\n")
    rep = check(tmp_path, "import usespr\nusespr.nothere\nimport json\njson.dumpz\n", python=py)
    assert verdict_of(rep, "nothere") == ("UNKNOWN", "optional_dep_outside_env")
    assert verdict_of(rep, "dumpz") == ("UNKNOWN", "optional_dep_outside_env")
