"""Stage 4: stress-test the one survivor, and replicate Gao et al. directly.

Stage 3 left exactly one candidate that clears its own broker's spread:
displacement formed in the 09:30-11:00 New York window on US100.cash continues,
+0.19 ATR net over 16 M15 bars, positive in all six years, placebo p = 0.013.
GER40 is a weaker second at +0.10 ATR net.

Two problems remain before any of this becomes an EA.

First, multiple testing.  Stage 1-3 swept 10 displacement variables x 6 horizons
x 7 symbols x 6 windows.  A t of 2.08 means very little against that many looks.
The defence is not a better t-stat, it is an independent specification: Gao,
Han, Li & Zhou (2018) predicted this effect, in this window, before I looked at
this data.  So `gao_regression` runs *their* specification, not a tuned version
of mine, and that number is the one that counts.

Second, the horizon and the variable were both picked by looking.  So the sweep
here is reported in full, not filtered, and everything is split into a
2021-2024 development period and a 2025-2026 holdout that no earlier stage saw.
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
from stage3 import POINT, window_edge, spread_audit

HOLDOUT_START = 2025


def gao_regression(symbol: str) -> dict:
    """The Gao, Han, Li & Zhou (2018) specification, on M15 bars.

    Their r1 is the first half-hour return measured from the previous close;
    r_{n-1} is the second-to-last half-hour; r_n is the last half-hour, which is
    what we predict.  On M15 bars a half hour is two bars.  The regression is

        r_n,t = a + b1 * r1,t + b2 * r_{n-1},t + e_t

    US index CFDs trade round the clock here, so "the session" is taken as the
    New York cash session 09:30-16:00, which is the window their S&P 500 ETF
    sample covers.
    """
    d = F.build(dataio.load(symbol, "M15"))
    # strictly < 16:00: the bar stamped 16:00 covers 16:00-16:15, which is
    # after the cash close and would drag post-close prices into r_n.
    rth = d[(d["ny_minute"] >= 9 * 60 + 30) & (d["ny_minute"] < 16 * 60)]

    rows = []
    for day, g in rth.groupby("ny_date", sort=True):
        g = g.sort_values("ny_minute")
        if len(g) < 24:  # a full 6.5h cash session is 26 M15 bars
            continue
        px = g["close"].to_numpy()
        op = g["open"].to_numpy()
        # r1: previous close -> end of first half hour (first two M15 bars)
        r1 = px[1] / op[0] - 1.0
        # second-to-last and last half hours
        r_nm1 = px[-3] / px[-5] - 1.0
        r_n = px[-1] / px[-3] - 1.0
        rows.append({"date": day, "r1": r1, "r_nm1": r_nm1, "r_n": r_n,
                     "year": g["year"].iloc[0]})
    t = pd.DataFrame(rows).dropna()
    if len(t) < 250:
        return {}

    def ols(X, y):
        X = np.column_stack([np.ones(len(X))] + [X[:, i] for i in range(X.shape[1])])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
        n, k = X.shape
        s2 = resid @ resid / (n - k)
        se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
        r2 = 1.0 - (resid @ resid) / ((y - y.mean()) @ (y - y.mean()))
        return beta, beta / se, r2

    y = t["r_n"].to_numpy()
    b1, t1, r2_1 = ols(t[["r1"]].to_numpy(), y)
    b2, t2, r2_2 = ols(t[["r_nm1"]].to_numpy(), y)
    b3, t3, r2_3 = ols(t[["r1", "r_nm1"]].to_numpy(), y)

    # same regression on the holdout only
    h = t[t["year"] >= HOLDOUT_START]
    if len(h) > 100:
        bh, th, r2h = ols(h[["r1", "r_nm1"]].to_numpy(), h["r_n"].to_numpy())
    else:
        bh, th, r2h = ([np.nan] * 3, [np.nan] * 3, np.nan)

    return {
        "symbol": symbol,
        "n_days": len(t),
        "beta_r1": b1[1], "t_r1": t1[1], "R2_r1": r2_1,
        "beta_rnm1": b2[1], "t_rnm1": t2[1], "R2_rnm1": r2_2,
        "joint_beta_r1": b3[1], "joint_t_r1": t3[1],
        "joint_beta_rnm1": b3[2], "joint_t_rnm1": t3[2],
        "R2_joint": r2_3,
        "holdout_t_r1": th[1], "holdout_t_rnm1": th[2], "holdout_R2": r2h,
        "n_holdout": len(h),
    }


def sweep(symbol: str) -> pd.DataFrame:
    """Full, unfiltered sweep of the NY-open continuation over var x horizon.

    Reported whole so the reader can see how much of the headline number is
    specification choice.  Split into development and holdout.
    """
    d = F.build(dataio.load(symbol, "M15"))
    cost = spread_audit(d).set_index("liq")["spread_atr"].get("ny_open", np.nan) * 2.5

    out = []
    for var in ["r_atr_1", "r_atr_4", "r_atr_12", "d_sopen", "d_vwap", "d_ema20"]:
        for h in [2, 4, 8, 16, 32]:
            ev = window_edge(d, "ny_open", var, h, sign=-1)
            if len(ev) < 300:
                continue
            dev = ev[ev["year"] < HOLDOUT_START]
            hold = ev[ev["year"] >= HOLDOUT_START]
            mu_d, t_d = nw_tstat(dev["ret_atr"].to_numpy(), lags=h)
            mu_h, t_h = nw_tstat(hold["ret_atr"].to_numpy(), lags=h)
            out.append({
                "symbol": symbol, "var": var, "h": h, "cost_atr": cost,
                "dev_n": len(dev), "dev_gross": mu_d, "dev_t": t_d,
                "dev_net": mu_d - cost,
                "hold_n": len(hold), "hold_gross": mu_h, "hold_t": t_h,
                "hold_net": mu_h - cost,
            })
    return pd.DataFrame(out)


if __name__ == "__main__":
    base = _os.path.join(_REPO, "results")

    gao = [g for s in dataio.ALL_SYMBOLS
           for g in [gao_regression(s)] if g]
    gdf = pd.DataFrame(gao)
    gdf.to_csv(f"{base}/stage4_gao.csv", index=False)
    print("=== Gao et al. (2018) specification, replicated on FTMO CFD data ===")
    print(gdf[["symbol", "n_days", "beta_r1", "t_r1", "R2_r1",
               "joint_t_r1", "joint_t_rnm1", "R2_joint",
               "holdout_t_r1", "holdout_t_rnm1"]].round(4).to_string(index=False))

    sw = pd.concat([sweep(s) for s in ["US100.cash", "GER40.cash", "US500.cash",
                                       "XAUUSD", "EURUSD"]], ignore_index=True)
    sw.to_csv(f"{base}/stage4_sweep.csv", index=False)
    print("\nwrote sweep", len(sw))
