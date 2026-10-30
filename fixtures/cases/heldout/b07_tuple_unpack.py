import numpy as np, pandas as pd
np, pd = (type("A", (), {"aa": 1}), type("B", (), {"bb": 2}))
print(np.aa, pd.bb)
