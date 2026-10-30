import json
s = json.dumps({"b": 1, "a": [1, 2]}, indent=2, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ": "))
print(json.loads(s, parse_float=float, object_hook=dict))
