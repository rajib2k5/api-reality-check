# api-reality-check v0.1 — design

Status: design approved for implementation (not yet built). ADR: `docs/adr/0001-static-parse-plus-subprocess-introspection.md`.

## 1. Problem, constraints, non-goals

AI-written Python calls APIs absent from the installed versions: misspelled or invented functions and kwargs,
wrong module paths, real names in the wrong place (`np.DataFrame`). DeepSec checks only package names; this
checks **modules, attributes and kwargs** against a *target* interpreter, automating Channel B of
`evidence-gated-validation` for existence claims while avoiding the traps in `runtime-audit.md` §8.

Constraints: **never execute the user's code** (`ast` only; library modules ARE imported — that is the
probe) · **precision over recall** — a false MISSING on working code is the worst outcome; undecidable ⇒
UNKNOWN · tool Python ≥ 3.10 stdlib-only; probe stdlib-only, Python ≥ 3.9 syntax · hook p95 < 3 s per edit.

Non-goals (v0.1): type inference beyond the one constructor rule (§4.3); return types of functions;
`with X() as y` bindings; `importlib.import_module("...")`/`__import__`/`getattr(m, "name")` strings;
builtins not reached through an import; notebooks and `.pyi`; checking argument *values*, arity or
positional counts; PEP 692 `**kwargs: Unpack[TypedDict]` expansion; a persistent cache; a network
sandbox; Windows process-group kill (best effort only); auto-fixing anything.

## 2. Measured facts this design rests on

Throwaway venv (kept): `/tmp/claude-1000/-home-rajib2k5-dev-api-reality-check/17eecbee-5135-48c9-a278-21ae90413329/scratchpad/evalvenv`
created with `uv 0.11.25`: `uv venv --python 3.12 evalvenv && uv pip install --python evalvenv/bin/python
pandas numpy requests yfinance` → numpy 2.5.4, pandas 3.1.0, requests 2.34.2, yfinance 1.7.0.
Probe scripts: same scratchpad, `probes/{sig,sig2,inst}.py`; all run as `evalvenv/bin/python -I <script>`.

| # | Check | Result | Design consequence |
|---|---|---|---|
| M1 | `inspect.signature` on `pd.DataFrame.rolling`, `pd.DataFrame` (class), `pd.DataFrame.from_dict`, `pd.read_csv`, `np.linspace`, `yf.download` | all OK, no `**kwargs` | kwarg checks are decidable for these |
| M2 | `np.array`, `np.zeros`, `np.add` (ufunc), `np.concatenate`, `np.ndarray.reshape` | **OK** (numpy 2.x ships text signatures) | assumption "np.array is an un-introspectable C builtin" is **false** for numpy 2.5 |
| M3 | `datetime.datetime`, `math.log`, `itertools.islice`, `dict`, `range` | `ValueError: no signature found` | ValueError/TypeError ⇒ UNKNOWN (trap 8.4) |
| M4 | `requests.get`, `requests.Session.get` | `(url, params=None, **kwargs: Unpack[_t.GetKwargs])` | `**kwargs` ⇒ unknown kwargs UNKNOWN; PEP 692 expansion is a v0.2 recall win |
| M5 | `yf.Ticker.history` | `(self, *args, **kwargs)`; real params live on `yfinance.scrapers.history.PriceHistory.history` behind a lazy delegate | kwargs to `Ticker.history` are UNKNOWN (recall cost, accepted) |
| M6 | `yf.download` | has `__wrapped__`; outer wrapper `(*args, **kwargs)` (`log_indent_decorator`, passthrough) | see wrapper rule §4.4 |
| M7 | 17 of 290 public pandas callables have `__wrapped__` (e.g. `DataFrame.mean/std/max`), most with `**kwargs` outer wrappers; `pandas.util._decorators.deprecate_kwarg` still used (`pandas/core/generic.py:4522`, `pandas/_testing/asserters.py`); no case found in these versions where the followed signature lacks the old kwarg — the trap is real in older pandas/sklearn, not demonstrated here | wrapper rule matters in practice |
| M8 | `np.float_`, `np.NaN` → `AttributeError: \`np.float_\` was removed in the NumPy 2.0 release. Use \`np.float64\` instead.`; `np.in1d`, `np.trapz`, `np.product` → plain AttributeError; `numpy` has module `__getattr__`, pandas 3.1 and yfinance do not | module `__getattr__` raising AttributeError ⇒ MISSING; keep its message as a sanitized hint |
| M9 | `import xml; xml.etree` and `import email; email.mime` → getattr fails; `importlib.import_module("xml.etree")` succeeds | try submodule import before MISSING |
| M10 | `concurrent.futures` getattr succeeded only because an earlier import loaded it | batched getattr is order-dependent; the fallback makes verdicts order-independent |
| M11 | `pd.Index(datetimes)` returns `DatetimeIndex`; `pd.Index` has no `tz_localize`; `pd.Timestamp(None)` returns `NaTType` | classes with custom `__new__` ⇒ instance attrs UNKNOWN |
| M12 | `pd.DataFrame` MRO defines `__getattr__` (NDFrame, column access); `inspect.getsource(pd.DataFrame)` → `OSError: could not find class definition` | DataFrame instance attrs not on the class ⇒ UNKNOWN (`df.rolling_mean()` is a recall miss) |
| M13 | `requests.Session().headers` is not a class attribute (set in `__init__`); `Session` source also has `setattr(self, attr, value)` in `__setstate__` | instance attr not on class ⇒ UNKNOWN unless provably impossible (§4.4) |
| M14 | `np.random.Generator.__dictoffset__ == 0`, instance has no `__dict__`; Python classes report `-1` | `__dictoffset__ == 0` and no `__getattr__` ⇒ instance attrs are exactly the type's |
| M15 | `import yfinance` + signatures under `strace -f -e trace=network`; under `-e openat,mkdir`; under a socket guard (`getaddrinfo`/`create_connection`/`connect` raise) | 0 `connect`/`sendto` (one `bind(::1, port 0)`: loopback IPv6 capability check); 962 `openat`, 0 with write flags; guard saw 0 calls | no network or file I/O at import in 1.7.0; eval re-asserts this on every run |
| M18 | `evil_local_module.py` in cwd: `python -c "import evil_local_module"` prints `PWNED`; with `-I` → `ModuleNotFoundError` | `-I` closes the cwd-import attack |
| M19 | `-I` hides user site-packages: `python3 -c "import absl"` OK from `~/.local/...`; `python3 -I -c "import absl"` → ModuleNotFoundError; `site.addsitedir(<user site>)` restores it | **`-I` alone yields false "not installed"** for `pip install --user` packages — probe must re-add user site (§5.2) |
| M20 | `/usr/lib/python3.12/venv/__main__.py` calls `main()` unguarded; `antigravity.py` calls `webbrowser.open` at import | denylist dunder components and known side-effect modules |
| M21 | batched `-I` import of numpy+pandas+requests+yfinance + 6 signatures (`/usr/bin/time`): 0.28 / 0.29 / 0.25 s wall warm, 96 MB max RSS; cold first imports 0.154 + 0.542 + 0.068 + 0.27 s ≈ 1.0 s; bare `-I` startup 0.01 s | one batched subprocess per run; ≈ 0.3–1 s per hook call for these libraries |
| M22 | numpy import spawns ~19 threads (strace) | set `OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=MKL_NUM_THREADS=1` in probe env |
| M23 | difflib (`cutoff=0.75`, public `dir()`): `linspce→linspace`, `read_csvv→read_csv`, `arange_like→[]`; `np.DataFrame` → no same-module match | add cross-module exact-name suggestion (`pandas.DataFrame`) |
| M24 | interpreters present: 3.10.20, 3.11.15, 3.12.3/3.12.13; **no 3.9** | probe 3.9 compatibility is unverified until CI installs 3.9 |

## 3. Architecture and module breakdown

