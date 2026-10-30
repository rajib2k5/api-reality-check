import json
import collections
del json
json = type("X", (), {"weird": 5})
print(json.weird, collections.Counter())
