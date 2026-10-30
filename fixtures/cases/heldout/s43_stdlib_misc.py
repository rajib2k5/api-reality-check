import csv, io, statistics, random, hashlib, time, uuid, textwrap, string, heapq, bisect, math
buf = io.StringIO()
w = csv.DictWriter(buf, fieldnames=["a"], extrasaction="ignore")
w.writeheader()
w.writerow({"a": 1, "b": 2})
random.seed(0)
print(buf.getvalue(), statistics.mean([1, 2]), random.choice([1]), random.sample(range(5), k=2), hashlib.sha256(b"x").hexdigest())
print(time.perf_counter() > 0, uuid.uuid4().hex, textwrap.dedent("  a"), string.ascii_letters[:3], heapq.nlargest(1, [1, 2]), bisect.bisect_left([1, 2], 2), math.isclose(1, 1, rel_tol=1e-9))
print(sorted([3, 1], key=lambda v: -v, reverse=True), "a,b".split(",", maxsplit=1), int("10", base=2), round(1.234, ndigits=1))
