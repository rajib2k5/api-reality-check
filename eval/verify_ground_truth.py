#!/usr/bin/env python
"""Verify the fixture ground truth by execution against the pinned libraries (no network).

Run with the eval venv:   fixtures/.venv/bin/python eval/verify_ground_truth.py

What it proves
1. Every clean fixture (and hard_cases_clean.py) runs to completion in the eval venv. Network paths are cut
   off below the library API so argument validation still runs for real:
     * requests: HTTPAdapter.send is replaced by a canned 200 response, so Session/Request preparation,
       kwarg validation, raise_for_status(), .json(), iter_content() all execute for real.
     * yfinance: YfData._make_request and curl_cffi's Session.request raise NetworkEdge. yfinance validates
       its arguments before it reaches that edge, so a wrong kwarg/attribute fails the function. Code that
       runs after the edge on empty data may legitimately fail (KeyError on empty frames, ...); those
       failures are tolerated ONLY for yfinance_clean.py and only after the edge was hit, and are counted
       in the summary. A static layer (bind_yfinance_calls) additionally resolves every `yf.<chain>` and
       every method called on an obvious yf.Ticker/Tickers/... instance in that file and binds the exact
       call-site arguments with inspect.signature, so post-edge code is still checked for existence/binding.
     * pandas plotting needs matplotlib, which is not part of the pins: a stub backend module is registered
       so df.plot(kind="line") runs through pandas' own PlotAccessor.
   A socket guard (connect / connect_ex / getaddrinfo / gethostbyname / create_connection) raises and
   records any attempt; any recorded attempt fails the run.
2. For every hallucination label with truth="execution", the manifest `probe` (one offending reference in
   isolation) raises AttributeError/TypeError/ImportError/ModuleNotFoundError, and the message names the
   label's `name` (kwarg: "unexpected keyword argument 'name'"), so a typo in the probe cannot pass.
   Labels with a `downstream` list also assert the kwarg is not a parameter of those callables
   (e.g. requests.Session.request), showing **kwargs does not consume it.
3. For truth="introspection" the probe is an expression that must evaluate truthy (hasattr / signature).
4. Every label's `name` (last dotted component) is a NAME token on its `line` (comments excluded), the manifest
   matches what fixtures/build_manifest.py builds now (no stale line numbers), and in the seeded files every
   module-rooted attribute chain / imported-callable kwarg on an UNLABELLED line resolves (no unlabelled
   hallucinations hiding among the "correct" uses).
Exit status is non-zero on any failure.
"""
import ast
import contextlib
import importlib
import importlib.util
import inspect
import io
import json
import os
import runpy
import socket
import sys
import tempfile
import tokenize
import types
import unittest
import warnings
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
CASES = FIXTURES / "cases"

# yfinance writes a tz/cookie cache under the user cache dir; keep it out of the real home.
_CACHE = tempfile.mkdtemp(prefix="arc-verify-cache-")
os.environ["XDG_CACHE_HOME"] = _CACHE
os.environ["HOME"] = _CACHE

failures = []


def fail(msg):
    failures.append(msg)
    print("FAIL:", msg)


# ---------------------------------------------------------------- network containment
network_attempts = []
edge_hits = {"yfinance": 0, "requests": 0}


class NetworkBlocked(OSError):
    pass


class NetworkEdge(Exception):
    """Raised where yfinance would start talking to the network."""


def _deny(*args, **kwargs):
    network_attempts.append(repr(args)[:120])
    raise NetworkBlocked("network access is blocked by verify_ground_truth.py")


def install_guards():
    socket.socket.connect = _deny
    socket.socket.connect_ex = _deny
    socket.getaddrinfo = _deny
    socket.gethostbyname = _deny
    socket.gethostbyname_ex = _deny
    socket.create_connection = _deny

    import requests
    import requests.adapters

    def fake_send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        edge_hits["requests"] += 1
        resp = requests.Response()
        resp.status_code = 200
        resp.reason = "OK"
        resp._content = json.dumps({"items": [1, 2], "next": None}).encode()
        resp._content_consumed = True
        resp.headers["Content-Type"] = "application/json"
        resp.encoding = "utf-8"
        resp.url = request.url
        resp.request = request
        return resp

    requests.adapters.HTTPAdapter.send = fake_send

    import yfinance  # noqa: F401
    from yfinance.data import YfData

    def edge(*args, **kwargs):
        edge_hits["yfinance"] += 1
        raise NetworkEdge("yfinance network edge reached")

    YfData._make_request = edge
    try:
        import curl_cffi.requests as cr

        cr.Session.request = edge
    except ImportError:
        pass

    # pandas plotting without matplotlib: a stub backend executed by pandas' own PlotAccessor
    stub = types.ModuleType("verify_stub_plot_backend")
    stub.plot = lambda data, kind=None, **kwargs: ("plotted", kind)
    sys.modules["verify_stub_plot_backend"] = stub
    import pandas as pd

    pd.options.plotting.backend = "verify_stub_plot_backend"