```
FILE.py ──read──▶ extract (ast) ──References──▶ plan (dedupe→Queries) ──JSON stdin──▶ probe.py in target
                                                                                       (python -I, temp cwd)
report ◀── Findings ◀── resolve (guards, locality, wrappers) ◀──JSONL (nonce'd) stdout──┘
```

`src/api_reality_check/`: `models.py` (types below) · `extract.py` `extract(path, source) -> FileAnalysis`
(pure: scopes, bindings, guards, references) · `locality.py` `is_local_module(top, file) -> bool` (stat only) ·
`probe.py` (stdlib-only, 3.9 syntax, imports nothing from the package, run by file path) · `runner.py`
`run_probe(python, queries, timeout, module_timeout) -> ProbeOutcome` (spawn, caps, deadlines, kill, resume) ·
`resolve.py` `resolve(analyses, outcome, policy) -> list[Finding]` · `report.py` (text/JSON, `sanitize`) ·
`cli.py` (console script `api-reality-check = api_reality_check.cli:main`) · `hook.py` (PostToolUse; repo-root
`hooks/post_tool_use.py` is a shim). Packaging: `pyproject.toml`, src layout, MIT, `requires-python >=3.10`,
no runtime deps, dev dep `pytest`.

Interface contracts (`models.py`):
```python
Kind = Literal["module", "attribute", "kwarg"]
Guard = Literal["try_except", "hasattr", "version", "platform"]   # forces UNKNOWN on a miss

@dataclass(frozen=True)
class Loc: line: int; col: int                    # 1-based line, 0-based col, of the identifier that would fail

@dataclass(frozen=True)
class KwargUse: name: str; loc: Loc

@dataclass(frozen=True)
class Reference:
    file: str
    module: str                     # importable dotted module, e.g. "numpy", "xml.etree"
    path: tuple[str, ...]           # attribute chain walked from the module: ("DataFrame", "from_dict")
    path_locs: tuple[Loc, ...]      # one Loc per path element; module_loc for the module itself
    module_loc: Loc
    instance_attr: str | None       # looked up on an INSTANCE of the class at `path` (§4.3)
    instance_loc: Loc | None
    kwargs: tuple[KwargUse, ...]    # explicit keywords at the call on the final object, () if not a call
    is_call: bool
    caller_star_kwargs: bool        # f(**opts) present; recorded, does not change explicit-kwarg checks
    guard: Guard | None
    optional_import: bool           # root import is inside try/except ImportError

@dataclass(frozen=True)
class Finding:
    file: str; line: int; col: int
    verdict: Literal["MISSING", "UNKNOWN"]          # OK is counted, never emitted
    kind: Kind
    name: str                       # failing identifier; for kind=module the dotted module as written
    qualname: str                   # "numpy.linspce", "numpy.linspace(nmu=)", "requests.Session().gett"
    reason: str                     # code from §4.6
    suggestions: tuple[str, ...]    # ≤3, identifiers only
    hint: str | None                # sanitized library error text, ≤200 chars
    dist: str | None; dist_version: str | None
```
`FileAnalysis = (path, status: "analysed"|"syntax_error"|"too_large"|"unreadable", references, skipped_local: set[str], notes)`.

## 4. Resolution algorithm

### 4.1 Extraction (parent, `ast` only)
1. Read bytes (cap 2 MiB → `too_large`), decode via `tokenize.open` semantics, `ast.parse`. `SyntaxError`,
   `RecursionError`, `MemoryError`, `ValueError` → file status `syntax_error`/`unreadable`; no references.
2. Build scopes: module, each `def`/`async def`/`lambda`, each comprehension. Class bodies are their own
   scope and never used for name lookup from methods (Python semantics).
3. Record **every** binding of every name per scope: assignment targets (incl. tuple unpack, starred),
   `AugAssign`, `AnnAssign` with value, `for`/`async for` targets, `with ... as`, `except ... as`, walrus,
   `import`/`from-import`, `def`/`class`, parameters, `del`, `match` captures, `global`/`nonlocal`
   declarations (a `global x` anywhere poisons module-level `x`).
4. A name is a **trusted import binding** iff, in its scope, it has exactly one binding, that binding is an
   import (or several imports of the *identical* target), and it is not inside an `if TYPE_CHECKING:` block
   (names bound only there produce no references). Relative imports (`from . import x`, level > 0) are
   never trusted and never queried.
   - `import a.b.c` binds `a` → module `a`, and records `a.b.c` as a module reference.
   - `import a.b as x` binds `x` → module `a.b`. `from a import b [as z]` → `z` → (module `a`, path `("b",)`)
     — `b` may be an attribute or a submodule; the probe decides (§4.4 step 3).
   - `from a import *` → a `star_exports(a)` query; any trusted binding in that scope whose name is in a's
     exports and whose import precedes the star line is downgraded to untrusted (post-processed in resolve).
5. Name lookup is Python's: a name bound anywhere in a function is local to it; otherwise module scope.
6. Emit a Reference for each `Attribute`/`Call` chain whose root `Name` resolves to a trusted import
   binding or an inferred instance (§4.3): maximal chain of `.attr` over that root, cut at the first
   non-attribute (subscript, call result) — `df.rolling(3).mean()` yields `df.rolling(window=…)` only.
   `Load` context only. `Store`/`Del` of `root.X` anywhere in the file marks `(binding, X)` as
   user-defined → references to it get no query (counted UNKNOWN reason `assigned_in_file`).
   `setattr(root, ...)` or `vars(root)`/`root.__dict__` anywhere → every attribute on that binding UNKNOWN.
7. Guards (set `Reference.guard`; a miss becomes UNKNOWN reason `guarded`): lexically inside a `try`
   body whose handlers catch any of `AttributeError, ImportError, ModuleNotFoundError, TypeError,
   NameError, LookupError, Exception, BaseException` or bare `except`; or inside either branch of an `if`/
   `IfExp`/`while` whose test contains a `hasattr`/`getattr` call, any identifier containing `version`
   (case-insensitive), `sys.platform`, `os.name`, or `platform.<anything>()`.
8. `Loc`: imports → `alias` node (3.10+ has `lineno`); attribute → `end_lineno/end_col_offset` of the
   `Attribute` node minus `len(attr)` (where the identifier sits); kwarg → `keyword.lineno/col_offset`.

### 4.2 Locality (parent)
Before querying top-level module `m`: walk from the file's directory up to the project root (first ancestor
with `pyproject.toml`, `setup.py`, `setup.cfg` or `.git`; max 10 levels) and that root's `src/`. Without a
root the walk stops at the home directory or a mount point and never includes `/`; a stdlib module name
found in an ancestor outside the home directory is not local (§14 A15). If
`m.py`, `m/__init__.py`, or a directory `m/` exists → **local**: no query, counted UNKNOWN
`local_module`. A local module shadows an installed one at runtime, so this is correct even if `m` is
also installed.

### 4.3 Instance inference ("obvious constructor results") — the only type rule
`x` is an instance of class `C` iff **all** hold:
1. `x` has exactly one binding in its scope (§4.1 step 3 counting every form) and it is
   `x = <chain>(...)` or `x: T = <chain>(...)`, a **direct child statement** of the module or function body
   (not nested in `if/for/while/try/with/match`);
2. `<chain>` is an attribute chain on a trusted import binding (`pd.DataFrame`, or `DataFrame` from
   `from pandas import DataFrame`);
3. the probe confirms `<chain>` resolves to a class (`isinstance(obj, type)`); otherwise UNKNOWN
   `not_a_class` (e.g. `pd.read_csv(...)` — return types are a non-goal).
Inline form `requests.Session().get(...)` uses the same rule with no binding. Only **one** attribute is
resolved on the instance (`instance_attr`); anything after it is not emitted.

### 4.4 Probe-side resolution of one query
1. **Module.** Validate (§6). `importlib.util.find_spec(top)` is `None` → MISSING `not_installed`
   (downgraded to UNKNOWN `optional_import` if the import is in try/except ImportError, or in hook mode
   without an explicitly configured interpreter, §7). Import raises anything (`BaseException` minus
   `KeyboardInterrupt`) → UNKNOWN `import_error` + hint. Dotted `import a.b`: same, per component.
