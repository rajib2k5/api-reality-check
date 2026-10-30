"""Valid code that looks suspicious to a naive static checker. Nothing here may be flagged."""
from __future__ import annotations

import argparse
import contextlib
import importlib
import inspect
import os
import os.path
import os.path as osp
import pstats
import sys
import types
import unittest
import xml
import xml.etree.ElementTree
from collections import Counter
from dataclasses import dataclass, field
from os.path import join
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from pandas import DataFrame as DF

import localpkg

if TYPE_CHECKING:
    from stubs_only_module import StubThing
    import stubs_only_package.types

try:
    from numpy import trapezoid as integrate
except ImportError:
    integrate = np.trapz

try:
    import orjson as json_impl
except ImportError:
    import json as json_impl

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    zstd = None

if sys.platform == "win32":
    import winreg

HAS_TRAPZ = hasattr(np, "trapz")
IS_WINDOWS = sys.platform == "win32"
NEW_NUMPY = np.__version__ >= "2"


@dataclass
class Order:
    symbol: str
    qty: int
    note: str = ""


@dataclass(frozen=True)
class Frozen:
    base: int
    doubled: int = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "doubled", self.base * 2)


def describe(thing: "StubThing" = None) -> str:
    return repr(thing)


def case_stdlib_dataclass_fields():
    prof = pstats.FunctionProfile(
        ncalls="3", tottime=0.1, percall_tottime=0.03, cumtime=0.2, percall_cumtime=0.07, file_name="x.py", line_number=1
    )
    return prof.ncalls, prof.tottime, prof.file_name


def case_local_dataclass():
    order = Order(symbol="AAPL", qty=3)
    frozen = Frozen(base=4)
    return order.symbol, order.qty, frozen.base, frozen.doubled


def case_df_plot_accessor():
    df = DF({"a": [1, 2, 3], "b": [3, 2, 1]})
    df.plot(kind="line")
    df.plot.line(x="a", y="b")
    return df.shape


def case_positional_or_keyword_c_functions():
    a = np.arange(start=1, stop=5)
    b = np.add(1, 2, sig="dd->d")
    c = np.where(a > 2, a, 0)
    return a, b, c


def case_positional_only_with_varkw():
    return Counter(iterable=3), dict(self=1)


def case_alias_and_classmethod():
    frame = pd.DataFrame.from_dict({"x": {"a": 1, "b": 2}, "y": {"a": 3, "b": 4}}, orient="index")
    other = DF.from_records([(1, 2), (3, 4)], columns=["p", "q"])
    return frame, other


def case_lazy_submodules():
    root = xml.etree.ElementTree.fromstring("<a><b/></a>")
    importlib.import_module("xml.dom.minidom")
    doc = xml.dom.minidom.parseString("<a/>")
    return root.tag, doc.documentElement.tagName, np.fft.fft(np.ones(4)), np.lib.stride_tricks.sliding_window_view(np.arange(5), 2)


def case_dynamic_option_accessors():
    pd.options.display.max_rows = 20
    return pd.options.display.width, requests.codes.ok, pd.api.types.is_numeric_dtype(np.arange(3))


def case_datetime_index():
    idx = pd.Index(pd.to_datetime(["2024-01-01", "2024-01-02"]))
    return idx.tz_localize("UTC"), idx.normalize()


def case_reassigned_variable():
    frame = pd.DataFrame({"a": [1, 2, 3]})
    frame = frame["a"]
    return frame.tolist()


def case_session_instance_attrs():
    session = requests.Session()
    session.headers["X-Demo"] = "1"
    session.headers.update({"Accept": "application/json"})
    resp = requests.Response()
    return session.headers, session.max_redirects, resp.status_code, resp.headers


def case_requests_kwargs_passthrough():
    opts = {"timeout": 5, "allow_redirects": False}
    first = requests.get("https://example.com/a", **opts)
    second = requests.get("https://example.com/b", verify=False, **opts)
    third = requests.Session().get("https://example.com/c", timeout=5)
    return first.status_code, second.ok, third.text


def case_local_module():
    helper = localpkg.Helper(name="x")
    return localpkg.compute(3, scale=4), localpkg.CONSTANT, helper.name


def case_monkeypatched_attribute():
    np.custom_thing = 1
    setattr(pd, "my_helper", lambda: 2)
    return np.custom_thing + 1, pd.my_helper()


def case_namespace_instances():
    ns = types.SimpleNamespace(alpha=1, beta=2)
    args = argparse.Namespace(verbose=True)
    parser = argparse.ArgumentParser(prog="demo")
    return ns.alpha, args.verbose, parser.prog


def case_mock_instance():
    mock = MagicMock()
    mock.rolling_mean(3)
    return mock.anything.goes


def case_yf_ticker_attrs():
    ticker = yf.Ticker("AAPL")
    return ticker.ticker, ticker.session is not None


def case_try_except_removed_attr():
    try:
        scalar = np.float_
    except AttributeError:
        scalar = np.float64
    return scalar


def case_except_star():
    try:
        value = np.trapz([1.0, 2.0, 3.0])
    except* AttributeError:
        value = np.trapezoid([1.0, 2.0, 3.0])
    return value


def case_early_return_after_hasattr(y=(1.0, 2.0, 3.0)):
    if not hasattr(np, "trapz"):
        return np.trapezoid(y)
    return np.trapz(y)


def case_flag_variable(y=(1.0, 2.0, 3.0)):
    if HAS_TRAPZ:
        return np.trapz(y)
    return np.trapezoid(y)


def case_getattr_or_fallback(y=(1.0, 2.0, 3.0)):
    area = getattr(np, "trapezoid", None) or np.trapz
    return area(y)


def case_version_ifexp(y=(1.0, 2.0, 3.0)):
    fn = np.trapezoid if NEW_NUMPY else np.trapz
    return fn(y)


def case_platform_flag(path="."):
    if IS_WINDOWS:
        os.startfile(path)
        return winreg.HKEY_CURRENT_USER
    return os.getcwd()


def case_match_platform(path="."):
    match sys.platform:
        case "win32":
            os.startfile(path)
        case _:
            return os.sep
    return None


def case_signature_probe():
    if "foo" in inspect.signature(np.sum).parameters:
        return np.sum([1, 2], foo=True)
    return np.sum([1, 2])


def case_startfile_guard(path="."):
    if not hasattr(os, "startfile"):
        return None
    os.startfile(path)
    return path


@unittest.skipIf(sys.platform != "win32", "windows only")
def case_skipif_decorated(path="."):
    os.startfile(path)
    return path


def case_integrate_fallback():
    return integrate([1.0, 2.0, 3.0]), json_impl.dumps({"a": 1}), zstd


def case_suppress_and_with():
    with contextlib.suppress(OSError):
        os.remove("does-not-exist.tmp")
    return os.path.join("a", "b")


def case_os_path_submodule_alias():
    return os.path.basename("a/b.txt"), join("a", "b"), osp.splitext("c.tar")


def case_name_checked_in_dir_string(y=(1.0, 2.0, 3.0)):
    if "trapz" in dir(np):
        return np.trapz(y)
    return np.trapezoid(y)


def case_kwarg_checked_in_varnames():
    if "dtyp" in np.eye.__code__.co_varnames:
        return np.eye(2, dtyp=float)
    return np.eye(2, dtype=float)
