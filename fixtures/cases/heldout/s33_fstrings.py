import numpy as np
import pandas as pd
x = np.array([1.5, 2.5])
s = pd.Series([1, 2], name="s")
print(f"{x.mean():.2f} {np.pi:.3f} {s.sum()} {s.name!r} {pd.__version__}")
