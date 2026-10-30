import io
import pandas as pd
buf = io.StringIO("a,b\n1,2\n,3\n")
df = pd.read_csv(buf, sep=",", header=0).dropna(how="any").reset_index(drop=True)
print(df.to_dict(orient="records"))
