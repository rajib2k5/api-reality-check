import pandas as pd
s = pd.Series(["a,b", "c"])
print(s.str.split(",", expand=True), s.str.contains("a", regex=False), s.str.upper().str.len(), pd.to_datetime(["2024-01-01"], format="%Y-%m-%d"))
print(pd.to_numeric(pd.Series(["1", "x"]), errors="coerce"), s.value_counts(normalize=True), s.map({"c": 1}).isna().sum())
