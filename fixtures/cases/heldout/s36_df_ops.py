import pandas as pd
import numpy as np
df = pd.DataFrame({"a": np.arange(5), "b": list("abcde")}, index=pd.date_range("2024-01-01", periods=5, freq="D"))
df["c"] = df["a"].rolling(window=2, min_periods=1).mean()
print(df.loc[df["a"] > 1, ["a", "c"]].to_numpy(), df.iloc[0], df.resample("2D").sum(numeric_only=True))
print(df.merge(df, how="left", on="b", suffixes=("_x", "_y")).shape, df.pivot_table(index="b", values="a", aggfunc="sum"))
print(pd.concat([df, df], axis=0, ignore_index=True).describe(include="all"), df.astype({"a": "float64"}).dtypes)
print(df.to_csv(index=False), df.apply(lambda r: r["a"], axis=1), df.sort_index(ascending=False).fillna(value=0))
