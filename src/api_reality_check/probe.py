"""api-reality-check probe (DESIGN §4.4, §5, §14 A2/A4/A6).

Runs INSIDE the target interpreter as ``python -I -S probe.py``. Stdlib only, Python 3.9 syntax,
imports nothing from the api_reality_check package. Reads one JSON request on stdin and writes
nonce-tagged JSON Lines on a private duplicate of fd 1; fd 1 itself is pointed at stderr so that
anything an imported library prints cannot corrupt the protocol stream.

Library modules ARE imported here (that is the probe); the user's code never is. No check calls
a library function.
"""
import os
import sys

if sys.version_info < (3, 9):
    sys.stderr.write("api-reality-check probe: needs Python >= 3.9\n")
    sys.exit(5)


def _private_out():
    fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return fd


OUT_FD = _private_out()

import difflib  # noqa: E402
import importlib  # noqa: E402
import importlib.machinery  # noqa: E402
import importlib.util  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402
import keyword  # noqa: E402
import site  # noqa: E402
import sysconfig  # noqa: E402
import types  # noqa: E402
import warnings  # noqa: E402

PROTOCOL = 1
MAX_REQUEST = 4 * 1024 * 1024
MAX_COMPONENTS = 20
MAX_NAME = 100
DENY_ANY = frozenset({
    "antigravity", "this", "__hello__", "__phello__", "idlelib",
    "test", "tests", "_examples", "examples", "conftest", "setup", "__main__",
})
_C_METHOD_TYPES = (
    types.BuiltinFunctionType, types.MethodDescriptorType, types.WrapperDescriptorType,
    types.MethodWrapperType, types.ClassMethodDescriptorType,
)

NONCE = ""
HINT_CHARS = 200
N_SUGGEST = 3


def emit(obj):
    obj["nonce"] = NONCE
    data = (json.dumps(obj, separators=(",", ":"), default=str) + "\n").encode("utf-8", "replace")
    while data:
        n = os.write(OUT_FD, data)
        data = data[n:]


def clean_hint(e):
    try:
        text = "%s: %s" % (type(e).__name__, e)
    except BaseException:
        text = type(e).__name__
    text = "".join(ch if ch.isprintable() else " " for ch in text)
    return " ".join(text.split())[:HINT_CHARS]


# ---------------------------------------------------------------------------------------------
# start-up
# ---------------------------------------------------------------------------------------------
def venv_config():
    """What site.venv() would find, read without running anything: (prefix, include_system_site, home)
    for a venv interpreter, else None."""
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    site_prefix = os.path.dirname(exe_dir)
    for conf in (os.path.join(exe_dir, "pyvenv.cfg"), os.path.join(site_prefix, "pyvenv.cfg")):
        if os.path.isfile(conf):
            break
    else:
        return None
    include, home = True, None
    try:
        with open(conf) as f:
            for line in f:
                if "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip().lower(), v.strip()
                if k == "include-system-site-packages":
                    include = v.lower() == "true"
                elif k == "home":
                    home = v
    except (OSError, UnicodeDecodeError):
        return None
    return site_prefix, include, home


def user_site_wanted(venv):
    """User site-packages iff this interpreter would add it without -I (DESIGN §5.2, M19)."""
    if venv is not None and not venv[1]:
        return False
    if hasattr(os, "getuid") and (os.getuid() != os.geteuid() or os.getgid() != os.getegid()):
        return False
    return True


def site_dirs():
    """The site directories `site` would add, in its order, computed under -S so that no .pth file is
    executed (F1b). Sets sys.prefix to the venv like site.venv() does. Returns (dirs, user_site)."""
    venv = venv_config()
    base = [sys.prefix, sys.exec_prefix]
    if venv is not None:
        sys.prefix = sys.exec_prefix = venv[0]
        sys._home = venv[2]
        prefixes = [venv[0]] + (base if venv[1] else [])
    else:
        prefixes = base
    dirs = []
    cands = list(site.getsitepackages(prefixes))
    paths = sysconfig.get_paths(vars={"base": sys.prefix, "platbase": sys.exec_prefix})
    cands += [paths.get("purelib"), paths.get("platlib")]
    user = None
    if user_site_wanted(venv):
        try:
            user = site.getusersitepackages()
        except BaseException:
            user = None
        cands.append(user)
    for d in cands:
        if d and os.path.isdir(d) and d not in dirs:
            dirs.append(d)
    return dirs, (user if user in dirs else None)


ROOTS = []
OUTSIDE_PATHS = []      # .pth path lines that point outside ROOTS: never on sys.path
FRONT_OUTSIDE = []      # outside directories a .pth line puts before site-packages (A25): they shadow
PTH_FILES = []          # every .pth file found in a site directory (read as text, never executed)
PTH_IMPORTS = []        # (sitedir, line) for every .pth import line (A19: machinery we did not run)
SITE_DIRS = []
STDLIB_DIRS = []        # the -I -S sys.path: the interpreter's own standard library
_READ_SITEDIRS = set()  # site directories whose .pth files were read


def _under_roots(path):
    rp = os.path.realpath(path)
    for r in ROOTS:
        if rp == r or rp.startswith(r.rstrip(os.sep) + os.sep):
            return True
    return False


def read_pth(sitedir):
    """site.addpackage() as text: returns the path lines (absolute, existing). Import lines are never run."""
    out = []
    if sitedir in _READ_SITEDIRS:
        return out
    _READ_SITEDIRS.add(sitedir)
    try:
        names = sorted(n for n in os.listdir(sitedir) if n.endswith(".pth") and not n.startswith("."))
    except OSError:
        return out
    for n in names:
        fn = os.path.join(sitedir, n)
        PTH_FILES.append(fn)
        try:
            with open(fn, "rb") as f:
                text = f.read(1024 * 1024).decode("utf-8", "replace")
        except OSError:
            continue
        for line in text.splitlines():
            if line.startswith(("import ", "import\t")):
                PTH_IMPORTS.append((sitedir, line))
                continue
            if line.startswith("#") or not line.strip():
                continue
            p = os.path.abspath(os.path.join(sitedir, line.rstrip()))
            if os.path.exists(p) and p not in out:
                out.append(p)
    return out


