import functools
import time
def timed(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        r = fn(*args, **kwargs)
        return r, time.perf_counter() - t0
    return wrapper
@timed
def compute(n, scale=1):
    return n * scale
@functools.lru_cache(maxsize=128, typed=False)
def sq(n):
    return n * n
print(compute(3, scale=2), sq(4), compute.__wrapped__(1, scale=1))
