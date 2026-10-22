"""Loading and cleaning MT5 exports for the displacement study.

Two traps this handles, both learned the hard way on this data set:

  * Early history is coarser than the file name claims.  The M15 export for
    US100.cash starts with one bar per *day* and only becomes true M15 later;
    the M5 export is hourly before late 2021.  Feeding that into an intrabar
    study silently produces day-scale "M15" displacement.  `trim_to_resolution`
    finds the first point after which the modal bar spacing matches nominal.

  * Bar timestamps are on the broker clock (FTMO, UTC+3 fixed).  New York
    observes DST, so a fixed offset is right for 48 weeks a year and an hour
    wrong for the other four.  Session labels always go through a real tz.
"""

from __future__ import annotations
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_DATA = _os.environ.get("BROKER_DATA_DIR", _os.path.join(_REPO, "data", "raw"))

import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

RAW = _DATA
SERVER_OFFSET_SEC = 10800  # from env.csv: FTMO-Demo is UTC+3, fixed year round

TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "D1": 86400}

NY = ZoneInfo("America/New_York")


def trim_to_resolution(df: pd.DataFrame, nominal_sec: int, window: int = 500) -> pd.DataFrame:
    """Drop the leading region where bar spacing is coarser than nominal.

    Walks forward in `window`-bar blocks and keeps everything from the first
    block whose median spacing equals the nominal timeframe onward.
    """
    dt = df["time"].diff().to_numpy()
    n = len(df)
    start = 0
    for i in range(0, n - window, window):
        block = dt[i + 1 : i + window]
        block = block[np.isfinite(block)]
        if len(block) == 0:
            continue
        if np.median(block) <= nominal_sec * 1.5:
            start = i
            break
    else:
        start = n
    return df.iloc[start:].reset_index(drop=True)


def load(symbol: str, timeframe: str) -> pd.DataFrame:
    """Return a clean bar frame with server, UTC and New York clocks attached."""
    path = f"{RAW}/bars_{symbol}_{timeframe}.csv"
    df = pd.read_csv(path)
    df = df.drop_duplicates(subset="time").sort_values("time").reset_index(drop=True)
    df = trim_to_resolution(df, TF_SECONDS[timeframe])

    # Explicit ns everywhere.  pandas 3 defaults `unit="s"` to datetime64[s],
    # which breaks floor()/day-bucketing arithmetic further down the pipeline.
    utc = pd.to_datetime(df["time"] - SERVER_OFFSET_SEC, unit="s", utc=True).astype(
        "datetime64[ns, UTC]"
    )
    df["ts_utc"] = utc
    df["ts_srv"] = utc.dt.tz_convert("Etc/GMT-3")
    df["ts_ny"] = utc.dt.tz_convert(NY)

    df["ny_date"] = df["ts_ny"].dt.date
    df["ny_minute"] = df["ts_ny"].dt.hour * 60 + df["ts_ny"].dt.minute
    df["year"] = df["ts_ny"].dt.year
    df["month"] = df["ts_ny"].dt.month
    df["dow"] = df["ts_ny"].dt.dayofweek

    df["symbol"] = symbol
    df["timeframe"] = timeframe
    return df


# Instrument families.  Cross-sectional work (Della Corte et al.) needs peers
# that share a liquidity provider, so these are grouped by what a market maker
# would actually warehouse together.
FAMILIES = {
    "index": ["US100.cash", "US500.cash", "US30.cash", "GER40.cash"],
    "metal": ["XAUUSD"],
    "fx": ["EURUSD", "GBPJPY"],
}

ALL_SYMBOLS = [s for v in FAMILIES.values() for s in v]


def family_of(symbol: str) -> str:
    for fam, syms in FAMILIES.items():
        if symbol in syms:
            return fam
    return "other"
