import numpy as np
rng = np.random.default_rng(0)
x = rng.normal(loc=0.0, scale=1.0, size=3)
y = rng.integers(low=0, high=10, size=4)
z = rng.choice([1, 2, 3], size=2, replace=False)
rng.shuffle(y)
print(x, y, z, rng.uniform(size=2))
