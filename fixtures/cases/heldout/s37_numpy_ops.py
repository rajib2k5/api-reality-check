import numpy as np
a = np.linspace(0, 1, num=5, endpoint=True)
b = np.where(a > 0.5, a, 0)
m = np.array([[1.0, 2.0], [3.0, 4.0]])
print(np.linalg.inv(m), np.linalg.norm(m, ord=2), np.mean(a, axis=0, keepdims=True), np.clip(a, 0.1, 0.9))
print(np.concatenate([a, b], axis=0), np.stack([a, b], axis=1).shape, np.argsort(a, kind="stable"), np.percentile(a, 50))
print(a.reshape(5, 1).T, m.astype(np.int32), np.einsum("ij->j", m), np.isclose(a, b, atol=1e-8), np.unique(b, return_counts=True))
print(np.full((2, 2), fill_value=3), np.save, np.random.seed(0), np.random.rand(2), np.nan_to_num(np.array([np.nan]), nan=0.0))
