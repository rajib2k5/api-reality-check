"""Command line (DESIGN §8). Exit 2: usage/internal error, unusable interpreter, or a file that could
not be analysed; else 1 if any MISSING; else 0. SUSPECT never changes the exit code."""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .engine import analyze
from .report import to_json, to_text
from .resolve import Policy
from .runner import ProbeError


def default_python() -> str:
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        cand = os.path.join(venv, "bin", "python")
        if os.path.exists(cand):
            return cand
    return sys.executable


def pythonpath_entries() -> list[str]:
    return [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]


def positive_seconds(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid number: {text!r}") from None
    if not value > 0:  # also rejects nan
        raise argparse.ArgumentTypeError(f"must be > 0, got {text!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="api-reality-check",
        description="Check that the modules, attributes and keyword arguments a Python file uses exist "
                    "in a target interpreter. The files are parsed, never executed.")
    p.add_argument("files", nargs="+", metavar="FILE")
    p.add_argument("--python", help="target interpreter (default: $VIRTUAL_ENV/bin/python, else this Python)")
    p.add_argument("--json", action="store_true", help="machine-readable output (includes UNKNOWN findings)")
    p.add_argument("--timeout", type=positive_seconds, default=30.0, help="time limit in seconds for the whole run: parsing, planning and the probe (default 30)")
    p.add_argument("--module-timeout", type=positive_seconds, default=10.0, help="per-module import budget (default 10)")
    p.add_argument("--show-unknown", action="store_true", help="also print UNKNOWN findings")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    # The probe runs in a private temp cwd: make a relative path absolute here. abspath, never realpath:
    # a venv's python is a symlink and resolving it would lose the venv's site-packages.
    python = os.path.abspath(args.python) if args.python else default_python()
    try:
        rep = analyze(args.files, python, timeout=args.timeout, module_timeout=args.module_timeout,
                      policy=Policy(pythonpath=pythonpath_entries()))
    except ProbeError as e:
        print(f"api-reality-check: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # internal error: never a silent pass
        print(f"api-reality-check: internal error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    sys.stdout.write(to_json(rep) + "\n" if args.json else to_text(rep, args.show_unknown))
    if any(fa.status != "analysed" for fa in rep.files):
        return 2
    return 1 if any(f.verdict == "MISSING" for f in rep.findings) else 0


if __name__ == "__main__":
    sys.exit(main())