2. **Walk `path`** with `getattr`. On a class, existence is `inspect.getattr_static` first, then `getattr`
   (metaclass descriptors); if `type(cls)` defines `__getattr__` → misses are UNKNOWN.
3. On `AttributeError` while the current object is a **module**: try
   `importlib.import_module(f"{mod}.{name}")` (M9/M10). Success → continue. `ModuleNotFoundError` for
   exactly that name → MISSING `not_found`. Any other exception → UNKNOWN `import_error`.
   A module `__getattr__` raising `AttributeError` is MISSING (M8); raising anything else → UNKNOWN
   `dynamic_getattr`.
4. **Instance attribute** on class `C` (§4.3): found via `getattr_static(C, name)` → OK. Not found → MISSING
   only if all hold, else UNKNOWN with the first failing reason:
   `C.__new__ is object.__new__` (else `custom_new`, M11); no class in the MRO except `object` defines
   `__getattr__`/`__getattribute__` (else `instance_getattr`, M12); and either `C.__dictoffset__ == 0` with
   no `"__dict__"` in any `__slots__` (M14), or every MRO class except `object` has source
   (`inspect.getsource`) whose AST contains no `self.<name>` store, no `setattr(self, …)`, no
   `self.__dict__`/`vars(self)` (else `instance_dict`, M13).
5. **Kwargs** (if `is_call`) on the final object `f`:
   a. `f` is a class → `inspect.signature(f)`; a plain function found on a class for an instance call →
      signature with the first parameter dropped; `classmethod`/`staticmethod` via `getattr`.
   b. `signature` raises `ValueError`/`TypeError` → every kwarg UNKNOWN `no_signature` (M3).
   c. Signature has `VAR_KEYWORD` → kwargs not named in it are UNKNOWN `var_keyword` (M4, M5).
   d. **Wrapper rule:** if `f` has `__wrapped__` and `signature(f, follow_wrapped=False)` has `VAR_KEYWORD`,
      kwargs absent from the followed signature are UNKNOWN `wrapper_varkw` — the wrapper may accept or
      rename them (pandas `deprecate_kwarg`, M7). Recall cost: `yf.download(bogus=1)` is UNKNOWN (M6).
   e. Kwarg matches a `POSITIONAL_ONLY` param and no `VAR_KEYWORD` → MISSING `positional_only`.
   f. Otherwise not in parameters → MISSING `not_in_signature`, suggestions from parameter names
      (`difflib`, cutoff 0.6).
6. **Suggestions** for attribute misses: `difflib.get_close_matches(name, public_names, n=3, cutoff=0.75)`
   where `public_names` = `dir(obj)` filtered by `str.isidentifier()` and not starting with `_`. If empty,
   cross-module: every other top-level module the same file imports that has `name` as an exact attribute
   → `"pandas.DataFrame"` (M23). Hint: the AttributeError message, sanitized (§6).
7. **Version:** `importlib.metadata.packages_distributions()` (3.10+; on 3.9 `dist` = null) → dist name and
   `version()`.
No check calls the library function (trap 8.3 — removed-but-present stubs like `torch.solve` read as OK;
a recall gap, never a false MISSING).

### 4.5 Verdict mapping (resolve.py)
OK = probe ok. MISSING = probe missing **and** no guard **and** no `optional_import` for module misses.
Everything else UNKNOWN. A miss at path index *i* produces one finding at `path_locs[i]`; later elements
are not reported. Duplicate (file, line, name, kind) findings collapse to one.

### 4.6 Reason codes
MISSING: `not_installed`, `not_found`, `not_in_signature`, `positional_only`.
UNKNOWN: `local_module`, `relative_import`, `optional_import`, `guarded`, `assigned_in_file`,
`import_error`, `dynamic_getattr`, `not_a_class`, `custom_new`, `instance_getattr`, `instance_dict`,
`instance_data_attr`, `no_signature`, `var_keyword`, `wrapper_varkw`, `denied`, `invalid_name`, `cap_exceeded`, `timeout`,
`crashed`, `protocol_error`.

## 5. Parent ↔ probe protocol and process handling

### 5.1 Protocol (version 1)
Request: one JSON object on stdin (≤ 4 MiB), then stdin closed.
```json
{"protocol": 1, "nonce": "<32 hex>",
 "limits": {"suggestions": 3, "hint_chars": 200},
 "queries": [
  {"id": 0, "module": "numpy", "path": ["linspace"], "instance_attr": null,
   "kwargs": ["num"], "is_call": true, "file": 0},
  {"id": 1, "module": "requests", "path": ["Session"], "instance_attr": "get",
   "kwargs": ["timeout"], "is_call": true, "file": 0}],
 "cross_modules": [["numpy", "pandas", "requests"]],
 "skip_modules": []}
```
Response: JSON Lines on a **private fd** (see 5.2), one object per line, each carrying `"nonce"`:
- `{"type":"hello","protocol":1,"python":"3.12.3","executable":"…","prefix":"…","user_site_added":false}`
- `{"type":"begin","module":"numpy"}` — before importing each top-level module group
- `{"type":"result","id":0,"status":"ok|missing|unknown","failed_index":1,"kind":"attribute","reason":"not_found","suggestions":["linspace"],"hint":null,"kwargs":[{"name":"nmu","status":"missing","reason":"not_in_signature","suggestions":["num"]}],"dist":"numpy","dist_version":"2.5.4"}`
  (`failed_index` indexes `[module] + path + [instance_attr]`; `null` when ok.)
- `{"type":"done"}`
Parent validation: lines without the run's nonce are ignored; a line > 1 MiB, total > 8 MiB, an unknown
`id`, a wrong type, a `status`/`kind`/`reason` outside its enum (§14 A12), or a non-identifier suggestion →
`protocol_error` for that record (UNKNOWN). `cross_modules` is sent once per request, one list per file;
a query names its file by index (§14 A13).

### 5.2 Probe start-up
1. `os.dup(1)` → private fd for protocol output; `os.dup2(2, 1)` and `sys.stdout = sys.stderr` so library
   prints cannot corrupt the stream.
2. Build `sys.path` by hand (the probe runs with `-I -S`, §14 A10): read `pyvenv.cfg` like `site.venv()`,
   set `sys.prefix`, add the site-packages directories `site` would add, and add user site-packages iff
   the interpreter would have without `-I` (M19): not a venv, or the venv's `pyvenv.cfg` says
   `include-system-site-packages = true`; and `os.getuid()==os.geteuid()` and `os.getgid()==os.getegid()`;
   and the directory exists. `.pth` files are read as text only. Then install the meta-path guard (A11).
3. `resource.setrlimit(RLIMIT_CORE, (0, 0))` where available. Group queries by top-level module, in
   request order, skipping `skip_modules`.

### 5.3 Spawning and timeouts — decision: one batched subprocess per run, with resume
`subprocess.Popen([python, "-I", "-S", probe_path], stdin=PIPE, stdout=PIPE, stderr=PIPE, cwd=tmpdir,
env=allowlist, start_new_session=True)` — list argv, never `shell=True`; `probe_path` is the installed
file `api_reality_check/probe.py`; `tmpdir = tempfile.mkdtemp()` (0700), removed afterwards.
Env allowlist: `PATH, HOME, USER, LOGNAME, LANG, LC_ALL, LC_CTYPE, TZ, SYSTEMROOT`, plus
`TMPDIR=tmpdir`, `PYTHONDONTWRITEBYTECODE=1`, `OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=MKL_NUM_THREADS=1`.
Secrets (API keys, tokens) in the parent env are not passed.
Deadlines: overall `--timeout` (default 30 s; hook 20 s) and per-module 10 s measured from each `begin`.
Reader thread drains stdout/stderr (stderr capped at 64 KiB, kept for `--json` diagnostics).
- Module exceeds its budget or overall deadline passes → `os.killpg(pgid, SIGKILL)`, `wait()`. The module
  that had `begin` and no results → its queries UNKNOWN `timeout`.
