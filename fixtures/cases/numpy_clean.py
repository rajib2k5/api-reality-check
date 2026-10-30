"""Numeric helpers of the kind an assistant writes for a small analytics script."""
import numpy as np
from numpy.linalg import norm, solve
from numpy.random import default_rng


def make_signal(n=256, seed=42):
    rng = default_rng(seed)
    t = np.linspace(0.0, 1.0, num=n, endpoint=False)
    clean = np.sin(2 * np.pi * 5 * t) + 0.5 * np.sin(2 * np.pi * 12 * t)
    noise = rng.normal(loc=0.0, scale=0.2, size=n)
    return t, clean + noise


def summarize(values):
    arr = np.asarray(values, dtype=np.float64)
    return {
        "mean": np.mean(arr),
        "median": np.median(arr),
        "std": np.std(arr, ddof=1),
        "p95": np.percentile(arr, 95, method="linear"),
        "min": np.min(arr),
        "max": np.max(arr),
        "argmax": int(np.argmax(arr)),
    }


def moving_average(values, window=5):
    kernel = np.ones(window, dtype=float) / window
    return np.convolve(values, kernel, mode="valid")


def spectrum(signal, sample_rate=256.0):
    coeffs = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(len(signal), d=1.0 / sample_rate)
    return freqs, np.abs(coeffs)


def fit_line(x, y):
    slope, intercept = np.polyfit(x, y, deg=1)
    resid = y - (slope * x + intercept)
    return slope, intercept, np.sqrt(np.mean(resid ** 2))


def solve_system():
    a = np.array([[3.0, 1.0], [1.0, 2.0]])
    b = np.array([9.0, 8.0])
    x = solve(a, b)
    assert np.allclose(a @ x, b, rtol=1e-8, atol=1e-10)
    return x, norm(x, ord=2)


def integrate(y, x):
    return np.trapezoid(y, x=x)


def reshape_and_stack():
    base = np.arange(12).reshape(3, 4)
    flipped = np.flip(base, axis=1)
    both = np.concatenate([base, flipped], axis=0)
    pairs = np.stack([base, flipped], axis=-1)
    return np.where(both % 2 == 0, both, -both), pairs.shape


def clip_and_round(values):
    out = np.clip(values, a_min=-1.0, a_max=1.0)
    return np.round(out, decimals=2)


def cumulative(values):
    return np.cumsum(values, dtype=float), np.diff(values, n=1), np.cumprod(values + 1.0)


def histogram_counts(values):
    counts, edges = np.histogram(values, bins=10, range=(-2.0, 2.0), density=False)
    return counts, edges


def grid_demo():
    xs = np.linspace(-1.0, 1.0, 5)
    gx, gy = np.meshgrid(xs, xs, indexing="ij")
    return np.hypot(gx, gy), np.eye(5, k=1, dtype=np.float32)


def sorting_demo(values):
    order = np.argsort(values, kind="stable")
    uniq, counts = np.unique(np.round(values, 1), return_counts=True)
    return order, uniq, counts


def correlation(a, b):
    return np.corrcoef(a, b)[0, 1], np.cov(a, b, ddof=1)[0, 1]


def masks(values):
    clean = values[~np.isnan(values)]
    return np.nanmean(values), np.isfinite(clean).all(), np.full(3, fill_value=np.pi)


def io_roundtrip(path="signal.csv"):
    data = np.arange(6, dtype=float).reshape(2, 3)
    np.savetxt(path, data, delimiter=",", fmt="%.3f")
    return np.loadtxt(path, delimiter=",", ndmin=2)


def dtype_demo():
    arr = np.zeros((2, 2), dtype=np.int64)
    arr += np.iinfo(np.int32).max
    return arr.astype(np.float64), np.finfo(np.float64).eps, np.int_(3), np.pi, np.nan, np.inf


def run():
    t, sig = make_signal(n=256, seed=1)
    stats = summarize(sig)
    smooth = moving_average(sig, window=7)
    freqs, amp = spectrum(sig)
    slope, intercept, rmse = fit_line(t, sig)
    x, xnorm = solve_system()
    area = integrate(sig, t)
    mixed, shape = reshape_and_stack()
    clipped = clip_and_round(sig)
    csum, delta, prod = cumulative(sig)
    counts, edges = histogram_counts(sig)
    dist, ident = grid_demo()
    order, uniq, ucounts = sorting_demo(sig)
    r, c = correlation(sig, np.roll(sig, shift=3))
    mean_nan, finite, filled = masks(sig)
    loaded = io_roundtrip()
    zeros, eps, i3, pi, nan, inf = dtype_demo()
    np.testing.assert_allclose(x, [2.0, 3.0], rtol=1e-6)
    return stats, area, loaded
