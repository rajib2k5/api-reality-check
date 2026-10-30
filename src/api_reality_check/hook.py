"""Claude Code PostToolUse hook (DESIGN §7, §14 A7/A8). Analysis only: reads the edited file,
never modifies anything, always exits 0.

Output: nothing when the file is clean or only UNKNOWN; ``hookSpecificOutput.additionalContext``
when MISSING or SUSPECT findings exist; ``systemMessage`` for refusals and internal errors.
"""
from __future__ import annotations

import json
import os
import stat
import sys

from .engine import analyze
from .extract import MAX_BYTES
from .report import hook_text, sanitize
from .resolve import Policy
from .runner import ProbeError

MAX_STDIN = 10 * 1024 * 1024
TOOLS = frozenset({"Write", "Edit", "MultiEdit"})
HOOK_TIMEOUT = 20.0
ALLOW_ENV = "API_REALITY_CHECK_ALLOW_PROJECT_VENV"


def _emit(out, obj) -> None:
    out.write(json.dumps(obj))
    out.flush()


def _file_ok(path) -> bool:
    if not isinstance(path, str) or not os.path.isabs(path) or not path.endswith(".py"):
        return False
    try:
        st = os.lstat(path)
    except (OSError, ValueError):
        return False
    return stat.S_ISREG(st.st_mode) and st.st_size <= MAX_BYTES


def choose_interpreter(environ) -> tuple[str | None, bool, str | None]:
    """(python, is_fallback, error). Only the user's own environment chooses: never file content,
    never tool input, no auto-discovery of ./.venv."""
    explicit = environ.get("API_REALITY_CHECK_PYTHON")
    if explicit:
        if not os.path.isabs(explicit):
            return None, False, "API_REALITY_CHECK_PYTHON must be an absolute path"
        return os.path.abspath(explicit), False, None
    venv = environ.get("VIRTUAL_ENV")
    if venv:
        if not os.path.isabs(venv):
            return None, False, "VIRTUAL_ENV must be an absolute path"
        return os.path.abspath(os.path.join(venv, "bin", "python")), False, None
    return sys.executable, True, None


def _inside(path: str, root: str) -> bool:
    """Inside the project lexically (abspath) or after resolving symlinks (realpath): either refuses."""
    for conv in (os.path.abspath, os.path.realpath):
        try:
            p, r = conv(path), conv(root)
            if os.path.commonpath([p, r]) == r:
                return True
        except ValueError:
            pass
    return False


def prefix_candidates(python: str) -> list[str]:
    """sys.prefix resolved without running the interpreter: the grandparent of the path as given and
    of its realpath (a symlink outside the project may point into a project venv)."""
    a = os.path.abspath(python)
    out = [os.path.dirname(os.path.dirname(a))]
    try:
        out.append(os.path.dirname(os.path.dirname(os.path.realpath(a))))
    except OSError:
        pass
    return out


def site_candidates(prefix: str) -> list[str]:
    """The site-packages directories of a prefix, found by name without running the interpreter (F6)."""
    out = []
    for lib in ("lib", "lib64"):
        try:
            names = os.listdir(os.path.join(prefix, lib))
        except OSError:
            continue
        for n in names:
            if n.startswith("python3"):
                for sub in ("site-packages", "dist-packages"):
                    d = os.path.join(prefix, lib, n, sub)
                    if os.path.isdir(d):
                        out.append(d)
    return out


def main(stdin=None, stdout=None, environ=None) -> int:
    """Always returns 0 (R5). KeyboardInterrupt and SystemExit keep their meaning."""
    stdout = stdout or sys.stdout
    try:
        return _main(stdin or sys.stdin.buffer, stdout, os.environ if environ is None else environ)
    except Exception as e:  # never break the user's session (RecursionError, MemoryError, bugs)
        try:
            _emit(stdout, {"systemMessage": f"api-reality-check: internal error: {type(e).__name__}"})
        except Exception:
            pass
        return 0


def _main(stdin, stdout, environ) -> int:
    try:
        raw = stdin.read(MAX_STDIN + 1)
        if len(raw) > MAX_STDIN:
            return 0
        data = json.loads(raw)
    except (ValueError, OSError, RecursionError):
        return 0
    if not isinstance(data, dict) or data.get("tool_name") not in TOOLS:
        return 0
    tool_input = data.get("tool_input")
    path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not _file_ok(path):
        return 0
    python, fallback, err = choose_interpreter(environ)
    if err:
        _emit(stdout, {"systemMessage": f"api-reality-check: {err}"})
        return 0
    project = environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd")
    if isinstance(project, str) and project and environ.get(ALLOW_ENV) != "1":
        prefixes = prefix_candidates(python)
        if any(_inside(p, project) for p in prefixes + [d for pre in prefixes for d in site_candidates(pre)]):
            _emit(stdout, {"systemMessage": (
                f"api-reality-check: not run: the interpreter {sanitize(python, 300)} or its site-packages is inside "
                f"the project directory, so modules the agent writes there could run in it. Set {ALLOW_ENV}=1 in your own "
                "settings env to allow it, or point API_REALITY_CHECK_PYTHON at an interpreter outside the project.")})
            return 0
    pythonpath = [p for p in environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    try:
        rep = analyze([path], python, timeout=HOOK_TIMEOUT, module_timeout=10.0,
                      policy=Policy(downgrade_not_installed=fallback, pythonpath=pythonpath))
    except ProbeError as e:
        _emit(stdout, {"systemMessage": f"api-reality-check: {sanitize(str(e), 400)}"})
        return 0
    except Exception as e:  # never break the user's session
        _emit(stdout, {"systemMessage": f"api-reality-check: internal error: {type(e).__name__}"})
        return 0
    if any(fa.status != "analysed" for fa in rep.files):
        return 0
    text = hook_text(rep)
    if text:
        _emit(stdout, {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}})
    return 0