- EOF without `done` (crash, `os._exit`, segfault) → in-flight module UNKNOWN `crashed`.
- After a timeout or crash, **resume once per event, max 2 resumes**, with `skip_modules` = completed +
  failed modules, if overall budget remains. Not-reached modules after that → UNKNOWN `timeout`.
- Probe exits with `done` → normal. Target interpreter missing/not executable/not Python ≥3.9 (hello
  missing) → internal error, exit 2. The message gives the real cause (§14 A14): "needs Python >= 3.9"
  only for probe exit code 5 or a `SyntaxError`; otherwise request too large (exit 3), protocol mismatch
  (exit 4), timed out before hello, or the exit code and last stderr line.
Rejected: one subprocess per module. Interpreter start is cheap (0.01 s, M21) but shared dependencies are
re-imported per process (pandas and yfinance both import numpy) — total cost not measured. Resume gives
the same hang isolation for the rare case where it matters. Would win if hangs/crashes prove common. Rejected: `signal.alarm` inside the probe (cannot interrupt C-level import).

## 6. Security (staff-security)

Trust boundaries and the four questions:

| Surface | Who controls it | What they could gain | Control | How we'd know |
|---|---|---|---|---|
| User file content | the AI (possibly prompt-injected) | code execution via our parser | `ast.parse` only; 2 MiB cap; Recursion/MemoryError caught | file status in report |
| **Names in the file → modules imported** | same | run import-time code of a chosen module, e.g. `import evil_local_module` next to the file (M18) | `-I -S` (no cwd/script dir, no `PYTHON*` env, no `.pth`/`sitecustomize`), cwd = empty private temp dir, local modules never queried (§4.2), relative imports never queried, `sys.path` and a meta-path guard restricted to the environment (§14 A10, A11) | test with planted `evil_local_module.py` |
| Names → side-effecting stdlib/installed modules | same | `import venv.__main__` runs venv's CLI; `antigravity` opens a browser (M20) | deny any dunder component (`__main__` etc.), and `antigravity`, `this`, `__hello__`, `__phello__`, `idlelib` → UNKNOWN `denied`; validate each component `str.isidentifier()` and not keyword, ≤ 100 chars, ≤ 20 components | unit test per denylist entry |
| Installed third-party modules | whoever installed them | import-time code runs (any network, files, env) | **accepted risk**: the same code runs when the user runs their program. Reduced by env allowlist (no secrets), timeouts, killpg | documented in README |
| Volume | same | DoS by thousands of names | caps: 500 modules, 5,000 queries, 50 kwargs/call per run → excess UNKNOWN `cap_exceeded`, applied before the locality check; one deadline for the whole run (§14 A13) | summary counts, warning |
| Probe output | imported library code (same process) | forge results, flood | Code that runs inside the probe can read the nonce from `__main__` and write to the private fd, so it **can forge findings** (for example a MISSING with a valid reason). This is why only interpreter-owned code may run there (§14 A10, A11). The parent accepts only records whose `status`, `kind` and `reason` are in fixed enums (the reason must fit the status), and sanitises every field it prints (§14 A12); size caps | `protocol_error` count |
| `--python` / hook interpreter | the user (CLI flag, env var) | arbitrary binary execution | only from argv or env vars `API_REALITY_CHECK_PYTHON` / `VIRTUAL_ENV`; **never** from file content or hook tool input; no auto-discovery of `./.venv` (the AI can write `.venv/bin/python`) | — |
| Hook stdin `tool_input.file_path` | the AI | make the hook read arbitrary files | must be `str`, absolute, suffix `.py`, `os.lstat` regular file (symlinks refused), ≤ 2 MiB; content is only parsed, never echoed | silent skip |
| Hook output → Claude context | file identifiers; library error messages | prompt injection into Claude | identifiers are `isidentifier()`-checked and ≤ 80 chars, shown in backticks; hints: strip control chars and newlines, collapse whitespace, ≤ 200 chars, quoted and labelled `library message (untrusted)`; whole reason ≤ 8,000 chars (doc limit 10,000) with "+N more" | unit tests |

No secrets, no network calls by the tool itself, no runtime dependencies (supply chain: dev-only `pytest`,
pinned). Residual risks: installed packages' import-time code; a library that sets instance attributes on
objects of *another* class (would make §4.4 step 4 a false MISSING — see failure modes).

## 7. Claude Code hook / plugin

