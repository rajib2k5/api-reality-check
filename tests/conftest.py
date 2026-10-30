import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from api_reality_check.engine import analyze
from api_reality_check.resolve import Policy

REPO = Path(__file__).resolve().parents[1]


def write_case(tmp_path: Path, src: str, name: str = "case.py") -> Path:
    """A file inside its own project root, so locality never looks above tmp_path."""
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "pyproject.toml").write_text("")
    f = proj / name
    f.write_text(textwrap.dedent(src))
    return f


def check(tmp_path, src, python=None, policy=None, timeout=60.0, module_timeout=20.0, name="case.py"):
    f = write_case(tmp_path, src, name)
    rep = analyze([str(f)], python or sys.executable, timeout=timeout, module_timeout=module_timeout,
                  policy=policy or Policy())
    return rep


def verdicts(rep):
    """{(name, kind): (verdict, reason)} for every finding."""
    return {(f.name, f.kind): (f.verdict, f.reason) for f in rep.findings}


def verdict_of(rep, name, kind=None):
    out = [(f.verdict, f.reason) for f in rep.findings if f.name == name and (kind is None or f.kind == kind)]
    return out[0] if out else ("OK", None)


@pytest.fixture
def arc_python():
    p = os.environ.get("ARC_TEST_PYTHON")
    if not p:
        pytest.skip("ARC_TEST_PYTHON not set (needs a venv with numpy 2.5.4, pandas 3.1.0, requests, yfinance)")
    if not os.path.exists(p):
        pytest.skip(f"ARC_TEST_PYTHON={p} does not exist")
    # The probe runs in a private temp cwd, so a relative path must be made absolute here. abspath, not
    # realpath: a venv's python is a symlink and resolving it would lose the venv's site-packages.
    return os.path.abspath(p)


def make_venv(root: Path, modules: dict[str, str] | None = None) -> tuple[str, Path]:
    """Throwaway venv (no pip) with the given modules written into its site-packages."""
    venv = root / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    py = venv / "bin" / "python"
    purelib = subprocess.run([str(py), "-I", "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                             check=True, capture_output=True, text=True).stdout.strip()
    sp = Path(purelib)
    for rel, src in (modules or {}).items():
        target = sp / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(src))
    return str(py), sp


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie still answers kill(0); check its state.
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split()[2] != "Z"
    except OSError:
        return False
