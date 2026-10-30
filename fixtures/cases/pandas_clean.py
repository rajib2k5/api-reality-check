"""Typical pandas report-building code on an in-memory sales table."""
import io

import numpy as np
import pandas as pd

RAW = """date,region,product,units,price
2024-01-02,north,widget,10,2.5
2024-01-03,south,widget,4,2.5
2024-01-03,north,gadget,7,9.0
2024-01-05,east,gadget,3,9.0
2024-01-09,south,gizmo,12,4.25
2024-01-10,east,widget,8,2.5
2024-01-15,north,gizmo,5,4.25
2024-01-20,south,gadget,9,9.0
"""


def load_sales():
    df = pd.read_csv(
        io.StringIO(RAW),
        sep=",",
        parse_dates=["date"],
        dtype={"region": "category"},
        usecols=["date", "region", "product", "units", "price"],
        index_col=False,
    )
    return df


def add_revenue(df):
    out = df.assign(revenue=lambda d: d["units"] * d["price"])
    out = out.rename(columns={"units": "qty"})
    return out.astype({"qty": "int64"})


def totals_by_region(df):
    grouped = df.groupby("region", observed=True).agg(
        revenue=("revenue", "sum"),
        orders=("qty", "count"),
        avg_qty=("qty", "mean"),
    )
    return grouped.sort_values("revenue", ascending=False).reset_index()


def monthly_pivot(df):
    pivot = pd.pivot_table(
        df, values="revenue", index="product", columns="region", aggfunc="sum", fill_value=0.0, observed=True
    )
    return pivot.round(2)


def daily_series(df):
    daily = df.set_index("date")["revenue"].resample("D").sum()
    rolled = daily.rolling(window=3, min_periods=1).mean()
    change = daily.pct_change(fill_method=None)
    return rolled, change.fillna(0.0), daily.cumsum()


def join_targets(df):
    targets = pd.DataFrame({"region": ["north", "south", "east"], "target": [100.0, 80.0, 60.0]})
    merged = df.merge(targets, on="region", how="left", validate="many_to_one")
    merged["pct_of_target"] = merged["revenue"] / merged["target"]
    return merged.query("pct_of_target > 0.05").drop(columns=["target"])


def clean_up(df):
    out = df.drop_duplicates(subset=["date", "region", "product"], keep="first")
    out = out.dropna(subset=["revenue"], how="any")
    out = out.sort_values(["date", "region"], ignore_index=True)
    return out.head(5), out.tail(3), out.sample(n=3, random_state=0)


def bins(df):
    df = df.copy()
    df["size"] = pd.cut(df["qty"], bins=[0, 5, 10, 100], labels=["s", "m", "l"])
    dummies = pd.get_dummies(df["size"], prefix="size", dtype=int)
    return pd.concat([df, dummies], axis=1), df["size"].value_counts(sort=False)


def dates(df):
    idx = pd.date_range("2024-01-01", periods=5, freq="D", tz="UTC")
    parsed = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
    return idx, parsed.dt.day_name(), parsed.dt.to_period("M")


def reshape(df):
    wide = df.pivot(index="date", columns="product", values="qty")
    long = wide.reset_index().melt(id_vars="date", var_name="product", value_name="qty")
    return wide, long.dropna(subset=["qty"])


def elementwise(df):
    names = df["product"].map(str.upper)
    shifted = df[["qty", "revenue"]].shift(periods=1)
    lagged = df[["qty", "revenue"]].diff(periods=1)
    scaled = df[["qty", "revenue"]].map(lambda v: v * 2)
    return names, shifted, lagged, scaled


def stats(df):
    summary = df[["qty", "revenue"]].describe(percentiles=[0.1, 0.9])
    corr = df[["qty", "revenue"]].corr(method="pearson")
    top = df.nlargest(3, "revenue")
    return summary, corr, top


def output(df):
    text = df.to_csv(index=False, float_format="%.2f", date_format="%Y-%m-%d")
    blob = df.to_json(orient="records", date_format="iso")
    back = pd.read_json(io.StringIO(blob), orient="records")
    return text, back.shape, df.isna().sum(), df.dtypes


def run():
    df = add_revenue(load_sales())
    regional = totals_by_region(df)
    pivot = monthly_pivot(df)
    rolled, change, running = daily_series(df)
    merged = join_targets(df)
    cleaned = clean_up(merged)
    binned, size_counts = bins(df)
    idx, names, months = dates(df)
    wide, long = reshape(df)
    up, shifted, lagged, scaled = elementwise(df)
    summary, corr, top = stats(df)
    text, shape, nulls, dtypes = output(df)
    return regional, pivot, np.sqrt(summary.loc["mean"]), top
