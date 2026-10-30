"""Locality (DESIGN §4.2, §14 A5). Stat calls only; nothing is imported or read."""
from __future__ import annotations

import os
import sys

ROOT_MARKERS = ("pyproject.toml", "setup.py", "setup.cfg", ".git")
MAX_LEVELS = 10
# Extension-module suffixes are matched loosely: any file named "<top>.<something>.so|pyd".
_MODULE_SUFFIXES = (".py", ".pyc", ".pyd", ".so")
_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ()))


def project_root(file: str) -> str | None:
    d = os.path.dirname(os.path.abspath(file))
    for _ in range(MAX_LEVELS + 1):
        if any(os.path.exists(os.path.join(d, m)) for m in ROOT_MARKERS):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    return None


def _home() -> str | None:
    h = os.path.expanduser("~")
    return os.path.abspath(h) if h and h != "~" else None


def _is_mount_point(d: str) -> bool:
    try:
        return os.path.ismount(d)
    except OSError:
        return True


def _search_dirs(file: str) -> tuple[list[str], set[str]]:
    """The file's directory and every ancestor up to the project root, plus root/src. Without a root the
    walk goes up at most MAX_LEVELS, but stops at the user's home directory and at a mount point, and never
    includes the filesystem root (F5: /sys is not a local module named sys). More directories means more
    UNKNOWN, never a false MISSING.

    Also returns the "system" directories of that list: ancestors outside both the project and the home
    directory, where a stdlib module name is never taken as local."""
    root = project_root(file)
    home = _home()
    d = os.path.dirname(os.path.abspath(file))
    dirs = []
    system = set()
    for i in range(MAX_LEVELS + 1):
        parent = os.path.dirname(d)
        if parent == d:            # the filesystem root itself
            break
        dirs.append(d)
        if root is None and i > 0 and not (home and (d == home or d.startswith(home.rstrip(os.sep) + os.sep))):
            system.add(d)
        if d == root or (root is None and (d == home or _is_mount_point(d))):
            break
        d = parent
    if root is not None:
        dirs.append(os.path.join(root, "src"))
    return dirs, system


class Locality:
    """One run's locality checks, with each directory listed at most once (F4)."""

    def __init__(self):
        self._listing: dict[str, frozenset[str]] = {}
        self._dirs: dict[str, tuple[list[str], set[str]]] = {}

    def _entries(self, directory: str) -> frozenset[str]:
        if directory not in self._listing:
            try:
                self._listing[directory] = frozenset(os.listdir(directory))
            except OSError:
                self._listing[directory] = frozenset()
        return self._listing[directory]

    def dir_has_module(self, directory: str, top: str) -> bool:
        entries = self._entries(directory)
        if top in entries and os.path.isdir(os.path.join(directory, top)):
            return True
        for suffix in _MODULE_SUFFIXES:
            if top + suffix in entries and os.path.isfile(os.path.join(directory, top + suffix)):
                return True
        prefix = top + "."
        return any(e.startswith(prefix) and e.endswith((".so", ".pyd")) for e in entries)

    def is_local_module(self, top: str, file: str) -> bool:
        key = os.path.abspath(file)
        if key not in self._dirs:
            self._dirs[key] = _search_dirs(file)
        dirs, system = self._dirs[key]
        stdlib = top in _STDLIB
        return any(self.dir_has_module(d, top) for d in dirs if not (stdlib and d in system))


def dir_has_module(directory: str, top: str) -> bool:
    return Locality().dir_has_module(directory, top)


def is_local_module(top: str, file: str) -> bool:
    return Locality().is_local_module(top, file)


def pythonpath_has_module(top: str, entries: list[str]) -> bool:
    """§14 A5: a module the user's PYTHONPATH provides is never reported not_installed.
    Checked by stat in the parent; the probe never sees PYTHONPATH (it runs with -I)."""
    return any(e and dir_has_module(e, top) for e in entries)
