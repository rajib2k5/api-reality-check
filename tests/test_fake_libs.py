"""Counter-examples from the adversarial review (DESIGN §14), as installed packages in a throwaway
venv so that they are queried exactly like third-party code."""
import pytest

from conftest import check, make_venv, verdict_of

FAKELIB = '''
import dataclasses, functools, inspect

@dataclasses.dataclass
class P:
    x: int
    y: int = 0

@dataclasses.dataclass(frozen=True)
class F:
    a: int
    def __post_init__(self):
        object.__setattr__(self, "b", self.a * 2)

class Slotted:
    __slots__ = ("v",)
    def __init__(self, v):
        self.v = v

def posonly(a, /, b=1):
    return a

def passthrough(fn):
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        return fn(*args, **kwargs)
    return inner

@passthrough
def wrapped(a):
    return a

def _inner(a):
    return a

@functools.wraps(_inner)
def outer(a, retries=3):
    return _inner(a)

def sig_override(*args, **kw):
    return 1
sig_override.__signature__ = inspect.Signature([inspect.Parameter("x", inspect.Parameter.POSITIONAL_OR_KEYWORD)])

class Meta(type):
    def __call__(cls, *a, **k):
        return {}

class M(metaclass=Meta):
    def __init__(self, a):
        pass

class K:
    def __init__(self, a, b=1):
        pass
    @classmethod
    def make(cls, size=1):
        return cls(size)
    def method(self, q=1):
        return q

class _AccessorView:
    def __init__(self, data):
        self.data = data

class _Accessor:
    def __get__(self, obj, owner):
        return _AccessorView if obj is None else _AccessorView(obj)

class D:
    acc = _Accessor()

def with_logger(cls):
    orig = cls.__init__
    def __init__(self, *a, **k):
        orig(self, *a, **k)
        self.log = 1
    cls.__init__ = __init__
    return cls

@with_logger
class W:
    def __init__(self):
        pass

class Shadow:
    def __init__(self, fast=False):
        if fast:
            self.send = lambda data, **kw: data

    def send(self, data, retries=1):
        return data

class SlottedSender:
    __slots__ = ()

    def send(self, data, retries=1):
        return data
'''


@pytest.fixture(scope="module")
def fakepy(tmp_path_factory):
    py, _ = make_venv(tmp_path_factory.mktemp("fakevenv"), {"fakelib.py": FAKELIB})
    return py


def test_dataclass_field_without_default_is_not_flagged(tmp_path, fakepy):
    rep = check(tmp_path, "import fakelib\np = fakelib.P(1)\np.x\np.y\n", python=fakepy)
    assert verdict_of(rep, "x") == ("OK", None) and verdict_of(rep, "y") == ("OK", None)


def test_dataclass_unknown_field_kwarg_is_missing(tmp_path, fakepy):
    rep = check(tmp_path, "import fakelib\nfakelib.P(1, z=2)\n", python=fakepy)
    assert verdict_of(rep, "z") == ("MISSING", "not_in_signature")


def test_object_setattr_in_post_init_is_not_missing(tmp_path, fakepy):
    rep = check(tmp_path, "import fakelib\nf = fakelib.F(1)\nf.b\n", python=fakepy)
    assert verdict_of(rep, "b") == ("UNKNOWN", "instance_data_attr")


def test_called_unknown_instance_attr_on_open_class_is_suspect(tmp_path, fakepy):
    rep = check(tmp_path, "import fakelib\nf = fakelib.F(1)\nf.b()\n", python=fakepy)
    assert verdict_of(rep, "b") == ("SUSPECT", "instance_attr_not_on_class")


def test_instance_attr_in_longer_chain_not_directly_called_is_unknown(tmp_path, fakepy):
    rep = check(tmp_path, "import fakelib\nf = fakelib.F(1)\nf.b.c()\nfakelib.F(1).d.e\n", python=fakepy)
    assert verdict_of(rep, "b") == ("UNKNOWN", "instance_data_attr")
    assert verdict_of(rep, "d") == ("UNKNOWN", "instance_data_attr")


def test_inline_instance_call_is_suspect_and_load_is_unknown(tmp_path, fakepy):
    rep = check(tmp_path, "import fakelib\nfakelib.F(1).b()\nfakelib.F(1).c\n", python=fakepy)
    assert verdict_of(rep, "b") == ("SUSPECT", "instance_attr_not_on_class")
    assert verdict_of(rep, "c") == ("UNKNOWN", "instance_data_attr")


def test_closed_class_missing_attr_is_missing_whether_called_or_not(tmp_path, fakepy):
    rep = check(tmp_path, "import fakelib\ns = fakelib.Slotted(1)\ns.w\ns.z()\n", python=fakepy)
    assert verdict_of(rep, "w") == ("MISSING", "not_found")
    assert verdict_of(rep, "z") == ("MISSING", "not_found")


