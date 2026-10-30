# Fixtures for api-reality-check

Seeded-hallucination fixtures and their ground truth. Fixture files are only ever **parsed** by the tool under
test; they are never imported or run by it. `eval/verify_ground_truth.py` is the only thing that executes them.

## Layout

| path | purpose |
|---|---|
| `requirements.in`, `requirements.lock` | pins (`numpy==2.5.4 pandas==3.1.0 requests==2.34.2 yfinance==1.7.0`) and the `uv pip compile` lock (Python 3.12) |
| `setup_venv.sh` | rebuilds `fixtures/.venv` (gitignored) from the pins |
| `cases/<lib>_clean.py` | realistic correct code, no hallucinations, for numpy/pandas/requests/yfinance |
| `cases/<lib>_seeded.py` | realistic code with seeded hallucinations plus correct uses |
| `cases/hard_cases_clean.py` | valid code that looks suspicious to a naive checker (DESIGN §9 must-not-flag list, §14 counter-examples) |
| `cases/localpkg/` | the project-local module imported by `hard_cases_clean.py` |
| `cases/heldout/*.py` | 61 held-out correct snippets written by the second adversarial review (not tuned against); clean files |
| `label_specs` (inside `build_manifest.py`) | the source of the labels; anchors each label to a unique source snippet |
| `build_manifest.py` | builds `manifest.json` from the specs and refreshes the counts below |
| `manifest.json` | generated; consumed by `eval/run_eval.py` and `eval/verify_ground_truth.py` |

## Rebuild

```
fixtures/setup_venv.sh                         # uv pip compile + uv venv + uv pip install
python3 fixtures/build_manifest.py             # regenerate manifest.json and the counts below
fixtures/.venv/bin/python eval/verify_ground_truth.py   # prove the ground truth (exit 0 = all good)
```

After editing any `*_seeded.py` file, rerun `build_manifest.py`: line numbers come from the snippet anchors, and
the verifier fails if the manifest is stale or a snippet is missing/ambiguous.

## Manifest format

`{"version":1,"labels":[...],"clean_files":[...]}`. Each label:

| field | meaning |
|---|---|
| `file`, `line` | repo-relative path and 1-based line of the offending reference |
| `name` | see the labelling rule |
| `kind` | `module`, `attribute` or `kwarg` |
| `category` | `misspelled`, `invented_function`, `invented_kwarg`, `wrong_module_path`, `wrong_place`, `removed_in_version`, `invented_method_on_instance`, `invented_kwarg_on_kwargs_func` |
| `hallucination` | always `true` in `labels` (the reference does not exist in the pinned version) |
| `expected` | the designed verdict per DESIGN §4/§14 (`MISSING`, `SUSPECT`, `UNKNOWN`); a regression table, not truth |
| `truth` | `execution` or `introspection`, how the ground truth is proven |
| `probe` | execution: a snippet that raises exactly because of this reference; introspection: statements ending in an expression that must be truthy |
| `downstream` | optional, for kwargs on `**kwargs` functions: callables whose signatures must not contain the kwarg |
| `note` | optional |

### Labelling rule

* `kind=attribute`: `name` is the **last component that does not exist**, nothing else. `np.linalg.normm` ->
  `normm`; `np.linalgg.norm` -> `linalgg`; `from numpy.linalg import matrix_inverse` -> `matrix_inverse`;
  `from pandas.io import read_csvv` -> `read_csvv` (the module `pandas.io` exists, the name does not);
  `df.rolling_mean(3)` -> `rolling_mean`.
* `kind=module`: `name` is the **full dotted module path** that cannot be imported. `import pandaz` -> `pandaz`;
  `import numpy.linalgg` -> `numpy.linalgg`; `import requests.http_client` -> `requests.http_client`.
* `kind=kwarg`: `name` is the keyword as written at the call site (`dtyp`, `timout`).
* `line` is the line holding that token. `verify_ground_truth.py` checks that the last dotted component of
  `name` is a code token (not a comment) on `line`.
* A name that is imported from a missing place is labelled once, on the import line; later uses of the same
  name are deliberately not present in the seeded files, so no second reference needs a label.
* `invented_function` covers any invented module attribute (function, class or constant).
  `invented_kwarg_on_kwargs_func` is a typo'd or invented keyword passed to a callable that takes `**kwargs`
  (`requests.get(url, timout=5)`): a real hallucination (execution raises `TypeError`) that a signature
  check can never prove, hence `expected: UNKNOWN`.
* `removed_in_version` means: absent in the pinned version, proven by introspection/execution. Whether the name
  existed in an older release is not checked offline (see the report notes).

### How `expected` was decided

* Module attribute missing, no guard -> `MISSING`. Missing module -> `MISSING`.
* Kwarg on a pure-Python function/class whose chain has no `**kwargs`/`__signature__` (`pd.read_csv`,
  `np.eye`, `np.loadtxt`, `yf.Ticker`, `requests.Session`, `Ticker.get_news`) -> `MISSING`.
* Kwarg on C/Cython/dispatcher callables (`np.zeros`, `np.linspace`, `np.savetxt`, `np.sort`,
  `np.random.default_rng`) -> `SUSPECT` (`untrusted_signature`).
