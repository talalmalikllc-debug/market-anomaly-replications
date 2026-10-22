"""Stage 6: the last candidate, costed honestly.

The 16:00-18:00 NY window showed the largest gross reversion in the whole study
(GBPJPY +0.56 ATR at h=4, t = 13.7, positive in every year, placebo p < 0.001).
It also sits in the thinnest liquidity of the day, which is exactly where a
median spread flatters a strategy: post-close spreads are heavily right-skewed,
so the median is nowhere near what a market order actually pays.

So this stage stops using a median and charges each event its own recorded
spread at the moment it would have been entered, plus the same spread again on
exit.  It also splits development from holdout, which no earlier stage did for
this candidate.
"""

from __future__ import annotations
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_DATA = _os.environ.get("BROKER_DATA_DIR", _os.path.join(_REPO, "data", "raw"))

import numpy as np
import pandas as pd

import dataio
import features as F
from study import nw_tstat
from stage3 import POINT

HOLDOUT_START = 2025


def costed_events(symbol: str, liq: str, var: str, h: int, q: float = 0.1,
                  sign: int = +1) -> pd.DataFrame:
    d = F.build(dataio.load(symbol, "M15"))
    point = POINT[symbol]

    cols = [var, f"fwd_{h}", "year", "atr", "spread", "close"]
    sub = d[d["liq"] == liq][cols].dropna()
    lo_c, hi_c = sub[var].quantile(q), sub[var].quantile(1 - q)
    lo = sub[sub[var] <= lo_c].assign(side=+1)
    hi = sub[sub[var] >= hi_c].assign(side=-1)
    ev = pd.concat([lo, hi]).copy()

    ev["gross_atr"] = sign * ev["side"] * ev[f"fwd_{h}"]
    # entry spread is the one recorded on the signal bar; exit is charged the
    # same, which is generous, since the exit lands h bars later and the window
    # gets thinner, not deeper.
    ev["cost_atr"] = 2.0 * (ev["spread"] * point) / ev["atr"]
    ev["net_atr"] = ev["gross_atr"] - ev["cost_atr"]
    return ev


def report(symbol: str, liq: str, var: str, h: int, sign: int, label: str) -> dict:
    ev = costed_events(symbol, liq, var, h, sign=sign)
    if len(ev) < 300:
        return {}
    dev = ev[ev["year"] < HOLDOUT_START]
    hold = ev[ev["year"] >= HOLDOUT_START]

    g_mu, g_t = nw_tstat(ev["gross_atr"].to_numpy(), lags=h)
    n_mu, n_t = nw_tstat(ev["net_atr"].to_numpy(), lags=h)
    d_mu, d_t = nw_tstat(dev["net_atr"].to_numpy(), lags=h)
    h_mu, h_t = nw_tstat(hold["net_atr"].to_numpy(), lags=h)
    yr = ev.groupby("year")["net_atr"].mean()

    return {
        "label": label,
        "symbol": symbol,
        "n": len(ev),
        "gross_atr": g_mu,
        "gross_t": g_t,
        "cost_med": ev["cost_atr"].median(),
        "cost_mean": ev["cost_atr"].mean(),
        "cost_p90": ev["cost_atr"].quantile(0.9),
        "net_atr": n_mu,
        "net_t": n_t,
        "dev_net": d_mu,
        "dev_t": d_t,
        "hold_net": h_mu,
        "hold_t": h_t,
        "yr_pos_frac": float((yr > 0).mean()),
        "yr_min": yr.min(),
    }


if __name__ == "__main__":
    cands = [
        ("GBPJPY", "post", "r_atr_4", 4, +1, "post-close reversion"),
        ("EURUSD", "post", "r_atr_4", 4, +1, "post-close reversion"),
        ("GBPJPY", "ny_close", "r_atr_4", 16, +1, "NY-close reversion"),
        ("US30.cash", "post", "r_atr_4", 4, +1, "post-close reversion"),
        ("GER40.cash", "post", "r_atr_4", 4, +1, "post-close reversion"),
    ]
    rows = [r for c in cands for r in [report(*c)] if r]
    df = pd.DataFrame(rows)
    df.to_csv(_os.path.join(_REPO, "results/stage6_costed.csv"), index=False)
    print(df.round(4).to_string(index=False))