Contract relied on (fetched 2026-10-29: https://code.claude.com/docs/en/hooks — docs.claude.com 301s there —
and https://code.claude.com/docs/en/plugins-reference):
- stdin: `session_id, transcript_path, cwd, permission_mode, hook_event_name, tool_name, tool_input,
  tool_response, tool_use_id`; `Write` → `tool_input {file_path, content}`, `Edit` → `{file_path, old_string,
  new_string, replace_all}`; "`tool_input.file_path` is always absolute".
- PostToolUse, exit 0 + JSON: `decision: "block"` "adds the `reason` next to the tool result" (nothing is
  undone); `systemMessage` = "warning message shown to the user". Exit 2 → "Shows stderr to Claude"; other
  codes → non-blocking notice to the user. Strings capped at 10,000 chars. Command-hook default timeout 600 s.
- Matcher of letters and `|` = exact-name list. `MultiEdit` is **not mentioned** in current docs; kept in
  the matcher (harmless if absent). Plugin: `.claude-plugin/plugin.json` (only `name` required, kebab-case,
  `claude-` prefix reserved); `hooks/hooks.json` at plugin root with a top-level `"hooks"` wrapper;
  `${CLAUDE_PLUGIN_ROOT}` substituted in `command`, double-quoted in shell form.

Behaviour (`hook.py`): read stdin (≤ 10 MiB) → if `tool_name ∉ {Write, Edit, MultiEdit}` or path checks
fail (§6) → exit 0, no output. Interpreter: `API_REALITY_CHECK_PYTHON` › `$VIRTUAL_ENV/bin/python` ›
`sys.executable`; with the last one, `not_installed` is downgraded to UNKNOWN (wrong-env flood guard).
Analyse with timeout 20 s. MISSING found → stdout
`{"decision":"block","reason":"api-reality-check: 2 API(s) not found in <python> …\n<file>:7 `numpy.linspce` — not found; did you mean `linspace`? …"}`, exit 0.
Clean or UNKNOWN only → exit 0, no output (no context spam). Internal error / tool Python < 3.10 →
exit 0 with `{"systemMessage":"api-reality-check: <short error>"}`. The hook never writes any file.

Files (plugin root = repo root):
```
.claude-plugin/plugin.json   {"name":"api-reality-check","version":"0.1.0","description":"…","license":"MIT"}
hooks/hooks.json             {"hooks":{"PostToolUse":[{"matcher":"Write|Edit|MultiEdit","hooks":[{"type":"command",
                               "command":"python3 -I \"${CLAUDE_PLUGIN_ROOT}\"/hooks/post_tool_use.py","timeout":60}]}]}}
hooks/post_tool_use.py       inserts "<plugin root>/src" into sys.path, calls api_reality_check.hook.main()
```
Opt-in: nothing runs until the user loads the plugin (`claude --plugin-dir /path/to/api-reality-check`,
or a marketplace install) or adds the manual entry to `~/.claude/settings.json` or
`<project>/.claude/settings.json`:
`{"hooks":{"PostToolUse":[{"matcher":"Write|Edit|MultiEdit","hooks":[{"type":"command","command":"python3 -I /abs/path/api-reality-check/hooks/post_tool_use.py","timeout":60}]}]}}`.
Validate with `claude plugin validate .` before release.

## 8. CLI and output
`api-reality-check FILE... [--python PATH] [--json] [--timeout S] [--show-unknown]`.
Interpreter default: `--python` › `$VIRTUAL_ENV/bin/python` › `sys.executable`. The header always names
the interpreter and `sys.prefix`, so a wrong env is visible. If ≥ 3 distinct third-party top-level
modules are all `not_installed`, print a warning "target env may be wrong".
Text: `path:line:col: MISSING attribute \`numpy.linspce\` — did you mean \`linspace\`? [numpy 2.5.4]`;
UNKNOWN lines only with `--show-unknown`; summary line with OK/MISSING/UNKNOWN counts and reasons.
JSON: `{"tool","version","protocol","target":{python,executable,prefix},"files":[{path,status}],"findings":[Finding…],"summary":{ok,missing,unknown,by_reason}}`.
Exit: 2 if usage error, internal error, unusable interpreter, or any file not analysable; else 1 if any
MISSING; else 0.

## 9. Fixtures and evaluation
- `fixtures/requirements.in` (top-level pins `numpy==2.5.4 pandas==3.1.0 requests==2.34.2
  yfinance==1.7.0`, as measured) and `fixtures/requirements.lock` from `uv pip compile`. Eval venv:
  `uv venv --python 3.12 fixtures/.venv && uv pip install --python fixtures/.venv/bin/python -r fixtures/requirements.lock`.
- `fixtures/cases/<lib>_{clean,seeded}.py` + `fixtures/cases/hard_cases_clean.py`. Fixture files are only
  ever parsed, never run. Seeded categories per library: `misspelled`, `invented_function`,
  `invented_kwarg`, `wrong_module_path`, `wrong_place` (`np.DataFrame`), `removed_in_version`
  (`np.float_`). Must-not-flag hard cases: `requests.get(verify=False, **opts)`, aliases (`import numpy as
  np`, `from pandas import DataFrame as DF`), lazy submodules (`import xml; xml.etree.ElementTree`,
  `np.fft.fft`), `hasattr` compat branch using `np.trapz`, try/except ImportError fallback,
  `TYPE_CHECKING` import, `sys.platform` branch, `session.headers` instance attr, `pd.Index(...).tz_localize`,
  reassigned variable, classmethod `pd.DataFrame.from_dict(orient=...)`, positional-only, local module next
  to the file (`fixtures/cases/localpkg/`), monkeypatched `np.custom = …`.
- `fixtures/manifest.json`:
  `{"version":1,"labels":[{"file":"fixtures/cases/numpy_seeded.py","line":7,"name":"linspce","kind":"attribute","category":"misspelled","hallucination":true,"expected":"MISSING"}],"clean_files":[...]}`.
  `hallucination` is ground truth (does the API really not exist?). `expected` is the designed verdict
  (`UNKNOWN` where §4 deliberately gives up, e.g. `yf.download(bogus=1)`, `df.rolling_mean()`).
- Matching rule: a MISSING finding is a TP iff an unmatched label has the same `file`, `line`, `name`, and
  `kind` and `hallucination: true`; each label matches at most one finding; column ignored (labels may add
  `col` to disambiguate). Every other MISSING is an FP (all MISSING in `clean_files` are FPs). Unmatched
  hallucination labels are FNs. Precision = TP/(TP+FP); recall = TP/(TP+FN); a second table reports
  conformance against `expected` (catches design regressions, separately from truth).
- `eval/run_eval.py` runs the CLI with `--json --python fixtures/.venv/bin/python`, writes
  `eval/results.json` (versions, git-free timestamp, TP/FP/FN, precision, recall, per-label outcome,
  conformance) and exits non-zero if precision < 1.0 on the fixture set. A manifest test asserts every
  label's `name` occurs on its `line` (guards against line drift). The eval also re-runs the M15 socket
  guard around `import yfinance` and fails if any connect is attempted.

## 10. Failure modes

| Mode | Behaviour |
|---|---|
| Null/empty | empty file / no imports → 0 refs, exit 0. Empty kwargs list → no signature call. Probe returns no `hello` → exit 2 "interpreter unusable". |
| Retried | stateless and idempotent; re-running gives the same verdicts except across venv changes. Hook re-fires on every edit — no state to corrupt. |
| Concurrent | parallel hooks each own a temp dir and subprocess; no shared files, no cache, no locks. |
| Partial | timeout/crash mid-batch → completed results kept, failed module UNKNOWN, ≤ 2 resumes (§5.3). Unparseable file among many → others analysed, exit 2. |
| Malicious | cwd module (blocked by `-I`, M18); dunder/side-effect modules (denied); output flooding (caps); prompt text in hints (sanitized); symlinked path (refused). Accepted: installed packages' import code. |
| 100× scale | 100 files → still one probe; queries deduped by `(module, path, instance_attr, is_call, frozenset(kwargs))`; caps convert overflow to UNKNOWN. Cost grows with distinct modules (≈ import time each), not with files. |
| Wrong target env | flood of `not_installed` → env warning; hook downgrades unless interpreter configured. |
| Library sets attrs on foreign instances / `__init__` via helper | §4.4 step 4 source scan misses it → possible false MISSING. Mitigation: only classes passing every condition; fixture coverage; revisit if eval FP. |
| Version skew | verdict is for the target env at run time; report names versions. |

SLIs: eval precision (target 1.0 on fixtures; any FP blocks release), recall reported per category; hook
p95 latency, measured by replaying recorded hook stdin payloads through `hooks/post_tool_use.py` under
`time` (stdin `duration_ms` is the *tool's* duration, not the hook's), target < 3 s. Cost: 0.25–0.29 s warm,
≈ 1.0 s cold (sum of measured cold import times) per run for the 4 eval libraries (M21), ~100 MB RSS transient. Blast radius: read-only; rollback =
disable plugin or remove the settings entry. Source of truth: the target interpreter at probe time;
nothing cached, so nothing stale.

## 11. Test plan (RED first, in this order)
1. extract: `import numpy as np; np.linspce` → Reference(numpy, (linspce,), loc of `linspce`);
   `from pandas import DataFrame as DF; DF(colums=1)` → kwarg `colums` at keyword loc.
2. extract: a second binding of `np` in any form (assign, for, with, del, global) → no reference;
   `df = pd.DataFrame(); df.rolling(window=3)` → instance ref; same inside `if`, or reassigned → none.
3. extract: guards (try/except ImportError, hasattr, `sys.platform`, `TYPE_CHECKING`); `np.custom = 1`
   then `np.custom` → no query; relative import → none. Locality: sibling `localpkg/`, `src/localpkg`.
4. probe (eval venv, via runner): each §2 row becomes a test — M2/M3 signatures, M4/M5 var-keyword, M8 module
   `__getattr__`, M9 submodule fallback, M11 custom `__new__`, M12–M14 instance rules, M19 user site.
5. security: planted `evil_local_module.py` beside the file and in cwd → never imported (sentinel absent);
   `import venv.__main__` / `antigravity` → `denied`, no side effect.
6. runner: a module that sleeps → UNKNOWN `timeout`, later modules resumed and OK, no orphan process; a
   module that `os._exit(1)`s → `crashed` + resume; prints at import, flooding, nonce-less lines → ignored.
7. hook: seeded Write → `decision: block` JSON; clean → no stdout; non-.py, symlink, missing → exit 0
   silent; repo file hashes unchanged. Report: hint with newlines/ANSI/instructions sanitized; 10,000 cap.
8. probe parses with `ast.parse(src, feature_version=(3, 9))`; CI runs it on a real 3.9. Eval: line-drift
   test; precision/recall arithmetic on a synthetic manifest.
Falsifiability: for 4–7, break the guarding code (drop `-I`, drop the `__new__` rule) and see the test fail.

## 12. Alternatives (full reasoning and revisit triggers in ADR 0001)
A. static stubs/library source without importing — misses module `__getattr__`, C extensions, lazy loaders
(the false-MISSING class). B. mypy/pyright — heavy dependency, untyped libs degrade to `Any`, stubs are a
different artifact than the installed code. C. jedi — heuristic inference yields wrong types → false MISSING.

## 13. Increments
v0.1: M1 models+extract (tests 1–7) → M2 probe+runner (8–13) → M3 resolve+report+CLI (15) → M4 fixtures
+eval (16–17, publish precision/recall) → M5 hook+plugin (14). Each milestone shippable and tested.
v0.2 candidates (each must hold eval precision at 1.0): PEP 692 `Unpack[TypedDict]` kwargs; `with X() as y`
when `__enter__` provably returns self; per-library `__getattr__` policies (pandas columns are never
callable); content-hash cache; `unshare --net` sandbox; `--no-import` stub mode.

## 14. Amendments after adversarial review (2026-10-29) — these override §4–§9 where they conflict

An Opus adversarial review refuted claims 1, 2, 3, 4 (part), 6 and 7 of this design with runnable
counter-examples (evidence kept in the session scratchpad `atk/`). The orchestrator re-ran two of them:
`np.arange(start=1, stop=5)` returns `[1 2 3 4]` although the text signature is
`(start_or_stop, /, stop=None, ...)`, and `getattr(pd.DataFrame, "plot")` is the class `PlotAccessor`
with signature `(data)`. The rules below replace the refuted parts. Principle: **MISSING only on
evidence that cannot lie.**

A1. **New verdict `SUSPECT`** (warning, never changes the exit code). Used where the evidence points to
    a hallucination but cannot prove it. Each SUSPECT carries a reason code and the closest match.

A2. **Instance attributes** (`df = pd.DataFrame(); df.foo`): the §4.4 step-4 source scan is **deleted**.
    Found by `inspect.getattr_static` on the class (MRO) → OK. Not found → MISSING only if the class is
    *closed*: instances have no `__dict__` (`__dictoffset__ == 0` and no `__dict__` in any MRO
    `__slots__`), no `__getattr__`/`__getattribute__` override, `__new__ is object.__new__` (or a C type's
    own), and `type(C).__call__ is type.__call__`. Otherwise (class not closed) a reference that is the
    `func` of a `Call` (`x.name(...)`) is SUSPECT `instance_attr_not_on_class`; any other use (a plain
    load, or a link in a longer chain not called directly) is UNKNOWN `instance_data_attr`, because data
    attributes set in `__init__` cannot be told from typos while a missing method call is the observed
    hallucination.

A3. **Guards** (force UNKNOWN on a miss, never MISSING or SUSPECT):
    - A whole `try`/`TryStar` statement (body, handlers, else, finally) when any handler catches
      `ImportError`, `ModuleNotFoundError`, `AttributeError`, `TypeError`, `NameError`, `Exception`,
      `BaseException`, or is bare.
    - Any `if`/`IfExp`/`while`/`match`/`BoolOp`/`assert` whose test mentions `hasattr`, `getattr`,
      `sys.platform`, `sys.version_info`, `os.name`, `platform.*`, `__version__`, `version(`,
      `inspect.signature`, `.parameters`, or a name assigned anywhere in the file from such an
      expression. Applies to both branches and to code after an early `return`/`raise`/`continue` in
      the same block (simplest: the whole enclosing function body).
    - Functions with any decorator whose source mentions `skip`, `platform`, or `version`.
    - File-wide: if the missing attribute/kwarg name occurs in any string literal in the file, it is
      guarded (`hasattr(np, "trapz")`, `getattr(..., "x", None)`, `"kw" in sig.parameters`).
    - The root object of a `getattr(obj, ...)`/`hasattr(obj, ...)` anywhere in the same function (or
      at module level for module-level code) is guarded within that function/module.

A4. **Kwargs.** MISSING only when the callable's signature comes from a real Python code object:
    `inspect.isfunction` (after unwrapping bound methods/classmethods/staticmethods), no
    `__signature__` attribute (unless it equals `inspect.signature` of a pure-Python `__wrapped__`),
    every function along the `__wrapped__` chain lacks the kwarg and has no VAR_KEYWORD, and the call
    site has no `**expr`. Class calls: MISSING only if `type(C).__call__ is type.__call__`, `__new__`
    is `object.__new__` or pure-Python without VAR_KEYWORD, and `__init__` is pure-Python, both lacking
    the kwarg. C/Cython `__text_signature__` callables (builtins, method descriptors, ufuncs, Cython
    functions) → SUSPECT `untrusted_signature` (still useful: `np.linspace(numm=5)` style typos).
    Attributes reached through a descriptor that returns a class or a non-function (pandas
    accessors such as `DataFrame.plot`) → UNKNOWN `descriptor_callable`.

A5. **Modules.** `find_spec(top) is None` → MISSING `not_installed` only when the module is not local
    (§4.2) and the user's `PYTHONPATH` entries (passed to the probe as data, filtered so entries inside
    the analysed project are dropped) also do not contain it. With the hook's own fallback
    interpreter → UNKNOWN (unchanged).

