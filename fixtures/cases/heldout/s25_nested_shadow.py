import numpy as np
def outer():
    def np_fn():
        np = {"linspce": 1}
        return np["linspce"]
    class np2:
        linspce = 3
    return np_fn(), np2.linspce
print(outer())