def test_class_decorator_wrapped_init_attr_not_missing(tmp_path, fakepy):
    rep = check(tmp_path, "import fakelib\nw = fakelib.W()\nw.log\n", python=fakepy)
    assert verdict_of(rep, "log")[0] != "MISSING"


def test_slotted_class_instance_attr_missing(tmp_path, fakepy):
    rep = check(tmp_path, "import fakelib\ns = fakelib.Slotted(1)\ns.v\ns.w\n", python=fakepy)
    assert verdict_of(rep, "v") == ("OK", None)
    assert verdict_of(rep, "w") == ("MISSING", "not_found")


def test_positional_only_as_keyword_is_missing(tmp_path, fakepy):
    rep = check(tmp_path, "import fakelib\nfakelib.posonly(a=1)\nfakelib.posonly(1, b=2)\n", python=fakepy)
    assert verdict_of(rep, "a") == ("MISSING", "positional_only")
    assert verdict_of(rep, "b") == ("OK", None)


def test_var_keyword_wrapper_makes_kwarg_unknown(tmp_path, fakepy):
    rep = check(tmp_path, "import fakelib\nfakelib.wrapped(1, bogus=2)\n", python=fakepy)
    assert verdict_of(rep, "bogus") == ("UNKNOWN", "wrapper_varkw")


def test_wraps_wrapper_with_extra_explicit_kwarg_is_ok(tmp_path, fakepy):
    rep = check(tmp_path, "import fakelib\nfakelib.outer(1, retries=2)\n", python=fakepy)
    assert verdict_of(rep, "retries") == ("OK", None)


def test_signature_override_is_not_trusted(tmp_path, fakepy):
    rep = check(tmp_path, "import fakelib\nfakelib.sig_override(1, y=2)\n", python=fakepy)
    assert verdict_of(rep, "y")[0] in ("UNKNOWN", "SUSPECT")


def test_metaclass_call_is_not_trusted(tmp_path, fakepy):
    rep = check(tmp_path, "import fakelib\nm = fakelib.M(1)\nm.keys\nfakelib.M(1, zz=2)\n", python=fakepy)
    assert verdict_of(rep, "keys")[0] != "MISSING"
    assert verdict_of(rep, "zz")[0] != "MISSING"


def test_classmethod_and_method_kwargs(tmp_path, fakepy):
    src = ("import fakelib\nfakelib.K.make(size=2)\nfakelib.K.make(sise=2)\n"
           "k = fakelib.K(1)\nk.method(q=2)\nk.method(qq=2)\nk.methd()\n")
    rep = check(tmp_path, src, python=fakepy)
    assert verdict_of(rep, "size") == ("OK", None)
    assert verdict_of(rep, "sise") == ("MISSING", "not_in_signature")
    assert verdict_of(rep, "q") == ("OK", None)
    assert verdict_of(rep, "qq") == ("SUSPECT", "instance_may_shadow")   # R3: K instances have __dict__
    assert verdict_of(rep, "methd") == ("SUSPECT", "instance_attr_not_on_class")


def test_attribute_reached_through_descriptor_is_not_trusted(tmp_path, fakepy):
    # Class access returns a class whose signature says nothing about how the attribute is used.
    rep = check(tmp_path, "import fakelib\nfakelib.D.acc(kind=1)\nd = fakelib.D()\nd.acc(kind=1)\n", python=fakepy)
    assert [(f.line, f.verdict, f.reason) for f in rep.findings if f.name == "kind"] == [
        (2, "UNKNOWN", "descriptor_callable"), (4, "UNKNOWN", "descriptor_callable")]


def test_method_kwarg_on_open_class_instance_is_capped_at_suspect(tmp_path, fakepy):
    # R3: Shadow(fast=True) replaces send on the instance, so send(retrys=) may be valid.
    rep = check(tmp_path, "import fakelib\ns = fakelib.Shadow(fast=True)\ns.send(1, retrys=2)\n", python=fakepy)
    assert verdict_of(rep, "retrys") == ("SUSPECT", "instance_may_shadow")


def test_method_kwarg_on_closed_class_instance_stays_missing(tmp_path, fakepy):
    rep = check(tmp_path, "import fakelib\ns = fakelib.SlottedSender()\ns.send(1, retrys=2)\n", python=fakepy)
    assert verdict_of(rep, "retrys") == ("MISSING", "not_in_signature")


def test_method_kwarg_through_the_class_is_still_missing(tmp_path, fakepy):
    # No instance involved: fakelib.Shadow.send is the class attribute itself.
    rep = check(tmp_path, "import fakelib\nfakelib.Shadow.send(None, 1, retrys=2)\n", python=fakepy)
    assert verdict_of(rep, "retrys") == ("MISSING", "not_in_signature")
