"""Quick-and-dirty pandas ETL; several of the calls below do not exist in pandas 3.1."""
import io

import pandas as pd
import pandas.plotting.extras
from pandas.io import read_csvv

CSV = "date,symbol,close,volume\n2024-01-02,AAA,10.0,100\n2024-01-03,AAA,10.5,120\n"


def load(path=None):
    src = io.StringIO(CSV) if path is None else path
    frame = pd.read_csv(src, index_coll=0, parse_dates=["date"])
    return frame


def load_with_header(path):
    return pd.read_csv(path, header_row=0, sep=",")


def load_excel(path):
    return pd.read_excell(path, sheet_name="Sheet1")


def load_wrapper(path):
    return pd.DataFrame(pd.read_csv(path), colums=["date", "close"])


def combine(frames):
    return pd.concat(frames, ignore_idx=True)


def combine_named(frames):
    return pd.concat_frames(frames, axis=0)


def join(left, right):
    return pd.merge(left, right, on="symbol", how="outer", suffix=("_l", "_r"))


def grid():
    return pd.linspace(0.0, 1.0, 11)


def legacy_roll(series):
    return pd.rolling_mean(series, window=5)


def legacy_index(values):
    return pd.Int64Index(values)


def legacy_panel(data):
    return pd.Panel(data)


def typo_frame(rows):
    return pd.Dataframe(rows)


def parse(series):
    return pd.to_datetime(series, formatt="%Y-%m-%d")


def calendar():
    return pd.date_range("2024-01-01", periods=5, frequency="D")


def pivot(df):
    return pd.pivot_table(df, values="close", index="symbol", fillvalue=0)


def returns(df):
    return df["close"].pct_change(fil_method=None)


def append_row(row):
    df = pd.DataFrame({"symbol": ["AAA"], "close": [10.0]})
    df = df.append(row, ignore_index=True)
    return df


def legacy_ix(rows):
    frame = pd.DataFrame(rows)
    return frame.ix[0]


def legacy_iter(rows):
    frame = pd.DataFrame(rows)
    for col, series in frame.iteritems():
        print(col, series.iloc[0])


def legacy_matrix(rows):
    frame = pd.DataFrame(rows)
    return frame.as_matrix()


def moving(rows):
    df = pd.DataFrame(rows)
    return df.rolling_mean(3)


def grouped(rows):
    df = pd.DataFrame(rows)
    return df.groupby_apply("symbol", len)


def ordered(rows):
    df = pd.DataFrame(rows)
    return df.sort_values("close", descending=True)


def as_list(rows):
    df = pd.DataFrame(rows)
    return df.tolist()


def tidy(rows):
    df = pd.DataFrame(rows)
    return df.dropna(how="any").reset_index(drop=True).head(10)