A6. **Import origin check (security).** Before importing any module the probe resolves
    `find_spec(top).origin` / `submodule_search_locations`. If it is not under the interpreter's
    stdlib, `purelib`, `platlib` or user-site directories (from `sysconfig`/`site`, resolved with
    `realpath`), the probe does not import it → UNKNOWN `origin_outside_env`. Editable installs
    therefore become UNKNOWN. Deny-list extended: any dotted component after the first that starts
    with `_`, and any component in `{test, tests, testing, _examples, examples, conftest, setup,
    __main__}`.

A7. **Project-local interpreters in the hook.** `-I` does **not** disable `.pth` processing (reviewer
    measured a `.pth` in a venv's site-packages executing under `-I`). An AI agent that can Write into
    the project can write a `.pth` into a project `.venv`. Therefore the hook refuses (one
    `systemMessage`, no probe run) when the chosen interpreter's `sys.prefix` (resolved without running
    it: the interpreter path's grandparent, `realpath`) lies inside `CLAUDE_PROJECT_DIR`, unless the
    user sets `API_REALITY_CHECK_ALLOW_PROJECT_VENV=1` in their own settings env. README documents the
    trade-off. The CLI (human-invoked) has no such restriction but documents the `.pth` risk.

A8. **Hook output.** Use `hookSpecificOutput: {"hookEventName": "PostToolUse", "additionalContext": …}`
    (the documented non-blocking feedback field) when MISSING or SUSPECT findings exist; no output when
    clean. Exit 0 always. Cap the text at 8,000 chars; names are printed via `repr`-style escaping and
    truncated to 100 chars each.

A9. **Eval gate.** `run_eval.py` fails if TP+FP == 0, if precision of MISSING < 1.0, or if recall of
    MISSING < the floor recorded in `eval/thresholds.json` (set from the first honest measurement,
    never lowered silently). It also reports precision/recall of MISSING∪SUSPECT. Ground truth is
    checked by **execution** where possible: `eval/verify_ground_truth.py` runs every clean fixture in
    the eval venv (network blocked by a socket guard; network-only calls are wrapped so only binding
    is checked) and asserts no exception, and for each seeded label runs the single offending
    expression and asserts AttributeError/TypeError/ImportError. Labels that cannot be executed
    offline are marked `"truth": "introspection"`. Every counter-example from the review becomes a
    must-not-flag fixture.

## 15. Amendments after the second adversarial review (2026-10-30) — these override earlier sections

A10. **No `.pth` code anywhere (F1, F1b).** The hook command is `python3 -I -S -B run_hook.py`: the
     hook needs only the stdlib and `src/`, and without `-S` a `.pth` in the site-packages of the
     `python3` on `PATH` (a project venv that is active) runs in the hook process with the full
     environment before the A7 refusal. The probe runs as `python -I -S probe.py` and builds `sys.path`
     itself (§5.2), so `.pth` import lines and `sitecustomize` in the target environment never run.
     `.pth` files are parsed as text: a path line inside the environment is added to `sys.path`; a path
     line outside it is recorded and never added, and a top-level module found there → UNKNOWN
     `origin_outside_env` (by stat, not imported). A top-level module that is not found but is named by
     a `.pth` import line, an `__editable__*` file, or a dist-info `top_level.txt`/`RECORD` → UNKNOWN
     `pth_configured`, not MISSING. Measured: for `fixtures/.venv`, `devvenv`, a Python 3.10 venv and
     Debian `/usr/bin/python3`, the new `sys.path` equals the `-I` one, except that editable `.pth`
     paths outside the environment are dropped and user site-packages is added where M19 wants it
     (the old probe added it later with `site.addsitedir`). The A7 refusal stays: an agent can still
     write a module straight into a project venv's site-packages.

A11. **Transitive imports stay in the environment (F2).** The origin check of A6 covered only the
     queried name. Now `sys.path` is restricted to ROOTS (the `-I -S` stdlib entries, stdlib,
     platstdlib, purelib, platlib, the site directories that were added, user site), and a finder that
     is first on `sys.meta_path` raises `ImportError` for any spec whose file or package path is
     outside ROOTS. A library's own optional import (`try: import simplejson`) of a planted file is
     therefore refused, and so is an import after the library extends `sys.path`. A spec without any
     location (made by a finder that is already running, for example `six.moves`) is allowed.

A12. **Forged probe records (F3).** See the §6 row. The parent accepts a reason only from the fixed set
     for its status (`models.PROBE_REASONS`), for results and kwargs, and `kind` only from
     {module, attribute}, consistent with `failed_index`. `report` sanitises every printed field
     (file, reason, verdict, names, hints, dist); `sanitize` drops every non-printable character,
     which includes Unicode Cf (bidi controls such as U+202E) and line/paragraph separators.

A13. **Volume (F4).** `cross_modules` is sent once per request. The 500-module cap counts every
     top-level module looked at (local or probed) and is applied before the locality check; locality
     lists each directory once per run. `--timeout` (CLI, default 30 s) and the hook's 20 s are one
     wall-clock deadline for reading, extraction, planning and the probe; past it, references are
     UNKNOWN `timeout` and a file not yet read has status `timeout`. Caps and deadlines add a warning.
     The parent refuses to send a request over 4 MiB with a truthful message. Measured on a 2 MB file
     with 140,742 distinct imports (hook, `fixtures/.venv`): before 10.7 s, 2.2 GB max RSS and every
     finding blanked by a false "needs Python >= 3.9"; after 4.6 s, 391 MB, findings reported.

A14. **CLI and hook robustness (R5, R6).** The hook's `main()` catches every `Exception` (deep JSON →
     `RecursionError`) and exits 0. `--timeout` and `--module-timeout` must be > 0.

