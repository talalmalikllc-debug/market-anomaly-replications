"""Displacement features and forward returns.

Everything is expressed in ATR units.  That is not cosmetic: the whole point of
the hypothesis is whether the *shape* of the forward distribution changes with
displacement, and raw points confound that with the volatility level, which is
itself strongly forecastable.  Normalising by a lagged ATR removes the scale
channel and leaves the shape channel, which is what we actually want to test.

Every feature at bar t uses only bars <= t.  Forward returns are measured from
the OPEN of bar t+1, so a signal that fires on the close of t is tradable at the
next open with no lookahead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# CFD trading day starts at 18:00 New York (the 17:00 close plus the one hour
# maintenance break).  Anchoring VWAP and "session open" here gives one
# well-defined 24h session for indices, metals and FX alike.
DAY_START_MINUTE = 18 * 60


def wilder_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev).abs(), (low - prev).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def session_id(df: pd.DataFrame) -> pd.Series:
    """Label each bar with the CFD trading day it belongs to (18:00 NY rollover)."""
    ny = df["ts_ny"]
    shifted = ny - pd.Timedelta(minutes=DAY_START_MINUTE)
    return shifted.dt.strftime("%Y-%m-%d")


def liquidity_window(minute: pd.Series) -> pd.Series:
    """Coarse liquidity state, by New York wall clock.

    The papers disagree about continuation vs reversion, and the thing that
    most plausibly separates them is how much liquidity was available while the
    displacement was being formed.  So this is a first-class conditioning
    variable, not a robustness afterthought.
    """
    m = minute.to_numpy()
    out = np.full(len(m), "asia", dtype=object)
    out[(m >= 3 * 60) & (m < 9 * 60 + 30)] = "london"
    out[(m >= 9 * 60 + 30) & (m < 11 * 60)] = "ny_open"
    out[(m >= 11 * 60) & (m < 15 * 60)] = "ny_mid"
    out[(m >= 15 * 60) & (m < 16 * 60)] = "ny_close"
    out[(m >= 16 * 60) & (m < 18 * 60)] = "post"
    return pd.Series(out, index=minute.index)


def build(df: pd.DataFrame, atr_n: int = 14, eq_window: int = 96) -> pd.DataFrame:
    d = df.copy()
    close, high, low = d["close"], d["high"], d["low"]
    vol = d["tick_volume"].astype(float).clip(lower=1.0)

    d["atr"] = wilder_atr(d, atr_n)
    a = d["atr"].replace(0.0, np.nan)

    d["session"] = session_id(d)
    d["liq"] = liquidity_window(d["ny_minute"])

    g = d.groupby("session", sort=False)

    # --- reference level 1: session-anchored VWAP -------------------------
    typ = (d["high"] + d["low"] + d["close"]) / 3.0
    pv = typ * vol
    d["vwap"] = (
        pv.groupby(d["session"], sort=False).cumsum()
        / vol.groupby(d["session"], sort=False).cumsum()
    )
    d["d_vwap"] = (close - d["vwap"]) / a

    # --- reference level 2: moving averages -------------------------------
    d["d_ema20"] = (close - close.ewm(span=20, adjust=False).mean()) / a
    d["d_ema50"] = (close - close.ewm(span=50, adjust=False).mean()) / a

    # --- reference level 3: session open ----------------------------------
    d["sess_open"] = g["open"].transform("first")
    d["d_sopen"] = (close - d["sess_open"]) / a

    # --- reference level 4: recent equilibrium (Donchian midpoint) --------
    mid = (
        high.rolling(eq_window).max() + low.rolling(eq_window).min()
    ) / 2.0
    d["d_eq"] = (close - mid) / a

    # --- reference level 5: k-bar return in ATR units ---------------------
    for k in (1, 4, 12):
        d[f"r_atr_{k}"] = (close - close.shift(k)) / a

    # --- reference level 6: consecutive directional movement --------------
    sign = np.sign(close.diff().fillna(0.0)).to_numpy()
    streak = np.zeros(len(sign))
    run = 0
    for i in range(1, len(sign)):
        s = sign[i]
        if s == 0:
            run = 0
        elif s == np.sign(run) or run == 0:
            run = run + s if run != 0 else s
        else:
            run = s
        streak[i] = run
    d["streak"] = streak

    # --- reference level 7: extreme short-term return percentile ----------
    r4 = d["r_atr_4"]
    d["pctile_r4"] = r4.rolling(1000, min_periods=250).rank(pct=True) * 2.0 - 1.0

    # --- overnight vs intraday displacement (Della Corte decomposition) ---
    # close-to-open of the CFD day, in ATR units, carried across the session
    first_open = d["sess_open"]
    prev_close = g["close"].transform("last").shift(1)
    d["d_overnight"] = (first_open - prev_close.ffill()) / a

    # --- forward returns, entered at the NEXT open ------------------------
    nxt_open = d["open"].shift(-1)
    for h in (1, 2, 4, 8, 16, 32):
        d[f"fwd_{h}"] = (close.shift(-h) - nxt_open) / a

    # Favourable / adverse excursion over the h=16 window, so a directionless
    # "it moved a lot" result can be told apart from a directional one.
    fwd_hi = high.shift(-16).rolling(16).max()
    fwd_lo = low.shift(-16).rolling(16).min()
    d["mfe_16"] = (fwd_hi - nxt_open) / a
    d["mae_16"] = (nxt_open - fwd_lo) / a

    return d


DISPLACEMENT_VARS = [
    "d_vwap",
    "d_ema20",
    "d_ema50",
    "d_sopen",
    "d_eq",
    "r_atr_1",
    "r_atr_4",
    "r_atr_12",
    "streak",
    "pctile_r4",
]

HORIZONS = [1, 2, 4, 8, 16, 32]
