import threading, logging, json, argparse, tempfile, dataclasses, functools
def work(x):
    return x
t = threading.Thread(target=work, args=(1,), daemon=True, name="w")
t.start()
t.join(timeout=1)
print(t.name, t.daemon, t.is_alive(), t.ident is not None)
fmt = logging.Formatter("{message}", style="{", validate=True, defaults={"a": 1})
enc = json.JSONEncoder(indent=2, sort_keys=True)
p = argparse.ArgumentParser(exit_on_error=False, allow_abbrev=False)
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
    print(d)
@dataclasses.dataclass(kw_only=True, slots=True)
class X:
    a: int = dataclasses.field(default=0, kw_only=True, metadata={"m": 1})
print(X(a=1), enc.encode({}), fmt.format(logging.makeLogRecord({"msg": "hi"})))
tl = threading.local()
tl.value = 3
print(tl.value)