def setup_path():
    """Build sys.path by hand (the probe runs with -I -S) and restrict it to ROOTS (F1b, F2)."""
    global ROOTS
    initial = list(sys.path)          # interpreter-owned: -I -S leaves only the stdlib entries
    STDLIB_DIRS[:] = [p for p in initial if p]
    dirs, user = site_dirs()
    SITE_DIRS[:] = dirs
    paths = sysconfig.get_paths(vars={"base": sys.prefix, "platbase": sys.exec_prefix})
    roots = set(p for p in initial if p)
    roots.update(p for p in (paths.get(k) for k in ("stdlib", "platstdlib", "purelib", "platlib")) if p)
    roots.update(dirs)
    ROOTS = sorted(set(os.path.realpath(r) for r in roots))
    new = [p for p in initial if p]
    for d in dirs:
        if d not in new:
            new.append(d)
        for p in read_pth(d):
            if _under_roots(p):
                if p not in new:
                    new.append(p)
            elif p not in OUTSIDE_PATHS:
                OUTSIDE_PATHS.append(p)
    sys.path[:] = [p for p in new if _under_roots(p)]
    scan_pth_imports()
    sys.path_importer_cache.clear()
    return user


def add_pth_dir(d, sitedir=False, front=False):
    """A25: a directory that a .pth import line adds with a constant string, applied as site would: inside
    ROOTS it goes on sys.path, outside it is an outside path. For addsitedir() its .pth files are read too."""
    if not os.path.exists(d):
        return
    if _under_roots(d):
        if d not in sys.path:
            if front:
                sys.path.insert(0, d)
            else:
                sys.path.append(d)
        if sitedir and d not in SITE_DIRS:
            SITE_DIRS.append(d)
    else:
        if d not in OUTSIDE_PATHS:
            OUTSIDE_PATHS.append(d)
        if front and d not in FRONT_OUTSIDE:
            FRONT_OUTSIDE.append(d)
    if sitedir and os.path.isdir(d):
        for p in read_pth(d):
            add_pth_dir(p)


def _locations(spec):
    locs = []
    if spec.origin and getattr(spec, "has_location", False):
        locs.append(spec.origin)
    if spec.submodule_search_locations:
        locs.extend(list(spec.submodule_search_locations))
    return locs


def origin_ok(spec):
    """§14 A6: only import code that lives inside this interpreter's own installation."""
    if spec.origin in ("built-in", "frozen"):
        return True
    locs = _locations(spec)
    if not locs:
        return False
    return all(_under_roots(p) for p in locs)


class OutsideEnv(ModuleNotFoundError):
    """A ModuleNotFoundError, so that a library's `except ModuleNotFoundError:` fallback still works."""


REFUSED = set()     # names refused while importing the current module group (A21)
OUTSIDE_META = [False]  # package metadata is on an outside path (A29), set at start-up
META_SEEN = [False]     # a metadata look-up in the current group found outside metadata (A29)
_QUIET = [0]        # > 0 while the probe itself looks a name up: that is not a library's optional import


def _refused(name):
    if not _QUIET[0]:
        REFUSED.add(name)


class RootGuard(object):
    """First on sys.meta_path (F2): any import, including a library's own optional imports
    (`try: import simplejson`), is refused when its file or package path is outside ROOTS. A spec
    without any location (six.moves and similar finder-made modules) comes from code that is
    already running here and is allowed."""

    @classmethod
    def find_spec(cls, name, path=None, target=None):
        if path is None and FRONT_OUTSIDE and outside_has([name], FRONT_OUTSIDE):
            # A25: at run time a directory before site-packages provides this module, not the installed copy.
            _refused(name)
            raise OutsideEnv("%s is outside the target environment" % name, name=name)
        for finder in list(sys.meta_path):
            if finder is cls or finder is OutsideRecorder:
                continue
            fs = getattr(finder, "find_spec", None)
            if fs is None:
                continue
            spec = fs(name, path, target)
            if spec is None:
                continue
            if spec.origin not in ("built-in", "frozen") and not all(_under_roots(p) for p in _locations(spec)):
                _refused(name)
                raise OutsideEnv("%s is outside the target environment" % name, name=name)
            return spec
        return None


class OutsideRecorder(object):
    """Last on sys.meta_path (A21): a name that no finder found here but that exists under a .pth path
    outside ROOTS would import when the user runs the program. Record it and refuse it, so that the
    names the importing module defines only on success are not reported MISSING."""

    @classmethod
    def find_spec(cls, name, path=None, target=None):
        if outside_has(name.split(".")):
            _refused(name)
            raise OutsideEnv("%s is outside the target environment" % name, name=name)
        return None

    @classmethod
    def find_distributions(cls, context=None):
        """A29: importlib.metadata asks every finder on sys.meta_path. A distribution that only an outside
        path holds is found when the user runs the program, so a library can define names only if it is
        there. Record the look-up as a refusal; find nothing. Reads metadata files only."""
        if _QUIET[0] or not OUTSIDE_META[0]:
            return iter(())
        try:
            import importlib.metadata as md
            if getattr(context, "path", sys.path) is not sys.path:
                return iter(())     # an explicit path, not sys.path: the run-time answer is the same
            name = getattr(context, "name", None)
            if name is None:
                found = True        # distributions(): lists every distribution, the outside ones too
            else:
                ctx = md.DistributionFinder.Context(name=name, path=list(OUTSIDE_PATHS))
                found = any(True for _ in md.MetadataPathFinder.find_distributions(ctx))
        except KeyboardInterrupt:
            raise
        except BaseException:
            found = True
        if found:
            META_SEEN[0] = True
            _refused("metadata:%s" % (name or "*"))
        return iter(())


