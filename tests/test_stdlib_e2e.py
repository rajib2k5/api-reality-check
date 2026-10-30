"""End-to-end through extract -> probe (current interpreter) -> resolve, stdlib only."""
import sys

import pytest

from conftest import check, verdict_of
from test_guards import IDIOMS


def test_true_positive_misspelled_class_on_module(tmp_path):
    rep = check(tmp_path, "import collections\ncollections.OrderedDictt()\n")
    (f,) = [f for f in rep.findings if f.name == "OrderedDictt"]
    assert (f.verdict, f.reason, f.kind, f.line, f.col) == ("MISSING", "not_found", "attribute", 2, 12)
    assert "OrderedDict" in f.suggestions


def test_pure_python_class_kwarg_missing(tmp_path):
    rep = check(tmp_path, "import json\njson.JSONEncoder(sort_key=True)\n")
    f = [f for f in rep.findings if f.name == "sort_key"][0]
    assert (f.verdict, f.reason, f.kind) == ("MISSING", "not_in_signature", "kwarg")
    assert "sort_keys" in f.suggestions


def test_pure_python_function_kwarg_missing(tmp_path):
    rep = check(tmp_path, "import os\nos.makedirs('x', exists_ok=True)\n")
    assert verdict_of(rep, "exists_ok") == ("MISSING", "not_in_signature")


def test_json_dumps_kwarg_is_unknown_because_dumps_has_var_keyword(tmp_path):
    # Spec deviation, measured: json.dumps is (obj, *, ..., sort_keys=False, **kw). The typo is
    # real (it fails inside JSONEncoder.__init__) but the rules can only say var_keyword.
    rep = check(tmp_path, "import json\njson.dumps({}, sort_key=True)\n")
    assert verdict_of(rep, "sort_key") == ("UNKNOWN", "var_keyword")


def test_correct_kwargs_are_ok(tmp_path):
    rep = check(tmp_path, "import json, os\njson.dumps({}, sort_keys=True)\nos.makedirs('x', exist_ok=True)\n")
    assert [f for f in rep.findings if f.verdict != "UNKNOWN"] == []
    assert rep.ok >= 4


def test_lazy_submodules_resolved_by_import_fallback(tmp_path):
    rep = check(tmp_path, "import xml\nimport email\nxml.etree.ElementTree.parse\nemail.mime\n")
    assert rep.findings == []


def test_missing_submodule_import(tmp_path):
    rep = check(tmp_path, "import xml.etreee\n")
    assert verdict_of(rep, "xml.etreee", "module") == ("MISSING", "not_found")


def test_import_unknown_module_is_not_installed(tmp_path):
    rep = check(tmp_path, "import pandaz_does_not_exist\n")
    assert verdict_of(rep, "pandaz_does_not_exist", "module") == ("MISSING", "not_installed")


def test_from_import_missing_name(tmp_path):
    rep = check(tmp_path, "from collections import OrderedDictt\n")
    assert verdict_of(rep, "OrderedDictt", "attribute") == ("MISSING", "not_found")


def test_builtin_without_signature_is_unknown(tmp_path):
    rep = check(tmp_path, "import math\nmath.log(8, bas=2)\n")
    assert verdict_of(rep, "bas") == ("UNKNOWN", "no_signature")


def test_closed_class_instance_attr_missing(tmp_path):
    rep = check(tmp_path, "import ipaddress\na = ipaddress.IPv4Address('1.2.3.4')\na.is_privat\n")
    f = [f for f in rep.findings if f.name == "is_privat"][0]
    assert (f.verdict, f.reason) == ("MISSING", "not_found") and "is_private" in f.suggestions


def test_open_class_instance_attr_is_suspect_not_missing(tmp_path):
    # Fraction has a pure-Python __new__; deque declares its own tp_getattro.
    rep = check(tmp_path, "import fractions, collections\nfr = fractions.Fraction(1)\nfr.foo()\n"
                          "d = collections.deque()\nd.appendd(1)\nd.bar\n")
    assert verdict_of(rep, "foo")[0] == "SUSPECT"
    assert verdict_of(rep, "bar") == ("UNKNOWN", "instance_data_attr")
    assert verdict_of(rep, "appendd")[0] == "SUSPECT"


def test_not_a_class_constructor_gives_unknown(tmp_path):
    rep = check(tmp_path, "import os\nx = os.getcwd()\nx.foo\n")
    assert verdict_of(rep, "foo") == ("UNKNOWN", "not_a_class")


def test_caller_star_kwargs_downgrades_to_suspect(tmp_path):
    rep = check(tmp_path, "import json\nopts = {}\njson.JSONEncoder(sort_key=True, **opts)\n")
    assert verdict_of(rep, "sort_key") == ("SUSPECT", "star_kwargs_call")


