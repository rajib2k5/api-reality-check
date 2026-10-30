import pandas as pd
def f(pd, np):
    return pd.foo + np.barbaz
class O:
    foo = 1
    barbaz = 2
print(f(O, O))
def g(json):
    return json.custom_attr()
print(g(type("J", (), {"custom_attr": staticmethod(lambda: 3)})))