# ---------------------------------------------------------------------------------------------
# names a .pth / editable install / dist-info may provide (F1b): not found -> UNKNOWN, never MISSING
# ---------------------------------------------------------------------------------------------
_PTH_NAMES = None


def _identifiers(text):
    out = set()
    word = []
    for ch in text + " ":
        if ch.isalnum() or ch == "_":
            word.append(ch)
        else:
            if word:
                w = "".join(word)
                if w.isidentifier():
                    out.add(w)
                word = []
    return out


def _string_constants(source):
    import ast
    out = set()
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return _identifiers(source)
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            top = n.value.split(".")[0]
            if top.isidentifier():
                out.add(top)
    return out


_PTH_OPAQUE = False
# A .pth import line runs this module, which provides a name that no string in it spells out.
PTH_ALIASES = {"_distutils_hack": ("distutils",)}


MAX_EXEC_DEPTH = 5


def _abs_const(n):
    """An absolute path written as one string constant, else None."""
    import ast
    if isinstance(n, ast.Constant) and isinstance(n.value, str) and os.path.isabs(n.value):
        return n.value
    return None


def _path_effects(tree):
    """A25: how code changes sys.path, read with ast. Returns (dirs, opaque). dirs: (dir, is_sitedir, front) for
    each sys.path.append/insert(0, ...)/extend and site.addsitedir() call whose path arguments are all absolute
    string constants. opaque: some other change to sys.path (a computed or relative path, an assignment, an
    insert at another index), so the probe cannot know which directories the program searches."""
    import ast
    aliases = set()     # `from sys import path [as p]`, `p = sys.path`
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "sys" and not n.level:
            aliases.update(a.asname or "path" for a in n.names if a.name == "path")
        elif isinstance(n, ast.Assign) and isinstance(n.value, ast.Attribute) and n.value.attr == "path":
            aliases.update(t.id for t in n.targets if isinstance(t, ast.Name))

    def is_path(n):
        return (isinstance(n, ast.Attribute) and n.attr == "path") or (isinstance(n, ast.Name) and n.id in aliases)

    dirs, opaque = [], False
    for n in ast.walk(tree):
        if isinstance(n, ast.AugAssign) and is_path(n.target):    # `path += [...]` changes the list itself
            opaque = True
        if isinstance(n, (ast.Attribute, ast.Subscript)) and isinstance(n.ctx, ast.Store):
            if is_path(n.value if isinstance(n, ast.Subscript) else n):
                opaque = True
            continue
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        fname = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
        if fname == "addsitedir":
            p = _abs_const(n.args[0]) if n.args else None
            if p is None:
                opaque = True
            else:
                dirs.append((p, True, False))
        elif fname in ("append", "insert", "extend") and is_path(f.value):
            a = n.args
            if fname == "append" and len(a) == 1 and _abs_const(a[0]) and not n.keywords:
                dirs.append((_abs_const(a[0]), False, False))
            elif fname == "insert" and len(a) == 2 and isinstance(a[0], ast.Constant) and a[0].value == 0 \
                    and _abs_const(a[1]) and not n.keywords:
                dirs.append((_abs_const(a[1]), False, True))
            elif fname == "extend" and len(a) == 1 and isinstance(a[0], (ast.List, ast.Tuple)) and a[0].elts \
                    and all(_abs_const(e) for e in a[0].elts) and not n.keywords:
                dirs.extend((_abs_const(e), False, False) for e in a[0].elts)
            else:
                opaque = True
    return dirs, opaque


def _pth_line_modules(line, depth=0):
    """The modules a .pth import line imports, whether it may import others we cannot name or change sys.path in
    a way we cannot follow, and the constant directories it adds (A25). exec/eval/compile of a string constant
    is read the same way (A26)."""
    import ast
    try:
        tree = ast.parse(line)
    except (SyntaxError, ValueError):
        return [], False, []    # site's exec() fails on it too: nothing runs
    mods = []
    dirs, opaque = _path_effects(tree)
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods.extend(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            if n.level or not n.module:
                opaque = True
            else:
                mods.append(n.module)
        elif isinstance(n, ast.Call):
            f = n.func
            fname = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if fname in ("__import__", "import_module"):
                arg = n.args[0] if n.args else None
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    mods.append(arg.value)
                else:
                    opaque = True
            elif fname in ("exec", "eval", "compile"):
                arg = n.args[0] if n.args else None
                code = arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, (str, bytes)) else None
                if code is None or depth >= MAX_EXEC_DEPTH:
                    opaque = True
                    continue
                if isinstance(code, bytes):
                    code = code.decode("utf-8", "replace")
                m2, o2, d2 = _pth_line_modules(code, depth + 1)
                mods.extend(m2)
                dirs.extend(d2)
                opaque = opaque or o2
            elif fname in ("exec_module", "load_module", "run_path", "run_module"):
                opaque = True
    return mods, opaque, dirs


def _is_stdlib(top):
    if top in sys.builtin_module_names:
        return True
    try:
        return importlib.machinery.PathFinder.find_spec(top, STDLIB_DIRS) is not None
    except BaseException:
        return False


def _module_source(parts, first_dir):
    """Source text of the module file for `parts`, looked up by stat, or None (missing or compiled)."""
    dirs = []
    for d in [first_dir] + SITE_DIRS + list(sys.path) + OUTSIDE_PATHS:
        if d and d not in dirs:
            dirs.append(d)
    for d in dirs:
        for fn in (os.path.join(d, *parts) + ".py", os.path.join(os.path.join(d, *parts), "__init__.py")):
            if os.path.isfile(fn):
                try:
                    with open(fn, "rb") as f:
                        return f.read(4 * 1024 * 1024).decode("utf-8", "replace")
                except OSError:
                    return None
    return None