# ---------------------------------------------------------------- 1. clean files
COVERED = {"numpy_clean.py", "pandas_clean.py", "requests_clean.py"}  # every statement must run


def public_functions(ns, path):
    out = []
    for name, obj in ns.items():
        if name.startswith("_") or not inspect.isfunction(obj):
            continue
        if inspect.unwrap(obj).__code__.co_filename == str(path):  # unwrap: decorated (e.g. skipIf) functions
            out.append((inspect.unwrap(obj).__code__.co_firstlineno, name, obj))
    return [(n, f) for _, n, f in sorted(out, key=lambda t: t[0])]


def post_edge_ok(exc):
    """Failures plausible only because the network returned nothing. Argument/attribute errors never qualify."""
    if isinstance(exc, NetworkEdge):
        return True
    if isinstance(exc, (KeyError, IndexError)):
        return True
    if isinstance(exc, AttributeError):
        return "'NoneType'" in str(exc)
    if isinstance(exc, TypeError):
        return "argument" not in str(exc) and "NoneType" in str(exc)
    return False


def run_heldout_file(rel, stats):
    """A held-out snippet is straight-line code: run it as __main__ (its prints are swallowed). Warnings
    are ignored: the corpus proves existence, and a deprecated name still exists (b03 uses
    Timestamp.dayofweek; yfinance itself triggers pandas' rename(inplace=) deprecation)."""
    path = ROOT / rel
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                runpy.run_path(str(path), run_name="__main__")
        except BaseException as exc:  # noqa: BLE001
            fail(f"{rel}: execution raised {type(exc).__name__}: {exc}")
            return
    stats["files"] += 1
    stats["heldout_ok"] += 1


def run_clean_file(rel, stats):
    if "/heldout/" in rel:
        return run_heldout_file(rel, stats)
    path = ROOT / rel
    is_yf = path.name == "yfinance_clean.py"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore" if is_yf else "error")
        # DeprecationWarning from third-party internals is not the fixture's fault, but a deprecated
        # *fixture* call is: keep Deprecation/Future as errors for non-network files.
        warnings.filterwarnings("ignore", message=".*pkg_resources.*")
        try:
            ns = runpy.run_path(str(path), run_name="fixture_" + path.stem)
        except BaseException as exc:  # noqa: BLE001
            fail(f"{rel}: module-level execution raised {type(exc).__name__}: {exc}")
            return
        stats["files"] += 1
        want_cover = path.name in COVERED
        executed = set()

        def tracer(frame, event, arg):
            if frame.f_code.co_filename != str(path):
                return None
            executed.add(frame.f_lineno)
            return tracer

        for name, func in public_functions(ns, path):
            if any(p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
                   for p in inspect.signature(func).parameters.values()):
                stats["helpers_via_entry_point"] += 1  # needs arguments; exercised by the file's run()
                continue
            before = edge_hits["yfinance"]
            if want_cover:
                sys.settrace(tracer)
            try:
                func()
                stats["functions_ok"] += 1
            except unittest.SkipTest:
                stats["functions_skipped"] += 1
            except BaseException as exc:  # noqa: BLE001
                if is_yf and edge_hits["yfinance"] > before and post_edge_ok(exc):
                    stats["post_edge_tolerated"] += 1
                    stats["tolerated_detail"].append(f"{path.name}:{name}: {type(exc).__name__}")
                else:
                    fail(f"{rel}: {name}() raised {type(exc).__name__}: {exc}")
            finally:
                sys.settrace(None)
        if want_cover:
            tree = ast.parse(path.read_text())
            stmts = set()

            def collect(node, in_func, in_handler):
                for child in ast.iter_child_nodes(node):
                    f = in_func or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    h = in_handler or isinstance(child, ast.ExceptHandler)  # error paths need real failures
                    if isinstance(child, ast.stmt) and f and not h and not isinstance(
                        child, (ast.FunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)
                    ):
                        if not (isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant)):
                            stmts.add(child.lineno)
                    collect(child, f, h)

            collect(tree, False, False)
            missed = sorted(stmts - executed)
            if missed:
                fail(f"{rel}: statements never executed by the entry points (lines {missed}); a clean fixture line was not proven")
            stats["covered_statements"] += len(stmts) - len(missed)


