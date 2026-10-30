"""Against real numpy 2.5.4 / pandas 3.1.0 / requests 2.34.2 / yfinance 1.7.0 (ARC_TEST_PYTHON).
Each "must not flag" case is code that runs correctly in that environment (DESIGN §14)."""
import pytest

from conftest import check, verdict_of

from test_guards import IDIOMS, skip_if_unparseable


def test_np_linspce_missing_with_suggestion(tmp_path, arc_python):
    rep = check(tmp_path, "import numpy as np\nnp.linspce(0, 1)\n", python=arc_python)
    f = [f for f in rep.findings if f.name == "linspce"][0]
    assert (f.verdict, f.reason, f.line, f.col) == ("MISSING", "not_found", 2, 3)
    assert f.suggestions[0] == "linspace" and f.dist == "numpy" and f.dist_version == "2.5.4"


def test_pd_read_csvv_missing(tmp_path, arc_python):
    rep = check(tmp_path, "import pandas as pd\npd.read_csvv('x')\n", python=arc_python)
    assert verdict_of(rep, "read_csvv") == ("MISSING", "not_found")


def test_requests_gett_missing(tmp_path, arc_python):
    rep = check(tmp_path, "import requests\nrequests.gett('u')\n", python=arc_python)
    assert verdict_of(rep, "gett") == ("MISSING", "not_found")


def test_from_numpy_import_dataframe_missing_with_cross_module_suggestion(tmp_path, arc_python):
    rep = check(tmp_path, "import pandas as pd\nfrom numpy import DataFrame\n", python=arc_python)
    f = [f for f in rep.findings if f.name == "DataFrame"][0]
    assert f.verdict == "MISSING" and "pandas.DataFrame" in f.suggestions


def test_import_pandaz_not_installed(tmp_path, arc_python):
    rep = check(tmp_path, "import pandaz\n", python=arc_python)
    assert verdict_of(rep, "pandaz", "module") == ("MISSING", "not_installed")


def test_removed_numpy_alias_missing_with_hint(tmp_path, arc_python):
    rep = check(tmp_path, "import numpy as np\nnp.float_\n", python=arc_python)
    f = [f for f in rep.findings if f.name == "float_"][0]
    assert f.verdict == "MISSING" and "float64" in (f.hint or "")


def test_df_plot_kind_is_not_flagged(tmp_path, arc_python):
    rep = check(tmp_path, "import pandas as pd\ndf = pd.DataFrame({'a': [1]})\ndf.plot(kind='line')\n",
                python=arc_python)
    assert verdict_of(rep, "kind") == ("UNKNOWN", "descriptor_callable")
    assert verdict_of(rep, "plot")[0] == "OK"


def test_np_arange_start_keyword_is_not_missing(tmp_path, arc_python):
    rep = check(tmp_path, "import numpy as np\nnp.arange(start=1, stop=5)\n", python=arc_python)
    assert verdict_of(rep, "start") == ("SUSPECT", "untrusted_signature")
    assert verdict_of(rep, "stop")[0] == "OK"


def test_np_add_sig_keyword_is_not_missing(tmp_path, arc_python):
    rep = check(tmp_path, "import numpy as np\nnp.add(1, 2, sig='dd->d')\n", python=arc_python)
    assert verdict_of(rep, "sig")[0] in ("SUSPECT", "UNKNOWN")


def test_np_linspace_kwarg_typo_is_suspect(tmp_path, arc_python):
    rep = check(tmp_path, "import numpy as np\nnp.linspace(0, 1, numm=5)\n", python=arc_python)
    f = [f for f in rep.findings if f.name == "numm"][0]
    assert f.verdict in ("SUSPECT", "MISSING") and "num" in f.suggestions


def test_pandas_pure_python_kwarg_missing(tmp_path, arc_python):
    rep = check(tmp_path, "import pandas as pd\npd.read_csv('x.csv', delim_whitespace=True)\n", python=arc_python)
    assert verdict_of(rep, "delim_whitespace") == ("MISSING", "not_in_signature")


def test_hard_cases_must_not_flag(tmp_path, arc_python):
    src = """
    import numpy as np
    import requests
    import xml
    from pandas import DataFrame as DF
    import pandas as pd
    import yfinance as yf
    opts = {}
    requests.get("u", verify=False, **opts)
    np.fft.fft
    xml.etree.ElementTree
    DF({"a": [1]})
    pd.DataFrame.from_dict({}, orient="index")
    s = requests.Session()
    s.headers
    idx = pd.Index([1, 2])
    idx.tz_localize
    yf.download("X", bogus=1)
    df = pd.DataFrame()
    df.rolling_mean()
    g = np.random.Generator(np.random.PCG64())
    g.bit_generator
    """
    rep = check(tmp_path, src, python=arc_python)
    assert [f for f in rep.findings if f.verdict == "MISSING"] == []


def test_closed_cython_class_instance_attr_missing(tmp_path, arc_python):
    rep = check(tmp_path, "import numpy as np\ng = np.random.Generator(np.random.PCG64())\ng.bit_generatr\n",
                python=arc_python)
    assert verdict_of(rep, "bit_generatr") == ("MISSING", "not_found")


NUMPY_IDIOMS = [k for k, (name, _) in IDIOMS.items() if name in ("trapz", "delim_whitespace")]


@pytest.mark.parametrize("label", NUMPY_IDIOMS)
def test_guard_idioms_never_missing_with_real_numpy(tmp_path, arc_python, label):
    skip_if_unparseable(label)
    name, src = IDIOMS[label]
    rep = check(tmp_path, src, python=arc_python)
    assert verdict_of(rep, name)[0] in ("UNKNOWN", "OK"), rep.findings


def test_unguarded_trapz_is_missing_control(tmp_path, arc_python):
    rep = check(tmp_path, "import numpy as np\nnp.trapz([1, 2])\n", python=arc_python)
    assert verdict_of(rep, "trapz") == ("MISSING", "not_found")
