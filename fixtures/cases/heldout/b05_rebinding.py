import pandas as pd
import numpy as np
from pathlib import Path
class Path(Path):
    def custom(self):
        return str(self)
print(Path("x").custom())
df = pd.DataFrame({"a": [1]})
df = type("D", (), {"weird_method": lambda self: 1})()
print(df.weird_method())
for np in [type("N", (), {"zzz": 1})]:
    print(np.zzz)
try:
    raise ValueError("x")
except ValueError as pd:
    print(pd.args, pd.with_traceback(None))
