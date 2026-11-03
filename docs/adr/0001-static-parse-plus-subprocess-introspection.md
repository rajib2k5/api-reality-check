# ADR-0001: Parse user code with `ast`; resolve names by importing libraries in a target-interpreter subprocess

Status: Proposed (becomes Accepted when the v0.1 eval reports precision on the fixture set)
Date: 2026-10-29
Deciders: project owner; design drafted by Claude

## Context
api-reality-check must say, for AI-written Python, whether each imported module, attribute chain and
keyword argument exists in the versions installed in a *target* venv. Forces:

- **Precision dominates.** A false "missing" on working code destroys trust in the tool and, in the
  Claude Code hook, makes Claude "fix" correct code. Undecidable cases must be UNKNOWN.
- **The user's code must never run.** It is AI-written and unreviewed by definition.
- The truth is the *installed* artifact, not documentation or stubs. Measured in a scratch venv (numpy
  2.5.4, pandas 3.1.0, requests 2.34.2, yfinance 1.7.0; full table in DESIGN.md §2):
  - numpy resolves names through a module `__getattr__`; removed names (`np.float_`) raise AttributeError
    with a migration message only available at runtime.
  - `xml.etree` / `email.mime` exist only after a submodule import; static attribute lookup alone is wrong.
  - `inspect.signature` works on most numpy 2.x builtins (`np.array`, ufuncs) but raises ValueError on
    `datetime.datetime`, `math.log`, `dict`.
  - `pd.Index(...)` returns `DatetimeIndex` via a custom `__new__`; `pd.DataFrame` instances use
    `__getattr__` for columns; `requests.Session` sets `headers` in `__init__`.
- Cost: a batched import of the four libraries plus signatures takes 0.25–0.29 s warm, ≈ 1.0 s cold,
  96 MB RSS. Interpreter start under `-I` is 0.01 s.
- Security: importing a module runs its code. With cwd on `sys.path`, `import evil_local_module` next to
  the file executed attacker code (measured); `-I` blocked it. `-I` also hides user site-packages, which
  turned an installed `~/.local` package into "not installed" (measured) unless the probe re-adds it.
- The tool must be stdlib-only; the probe must run in any target venv, Python ≥ 3.9.

## Decision
We will:
1. Parse the user's files with `ast` in the tool's own process and extract references through a
   deliberately small binding model (trusted single imports, plus one "obvious constructor" instance rule).
2. Resolve every reference by **introspection inside the target interpreter**: one stdlib-only probe
   script, started as `python -I probe.py` with an empty private cwd, an allowlisted environment, its own
   process group and a timeout; JSON request on stdin, nonce-tagged JSON Lines back on a private fd.
3. Run **one batched probe per run**, grouped by top-level module, with per-module deadlines; on a hang
   or crash, kill the process group, mark that module UNKNOWN and resume the remaining modules in a fresh
   probe (at most two resumes).
4. Emit MISSING only on a positive, guarded negative (AttributeError after a submodule import attempt; a
   kwarg absent from a signature with no `**kwargs`, no `**kwargs` wrapper, no custom `__new__`); every
   other outcome is UNKNOWN.

## Alternatives considered
**A. Static resolution from stubs and library source (typeshed, shipped `.pyi`, `ast` of site-packages),
no imports.** Safest — no third-party code runs. Rejected because it is wrong exactly where precision
matters: module `__getattr__` (numpy), lazy loaders, C extensions without stubs, dynamic `__all__` and
re-export chains all read as "missing" unless a full import-system emulator is written. That emulator is
a larger project than this tool and would still diverge from runtime. It would win if running the target
venv's import-time code became unacceptable (e.g. scanning untrusted venvs); then it becomes a
`--no-import` mode that may only emit OK/UNKNOWN.

**B. Run mypy or pyright against the target venv and filter attribute/call diagnostics.** Much better
inference (method chains, return types). Rejected for v0.1: heavy non-stdlib dependency the hook would
need in every environment; cold-start latency (not measured here) on pandas-sized packages is a risk for a
per-edit hook; untyped libraries (yfinance) degrade to `Any` and silently pass; typed stubs (pandas-stubs)
describe a different artifact from the installed code, so a stub/runtime mismatch produces false
"missing". It would win for a project that already runs pyright in CI: consuming its
`reportAttributeAccessIssue` / `reportCallIssue` output adds recall at no extra cost.

**C. jedi.** Mixes static analysis with runtime introspection of compiled modules and infers return
types. Rejected: heuristic inference can assign the wrong type, and a wrong type yields a false MISSING;
third-party dependency; it has no "does not exist" diagnostic, so we would build verdict logic on top of
inference we cannot audit. It would win if a later version wants recall on method chains and can keep
jedi-derived findings at UNKNOWN-only or behind a flag.

**D. (sub-decision) One subprocess per module instead of one batched probe.** Isolates hangs and import
side effects between modules. Rejected: shared dependencies (numpy under pandas and yfinance) are
re-imported per process; batching with resume-after-hang gives the same isolation for the rare failure.
Would win if eval or dogfooding shows hangs or crashes in more than ~1 % of runs.

**E. (sub-decision) `python -E -c <probe>` with an empty cwd instead of `-I` plus user-site re-add.**
Lets the interpreter decide user-site itself. Rejected narrowly: `-I` also strips the script directory and
needs no reliance on cwd emptiness; `-P` (3.11+) is not available on 3.9/3.10 targets. Revisit if the
user-site re-add logic disagrees with `site.py` on some platform.

## Consequences
Positive: verdicts reflect the installed code, including runtime-only names and messages; zero runtime
dependencies; user code never executes; local and relative modules are never imported.

Negative, accepted:
- **Import-time code of installed packages runs** (network, files, env reads). Mitigated, not removed:
  env allowlist (no secrets), timeouts, process-group kill, denylist for known side-effect modules
  (`antigravity`, dunder components such as `venv.__main__`). The same code runs when the user runs their
  program; documented as an accepted risk.
- **Recall gaps by design**: kwargs to `**kwargs` functions (`requests.get`, `yf.Ticker.history`), to
  `**kwargs` wrappers (`yf.download`), attributes on DataFrame instances (`df.rolling_mean()`), anything
  after a call result, `with` bindings. The eval reports these as hallucinations with `expected: UNKNOWN`
  so the cost is visible.
- Removed-but-present stubs (`hasattr` true, call raises) read as OK (trap 8.3) — recall gap.
- A batched probe makes getattr on submodules order-dependent; the submodule-import fallback restores
  order independence at the cost of importing more submodules.
- Probe compatibility with Python 3.9 is unverified until CI installs 3.9 (none is installed here).

## Revisit when
- The fixture eval or dogfooding shows **any** false MISSING that the rules cannot exclude without
  special-casing → reconsider the instance rule (§4.4 step 4) first.
- Recall on seeded hallucinations stays below ~50 % because of `**kwargs`/wrapper UNKNOWNs → add PEP 692
  `Unpack[TypedDict]` resolution or per-library policies before considering B or C.
- A user needs to scan a venv they do not trust → implement alternative A as `--no-import`.
- Probe hangs/crashes exceed ~1 % of runs → alternative D.
- Hook p95 latency exceeds 3 s on real projects → add a content-hash cache keyed by (interpreter, dist
  versions, query).