A15. **Locality walk (F5).** See §4.2. `/sys` was taken for a local module named `sys` when no project
     root existed.

A16. **Symlinked site-packages (F6).** The A7 check also resolves `<prefix>/lib*/python3*/site-packages`
     (and `dist-packages`) with `realpath`; one inside the project → refusal.

A17. **Residual (F7).** A process that calls `setsid()` and double-forks leaves the probe's process group,
     so `killpg` does not reach it. Only installed library code can do this (the same code runs when the
     user runs the program); accepted and documented.

A18. **Correctness fixes.** R1: a dotted prefix found in `sys.modules` is used for every part, the last
     included, before the `__path__` check (`import os.path`, `typing.io`), still subject to the deny-list
     and, when it has a location, the origin check. R3: a kwarg checked on a method reached through the
     constructor rule on a class that is not closed (A2) is capped at SUSPECT `instance_may_shadow`,
     because the instance can shadow the method (`self.send = ...`). R4: `summary.by_reason` is a dict per
     verdict. Held-out corpus: 61 correct snippets in `fixtures/cases/heldout/` (from the second review,
     not tuned against) are clean files; `eval/verify_ground_truth.py` runs each one as `__main__`.

A19. **`.pth` import lines are machinery we did not run (third review, a/b).** The probe never runs a
     `.pth` import line, so a name that such a line provides is not proof of absence. For each module X
     that a `.pth` import line imports (`import X`, `from X import …`, `__import__('X')`,
     `importlib.import_module('X')`, read with `ast`), the probe finds `X.py` or `X/__init__.py` (and
     each dotted prefix) by stat, first in the `.pth` file's site directory, then in the other site
     directories, `sys.path` and the outside `.pth` paths, parses it with `ast` (never executes it) and
     adds every identifier-like string constant to the `pth_configured` names. Standard-library
     modules (found on the `-I -S` path, or built in) are not scanned. Explicit alias:
     `_distutils_hack` → `distutils` (setuptools' `distutils-precedence.pth` provides `distutils` on
     Python ≥ 3.12). Backstop: if a `.pth` import line names a module whose source cannot be found or
     parsed (compiled only, missing), or calls `exec`/`eval`/`__import__` with a non-constant, the probe
     cannot rule out an import finder, so every top-level not-found becomes UNKNOWN `pth_configured`.
     Fixed false MISSINGs: `from distutils.version import LooseVersion` on Debian `/usr/bin/python3`
     3.12; a hatchling/`editables` editable install (`_editable_impl_tinyh.pth` → `F.map_module('tinyh', …)`).

A20. **Namespace portions outside the environment (c, d).** A dotted module `a.b` that is not found
     → UNKNOWN `origin_outside_env` when `a/b` (directory, `.py`, bytecode or extension module) exists
     under an outside `.pth` path: PEP 420 namespace packages and `pkgutil.extend_path` would merge it
     at run time. Applies to the module form (`import nsx.b`) and the attribute form (`from nsx import b`).

A21. **Optional dependencies outside the environment (e).** A finder at the end of `sys.meta_path`
     records any name that no other finder found but that exists under an outside `.pth` path, and
     raises `ImportError`. RootGuard records its refusals too. Both raise `OutsideEnv`, now a
     `ModuleNotFoundError` subclass, so a library's `except ModuleNotFoundError:` fallback still runs.
     Refusals are tracked per module group (the import of one top-level module and its queries); the
     probe's own look-ups do not count. If any refusal happened in a group, that group's MISSING
     attributes and kwargs → UNKNOWN `optional_dep_outside_env` (new reason code in
     `models.PROBE_REASONS`). A record sent before a later refusal in the same group (a lazy import in
     a later query) is sent again, downgraded; the parent keeps the last valid record per id.
     Consequence: the F2 test `usesjson.Y` (with `simplejson` on an outside `.pth` path) is now UNKNOWN
     `optional_dep_outside_env`, not MISSING.

A22. **Deny-list (f).** `testing` is removed from the deny-list: `numpy.testing` and `pandas.testing`
     are public APIs. The list is now `test`, `tests`, `_examples`, `examples`, `conftest`, `setup`,
     `__main__`, any dunder component, `antigravity`, `this`, `__hello__`, `__phello__`, `idlelib`, and
     any component after the first that starts with `_`. Measured: `numpy_seeded.py:104`
     (`np.testing.assert_array_equals`) is now MISSING as labelled; MISSING recall 62/104 (0.596),
     floor raised to 0.59.

A23. **Free text in probe records (F3 residual).** An installed module can patch `__main__.emit` and
     change legitimate records. The parent now drops `dist` unless it matches
     `^[A-Za-z0-9][A-Za-z0-9._-]{0,59}$` and `dist_version` unless it matches `^[A-Za-z0-9.+!_-]{1,40}$`,
     and drops each suggestion (result, kwarg and cross-module) that is not a dotted identifier of at
     most 60 characters. A suggestion that is not an identifier is now dropped, not a reason to reject
     the whole record. Tested through the real hook command with a module that patches `emit`.