def _scan_pth_module(dotted, sitedir):
    """String constants of a module a .pth line runs, and its prefixes (A19), and the constant directories
    they add to sys.path (A25). None: cannot be read, or changes sys.path in a way we cannot follow."""
    import ast
    parts = dotted.split(".")
    if not all(p.isidentifier() for p in parts):
        return None
    if _is_stdlib(parts[0]):
        return set(), []
    names = set(PTH_ALIASES.get(dotted, ()))
    dirs = []
    for i in range(1, len(parts) + 1):
        src = _module_source(parts[:i], sitedir)
        if src is None:
            return None
        try:
            tree = ast.parse(src)
        except (SyntaxError, ValueError):
            return None
        found, opaque = _path_effects(tree)
        if opaque:
            return None
        dirs.extend(found)
        names |= _string_constants(src)
    return names, dirs


_PTH_MODULE_NAMES = set()


def scan_pth_imports():
    """A19/A25, at start-up: read each .pth import line and the modules it runs, never run them. Collects the
    names they spell, sets _PTH_OPAQUE for code we cannot follow, and applies the directories they add to
    sys.path with constant strings (an addsitedir() can add more .pth lines: they are read in turn)."""
    global _PTH_OPAQUE
    i = 0
    while i < len(PTH_IMPORTS):
        sitedir, line = PTH_IMPORTS[i]
        i += 1
        mods, opaque, dirs = _pth_line_modules(line)
        _PTH_OPAQUE = _PTH_OPAQUE or opaque
        for m in mods:
            found = _scan_pth_module(m, sitedir)
            if found is None:
                _PTH_OPAQUE = True
            else:
                _PTH_MODULE_NAMES.update(found[0])
                dirs.extend(found[1])
        for d, is_site, front in dirs:
            add_pth_dir(d, is_site, front)


def pth_names():
    """Top-level names that some site-directory file says exist: identifiers on .pth import lines,
    string constants in the modules those lines import (A19) and in __editable__ finders, dist-info
    top_level.txt and RECORD entries. Text only. _PTH_OPAQUE is set at start-up when a .pth line runs
    code we cannot read (A19 backstop)."""
    global _PTH_NAMES
    if _PTH_NAMES is not None:
        return _PTH_NAMES
    names = set(_PTH_MODULE_NAMES)
    for fn in PTH_FILES:
        try:
            with open(fn, "rb") as f:
                text = f.read(1024 * 1024).decode("utf-8", "replace")
        except OSError:
            continue
        for line in text.splitlines():
            if line.startswith(("import ", "import\t")):
                names |= _identifiers(line)
    for d in SITE_DIRS:
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for e in entries:
            fn = os.path.join(d, e)
            if e.startswith("__editable__"):
                names.add(e.split("-")[0].replace("__editable__.", "").replace("__editable___", ""))
                if e.endswith(".py"):
                    try:
                        with open(fn, "rb") as f:
                            names |= _string_constants(f.read(1024 * 1024).decode("utf-8", "replace"))
                    except OSError:
                        pass
            elif e.endswith((".dist-info", ".egg-info")):
                for meta in ("top_level.txt", "RECORD"):
                    try:
                        with open(os.path.join(fn, meta), "rb") as f:
                            text = f.read(8 * 1024 * 1024).decode("utf-8", "replace")
                    except OSError:
                        continue
                    for line in text.splitlines():
                        first = line.split(",")[0].replace("\\", "/").split("/")[0].strip()
                        top = first.split(".")[0]
                        if top.isidentifier():
                            names.add(top)
    _PTH_NAMES = names
    return names


def _zip_has(archive, parts):
    """A27: a zip or egg file holds a module or package for `parts`. zipimporter reads the archive's
    directory only; nothing in it runs."""
    import zipimport
    try:
        zi = zipimport.zipimporter(os.path.join(archive, *parts[:-1]) if len(parts) > 1 else archive)
        if hasattr(zi, "find_spec"):
            return zi.find_spec(parts[-1]) is not None
        loader, portions = zi.find_loader(parts[-1])     # Python 3.9
        return loader is not None or bool(portions)
    except KeyboardInterrupt:
        raise
    except BaseException:
        return False


def outside_has(parts, dirs=None):
    """By stat: a package directory or module file for the dotted `parts` under a .pth path outside
    ROOTS. For a dotted name this is a namespace portion (PEP 420) or an extend_path() portion (A20).
    A path that is a file is read as a zip or egg archive (A27)."""
    suffixes = importlib.machinery.all_suffixes()
    for d in (OUTSIDE_PATHS if dirs is None else dirs):
        if os.path.isfile(d):
            if _zip_has(d, parts):
                return True
            continue
        base = os.path.join(d, *parts)
        if os.path.isdir(base) or any(os.path.isfile(base + s) for s in suffixes):
            return True
    return False


def not_found_top(name, hint=None):
    """A top-level module the path search did not find (F1b)."""
    if outside_has([name]):
        return Outcome("unknown", "origin_outside_env", hint="module is on a .pth path outside the target environment")
    if name in pth_names() or _PTH_OPAQUE:
        return Outcome("unknown", "pth_configured", hint="a .pth file, editable install or dist-info names it")
    return Outcome("missing", "not_installed", hint=hint)


def not_found_sub(parts, hint=None):
    """A dotted module (2+ parts) whose parent imported but which the path search did not find."""
    if outside_has(parts):
        return Outcome("unknown", "origin_outside_env", hint="module is on a .pth path outside the target environment")
    return Outcome("missing", "not_found", hint=hint)


def validate_module(dotted):
    """Returns None if the dotted name may be imported, else an UNKNOWN reason."""
    parts = dotted.split(".")
    if len(parts) > MAX_COMPONENTS:
        return "invalid_name"
    for i, p in enumerate(parts):
        if not p.isidentifier() or keyword.iskeyword(p) or len(p) > MAX_NAME:
            return "invalid_name"
    for i, p in enumerate(parts):
        if (p.startswith("__") and p.endswith("__")) or p in DENY_ANY or (i > 0 and p.startswith("_")):
            return "denied"
    return None


# ---------------------------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------------------------
class Outcome(object):
    def __init__(self, status, reason=None, hint=None, suggestions=(), value=None, descriptor=False):
        self.status = status          # ok | missing | suspect | unknown
        self.reason = reason
        self.hint = hint
        self.suggestions = list(suggestions)
        self.value = value
        self.descriptor = descriptor  # reached through a non-function descriptor (§14 A4)
        self.static = None            # raw class attribute, for instance calls


