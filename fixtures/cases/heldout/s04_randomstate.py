import numpy as np
rs = np.random.RandomState(seed=42)
print(rs.randn(3), rs.randint(0, 5, size=3), rs.permutation(4), rs.rand(2))