A24. **Residuals and test gaps.** Accepted and documented: (1) user site-packages (`~/.local`) is in
     ROOTS when the interpreter would add it, so an agent that can write there can plant a module (the
     same class as the project-venv risk of A7); (2) installed library code can load any file itself
     (`spec_from_file_location`, `exec`), which no finder sees — out of scope, installed code is trusted;
     (3) refusals are per group: a module imported in an earlier group with a refusal and reused by a
     later group does not taint the later group (fixed by A28); (4) a zip or egg file on an outside `.pth`
     path is not looked into (fixed by A27). New tests: the R1 origin check for a module that installed code put in `sys.modules`
     from outside the environment; `sys.path` restricted to ROOTS (observed by an installed module that
     reads `sys.path`); `ARC_TEST_PYTHON` may be relative (conftest applies `abspath`, not `realpath`).

**Fourth adversarial review (2026-10-30), A25–A31.** These override earlier amendments where they conflict. Each finding was reproduced by the reviewer: the user file ran with the venv's own python, and the CLI
said MISSING. Rule kept: MISSING only on evidence that cannot lie.

A25. **`.pth` code that changes `sys.path`.** A19 skipped standard-library modules (`sys`, `site`), and a
     scanned module that grows `sys.path` counted as "found and parsed", so `import site;
     site.addsitedir(d)`, `import sys; sys.path.append(d)` and a `.pth` line `import basehook` (where
     `basehook.py` appends a computed directory) gave a false MISSING. The probe now reads, with `ast`,
     each `.pth` import line and each module such a line imports (the modules and their dotted
     prefixes, as in A19) for changes to `sys.path`: `.append`, `.insert` and `.extend` on `*.path` (also
     through `from sys import path [as p]` and `p = sys.path`), any `addsitedir(...)`, and any store to
     `*.path` or `*.path[...]` (assignment, augmented assignment). When every path argument is an
     absolute string constant (`append(c)`, `insert(0, c)`, `extend([c, ...])`, `addsitedir(c)`), the
     directory is applied as `site` would apply it: inside ROOTS it goes on `sys.path` (at the front for
     `insert(0, …)`), outside ROOTS it is an outside path (A20, A21); for `addsitedir` the directory's own
     `.pth` files are read in turn (each directory once). Any other change (a computed or relative path,
     a store, an insert at another index) sets the A19 backstop: every top-level not-found → UNKNOWN
     `pth_configured`. A module that changes `sys.path` in a way the probe cannot follow is treated as
     unreadable (same backstop). An outside directory that `insert(0, …)` puts first shadows installed
     modules at run time, so RootGuard refuses a top-level name that exists there (UNKNOWN
     `origin_outside_env`, and a refusal for A21). This scan now runs at start-up, before any library is
     imported, because the outside paths it finds are used by RootGuard and the A21 recorder. Real case
     that this fixes: `uv run --with …` writes `_uv_ephemeral_overlay.pth` =
     `import site; site.addsitedir("<cache>/site-packages"); site.addsitedir("<project>/.venv/…")`.

A26. **`exec`/`eval`/`compile` of a constant in a `.pth` line.** A19 set the backstop for any `exec`,
     which turned off top-level MISSING in every environment with pytest-cov < 7
     (`import os, sys;exec('if \'COV_CORE_SOURCE\' in os.environ: … from pytest_cov.embed import init …')`).
     A string (or bytes) constant passed to `exec`, `eval` or `compile` is now parsed with `ast` and read
     by the same rules (imported modules, A25 path changes), to a depth of 5. Only a non-constant argument
     (or deeper nesting) sets the backstop. A constant that does not parse adds nothing (it raises at run
     time).

A27. **Zip and egg files on an outside `.pth` path line.** `outside_has` reads a path entry that is a file
     with `zipimport.zipimporter(entry[/inner/dirs]).find_spec(last)` (`find_loader` on Python 3.9). This
     reads the archive's directory only and never runs code. A name that is not in the archive stays
     MISSING.

A28. **Taint across groups (A24 (3)).** At the start of each group the probe records `set(sys.modules)`.
     If the group had a refusal, every top-level module first imported during it is tainted. A later group
     whose top-level module is tainted is downgraded as if it had a refusal (A21). `REFUSED` is still
     cleared per group, so a group that imports nothing tainted keeps its MISSING (`json.dumpz` in
     `test_optional_dependency_outside_the_env_downgrades_its_group`).

A29. **Package metadata outside the environment.** A library can define a name only when
     `importlib.metadata.version("x")` succeeds, and the dist-info of `x` can sit on an outside path that
     the probe does not search. The fix asked for was: if any outside path holds a `*.dist-info` or
     `*.egg-info`, treat every group as refused. Measured: that rule downgrades every group, the
     standard library included, under `uv run --with …` (A25 now makes the overlay's site-packages an
     outside path, and it holds dist-info directories): 18 tests failed on Python 3.10. Implemented
     instead, with the same principle: the A21 recorder at the end of `sys.meta_path` also has
     `find_distributions(context)`, which `importlib.metadata` (and the `importlib_metadata` backport)
     calls on every finder. If outside metadata exists at all (a `*.dist-info`, `*.egg-info` or `EGG-INFO`
     in an outside directory or zip), a look-up by name that finds the distribution on the outside paths
     (read with `MetadataPathFinder` on those paths: metadata files only), or any look-up without a name
     (`distributions()`), counts as a refusal of the current group. The recorder finds nothing, so the
     library sees what the probe can check. In a group with such a metadata refusal, a dotted module that
     was not found (`import pkg.sub`, reason `not_found`) is also downgraded. `pkg_resources` does not use
     `sys.meta_path` for metadata: when outside metadata exists and `pkg_resources` is in `sys.modules`,
     every group from then on is treated as refused. The probe's own `dist_of()` look-ups do not count.
     This choice needs sign-off: it keeps recall in the common `uv run --with` case, but it trusts that
     metadata is read through `importlib.metadata` or `pkg_resources`.

A30. **Record order rules (they catch malformed output only).** The parent checks the probe output for
     order. A result counts only while its own group is open, between the probe's `begin` and `end`
     records for that group. Each group may begin once. Groups must begin in the order the parent sent
     them. An `end` must name the open group. A `begin` while a group is open is not allowed. On a
     violation, the parent counts a protocol error and treats the attempt as crashed. The group that was
     open becomes UNKNOWN `crashed` (its MISSING records and kwargs are downgraded), and the parent
     resumes with the groups that remain. The first record for an id is kept. A second record for the
     same id replaces it only if it is the A21 downgrade: the same kind, `failed_index`, suggestions,
     dist and kwarg names, and each status/reason either unchanged or moved from `missing` to
     `unknown`/`optional_dep_outside_env`. If a group times out or crashes, its records that were
     already sent with a MISSING status or MISSING kwargs become UNKNOWN `timeout` or `crashed`,
     because a later refusal in that group could not be sent.
     These rules are not a defence against hostile code. The tool trusts installed code. Code that is
     installed in the target environment runs inside the probe. It can write any record for any group
     that has not run yet, for example to turn a later MISSING into OK. The order rules and the
     first-record rule catch only malformed output.

A31. **`__future__`.** `import __future__` (and `from __future__ import …`, as before) is never queried:
     it gave UNKNOWN `denied` noise.

Residuals that can still give a false MISSING (documented in the README): (1) a `.pth`-run module is
scanned, but the modules that it imports are not; one of them can change `sys.path` or install a
finder; (2) indirect changes to `sys.path` (`getattr(sys, "path")`, a function that receives the list)
are not seen; (3) a computed `sys.path.insert(0, …)` can shadow an installed module, and the probe then
checks the installed copy; (4) `sitecustomize` and `usercustomize` are not run or read (`-S`), and they
can change `sys.path`; (5) installed library code can change `sys.path` or load files itself (A24 (2));
(6) library code that reads metadata files directly, not through `importlib.metadata` or
`pkg_resources`, is not seen (A29); (7) when a `.pth` file, or a module that it imports, adds a computed
path to `sys.path`, or a `.pth` file names a package that is no longer installed, every top-level module
that is not found is UNKNOWN `pth_configured`, so a typo in a top-level import is not flagged there.