def ok(value, descriptor=False):
    return Outcome("ok", value=value, descriptor=descriptor)


def public_names(obj):
    try:
        names = dir(obj)
    except BaseException:
        return []
    return [n for n in names if isinstance(n, str) and n.isidentifier() and not n.startswith("_")]


def close(name, candidates, cutoff):
    try:
        return difflib.get_close_matches(name, candidates, n=N_SUGGEST, cutoff=cutoff)
    except BaseException:
        return []


_MODULES = {}


def import_dotted(dotted):
    """Import a module after validation and the origin check. Cached per process."""
    if dotted in _MODULES:
        return _MODULES[dotted]
    bad = validate_module(dotted)
    if bad:
        out = Outcome("unknown", bad)
    else:
        out = _import_uncached(dotted)
    _MODULES[dotted] = out
    return out


def _import_uncached(dotted):
    parts = dotted.split(".")
    mod = None
    for i in range(1, len(parts) + 1):
        name = ".".join(parts[:i])
        if name in sys.modules:
            # Already imported by code that ran here (os.path is posixpath, typing.io is a class):
            # use it for every part, the last included, before any __path__ check (R1).
            mod = sys.modules[name]
            if mod is None:
                return Outcome("unknown", "import_error", hint="%s is blocked in sys.modules" % name)
            spec = getattr(mod, "__spec__", None)
            if spec is not None and (getattr(spec, "origin", None) is not None
                                     or getattr(spec, "submodule_search_locations", None)) and not origin_ok(spec):
                return Outcome("unknown", "origin_outside_env", hint="module file is outside the target environment")
            continue
        if i > 1:
            parent = sys.modules.get(".".join(parts[:i - 1]))
            if parent is not None and not hasattr(parent, "__path__"):
                return Outcome("missing", "not_installed" if i == 1 else "not_found",
                               hint="%s is not a package" % ".".join(parts[:i - 1]))
        _QUIET[0] += 1
        try:
            spec = importlib.util.find_spec(name)
        except OutsideEnv:
            return Outcome("unknown", "origin_outside_env", hint="module file is outside the target environment")
        except ModuleNotFoundError as e:
            return not_found_top(name, clean_hint(e)) if i == 1 else not_found_sub(parts[:i], clean_hint(e))
        except KeyboardInterrupt:
            raise
        except BaseException as e:
            return Outcome("unknown", "import_error", hint=clean_hint(e))
        finally:
            _QUIET[0] -= 1
        if spec is None:
            return not_found_top(name) if i == 1 else not_found_sub(parts[:i])
        if name not in sys.modules and not origin_ok(spec):
            return Outcome("unknown", "origin_outside_env", hint="module file is outside the target environment")
        try:
            mod = importlib.import_module(name)
        except ModuleNotFoundError as e:
            if e.name == name:
                return not_found_top(name, clean_hint(e)) if i == 1 else not_found_sub(parts[:i], clean_hint(e))
            return Outcome("unknown", "import_error", hint=clean_hint(e))
        except KeyboardInterrupt:
            raise
        except BaseException as e:
            return Outcome("unknown", "import_error", hint=clean_hint(e))
    return ok(mod)


def _defines(klass, names):
    d = getattr(klass, "__dict__", {})
    return any(n in d for n in names)


def module_getattr(mod, name):
    try:
        return ok(getattr(mod, name))
    except AttributeError as e:
        err = e
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        return Outcome("unknown", "dynamic_getattr", hint=clean_hint(e))
    hint = clean_hint(err)
    sugg = close(name, public_names(mod), 0.75)
    if hasattr(mod, "__path__") and isinstance(getattr(mod, "__name__", None), str):
        sub = import_dotted(mod.__name__ + "." + name)
        if sub.status == "ok":
            return sub
        if sub.status == "missing":
            return Outcome("missing", "not_found", hint=hint, suggestions=sugg)
        return Outcome(sub.status, sub.reason, hint=sub.hint or hint, suggestions=sugg)
    return Outcome("missing", "not_found", hint=hint, suggestions=sugg)


def _plain_class_attr(static, value):
    return (static is value or isinstance(static, (types.FunctionType, classmethod, staticmethod, type))
            or isinstance(static, _C_METHOD_TYPES))


def class_getattr(cls, name):
    try:
        static = inspect.getattr_static(cls, name)
        found = True
    except AttributeError:
        found = False
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        return Outcome("unknown", "dynamic_getattr", hint=clean_hint(e))
    try:
        value = getattr(cls, name)
    except AttributeError as e:
        if found:
            return Outcome("unknown", "dynamic_getattr", hint=clean_hint(e))
        meta = type(cls)
        if any(_defines(k, ("__getattr__", "__getattribute__")) for k in meta.__mro__ if k not in (type, object)):
            return Outcome("unknown", "dynamic_getattr", hint=clean_hint(e))
        return Outcome("missing", "not_found", hint=clean_hint(e), suggestions=close(name, public_names(cls), 0.75))
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        return Outcome("unknown", "dynamic_getattr", hint=clean_hint(e))
    out = ok(value, descriptor=not (found and _plain_class_attr(static, value)))
    out.static = static if found else None
    return out


def _has_instance_dict(obj):
    try:
        object.__getattribute__(obj, "__dict__")
        return True
    except BaseException:
        return False


def object_getattr(obj, name):
    try:
        return ok(getattr(obj, name))
    except AttributeError as e:
        hint = clean_hint(e)
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        return Outcome("unknown", "dynamic_getattr", hint=clean_hint(e))
    sugg = close(name, public_names(obj), 0.75)
    t = type(obj)
    if any(_defines(k, ("__getattr__", "__getattribute__")) for k in t.__mro__ if k is not object):
        return Outcome("unknown", "dynamic_getattr", hint=hint)
    if _has_instance_dict(obj):
        return Outcome("suspect", "instance_attr_not_on_class", hint=hint, suggestions=sugg)
    return Outcome("missing", "not_found", hint=hint, suggestions=sugg)