def bind_yfinance_calls(rel, stats):
    """Static complement for yfinance_clean.py: resolve chains rooted at `yf` and bind call-site arguments."""
    import yfinance as yf

    path = ROOT / rel
    tree = ast.parse(path.read_text())

    def resolve_yf(node):
        """Return the object for an attribute chain rooted at the name `yf`, else None."""
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not (isinstance(node, ast.Name) and node.id == "yf"):
            return None
        obj = yf
        for part in reversed(parts):
            obj = getattr(obj, part)  # AttributeError -> reported by caller
        return obj

    def dummy_bind(func, call, drop_self):
        if any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords):
            return
        args = [object() for _ in call.args]
        kwargs = {k.arg: object() for k in call.keywords}
        sig = inspect.signature(func)
        sig.bind(*([object()] if drop_self else []), *args, **kwargs)

    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        classes = {}  # local var -> yfinance class, from `v = yf.Cls(...)`
        for st in ast.walk(fn):
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                v = st.value
                if isinstance(v, ast.Call):
                    try:
                        obj = resolve_yf(v.func)
                    except AttributeError:
                        obj = None
                    if inspect.isclass(obj):
                        classes[st.targets[0].id] = obj
        for node in ast.walk(fn):
            where = f"{rel}:{node.lineno}" if hasattr(node, "lineno") else rel
            try:
                if isinstance(node, ast.Call):
                    f = node.func
                    obj = resolve_yf(f)
                    if obj is not None:
                        if callable(obj):
                            dummy_bind(obj, node, drop_self=False)
                            stats["static_bound"] += 1
                        continue
                    if isinstance(f, ast.Attribute):
                        owner = None
                        if isinstance(f.value, ast.Name) and f.value.id in classes:
                            owner = classes[f.value.id]
                        elif isinstance(f.value, ast.Call):
                            cand = resolve_yf(f.value.func)
                            owner = cand if inspect.isclass(cand) else None
                        if owner is not None:
                            member = inspect.getattr_static(owner, f.attr)
                            if isinstance(member, property):
                                continue
                            target = getattr(owner, f.attr)
                            if (owner, f.attr) == (yf.Ticker, "history"):
                                # Ticker.history(*args, **kwargs) only forwards; the real signature is here, and a
                                # cold tz cache makes the call hit the network edge before it validates anything.
                                from yfinance.scrapers.history import PriceHistory

                                target = PriceHistory.history
                            dummy_bind(target, node, drop_self=True)
                            stats["static_bound"] += 1
                elif isinstance(node, ast.Attribute):
                    resolve_yf(node)
            except (AttributeError, TypeError) as exc:
                fail(f"{where}: static yfinance check failed: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- 2/3. labels
ALLOWED_EXC = (AttributeError, TypeError, ImportError)  # ModuleNotFoundError is an ImportError


def resolve_dotted(path):
    parts = path.split(".")
    for i in range(len(parts), 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:i]))
        except ImportError:
            continue
        for p in parts[i:]:
            obj = getattr(obj, p)
        return obj
    raise ImportError(path)


def check_message(label, exc):
    name, kind = label["name"], label["kind"]
    msg = str(exc)
    last = name.split(".")[-1]
    if kind == "module":
        ok = isinstance(exc, ModuleNotFoundError) and name in msg
    elif kind == "kwarg":
        ok = isinstance(exc, TypeError) and "keyword argument" in msg and f"'{name}'" in msg
    else:
        ok = (isinstance(exc, AttributeError) and last in msg) or (
            isinstance(exc, ImportError) and last in msg
        )
    return ok


