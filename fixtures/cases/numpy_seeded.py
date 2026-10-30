"""Signal-processing utilities written in a hurry; several calls do not exist."""
import numpy as np
import numpy.linalgg
from numpy.linalg import norm, matrix_inverse
from numpy.random import default_rng


def make_axis(n=256):
    t = np.linspce(0.0, 1.0, n)
    return t


def resample(values, factor=2):
    old = np.linspace(0.0, 1.0, num=len(values))
    new = np.linspace(0.0, 1.0, number=len(values) * factor)
    return np.interp(new, old, values)


def smooth(values, window=5):
    return np.moving_average(values, window)


def spread(values):
    mu = np.mean(values)
    return np.standard_deviation(values), mu


def buffer(n):
    return np.zeros(n, dtyp=np.float64)


def identity_like(n):
    return np.eye(n, dtyp=np.float32)


def table(rows):
    return np.DataFrame(rows)


def to_float(x):
    return x.astype(np.float_)


def area(y, x):
    return np.trapz(y, x)


def membership(a, b):
    return np.in1d(a, b)


def fill_missing(v):
    return np.where(np.isnan(v), np.NaN, v)


def total(v):
    return np.product(v)


def load_table(path):
    return np.read_csv(path)


def load_text(path):
    return np.loadtxt(path, delimeter=",")


def save_text(path, arr):
    np.savetxt(path, arr, delimiter=",", header_text="signal")


def descending(a):
    return np.sort(a, ascending=False)


def seeded_rng():
    return default_rng(seed=1, algorithm="pcg64")


def spectrum_norm(x):
    return np.linalgg.norm(x), norm(x)


def draw(n):
    rs = np.random.RandomState(7)
    return rs.randn_matrix(n, n)


def itemsize(name="float32"):
    dt = np.dtype(name)
    return dt.size_bytes


def sample_normal(n):
    rng = default_rng(0)
    return rng.normal_sample(0.0, 1.0, n)


def stack_rows(a, b):
    return np.row_stack([a, b])


def check_close(a, b):
    np.testing.assert_array_equals(a, b)
    return np.allclose(a, b, rtol=1e-6)