def _declared_fields(cls):
    names = set()
    for k in cls.__mro__:
        d = getattr(k, "__dict__", {})
        for key in ("__annotations__", "__dataclass_fields__"):
            try:
                v = d.get(key)
                if isinstance(v, dict):
                    names.update(v)
            except BaseException:
                pass
        try:
            fields = d.get("_fields")
            if isinstance(fields, tuple):
                names.update(f for f in fields if isinstance(f, str))
        except BaseException:
            pass
    return names


def _python_new(klass):
    raw = klass.__dict__.get("__new__")
    if isinstance(raw, staticmethod):
        raw = raw.__func__
    return isinstance(raw, types.FunctionType)


def is_closed(cls):
    """§14 A2: instances provably cannot carry attributes their class does not define."""
    try:
        if cls.__dictoffset__ != 0:
            return False
        for k in cls.__mro__:
            slots = k.__dict__.get("__slots__", ())
            if isinstance(slots, str):
                slots = (slots,)
            if "__dict__" in tuple(slots):
                return False
        for k in cls.__mro__:
            if k is object:
                continue
            if _defines(k, ("__getattr__", "__getattribute__")):
                return False
        for k in cls.__mro__:
            if "__new__" in k.__dict__:
                if k is not object and _python_new(k):
                    return False
                break
        return type(cls).__call__ is type.__call__
    except BaseException:
        return False


def instance_attr(cls, name, is_call=False):
    if not isinstance(cls, type):
        return Outcome("unknown", "not_a_class")
    try:
        static = inspect.getattr_static(cls, name)
        out = ok(static)
        out.static = static
        return out
    except AttributeError:
        pass
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        return Outcome("unknown", "dynamic_getattr", hint=clean_hint(e))
    if name in _declared_fields(cls):
        out = ok(None)
        out.static = None
        return out
    sugg = close(name, public_names(cls), 0.75)
    hint = "%s object has no attribute %s" % (getattr(cls, "__name__", "?"), name)
    if is_closed(cls):
        return Outcome("missing", "not_found", hint=hint, suggestions=sugg)
    if not is_call:  # §14 A2: data attributes set in __init__ are indistinguishable from typos
        return Outcome("unknown", "instance_data_attr", hint=hint, suggestions=sugg)
    return Outcome("suspect", "instance_attr_not_on_class", hint=hint, suggestions=sugg)


# ---------------------------------------------------------------------------------------------
# keyword arguments (§14 A4)
# ---------------------------------------------------------------------------------------------
P = inspect.Parameter


def _code_sig(fn):
    return inspect.signature(fn, follow_wrapped=False)


def _kw(status, reason=None, suggestions=()):
    return {"status": status, "reason": reason, "suggestions": list(suggestions)}


def _param_names(sig, drop):
    params = list(sig.parameters.values())[drop:]
    return params


def _untrusted(obj, kwargs, drop):
    try:
        sig = inspect.signature(obj)
    except KeyboardInterrupt:
        raise
    except BaseException:
        return dict((k, _kw("unknown", "no_signature")) for k in kwargs)
    params = _param_names(sig, drop)
    varkw = any(p.kind == P.VAR_KEYWORD for p in params)
    named = [p.name for p in params if p.kind not in (P.VAR_KEYWORD, P.VAR_POSITIONAL)]
    out = {}
    for k in kwargs:
        if any(p.name == k and p.kind != P.POSITIONAL_ONLY for p in params):
            out[k] = _kw("ok")
        elif varkw:
            out[k] = _kw("unknown", "var_keyword")
        else:
            out[k] = _kw("suspect", "untrusted_signature", close(k, named, 0.6))
    return out


def _function_chain(fn, kwargs, drop):
    """Pure-Python function, following __wrapped__. MISSING only if every function on the chain
    is a real Python function that lacks the kwarg and has no **kwargs."""
    chain = []
    g, seen = fn, set()
    while g is not None and id(g) not in seen and len(chain) < 20:
        seen.add(id(g))
        chain.append(g)
        g = getattr(g, "__wrapped__", None)
    trusted = all(isinstance(c, types.FunctionType) for c in chain) and \
        getattr(fn, "__signature__", None) is None
    sigs = []
    for i, c in enumerate(chain):
        try:
            sigs.append(_code_sig(c) if isinstance(c, types.FunctionType) else inspect.signature(c))
        except KeyboardInterrupt:
            raise
        except BaseException:
            return dict((k, _kw("unknown", "no_signature")) for k in kwargs)
    outer = _param_names(sigs[0], drop)
    named = [p.name for p in outer if p.kind not in (P.VAR_KEYWORD, P.VAR_POSITIONAL)]
    out = {}
    for k in kwargs:
        accepted = False
        varkw_at = None
        posonly = False
        for i, s in enumerate(sigs):
            params = _param_names(s, drop)
            if any(p.name == k and p.kind != P.POSITIONAL_ONLY for p in params):
                accepted = True
                break
            if any(p.kind == P.VAR_KEYWORD for p in params):
                varkw_at = i if varkw_at is None else varkw_at
            if i == 0 and any(p.name == k and p.kind == P.POSITIONAL_ONLY for p in params):
                posonly = True
        if accepted:
            out[k] = _kw("ok")
        elif varkw_at is not None:
            # A **kwargs wrapper (or any **kwargs below it) may accept or rename the kwarg.
            out[k] = _kw("unknown", "var_keyword" if len(chain) == 1 else "wrapper_varkw")
        elif not trusted:
            out[k] = _kw("suspect", "untrusted_signature", close(k, named, 0.6))
        elif posonly:
            out[k] = _kw("missing", "positional_only", close(k, named, 0.6))
        else:
            out[k] = _kw("missing", "not_in_signature", close(k, named, 0.6))
    return out


