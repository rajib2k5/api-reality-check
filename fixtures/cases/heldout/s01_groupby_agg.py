import pandas as pd
df = pd.DataFrame({"a": [1, 1, 2], "b": [3, 4, 5]})
out = df.groupby("a").agg(total=("b", "sum"), mean_b=("b", "mean")).reset_index()
print(out.sort_values(by="total", ascending=False).head(n=2))
