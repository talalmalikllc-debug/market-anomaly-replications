"""Stage 5: the cross-sectional form, which is what the strongest paper actually did.

Everything up to here measured displacement against an instrument's *own*
history.  Della Corte, Kosowski, Liu & Wang (2022) do something different:
displacement is measured relative to the *peer group* on the same day, and the
strategy is a zero-investment long-short book across peers.  Their headline
Sharpe of 5.5 on equity index futures is a cross-sectional number, and it does
not follow from anything a single-instrument test can see.

Their construction, reproduced exactly:

    w_i,t-1 = -(1/N) * (r_i,t-1 - rbar_t-1)

where r_i,t-1 is the formation return and rbar is the equal-weighted mean over
the N assets available.  Payoff is

    rp_t = sum_i w_i,t-1 * r_i,t / (d_t-1 / 2)

with d_t-1 = sum_i |w_i,t-1|, i.e. the Lehmann/Nagel 50% margin convention, so
the strategy costs $1 of capital.

Four formation/realisation pairings are run, as in their Table 2:
    CC-CC   close-to-close  -> close-to-close   (the conventional reversal)
    OO-OO   open-to-open    -> open-to-open
    OC-OC   intraday        -> intraday
    CO-OC   overnight       -> intraday         (their result)

The peer group has to share a liquidity provider for the mechanism to make
sense, so the indices are one book and everything else is reported but not
pooled with them.
"""

from __future__ import annotations
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_DATA = _os.environ.get("BROKER_DATA_DIR", _os.path.join(_REPO, "data", "raw"))

import numpy as np
import pandas as pd

import dataio
import features as F
from stage3 import POINT

ANN = np.sqrt(252.0)


def daily_panel(symbols: list[str], timeframe: str = "M15") -> pd.DataFrame:
    """One row per (session, symbol) with the open/close of that CFD day."""
    frames = []
    for s in symbols:
        try:
            d = F.build(dataio.load(s, timeframe))
        except FileNotFoundError:
            continue
        g = d.groupby("session", sort=True)
        t = pd.DataFrame(
            {
                "open": g["open"].first(),
                "close": g["close"].last(),
                "atr": g["atr"].first(),
                "spread_pts": g["spread"].median(),
            }
        )
        t["symbol"] = s
        t["point"] = POINT[s]
        frames.append(t.reset_index())
    p = pd.concat(frames, ignore_index=True)
    p = p.sort_values(["symbol", "session"])
    p["prev_close"] = p.groupby("symbol")["close"].shift(1)
    p["prev_open"] = p.groupby("symbol")["open"].shift(1)

    p["r_cc"] = p["close"] / p["prev_close"] - 1.0
    p["r_oo"] = p["open"] / p["prev_open"] - 1.0
    p["r_oc"] = p["close"] / p["open"] - 1.0
    p["r_co"] = p["open"] / p["prev_close"] - 1.0
    # one-way cost of trading this instrument, as a return
    p["cost_ret"] = (p["spread_pts"] * p["point"]) / p["close"]

    # Formation returns must be observable BEFORE the realisation window opens.
    # For CC/OO/OC the formation leg is the previous session's return, so it has
    # to be lagged one session per symbol; using the contemporaneous value makes
    # the payoff -(1/N) * sum (r - rbar)^2, negative by construction.
    # r_co needs no lag: the overnight jump is complete at the session open,
    # before the open-to-close window it predicts has begun.
    for c in ("r_cc", "r_oo", "r_oc"):
        p[f"{c}_lag"] = p.groupby("symbol")[c].shift(1)

    return p.dropna(subset=["r_cc", "r_oc", "r_co"])


def reversal_strategy(
    panel: pd.DataFrame, form: str, real: str, charge_cost: bool = True
) -> pd.Series:
    """Daily payoff of the Lehmann/Nagel contrarian book.

    `form` is the formation return column observed at t-1 (or, for CO, at the
    open of t), `real` is the return realised over the trading period of t.
    """
    out = {}
    for sess, g in panel.groupby("session", sort=True):
        g = g.dropna(subset=[form, real])
        n = len(g)
        if n < 3:
            continue
        r_form = g[form].to_numpy()
        r_real = g[real].to_numpy()
        w = -(r_form - r_form.mean()) / n
        d = np.abs(w).sum()
        if d <= 0:
            continue
        gross = float(w @ r_real) / (d / 2.0)
        if charge_cost:
            # each unit of |w| is opened and closed once
            cost = float((np.abs(w) * g["cost_ret"].to_numpy() * 2.0).sum()) / (d / 2.0)
            out[sess] = gross - cost
        else:
            out[sess] = gross
    return pd.Series(out).sort_index()


def summarise(r: pd.Series, label: str) -> dict:
    r = r.dropna()
    if len(r) < 100:
        return {}
    mu = r.mean()
    sd = r.std()
    t = mu / (sd / np.sqrt(len(r)))
    yr = r.groupby(pd.Series(r.index).str[:4].to_numpy()).mean()
    return {
        "strategy": label,
        "n_days": len(r),
        "mean_pct_day": mu * 100,
        "vol_pct_day": sd * 100,
        "t_stat": t,
        "sharpe_ann": (mu / sd) * ANN if sd else np.nan,
        "yr_pos_frac": float((yr > 0).mean()),
        "yr_min_pct": yr.min() * 100,
        "yr_max_pct": yr.max() * 100,
    }


PAIRS = [
    ("r_cc_lag", "r_cc", "CC-CC (conventional reversal)"),
    ("r_oo_lag", "r_oo", "OO-OO"),
    ("r_oc_lag", "r_oc", "OC-OC (intraday->intraday)"),
    ("r_co", "r_oc", "CO-OC (overnight->intraday)"),
]


def run() -> None:
    base = _os.path.join(_REPO, "results")
    books = {
        "index (4 CFDs)": dataio.FAMILIES["index"],
        "all 7 instruments": dataio.ALL_SYMBOLS,
    }
    rows = []
    for book, syms in books.items():
        panel = daily_panel(syms)
        for form, real, label in PAIRS:
            for charge in (False, True):
                r = reversal_strategy(panel, form, real, charge_cost=charge)
                s = summarise(r, label)
                if not s:
                    continue
                s["book"] = book
                s["costs"] = "net" if charge else "gross"
                rows.append(s)
        print(f"[ok] {book}: {panel.session.nunique()} sessions", flush=True)

    res = pd.DataFrame(rows)
    res.to_csv(f"{base}/stage5_cross_sectional.csv", index=False)
    cols = ["book", "costs", "strategy", "n_days", "mean_pct_day", "t_stat",
            "sharpe_ann", "yr_pos_frac", "yr_min_pct"]
    print(res[cols].round(4).to_string(index=False))


if __name__ == "__main__":
    run()
