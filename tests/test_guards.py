"""Guard idioms A-K from the adversarial review (DESIGN §14 A3). Each is correct, working code
that touches a name absent from some environments; the reference to it must be guarded."""
import sys
import textwrap

import pytest

from api_reality_check.extract import extract

IDIOMS = {
    "A_except_handler_fallback_import": ("trapz", """
        try:
            from numpy import trapezoid
        except ImportError:
            from numpy import trapz as trapezoid
        r = trapezoid([1, 2, 3])
        """),
    "B_early_return_after_hasattr": ("trapz", """
        import numpy as np
        def integrate(y):
            if hasattr(np, "trapezoid"):
                return np.trapezoid(y)
            return np.trapz(y)
        """),
    "C_hasattr_flag_variable": ("trapz", """
        import numpy as np
        HAS_TRAPEZOID = hasattr(np, "trapezoid")
        def integrate(y):
            if not HAS_TRAPEZOID:
                return np.trapz(y)
            return np.trapezoid(y)
        """),
    "C2_flag_early_return": ("startfile", """
        import os, sys
        IS_WINDOWS = sys.platform == "win32"
        def open_file(p):
            if not IS_WINDOWS:
                return None
            os.startfile(p)
        """),
    "D_getattr_or_fallback": ("trapz", """
        import numpy as np
        trapezoid = getattr(np, "trapezoid", None) or np.trapz
        """),
    "E_platform_flag": ("startfile", """
        import os, sys
        IS_WINDOWS = sys.platform == "win32"
        def open_file(p):
            if IS_WINDOWS:
                os.startfile(p)
        """),
    "F_match_sys_platform": ("startfile", """
        import os, sys
        def open_file(p):
            match sys.platform:
                case "win32":
                    os.startfile(p)
                case _:
                    pass
        """),
    "G_inspect_signature_parameters": ("delim_whitespace", """
        import inspect, io, pandas as pd
        src = io.StringIO("a b\\n1 2")
        if "delim_whitespace" in inspect.signature(pd.read_csv).parameters:
            df = pd.read_csv(src, delim_whitespace=True)
        else:
            df = pd.read_csv(src, sep=r"\\s+")
        """),
    "H_not_hasattr_return": ("startfile", """
        import os
        def open_file(p):
            if not hasattr(os, "startfile"):
                return None
            os.startfile(p)
        """),
    "I_skipif_decorator": ("startfile", """
        import os, sys, pytest
        @pytest.mark.skipif(sys.platform != "win32", reason="windows only")
        def test_open():
            os.startfile("x")
        """),
    "J_version_flag_ifexp": ("trapz", """
        import numpy as np
        NP2 = int(np.__version__.split(".")[0]) >= 2
        def integrate(y):
            return np.trapezoid(y) if NP2 else np.trapz(y)
        """),
    "K_except_star": ("trapz", """
        import numpy as np
        try:
            r = np.trapz([1, 2, 3])
        except* AttributeError:
            r = np.trapezoid([1, 2, 3])
        """),
}


def skip_if_unparseable(label):
    if label.startswith("K_") and sys.version_info < (3, 11):
        pytest.skip("except* only parses on Python >= 3.11 (the tool's own interpreter)")


def _refs_touching(src, name):
    fa = extract("t.py", textwrap.dedent(src).encode())
    assert fa.status == "analysed", fa.notes
    out = []
    for r in fa.references:
        if name in r.path or r.instance_attr == name or any(k.name == name for k in r.kwargs):
            out.append(r)
    return fa, out


@pytest.mark.parametrize("label", sorted(IDIOMS))
def test_guard_idiom_marks_reference_guarded(label):
    skip_if_unparseable(label)
    name, src = IDIOMS[label]
    fa, rs = _refs_touching(src, name)
    # Either the reference is guarded, or it was never emitted, or the name sits in a string
    # literal (the resolver's file-wide rule). It must not be an unguarded, queryable reference.
    exposed = [r for r in rs if not r.guard and r.skip_reason is None and name not in fa.string_tokens]
    assert exposed == [], exposed


def test_guard_rules_do_not_guard_everything():
    # Control: the same names with no guard idiom are exposed.
    for src, name in [("import numpy as np\nnp.trapz([1])\n", "trapz"),
                      ("import os\ndef f(p):\n    os.startfile(p)\n", "startfile")]:
        fa, rs = _refs_touching(src, name)
        assert rs and not rs[0].guard and name not in fa.string_tokens


def test_hasattr_guard_in_one_function_does_not_leak_to_another():
    src = """
    import os
    def a():
        if hasattr(os, "x"):
            pass
    def b(p):
        os.startfile(p)
    """
    fa, rs = _refs_touching(src, "startfile")
    assert rs and not rs[0].guard


def test_module_level_platform_if_guards_only_that_statement():
    src = """
    import os, sys
    if sys.platform == "win32":
        os.startfile("x")
    os.startfilee("y")
    """
    fa = extract("t.py", textwrap.dedent(src).encode())
    by = {r.path: r.guard for r in fa.references if r.module == "os" and r.path}
    assert by[("startfile",)] is True and by[("startfilee",)] is False


def test_try_except_valueerror_is_not_a_guard():
    src = "import os\ntry:\n    os.startfile('x')\nexcept ValueError:\n    pass\n"
    fa, rs = _refs_touching(src, "startfile")
    assert rs and not rs[0].guard


def test_optional_import_flag():
    src = "try:\n    import pandaz\nexcept ImportError:\n    pandaz = None\n"
    fa = extract("t.py", src.encode())
    r = [r for r in fa.references if r.module == "pandaz"][0]
    assert r.optional_import and r.guard