def check_label(label, stats):
    where = f"{label['file']}:{label['line']} {label['name']}"
    probe = label["probe"]
    if label["truth"] == "execution":
        ns = {}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                exec(compile(probe, "<probe>", "exec"), ns)  # noqa: S102
            except ALLOWED_EXC as exc:
                if not check_message(label, exc):
                    fail(f"{where}: probe raised {type(exc).__name__} but message does not name the label: {exc}")
                    return
            except BaseException as exc:  # noqa: BLE001
                fail(f"{where}: probe raised unexpected {type(exc).__name__}: {exc}")
                return
            else:
                fail(f"{where}: probe did not raise, so this is NOT a hallucination in the pinned version: {probe}")
                return
        stats["execution_ok"] += 1
    elif label["truth"] == "introspection":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                mod = ast.parse(probe)
                if not mod.body or not isinstance(mod.body[-1], ast.Expr):
                    raise ValueError("introspection probe must end in an expression")
                env = globals_for_probe()
                head = ast.Module(body=mod.body[:-1], type_ignores=[])
                exec(compile(head, "<probe>", "exec"), env)  # noqa: S102
                value = eval(compile(ast.Expression(mod.body[-1].value), "<probe>", "eval"), env)  # noqa: S307
            except BaseException as exc:  # noqa: BLE001
                fail(f"{where}: introspection probe raised {type(exc).__name__}: {exc}")
                return
            if not value:
                fail(f"{where}: introspection probe evaluated falsy: {probe}")
                return
        stats["introspection_ok"] += 1
    else:
        fail(f"{where}: unknown truth {label['truth']!r}")
        return
    for dotted in label.get("downstream", []):
        try:
            params = inspect.signature(resolve_dotted(dotted)).parameters
        except Exception as exc:  # noqa: BLE001
            fail(f"{where}: cannot inspect downstream {dotted}: {exc}")
            continue
        if label["name"] in params:
            fail(f"{where}: kwarg IS a parameter of downstream {dotted}")
        else:
            stats["downstream_ok"] += 1


def globals_for_probe():
    import numpy as np
    import pandas as pd
    import requests
    import yfinance as yf

    return {"np": np, "pd": pd, "requests": requests, "yf": yf}


