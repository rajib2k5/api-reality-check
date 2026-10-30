import contextlib, io, sys, warnings
with contextlib.redirect_stdout(io.StringIO()) as buf:
    print("x")
with contextlib.suppress(KeyError):
    {}["a"]
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    warnings.warn("x", category=DeprecationWarning, stacklevel=2)
print(buf.getvalue(), len(w), sys.version_info >= (3, 8), sys.argv[:0])
