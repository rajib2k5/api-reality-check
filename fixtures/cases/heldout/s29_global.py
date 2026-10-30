import numpy as np
np_mod = None
def setup():
    global np
    import types
    np = types.SimpleNamespace(fancy=lambda: 1)
setup()
print(np.fancy())
