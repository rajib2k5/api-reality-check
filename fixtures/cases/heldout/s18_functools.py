import functools
from functools import lru_cache, partial, reduce, wraps
@lru_cache(maxsize=None)
def fib(n):
    return n if n < 2 else fib(n - 1) + fib(n - 2)
def deco(fn):
    @wraps(fn)
    def inner(*a, **k):
        return fn(*a, **k)
    return inner
@deco
def g(a, b=2):
    return a + b
print(fib(10), fib.cache_info(), partial(int, base=2)("101"), reduce(lambda a, b: a + b, [1, 2], 0), g(1, b=3))
print(functools.cmp_to_key(lambda a, b: a - b), functools.cached_property)
