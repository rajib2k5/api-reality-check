import numpy as np
x = np.array([1, 2], dtype=np.float32)
info = np.finfo(np.float64)
print(x.dtype.name, info.eps, np.iinfo(np.int64).max, np.dtype("int8").itemsize, np.ndarray, np.bool_(True), np.float64(1).item())
print(np.ma.masked_array([1, 2], mask=[0, 1]).sum(), np.fft.fft(x).real, np.polynomial.Polynomial([1, 2])(1), np.testing.assert_allclose)