def _class_call(cls, kwargs):
    if type(cls).__call__ is not type.__call__ or getattr(cls, "__signature__", None) is not None:
        return _untrusted(cls, kwargs, 0)
    parts = []
    new = cls.__new__
    init = cls.__init__
    if new is not object.__new__:
        if isinstance(new, types.FunctionType):
            parts.append(_function_chain(new, kwargs, 1))
        else:
            return _untrusted(cls, kwargs, 0)
    if init is not object.__init__:
        if isinstance(init, types.FunctionType):
            parts.append(_function_chain(init, kwargs, 1))
        else:
            return _untrusted(cls, kwargs, 0)
    if not parts:   # object.__new__ and object.__init__: takes no arguments at all
        return dict((k, _kw("missing", "not_in_signature")) for k in kwargs)
    out = {}
    rank = {"ok": 0, "unknown": 1, "suspect": 2, "missing": 3}
    for k in kwargs:
        # A kwarg is reported only as strongly as the most forgiving part allows.
        out[k] = min((p[k] for p in parts), key=lambda v: rank[v["status"]])
    return out


def check_kwargs(target, kwargs, instance_call, cls=None):
    """target: Outcome of the final object. For instance calls target.static is the raw class
    attribute (from getattr_static) and cls the class."""
    if not kwargs:
        return {}
    if target.descriptor:
        return dict((k, _kw("unknown", "descriptor_callable")) for k in kwargs)
    if instance_call:
        s = target.static
        if s is None:
            return dict((k, _kw("unknown", "no_signature")) for k in kwargs)
        if isinstance(s, staticmethod):
            fn = s.__func__
            return _function_chain(fn, kwargs, 0) if isinstance(fn, types.FunctionType) else _untrusted(fn, kwargs, 0)
        if isinstance(s, classmethod):
            fn = s.__func__
            return _function_chain(fn, kwargs, 1) if isinstance(fn, types.FunctionType) else _untrusted(fn, kwargs, 1)
        if isinstance(s, types.FunctionType):
            return _function_chain(s, kwargs, 1)
        if isinstance(s, type):
            return _class_call(s, kwargs)
        if isinstance(s, (types.MethodDescriptorType, types.WrapperDescriptorType)):
            return _untrusted(s, kwargs, 1)
        if isinstance(s, types.BuiltinFunctionType):
            return _untrusted(s, kwargs, 0)
        return dict((k, _kw("unknown", "descriptor_callable")) for k in kwargs)
    f = target.value
    if isinstance(f, type):
        return _class_call(f, kwargs)
    if isinstance(f, types.MethodType):
        fn = f.__func__
        if isinstance(fn, types.FunctionType):
            return _function_chain(fn, kwargs, 1)
        return _untrusted(f, kwargs, 0)
    if isinstance(f, types.FunctionType):
        return _function_chain(f, kwargs, 0)
    if isinstance(f, types.ModuleType):
        return dict((k, _kw("unknown", "no_signature")) for k in kwargs)
    return _untrusted(f, kwargs, 0)


# ---------------------------------------------------------------------------------------------
# one query
# ---------------------------------------------------------------------------------------------
_DISTS = None


def dist_of(top):
    global _DISTS
    _QUIET[0] += 1
    try:
        import importlib.metadata as md
        if _DISTS is None:
            _DISTS = md.packages_distributions() if hasattr(md, "packages_distributions") else {}
        names = _DISTS.get(top) or []
        if not names:
            return None, None
        return names[0], md.version(names[0])
    except BaseException:
        return None, None
    finally:
        _QUIET[0] -= 1


def result(qid, outcome, index, kwargs=None, top=None):
    dist, ver = dist_of(top) if top else (None, None)
    rec = {"type": "result", "id": qid, "status": outcome.status,
           "failed_index": None if outcome.status == "ok" else index,
           "kind": "module" if index == 0 else "attribute",
           "reason": outcome.reason, "suggestions": outcome.suggestions[:N_SUGGEST],
           "hint": outcome.hint, "kwargs": [], "dist": dist, "dist_version": ver}
    for name, v in (kwargs or {}).items():
        v = dict(v)
        v["name"] = name
        v["suggestions"] = v["suggestions"][:N_SUGGEST]
        rec["kwargs"].append(v)
    return rec


def run_query(q):
    module = q["module"]
    top = module.split(".")[0]
    path = list(q.get("path") or [])
    inst = q.get("instance_attr")
    kwargs = list(q.get("kwargs") or [])
    m = import_dotted(module)
    if m.status != "ok":
        return result(q["id"], m, 0, top=top)
    cur = m
    for i, name in enumerate(path, 1):
        if not (isinstance(name, str) and name.isidentifier()):
            return result(q["id"], Outcome("unknown", "invalid_name"), i, top=top)
        if cur.descriptor:
            return result(q["id"], Outcome("unknown", "descriptor_callable"), i, top=top)
        obj = cur.value
        if isinstance(obj, types.ModuleType):
            nxt = module_getattr(obj, name)
        elif isinstance(obj, type):
            nxt = class_getattr(obj, name)
        else:
            nxt = object_getattr(obj, name)
        if nxt.status != "ok":
            return result(q["id"], nxt, i, top=top)
        cur = nxt
    if inst is not None:
        idx = len(path) + 1
        if not (isinstance(inst, str) and inst.isidentifier()):
            return result(q["id"], Outcome("unknown", "invalid_name"), idx, top=top)
        if cur.descriptor or not isinstance(cur.value, type):
            return result(q["id"], Outcome("unknown", "not_a_class"), idx, top=top)
        ia = instance_attr(cur.value, inst, bool(q.get("is_call")))
        if ia.status != "ok":
            return result(q["id"], ia, idx, top=top)
        kw = check_kwargs(ia, kwargs, True, cur.value) if q.get("is_call") else {}
        if kw and not is_closed(cur.value):
            # R3: an instance of an open class can shadow the method (self.send = ...), so the class
            # attribute's signature is not proof for a call made through the instance.
            for k, v in kw.items():
                if v["status"] == "missing":
                    kw[k] = _kw("suspect", "instance_may_shadow", v["suggestions"])
        return result(q["id"], ia, idx, kw, top=top)
    kw = check_kwargs(cur, kwargs, False) if q.get("is_call") else {}
    return result(q["id"], cur, len(path), kw, top=top)


