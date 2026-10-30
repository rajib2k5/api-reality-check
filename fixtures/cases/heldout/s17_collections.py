from collections import Counter, defaultdict, deque, OrderedDict, namedtuple
import collections
c = Counter("aabbc")
d = defaultdict(list)
d["x"].append(1)
q = deque(maxlen=3)
q.appendleft(1)
P = namedtuple("P", ["x", "y"], defaults=[0])
od = OrderedDict()
od["a"] = 1
od.move_to_end("a", last=False)
print(c.most_common(n=2), dict(d), q, P(x=1)._asdict(), collections.ChainMap({}, {"a": 1})["a"])
