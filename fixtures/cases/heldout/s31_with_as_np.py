import numpy as np
import contextlib
@contextlib.contextmanager
def ctx():
    yield {"a": 1}
with ctx() as np:
    print(np["a"], np.get("a"), np.keys())
