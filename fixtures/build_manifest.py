#!/usr/bin/env python3
"""Build fixtures/manifest.json from the label specs below, and refresh the counts in README.md.

Each spec anchors a label to a unique source snippet instead of a hard-coded line number, so editing
a fixture file cannot silently shift labels: the builder fails if a snippet is missing or ambiguous.
Run with any Python 3.9+ (stdlib only):  python3 fixtures/build_manifest.py
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = "fixtures/cases/"

NP = "import numpy as np; "
PD = "import pandas as pd; "
RQ = "import requests; "
YF = "import yfinance as yf; "
URL = "'https://example.invalid/x'"

# (lib, snippet, name, kind, category, expected, probe[, extra]) -- extra: truth / downstream / note
_S = []


def L(lib, snippet, name, kind, category, expected, probe, **extra):
    _S.append((lib, snippet, name, kind, category, expected, probe, extra))


I = {"truth": "introspection"}

# ---------------------------------------------------------------- numpy
L("numpy", "import numpy.linalgg", "numpy.linalgg", "module", "wrong_module_path", "MISSING", "import numpy.linalgg")
L("numpy", "import norm, matrix_inverse", "matrix_inverse", "attribute", "invented_function", "MISSING", "from numpy.linalg import matrix_inverse")
L("numpy", "np.linspce(", "linspce", "attribute", "misspelled", "MISSING", NP + "np.linspce")
L("numpy", "number=len(values)", "number", "kwarg", "invented_kwarg", "SUSPECT", NP + "np.linspace(0.0, 1.0, number=5)")
L("numpy", "np.moving_average(", "moving_average", "attribute", "invented_function", "MISSING", NP + "np.moving_average")
L("numpy", "np.standard_deviation(", "standard_deviation", "attribute", "invented_function", "MISSING", NP + "np.standard_deviation")
L("numpy", "np.zeros(n, dtyp=", "dtyp", "kwarg", "misspelled", "SUSPECT", NP + "np.zeros(3, dtyp=np.float64)")
L("numpy", "np.eye(n, dtyp=", "dtyp", "kwarg", "misspelled", "MISSING", NP + "np.eye(3, dtyp=np.float32)")
L("numpy", "np.DataFrame(rows)", "DataFrame", "attribute", "wrong_place", "MISSING", NP + "np.DataFrame")
L("numpy", "np.float_)", "float_", "attribute", "removed_in_version", "MISSING", NP + "np.float_")
L("numpy", "np.trapz(y, x)", "trapz", "attribute", "removed_in_version", "MISSING", NP + "np.trapz")
L("numpy", "np.in1d(", "in1d", "attribute", "removed_in_version", "MISSING", NP + "np.in1d")
L("numpy", "np.NaN,", "NaN", "attribute", "removed_in_version", "MISSING", NP + "np.NaN")
L("numpy", "np.product(", "product", "attribute", "removed_in_version", "MISSING", NP + "np.product")
L("numpy", "np.row_stack(", "row_stack", "attribute", "removed_in_version", "MISSING", NP + "np.row_stack")
L("numpy", "np.read_csv(", "read_csv", "attribute", "wrong_place", "MISSING", NP + "np.read_csv")
L("numpy", 'delimeter=","', "delimeter", "kwarg", "misspelled", "MISSING", NP + "np.loadtxt('x.csv', delimeter=',')")
L("numpy", "header_text=", "header_text", "kwarg", "invented_kwarg", "SUSPECT", NP + "np.savetxt('x.csv', np.zeros(2), header_text='h')")
L("numpy", "ascending=False", "ascending", "kwarg", "invented_kwarg", "SUSPECT", NP + "np.sort(np.zeros(2), ascending=False)")
L("numpy", 'algorithm="pcg64"', "algorithm", "kwarg", "invented_kwarg", "SUSPECT", NP + "np.random.default_rng(seed=1, algorithm='pcg64')")
L("numpy", "np.linalgg.norm(x)", "linalgg", "attribute", "misspelled", "MISSING", NP + "np.linalgg")
L("numpy", "rs.randn_matrix(", "randn_matrix", "attribute", "invented_method_on_instance", "MISSING",
  NP + "rs = np.random.RandomState(7); rs.randn_matrix(2, 2)")
L("numpy", "dt.size_bytes", "size_bytes", "attribute", "invented_method_on_instance", "MISSING",
  NP + "dt = np.dtype('float32'); dt.size_bytes")
L("numpy", "rng.normal_sample(", "normal_sample", "attribute", "invented_method_on_instance", "UNKNOWN",
  NP + "rng = np.random.default_rng(0); rng.normal_sample(0.0, 1.0, 3)")
L("numpy", "assert_array_equals(", "assert_array_equals", "attribute", "misspelled", "MISSING", NP + "np.testing.assert_array_equals")

# ---------------------------------------------------------------- pandas
DF = PD + "df = pd.DataFrame({'symbol': ['A'], 'close': [1.0]}); "
L("pandas", "import pandas.plotting.extras", "pandas.plotting.extras", "module", "wrong_module_path", "MISSING", "import pandas.plotting.extras")
L("pandas", "import read_csvv", "read_csvv", "attribute", "wrong_module_path", "MISSING", "from pandas.io import read_csvv")
L("pandas", "index_coll=0", "index_coll", "kwarg", "misspelled", "MISSING", PD + "pd.read_csv('x.csv', index_coll=0)")
L("pandas", "header_row=0", "header_row", "kwarg", "invented_kwarg", "MISSING", PD + "pd.read_csv('x.csv', header_row=0)")
L("pandas", "pd.read_excell(", "read_excell", "attribute", "misspelled", "MISSING", PD + "pd.read_excell")
L("pandas", "colums=[", "colums", "kwarg", "misspelled", "MISSING", PD + "pd.DataFrame({'a': [1]}, colums=['a'])")
L("pandas", "ignore_idx=True", "ignore_idx", "kwarg", "misspelled", "MISSING", DF + "pd.concat([df, df], ignore_idx=True)")
L("pandas", "pd.concat_frames(", "concat_frames", "attribute", "invented_function", "MISSING", PD + "pd.concat_frames")
L("pandas", "suffix=(", "suffix", "kwarg", "misspelled", "MISSING", DF + "pd.merge(df, df, on='symbol', how='outer', suffix=('_l', '_r'))")
L("pandas", "pd.linspace(", "linspace", "attribute", "wrong_place", "MISSING", PD + "pd.linspace")
L("pandas", "pd.rolling_mean(", "rolling_mean", "attribute", "removed_in_version", "MISSING", PD + "pd.rolling_mean")
L("pandas", "pd.Int64Index(", "Int64Index", "attribute", "removed_in_version", "MISSING", PD + "pd.Int64Index")
L("pandas", "pd.Panel(", "Panel", "attribute", "removed_in_version", "MISSING", PD + "pd.Panel")
L("pandas", "pd.Dataframe(", "Dataframe", "attribute", "misspelled", "MISSING", PD + "pd.Dataframe")
L("pandas", "formatt=", "formatt", "kwarg", "misspelled", "MISSING", PD + "pd.to_datetime(pd.Series(['2024-01-01']), formatt='%Y-%m-%d')")
L("pandas", 'frequency="D"', "frequency", "kwarg", "invented_kwarg_on_kwargs_func", "UNKNOWN", PD + "pd.date_range('2024-01-01', periods=5, frequency='D')")
L("pandas", "fillvalue=0", "fillvalue", "kwarg", "invented_kwarg_on_kwargs_func", "UNKNOWN", DF + "pd.pivot_table(df, values='close', index='symbol', fillvalue=0)")
L("pandas", "fil_method=None", "fil_method", "kwarg", "invented_kwarg_on_kwargs_func", "UNKNOWN", DF + "df['close'].pct_change(fil_method=None)")
L("pandas", "df.append(row", "append", "attribute", "removed_in_version", "SUSPECT", DF + "df.append({'symbol': 'B', 'close': 2.0}, ignore_index=True)")
L("pandas", "frame.ix[0]", "ix", "attribute", "removed_in_version", "UNKNOWN", DF + "df.ix[0]")
L("pandas", "frame.iteritems()", "iteritems", "attribute", "removed_in_version", "SUSPECT", DF + "list(df.iteritems())")
L("pandas", "frame.as_matrix()", "as_matrix", "attribute", "removed_in_version", "SUSPECT", DF + "df.as_matrix()")
L("pandas", "df.rolling_mean(3)", "rolling_mean", "attribute", "invented_method_on_instance", "SUSPECT", DF + "df.rolling_mean(3)")
L("pandas", "df.groupby_apply(", "groupby_apply", "attribute", "invented_method_on_instance", "SUSPECT", DF + "df.groupby_apply('symbol', len)")
L("pandas", "descending=True", "descending", "kwarg", "invented_kwarg", "SUSPECT", DF + "df.sort_values('close', descending=True)")
L("pandas", "df.tolist()", "tolist", "attribute", "invented_method_on_instance", "SUSPECT", DF + "df.tolist()")

# ---------------------------------------------------------------- requests
GET_DOWN = {"downstream": ["requests.Session.request"]}
L("requests", "import requests.http_client", "requests.http_client", "module", "wrong_module_path", "MISSING", "import requests.http_client")
L("requests", "import get_json", "get_json", "attribute", "invented_function", "MISSING", "from requests import get_json")
L("requests", "HTTPAdapter, RetryAdapter", "RetryAdapter", "attribute", "invented_function", "MISSING", "from requests.adapters import RetryAdapter")
L("requests", "timout=5", "timout", "kwarg", "invented_kwarg_on_kwargs_func", "UNKNOWN", RQ + "requests.get(" + URL + ", timout=5)", **GET_DOWN)
L("requests", "retries=3)\n", "retries", "kwarg", "invented_kwarg_on_kwargs_func", "UNKNOWN", RQ + "requests.get(" + URL + ", timeout=5, retries=3)", **GET_DOWN)
L("requests", "param={", "param", "kwarg", "invented_kwarg_on_kwargs_func", "UNKNOWN", RQ + "requests.get(" + URL + ", param={'page': 1}, timeout=5)", **GET_DOWN)
L("requests", "json_data=payload", "json_data", "kwarg", "invented_kwarg_on_kwargs_func", "UNKNOWN", RQ + "requests.post(" + URL + ", json_data={}, timeout=5)", **GET_DOWN)
L("requests", "follow_redirects=True", "follow_redirects", "kwarg", "invented_kwarg_on_kwargs_func", "UNKNOWN", RQ + "requests.request('GET', " + URL + ", follow_redirects=True)", **GET_DOWN)
L("requests", "allow_redirect=False", "allow_redirect", "kwarg", "invented_kwarg_on_kwargs_func", "UNKNOWN", RQ + "requests.head(" + URL + ", allow_redirect=False)", **GET_DOWN)
L("requests", "Session(timeout=10)", "timeout", "kwarg", "invented_kwarg", "MISSING", RQ + "requests.Session(timeout=10)")
L("requests", "backoff=0.5", "backoff", "kwarg", "invented_kwarg", "MISSING", RQ + "import requests.adapters; requests.adapters.HTTPAdapter(max_retries=3, backoff=0.5)")
L("requests", "pool_connection=4", "pool_connection", "kwarg", "misspelled", "MISSING", RQ + "import requests.adapters; requests.adapters.HTTPAdapter(pool_connection=4)")
L("requests", "requests.fetch(", "fetch", "attribute", "invented_function", "MISSING", RQ + "requests.fetch")
L("requests", "requests.urlopen(", "urlopen", "attribute", "wrong_place", "MISSING", RQ + "requests.urlopen")
L("requests", "requests.Request.get(", "get", "attribute", "invented_function", "MISSING", RQ + "requests.Request.get")
L("requests", "s.set_timeout(", "set_timeout", "attribute", "invented_method_on_instance", "SUSPECT", RQ + "s = requests.Session(); s.set_timeout(5)")
L("requests", "verify_ssl=False", "verify_ssl", "kwarg", "invented_kwarg_on_kwargs_func", "UNKNOWN", RQ + "s = requests.Session(); s.get(" + URL + ", verify_ssl=False)", **GET_DOWN)
L("requests", "raise_on_error=True", "raise_on_error", "kwarg", "invented_kwarg_on_kwargs_func", "UNKNOWN", RQ + "s = requests.Session(); s.post(" + URL + ", json={}, raise_on_error=True)", **GET_DOWN)
L("requests", "requests.exceptions.TimeoutError", "TimeoutError", "attribute", "wrong_place", "MISSING", RQ + "requests.exceptions.TimeoutError")
L("requests", "requests.exceptions.RateLimitError", "RateLimitError", "attribute", "invented_function", "MISSING", RQ + "requests.exceptions.RateLimitError")
L("requests", "resp.status ==", "status", "attribute", "invented_method_on_instance", "UNKNOWN", RQ + "resp = requests.Response(); resp.status")
L("requests", "resp.get_json()", "get_json", "attribute", "invented_method_on_instance", "SUSPECT", RQ + "resp = requests.Response(); resp.get_json()")
L("requests", "requests.compat.unicode(", "unicode", "attribute", "removed_in_version", "MISSING", RQ + "requests.compat.unicode")
L("requests", "requests.gett(", "gett", "attribute", "misspelled", "MISSING", RQ + "requests.gett")
L("requests", "requests.Sesion()", "Sesion", "attribute", "misspelled", "MISSING", RQ + "requests.Sesion")
L("requests", "requests.structures.CaseSensitiveDict", "CaseSensitiveDict", "attribute", "invented_function", "MISSING", RQ + "requests.structures.CaseSensitiveDict")
L("requests", "resp.parsed_json()", "parsed_json", "attribute", "invented_method_on_instance", "UNKNOWN",
  "r = requests.Response(); not hasattr(requests.Response, 'parsed_json') and not hasattr(r, 'parsed_json')", **I)
L("requests", "resp.is_success", "is_success", "attribute", "invented_method_on_instance", "UNKNOWN",
  "r = requests.Response(); not hasattr(requests.Response, 'is_success') and not hasattr(r, 'is_success')", **I)
L("requests", "requests.utils.build_url(", "build_url", "attribute", "invented_function", "MISSING", RQ + "requests.utils.build_url")

# ---------------------------------------------------------------- yfinance
L("yfinance", "import yfinance.scraper", "yfinance.scraper", "module", "wrong_module_path", "MISSING", "import yfinance.scraper")
L("yfinance", "import Screener", "Screener", "attribute", "invented_function", "MISSING", "from yfinance import Screener")
L("yfinance", "yf.pdr_override()", "pdr_override", "attribute", "removed_in_version", "MISSING", YF + "yf.pdr_override")
L("yfinance", 'perid="1y"', "perid", "kwarg", "invented_kwarg_on_kwargs_func", "UNKNOWN", YF + "yf.download('AAPL', perid='1y')")
L("yfinance", "yf.get_history(", "get_history", "attribute", "invented_function", "MISSING", YF + "yf.get_history")
L("yfinance", 'yf.Ticker(symbol, period="1d")', "period", "kwarg", "invented_kwarg", "MISSING", YF + "yf.Ticker('AAPL', period='1d')")
L("yfinance", 'perod="1mo"', "perod", "kwarg", "invented_kwarg_on_kwargs_func", "UNKNOWN",
  "import inspect; from yfinance.scrapers.history import PriceHistory; sig = inspect.signature(PriceHistory.history); "
  "'perod' not in sig.parameters and not any(p.kind is p.VAR_KEYWORD for p in sig.parameters.values())", **I,
  note="Ticker.history(*args, **kwargs) forwards to PriceHistory.history; executing it first hits the network "
       "when the tz cache is cold, so the proof is the forwarded-to signature")
L("yfinance", "ticker.get_price()", "get_price", "attribute", "invented_method_on_instance", "SUSPECT", YF + "yf.Ticker('AAPL').get_price()")
L("yfinance", "ticker.price_history", "price_history", "attribute", "invented_method_on_instance", "UNKNOWN", YF + "yf.Ticker('AAPL').price_history")
L("yfinance", "ticker.get_eps_history(", "get_eps_history", "attribute", "invented_method_on_instance", "SUSPECT", YF + "yf.Ticker('AAPL').get_eps_history()")
L("yfinance", "get_news(limit=5)", "limit", "kwarg", "invented_kwarg", "SUSPECT", YF + "yf.Ticker('AAPL').get_news(limit=5)")
L("yfinance", "get_dividends(years=5)", "years", "kwarg", "invented_kwarg", "SUSPECT", YF + "yf.Ticker('AAPL').get_dividends(years=5)")
L("yfinance", "calls_only=True", "calls_only", "kwarg", "invented_kwarg", "SUSPECT", YF + "yf.Ticker('AAPL').option_chain('2025-01-17', calls_only=True)")
L("yfinance", "bogus_flag=True", "bogus_flag", "kwarg", "invented_kwarg_on_kwargs_func", "UNKNOWN", YF + "yf.Tickers('AAPL MSFT').history(period='1mo', bogus_flag=True)")
L("yfinance", "yf.Search(query, limit=5)", "limit", "kwarg", "invented_kwarg", "MISSING", YF + "yf.Search('apple', limit=5)")
L("yfinance", "refresh=True", "refresh", "kwarg", "invented_kwarg", "MISSING", YF + "yf.Market('US', refresh=True)")
L("yfinance", "create=True", "create", "kwarg", "invented_kwarg", "MISSING", YF + "yf.set_tz_cache_location('x', create=True)")
L("yfinance", "yf.DataFrame(rows)", "DataFrame", "attribute", "wrong_place", "MISSING", YF + "yf.DataFrame")
L("yfinance", "yf.read_csv(", "read_csv", "attribute", "wrong_place", "MISSING", YF + "yf.read_csv")
L("yfinance", "yf.Quote(", "Quote", "attribute", "invented_function", "MISSING", YF + "yf.Quote")
L("yfinance", "yf.Tickrs(", "Tickrs", "attribute", "misspelled", "MISSING", YF + "yf.Tickrs")
L("yfinance", ".moving_average(5)", "moving_average", "attribute", "invented_method_on_instance", "UNKNOWN",
  "import pandas as pd; not hasattr(pd.Series, 'moving_average') and not hasattr(pd.DataFrame, 'moving_average')", **I)
L("yfinance", "prices.to_list()", "to_list", "attribute", "invented_method_on_instance", "UNKNOWN",
  "import pandas as pd; not hasattr(pd.DataFrame, 'to_list')", **I)
L("yfinance", ".histroy(", "histroy", "attribute", "misspelled", "SUSPECT", YF + "yf.Ticker('AAPL').histroy(period='1d')")

CLEAN_FILES = [CASES + f for f in (
    "numpy_clean.py", "pandas_clean.py", "requests_clean.py", "yfinance_clean.py", "hard_cases_clean.py")]
# Held-out clean corpus: short correct snippets written by the second adversarial review, not tuned
# against. eval/verify_ground_truth.py executes each one as __main__.
HELDOUT = "heldout/"
CLEAN_FILES += sorted(CASES + HELDOUT + p.name for p in (ROOT / CASES / HELDOUT).glob("*.py"))


def build():
    labels = []
    for lib, snippet, name, kind, category, expected, probe, extra in _S:
        rel = CASES + lib + "_seeded.py"
        lines = (ROOT / rel).read_text().split("\n")
        hits = [i + 1 for i, ln in enumerate(lines) if snippet.rstrip("\n") in ln
                and (not snippet.endswith("\n") or ln.rstrip().endswith(snippet.rstrip("\n")))]
        if len(hits) != 1:
            sys.exit(f"snippet {snippet!r} in {rel}: {len(hits)} matches {hits} (need exactly 1)")
        entry = {"file": rel, "line": hits[0], "name": name, "kind": kind, "category": category,
                 "hallucination": True, "expected": expected,
                 "truth": extra.get("truth", "execution"), "probe": probe}
        if "downstream" in extra:
            entry["downstream"] = extra["downstream"]
        if "note" in extra:
            entry["note"] = extra["note"]
        labels.append(entry)
    labels.sort(key=lambda e: (e["file"], e["line"], e["name"]))
    return {"version": 1, "labels": labels, "clean_files": CLEAN_FILES}


def counts_markdown(manifest):
    labels = manifest["labels"]
    lib = lambda e: Path(e["file"]).name.split("_")[0]
    libs = sorted({lib(e) for e in labels})
    cats = sorted({e["category"] for e in labels})
    exps = ["MISSING", "SUSPECT", "UNKNOWN"]
    out = [f"Total labels: {len(labels)} (truth=execution: {sum(e['truth'] == 'execution' for e in labels)}, "
           f"truth=introspection: {sum(e['truth'] == 'introspection' for e in labels)}).", ""]
    out += ["| library | labels | " + " | ".join(exps) + " |", "|---|---|" + "---|" * len(exps)]
    for lb in libs:
        c = Counter(e["expected"] for e in labels if lib(e) == lb)
        out.append(f"| {lb} | {sum(c.values())} | " + " | ".join(str(c[x]) for x in exps) + " |")
    out += ["", "| category | " + " | ".join(libs) + " | total |", "|---|" + "---|" * (len(libs) + 1)]
    for cat in cats:
        row = [sum(1 for e in labels if lib(e) == lb and e["category"] == cat) for lb in libs]
        out.append(f"| {cat} | " + " | ".join(map(str, row)) + f" | {sum(row)} |")
    kinds = Counter(e["kind"] for e in labels)
    out += ["", "By kind: " + ", ".join(f"{k}={kinds[k]}" for k in sorted(kinds)) + "."]
    return "\n".join(out)


def main():
    manifest = build()
    (ROOT / "fixtures/manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    readme = ROOT / "fixtures/README.md"
    if readme.exists():
        text = readme.read_text()
        block = "<!-- counts:begin -->\n" + counts_markdown(manifest) + "\n<!-- counts:end -->"
        text, n = re.subn(r"<!-- counts:begin -->.*?<!-- counts:end -->", lambda _: block, text, flags=re.S)
        if n:
            readme.write_text(text)
    print(counts_markdown(manifest))


if __name__ == "__main__":
    main()