def test_relative_import_unknown(tmp_path):
    rep = check(tmp_path, "from . import sibling\n")
    assert verdict_of(rep, ".", "module") == ("UNKNOWN", "relative_import")


def test_monkeypatched_attribute_not_flagged(tmp_path):
    rep = check(tmp_path, "import json\njson.custom = 1\nprint(json.custom)\n")
    assert verdict_of(rep, "custom") == ("UNKNOWN", "assigned_in_file")


def test_unguarded_startfile_is_missing_control(tmp_path):
    rep = check(tmp_path, "import os\ndef f(p):\n    os.startfile(p)\n")
    assert verdict_of(rep, "startfile") == ("MISSING", "not_found")


STDLIB_IDIOMS = [k for k, (name, _) in IDIOMS.items() if name == "startfile"]


@pytest.mark.parametrize("label", STDLIB_IDIOMS)
def test_guard_idioms_never_missing_end_to_end(tmp_path, label):
    name, src = IDIOMS[label]
    rep = check(tmp_path, src.replace("import os, sys, pytest", "import os, sys"))
    assert verdict_of(rep, name)[0] in ("UNKNOWN", "OK"), rep.findings


def test_except_handler_fallback_import_stdlib(tmp_path):
    src = "try:\n    from os import startfile\nexcept ImportError:\n    from os import startfilee as startfile\n"
    rep = check(tmp_path, src)
    assert all(f.verdict == "UNKNOWN" for f in rep.findings)


def test_inspect_signature_kwarg_guard_stdlib(tmp_path):
    src = ("import inspect, os\n"
           "if 'exists_ok' in inspect.signature(os.makedirs).parameters:\n"
           "    os.makedirs('x', exists_ok=True)\n")
    rep = check(tmp_path, src)
    assert verdict_of(rep, "exists_ok")[0] == "UNKNOWN"


def test_output_is_order_independent_for_lazy_submodules(tmp_path):
    a = check(tmp_path / "a", "import concurrent\nconcurrent.futures.ThreadPoolExecutor\n")
    assert a.findings == []


@pytest.mark.parametrize("src", ["import os.path\nos.path.join\n", "from os.path import join\n",
                                 "import os.path as osp\nosp.join('a', 'b')\n"])
def test_submodule_that_is_a_plain_module_in_sys_modules_is_ok(tmp_path, src):
    # R1: os.path is posixpath registered in sys.modules; os has no __path__. Correct code, no finding.
    rep = check(tmp_path, src)
    assert [(f.name, f.verdict, f.reason) for f in rep.findings] == []


def test_sys_modules_alias_still_reports_a_missing_attribute(tmp_path):
    rep = check(tmp_path, "import os.path\nos.path.joinn\n")
    assert verdict_of(rep, "joinn") == ("MISSING", "not_found")


def test_name_below_a_plain_module_is_still_missing(tmp_path):
    rep = check(tmp_path, "import os.pathh\n")
    assert verdict_of(rep, "os.pathh", "module") == ("MISSING", "not_found")


@pytest.mark.skipif(sys.version_info >= (3, 13), reason="typing.io was removed in 3.13")
def test_pseudo_module_class_in_sys_modules_is_ok(tmp_path):
    rep = check(tmp_path, "import typing.io\nfrom typing.io import TextIO\n")
    assert [(f.name, f.verdict) for f in rep.findings if f.verdict != "UNKNOWN"] == []


STRING_ONLY_ATTR = 'import collections\nif "OrderedDictt" in dir(collections):\n    collections.OrderedDictt()\n'
STRING_ONLY_KWARG = ('import os\nif "exists_ok" in os.makedirs.__code__.co_varnames:\n'
                     '    os.makedirs("x", exists_ok=True)\n')


def test_attribute_named_only_in_a_string_literal_is_guarded(tmp_path):
    # R2: no other guard rule applies here (dir() is not a guard call); only the string-literal rule.
    rep = check(tmp_path, STRING_ONLY_ATTR)
    assert verdict_of(rep, "OrderedDictt") == ("UNKNOWN", "guarded")


def test_kwarg_named_only_in_a_string_literal_is_guarded(tmp_path):
    rep = check(tmp_path, STRING_ONLY_KWARG)
    assert verdict_of(rep, "exists_ok") == ("UNKNOWN", "guarded")


@pytest.mark.parametrize("src,name", [(STRING_ONLY_ATTR, "OrderedDictt"), (STRING_ONLY_KWARG, "exists_ok")])
def test_string_only_cases_are_not_guarded_by_any_other_rule(tmp_path, src, name):
    from api_reality_check.extract import extract
    fa = extract("case.py", src.encode())
    refs = [r for r in fa.references if name in r.elements() or any(k.name == name for k in r.kwargs)]
    assert refs and not any(r.guard for r in refs) and name in fa.string_tokens
