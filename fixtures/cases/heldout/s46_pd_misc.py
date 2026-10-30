import pandas as pd
from pandas import DataFrame, Series, Timestamp
import pandas.api.types as ptypes
df = DataFrame({"a": [1]})
print(ptypes.is_numeric_dtype(df["a"]), Timestamp("2024-01-01").tz_localize("UTC"), pd.Timedelta(days=1), pd.NA, pd.isna(None))
print(Series([1]).dt if False else None, pd.Categorical(["a"]), pd.IndexSlice, pd.options.display.max_rows, pd.set_option("display.width", 100))
print(df.style if False else None, pd.MultiIndex.from_tuples([(1, 2)], names=["x", "y"]), pd.cut([1, 2], bins=2, labels=False))