def outside_metadata():
    """A29: package metadata (a dist-info, egg-info or EGG-INFO, also inside a zip or egg) on an outside path."""
    import zipfile
    for d in OUTSIDE_PATHS:
        if os.path.isfile(d):
            try:
                with zipfile.ZipFile(d) as z:
                    names = z.namelist()
            except KeyboardInterrupt:
                raise
            except BaseException:
                continue
            if any(c.endswith((".dist-info", ".egg-info")) or c == "EGG-INFO" for n in names for c in n.split("/")):
                return True
            continue
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        if any(e.endswith((".dist-info", ".egg-info")) or e == "EGG-INFO" for e in entries):
            return True
    return False


def downgrade_optional(rec, hint, dotted=False):
    """A21: an import was refused while this module group ran, so what the module defines may depend
    on an optional dependency outside the environment. MISSING attributes and kwargs become UNKNOWN.
    With `dotted` (A29), a dotted module that was not found also becomes UNKNOWN."""
    changed = False
    if rec.get("status") == "missing" and (rec.get("kind") == "attribute"
                                           or (dotted and rec.get("reason") == "not_found")):
        rec["status"], rec["reason"], rec["hint"] = "unknown", "optional_dep_outside_env", hint
        changed = True
    for k in rec.get("kwargs") or []:
        if k.get("status") == "missing":
            k["status"], k["reason"] = "unknown", "optional_dep_outside_env"
            changed = True
    return changed


def cross_suggestions(name, modules):
    out = []
    for m in modules:
        mod = sys.modules.get(m)
        if mod is None or not isinstance(name, str):
            continue
        try:
            if name in getattr(mod, "__dict__", {}):
                out.append("%s.%s" % (m, name))
        except BaseException:
            pass
    return out[:N_SUGGEST]


def main():
    global NONCE, HINT_CHARS, N_SUGGEST
    warnings.simplefilter("ignore")
    sys.dont_write_bytecode = True
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except BaseException:
        pass
    raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
    if len(raw) > MAX_REQUEST:
        return 3
    try:
        req = json.loads(raw.decode("utf-8"))
    except ValueError:
        return 4
    if not isinstance(req, dict) or req.get("protocol") != PROTOCOL:
        return 4
    NONCE = str(req.get("nonce", ""))
    limits = req.get("limits") or {}
    HINT_CHARS = int(limits.get("hint_chars", 200))
    N_SUGGEST = int(limits.get("suggestions", 3))
    user_site = setup_path()
    sys.meta_path.insert(0, RootGuard)
    sys.meta_path.append(OutsideRecorder)
    emit({"type": "hello", "protocol": PROTOCOL, "python": "%d.%d.%d" % sys.version_info[:3],
          "executable": sys.executable, "prefix": sys.prefix, "user_site_added": bool(user_site)})
    skip = set(req.get("skip_modules") or [])
    groups = []
    by_top = {}
    for q in req.get("queries") or []:
        top = str(q.get("module", "")).split(".")[0]
        if top not in by_top:
            by_top[top] = []
            groups.append(top)
        by_top[top].append(q)
    misses = []
    tainted = set()     # A28: top-level modules first imported in a group that had a refusal
    OUTSIDE_META[0] = outside_metadata()
    for top in groups:
        if top in skip:
            continue
        emit({"type": "begin", "module": top})
        REFUSED.clear()
        META_SEEN[0] = False
        before = set(sys.modules)
        done = []

        def why():
            if OUTSIDE_META[0] and "pkg_resources" in sys.modules:
                # pkg_resources reads metadata from its own scan of sys.path, not through sys.meta_path (A29).
                META_SEEN[0] = True
                REFUSED.add("metadata:pkg_resources")
            if REFUSED:
                return ("an import or metadata look-up outside the target environment was refused: %s"
                        % ", ".join(sorted(REFUSED)[:3]))
            if top in tainted:
                return "imported in a group where an import from outside the target environment was refused"
            return None

        for q in by_top[top]:
            try:
                rec = run_query(q)
            except KeyboardInterrupt:
                raise
            except BaseException as e:
                rec = result(q.get("id"), Outcome("unknown", "import_error", hint=clean_hint(e)), 0)
            reason = why()
            if reason:
                downgrade_optional(rec, reason, META_SEEN[0] and "." in str(q.get("module", "")))
            emit(rec)
            done.append((q, rec))
        reason = why()
        if REFUSED:
            # A refusal after a record was sent (a lazy import in a later query): send it again. The parent
            # accepts a second record for an id only as this downgrade, and only during this group (A30).
            for q, rec in done:
                if downgrade_optional(rec, reason, META_SEEN[0] and "." in str(q.get("module", ""))):
                    emit(rec)
            tainted.update(m.split(".")[0] for m in set(sys.modules) - before)
        for q, rec in done:
            if rec["status"] in ("missing", "suspect") and rec["failed_index"] and not rec["suggestions"]:
                misses.append((q, rec))
        emit({"type": "end", "module": top})
    cross = req.get("cross_modules") or []
    for q, rec in misses:
        elems = [q["module"]] + list(q.get("path") or []) + ([q["instance_attr"]] if q.get("instance_attr") else [])
        idx = rec["failed_index"]
        fi = q.get("file")
        mods = cross[fi] if isinstance(fi, int) and 0 <= fi < len(cross) and isinstance(cross[fi], list) else []
        top = str(q.get("module", "")).split(".")[0]
        if idx is not None and idx < len(elems):
            s = cross_suggestions(elems[idx], [m for m in mods if m != top])
            if s:
                emit({"type": "suggest", "id": q["id"], "suggestions": s})
    emit({"type": "done"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