def check_line_anchor(label):
    path = ROOT / label["file"]
    last = label["name"].split(".")[-1]
    with open(path, "rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type == tokenize.NAME and tok.string == last and tok.start[0] <= label["line"] <= tok.end[0]:
                return True
    fail(f"{label['file']}:{label['line']}: name {label['name']!r} is not a code token on that line")
    return False


def check_manifest_fresh(manifest):
    spec = importlib.util.spec_from_file_location("build_manifest", FIXTURES / "build_manifest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    built = mod.build()
    if built != manifest:
        fail("fixtures/manifest.json is stale: run `python3 fixtures/build_manifest.py`")


# ---------------------------------------------------------------- 4. unlabelled lines in seeded files
def check_unlabelled(rel, labelled_lines, stats):
    path = ROOT / rel
    tree = ast.parse(path.read_text())
    bindings = {}
    for node in tree.body:
        if node.lineno in labelled_lines:
            continue
        try:
            if isinstance(node, ast.Import):
                for a in node.names:
                    bindings[a.asname or a.name.split(".")[0]] = importlib.import_module(a.name if a.asname else a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                mod = importlib.import_module(node.module)
                for a in node.names:
                    bindings[a.asname or a.name] = getattr(mod, a.name)
        except Exception as exc:  # noqa: BLE001
            fail(f"{rel}:{node.lineno}: unlabelled import does not resolve: {exc}")
    inner = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    call_of = {id(n.func): n for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Attribute, ast.Name)) or id(node) in inner:
            continue
        if node.lineno in labelled_lines:
            continue
        chain, cur = [], node
        while isinstance(cur, ast.Attribute):
            chain.append(cur.attr)
            cur = cur.value
        if not (isinstance(cur, ast.Name) and cur.id in bindings):
            continue
        if isinstance(node, ast.Name) and id(node) not in call_of:
            continue
        obj = bindings[cur.id]
        try:
            for part in reversed(chain):
                try:
                    obj = getattr(obj, part)
                except AttributeError:
                    if isinstance(obj, types.ModuleType):
                        obj = importlib.import_module(f"{obj.__name__}.{part}")
                    else:
                        raise
        except Exception as exc:  # noqa: BLE001
            fail(f"{rel}:{node.lineno}: UNLABELLED reference does not resolve: {'.'.join([cur.id] + chain[::-1])} ({exc})")
            continue
        stats["unlabelled_chains_ok"] += 1
        call = call_of.get(id(node))
        if call is not None and call.keywords and not any(k.arg is None for k in call.keywords):
            try:
                params = inspect.signature(obj).parameters
            except (ValueError, TypeError):
                continue
            if any(p.kind is p.VAR_KEYWORD for p in params.values()):
                continue
            for k in call.keywords:
                if k.arg not in params:
                    fail(f"{rel}:{call.lineno}: UNLABELLED kwarg {k.arg!r} not in signature of {'.'.join([cur.id] + chain[::-1])}")


# ---------------------------------------------------------------- main
def check_pins():
    pins = {}
    for line in (FIXTURES / "requirements.in").read_text().split():
        name, _, ver = line.partition("==")
        pins[name] = ver
    for name, ver in pins.items():
        mod = importlib.import_module(name)
        if mod.__version__ != ver:
            fail(f"{name} is {mod.__version__} but requirements.in pins {ver}")
    return pins


def main():
    expected_venv = FIXTURES / ".venv"
    if Path(sys.prefix).resolve() != expected_venv.resolve():
        print(f"WARNING: running under {sys.prefix}, not {expected_venv}; pins may not match", file=sys.stderr)
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    if manifest.get("version") != 1:
        fail("manifest version != 1")
    install_guards()
    pins = check_pins()

    tmp = tempfile.mkdtemp(prefix="arc-verify-cwd-")
    os.chdir(tmp)
    sys.path.insert(0, str(CASES))  # local module `localpkg` next to the fixtures

    stats = Counter()
    stats["tolerated_detail"] = []
    for rel in manifest["clean_files"]:
        run_clean_file(rel, stats)
    bind_yfinance_calls("fixtures/cases/yfinance_clean.py", stats)

    check_manifest_fresh(manifest)
    labelled = {}
    for label in manifest["labels"]:
        if not label.get("hallucination"):
            fail(f"{label['file']}:{label['line']}: non-hallucination label in labels[]")
            continue
        check_line_anchor(label)
        check_label(label, stats)
        labelled.setdefault(label["file"], set()).add(label["line"])
    for rel in sorted(labelled):
        check_unlabelled(rel, labelled[rel], stats)

    if network_attempts:
        fail(f"{len(network_attempts)} socket-level network attempt(s): {network_attempts[:3]}")

    labels = manifest["labels"]
    by_lib = Counter(Path(e["file"]).name.split("_")[0] for e in labels)
    print("\n==== verify_ground_truth summary ====")
    print("pins:", ", ".join(f"{k}=={v}" for k, v in pins.items()))
    print(f"clean files executed: {stats['files']}/{len(manifest['clean_files'])}; "
          f"functions ok={stats['functions_ok']} skipped={stats['functions_skipped']} "
          f"helpers-via-run()={stats['helpers_via_entry_point']} statements-proven={stats['covered_statements']} "
          f"post-network-tolerated={stats['post_edge_tolerated']} heldout-snippets-ok={stats['heldout_ok']}")
    for d in stats["tolerated_detail"]:
        print("   tolerated:", d)
    print(f"network edge hits: requests(fake adapter)={edge_hits['requests']} yfinance(blocked)={edge_hits['yfinance']}; "
          f"socket attempts={len(network_attempts)}")
    print(f"yfinance static calls bound: {stats['static_bound']}")
    print(f"labels: {len(labels)} total; execution-verified={stats['execution_ok']}; "
          f"introspection-verified={stats['introspection_ok']}; downstream checks={stats['downstream_ok']}")
    print("by library:", dict(sorted(by_lib.items())))
    print("by category:", dict(sorted(Counter(e["category"] for e in labels).items())))
    print("by expected:", dict(sorted(Counter(e["expected"] for e in labels).items())))
    print(f"unlabelled references in seeded files resolved: {stats['unlabelled_chains_ok']}")
    print(f"FAILURES: {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