* Kwarg on `**kwargs` or wrapped-with-`**kwargs` callables (`requests.get/post/head/request`, `Session.get`,
  `pd.date_range`, `pd.pivot_table`, `yf.download`, `Ticker.history`, `Tickers.history`) -> `UNKNOWN`.
* Attribute on an instance of a class with `__dict__` or `__getattr__` (`pd.DataFrame`, `requests.Session`,
  `requests.Response`, `yf.Ticker`) -> `SUSPECT`.
* Attribute on an instance of a *closed* C type (`np.random.RandomState`, `np.dtype`: `__dictoffset__ == 0`,
  no `__getattr__`) -> `MISSING`. This relies on reading A2's "or a C type's own `__new__`" as allowing
  these types; if the tool treats a C `__new__` as `custom_new`, these two labels will show as conformance
  differences, not as truth errors.
* Receiver that is not an obvious constructor result (`default_rng(0).x`, `requests.get(...).x`,
  `df["close"].pct_change(...)` on a parameter) -> `UNKNOWN`.

## How the ground truth is proven (`eval/verify_ground_truth.py`)

Runs under `fixtures/.venv/bin/python` with a socket guard (connect/connect_ex/getaddrinfo/gethostbyname/
create_connection raise and are recorded; any attempt fails the run).

1. **Clean files**: each is executed with `runpy`, then every public function that needs no arguments is
   called (`run()` entry points call the helpers that need arguments). Deprecation/Future warnings are errors
   for the offline libraries. For numpy/pandas/requests every statement outside `except` handlers is
   line-traced and must have run. A held-out snippet (`cases/heldout/`) is straight-line code: it is run as
   `__main__` with warnings ignored (it proves existence; `b03` uses the deprecated `Timestamp.dayofweek`, and
   yfinance itself triggers a pandas deprecation). The yfinance snippets complete because yfinance swallows
   the blocked network edge. `b13_requests_resp.py` from the review is not included: it calls `.ok` on an
   empty `requests.Response()`, which raises `TypeError` at runtime.
   * `requests`: `HTTPAdapter.send` returns a canned 200 response, so kwargs validation, request
     preparation, `raise_for_status()`, `.json()` and `iter_content()` run for real.
   * `yfinance`: network functions are never invoked against the network. `YfData._make_request` and
     curl_cffi's `Session.request` raise a sentinel; yfinance validates most arguments before that edge, and
     failures that can only come from empty data after the edge (`KeyError`, `'NoneType'` attribute errors)
     are tolerated for that one file and counted. `TypeError`s mentioning an argument are never tolerated.
     A static pass also resolves every `yf.<chain>` in the file and binds the exact call-site arguments
     with `inspect.signature` (for `yf.Ticker(...)` instances too; `Ticker.history` is bound against the
     `PriceHistory.history` it forwards to, because a cold timezone cache makes it hit the network edge before
     it validates anything).
   * pandas plotting needs matplotlib (not pinned): a stub backend module is registered so
     `df.plot(kind="line")` runs through pandas' own `PlotAccessor`.
2. **Labels, `truth=execution`**: the `probe` must raise `AttributeError`/`TypeError`/`ImportError`/
   `ModuleNotFoundError` **and** the message must name the label (`unexpected keyword argument 'name'`, `No module
   named 'name'`, `no attribute 'name'`), so a typo in a probe cannot pass.
3. **Labels, `truth=introspection`** (receiver only obtainable via the network, e.g. `requests.get(...)` ->
   `Response`): the probe is `hasattr`/`inspect.signature` on the class or a locally constructed instance.
   `downstream` additionally asserts a kwarg is not a parameter of e.g. `requests.Session.request`.
4. The manifest equals what `build_manifest.py` builds now; in the seeded files every module-rooted attribute
   chain and imported-callable keyword on an **unlabelled** line resolves (no accidental hallucinations among
   the correct uses).

## Counts (measured from `manifest.json` by `build_manifest.py`)

<!-- counts:begin -->
Total labels: 104 (truth=execution: 99, truth=introspection: 5).

| library | labels | MISSING | SUSPECT | UNKNOWN |
|---|---|---|---|---|
| numpy | 25 | 19 | 5 | 1 |
| pandas | 26 | 15 | 7 | 4 |
| requests | 29 | 16 | 2 | 11 |
| yfinance | 24 | 12 | 6 | 6 |

| category | numpy | pandas | requests | yfinance | total |
|---|---|---|---|---|---|
| invented_function | 3 | 1 | 7 | 3 | 14 |
| invented_kwarg | 4 | 2 | 2 | 7 | 15 |
| invented_kwarg_on_kwargs_func | 0 | 3 | 8 | 3 | 14 |
| invented_method_on_instance | 3 | 3 | 5 | 5 | 16 |
| misspelled | 6 | 7 | 3 | 2 | 18 |
| removed_in_version | 6 | 7 | 1 | 1 | 15 |
| wrong_module_path | 1 | 2 | 1 | 1 | 5 |
| wrong_place | 2 | 1 | 2 | 2 | 7 |

By kind: attribute=62, kwarg=38, module=4.
<!-- counts:end -->
