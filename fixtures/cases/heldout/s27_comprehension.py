import numpy as np
arrays = [np.arange(3) for _ in range(2)]
sums = [a.sum() for a in arrays]
print(sums, {k: v for k, v in zip("ab", sums)}, [np for np in range(2)])
