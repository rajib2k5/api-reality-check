import json
def f():
    json = type("J", (), {"dumpz": staticmethod(lambda x: str(x))})
    return json.dumpz(1)
print(f())
