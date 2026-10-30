"""Extraction (DESIGN §4.1, §4.3, §14 A3). Pure ast; nothing here imports a library."""
import textwrap

from api_reality_check.extract import extract
from api_reality_check.models import Loc


def refs(src):
    fa = extract("t.py", textwrap.dedent(src).encode())
    assert fa.status == "analysed", fa.notes
    return fa.references


def chains(src):
    return {(r.module, r.path, r.instance_attr) for r in refs(src) if r.skip_reason is None}


def find(src, module, path, instance_attr=None):
    out = [r for r in refs(src) if (r.module, r.path, r.instance_attr) == (module, path, instance_attr)]
    out.sort(key=lambda r: not r.is_call)  # prefer the call-site reference over the import itself
    assert out, f"no reference {module} {path} {instance_attr}"
    return out[0]


def test_attribute_on_module_alias_has_loc_of_identifier():
    r = find("import numpy as np\nnp.linspce(0, 1)\n", "numpy", ("linspce",))
    assert r.path_locs == (Loc(2, 3),)
    assert r.is_call and not r.guard


def test_from_import_alias_call_records_kwarg_loc():
    r = find("from pandas import DataFrame as DF\nDF(colums=1)\n", "pandas", ("DataFrame",))
    assert [(k.name, k.loc) for k in r.kwargs] == [("colums", Loc(2, 3))]


def test_import_statement_is_a_module_reference():
    r = find("import pandaz\n", "pandaz", ())
    assert r.module_loc == Loc(1, 7) and r.module_as_written == "pandaz"


def test_dotted_import_records_full_module():
    assert ("xml.etree.ElementTree", (), None) in chains("import xml.etree.ElementTree\n")


def test_from_import_records_module_and_name():
    assert ("numpy", ("DataFrame",), None) in chains("from numpy import DataFrame\n")


def test_chain_is_cut_at_call_result():
    c = chains("import pandas as pd\npd.read_csv('x').head().foo\n")
    assert ("pandas", ("read_csv",), None) in c
    assert not any("head" in p for _, p, _ in c)


def test_second_binding_of_any_form_untrusts_name():
    for second in ["np = 1", "for np in []: pass", "with open('x') as np: pass", "del np",
                   "def f():\n    global np\n    np = 2", "(np := 3)", "np += 1",
                   "try:\n    pass\nexcept Exception as np:\n    pass",
                   "match 1:\n    case np:\n        pass"]:
        src = "import numpy as np\n" + second + "\nnp.linspce\n"
        assert ("numpy", ("linspce",), None) not in chains(src), second


def test_function_local_import_shadows_nothing_outside():
    src = """
    import numpy as np
    def f():
        np = None
        return np.zeros
    np.linspce
    """
    c = chains(src)
    assert ("numpy", ("linspce",), None) in c
    assert ("numpy", ("zeros",), None) not in c


def test_method_does_not_see_class_scope_binding():
    src = """
    import numpy as np
    class K:
        np = None
        def m(self):
            return np.linspce
    """
    assert ("numpy", ("linspce",), None) in chains(src)


def test_relative_import_is_never_queried():
    rs = refs("from . import thing\nfrom .mod import x\nthing.foo\n")
    assert all(r.skip_reason == "relative_import" for r in rs)


def test_type_checking_imports_produce_no_references():
    src = """
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        import pandaz as pz
    def f(x: "pz.Frame"):
        return pz.read
    """
    assert not any(r.module == "pandaz" for r in refs(src))


def test_instance_inference_direct_child_only():
    src = """
    import pandas as pd
    df = pd.DataFrame()
    df.rolling(window=3)
    """
    r = find(src, "pandas", ("DataFrame",), "rolling")
    assert r.is_call and [k.name for k in r.kwargs] == ["window"]
    nested = """
    import pandas as pd
    if True:
        df = pd.DataFrame()
    df.rolling(window=3)
    """
    assert ("pandas", ("DataFrame",), "rolling") not in chains(nested)
    reassigned = """
    import pandas as pd
    df = pd.DataFrame()
    df = df.dropna()
    df.rolling
    """
    assert ("pandas", ("DataFrame",), "rolling") not in chains(reassigned)


def test_inline_constructor_instance_attr():
    r = find("import requests\nrequests.Session().gett('u')\n", "requests", ("Session",), "gett")
    assert r.instance_loc == Loc(2, 19)


def test_only_one_attribute_resolved_on_instance():
    c = chains("import requests\ns = requests.Session()\ns.headers.update\n")
    assert ("requests", ("Session",), "headers") in c
    assert not any(ia == "update" for _, _, ia in c)


def test_store_on_module_attribute_marks_assigned_in_file():
    rs = refs("import numpy as np\nnp.custom = 1\nprint(np.custom)\n")
    r = [r for r in rs if r.path == ("custom",)]
    assert r and all(x.skip_reason == "assigned_in_file" for x in r)


def test_setattr_on_binding_poisons_every_attribute():
    rs = refs("import numpy as np\nsetattr(np, 'x', 1)\nnp.linspce\n")
    assert [r.skip_reason for r in rs if r.path == ("linspce",)] == ["assigned_in_file"]


def test_aliasing_module_object_poisons_its_attributes():
    rs = refs("import numpy as np\nm = np\nm.custom = 1\nnp.custom\n")
    assert [r.skip_reason for r in rs if r.path == ("custom",)] == ["assigned_in_file"]


def test_star_kwargs_recorded():
    r = find("import requests\nrequests.get('u', verify=False, **opts)\n", "requests", ("get",))
    assert r.caller_star_kwargs and [k.name for k in r.kwargs] == ["verify"]


def test_syntax_error_status():
    assert extract("t.py", b"def (:\n").status == "syntax_error"


def test_too_large_status():
    assert extract("t.py", b"x = 1\n" * 400_000).status == "too_large"


def test_string_tokens_collected():
    fa = extract("t.py", b"import numpy as np\nif hasattr(np, 'trapz'):\n    pass\nx = f'use {1} trapezoid now'\n")
    assert {"trapz", "trapezoid"} <= fa.string_tokens


def test_star_import_untrusts_earlier_bindings_in_scope():
    src = "import numpy as np\nfrom os.path import *\nnp.linspce\n"
    assert ("numpy", ("linspce",), None) not in chains(src)
    assert ("os.path", (), None) in chains(src)


def test_type_annotations_do_not_count_as_aliasing():
    src = """
    from typing import Optional
    from pandas import DataFrame
    def f(x: DataFrame, y: Optional[DataFrame] = None) -> dict[str, DataFrame]:
        z: DataFrame = x
        return DataFrame.from_dictt({})
    isinstance(1, (DataFrame, int))
    """
    rs = [r for r in refs(src) if r.path == ("DataFrame", "from_dictt")]
    assert rs and rs[0].skip_reason is None


def test_passing_class_to_unknown_function_poisons_it():
    rs = refs("from pandas import DataFrame\nregister(DataFrame)\nDataFrame.custom\n")
    assert [r.skip_reason for r in rs if r.path == ("DataFrame", "custom")] == ["assigned_in_file"]


def test_future_imports_are_never_queried():
    assert refs("import __future__\nfrom __future__ import annotations\n__future__.annotations\n") == []
