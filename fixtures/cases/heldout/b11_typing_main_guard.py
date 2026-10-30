from __future__ import annotations
import sys
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import pandas as pd
def f(df: pd.DataFrame) -> int:
    return len(df)
if __name__ == "__main__":
    print(f([1]), sys.maxsize)
