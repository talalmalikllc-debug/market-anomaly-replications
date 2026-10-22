"""Stage 3: put the two surviving patterns through the wringer.

Stage 2 produced two candidates with opposite signs:

  A. NY OPEN CONTINUATION, indices only.  Displacement measured in the
     09:30-11:00 NY window continues.  US100 h=16 shows -0.25 ATR of fade edge,
     i.e. a quarter of an ATR of continuation.  Absent in XAUUSD and EURUSD.
     This is the Gao et al. intraday-momentum effect on our own broker data.

  B. POST-CLOSE REVERSION, FX especially.  GBPJPY shows +0.56 ATR at h=4 in the
     16:00-18:00 NY window.  A number that large in the thinnest window of the
     day is far more likely to be bid-ask bounce on stale quotes than an edge,
     so it gets a spread audit before anything else.

Controls applied to both, in the order that kills candidates fastest:
  1. cost hurdle in ATR units, using the broker's own recorded spread
  2. per-year stability
  3. time-of-day x month stratified placebo
  4. mirror control: the same rule with the entry side flipped
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

# specs.csv is unusable here: the description field contains an unquoted comma
# ("NASDAQ 100 Index, Spot CFD"), which shifts every later column and leaves the
# symbol column holding digit counts.  Reading tick_value off it silently gives
# a forex default for the index CFDs.  Point size is fully determined by the
# quoted digits, so take it from there instead.
POINT = {
    "US100.cash": 0.01,
    "US500.cash": 0.01,
    "US30.cash": 0.01,
    "GER40.cash": 0.01,
    "XAUUSD": 0.01,
    "EURUSD": 0.00001,
    "GBPJPY": 0.001,
}


def spread_audit(d: pd.DataFrame) -> pd.DataFrame:
    """Median broker spread per liquidity window, in ATR units.

    The `spread` column is in points, so spread * point / ATR gives the
    round-trip cost of one trade on the same scale as every edge in this study.
    """
    sym = d["symbol"].iloc[0]
    point = POINT[sym]
    out = []
    for liq, grp in d.groupby("liq"):
        sp_pts = grp["spread"].replace(0, np.nan).median()
        atr = grp["atr"].median()
        out.append(
            {
                "liq": liq,
                "med_spread_pts": sp_pts,
                "med_atr_price": atr,
                "spread_atr": (sp_pts * point) / atr if atr else np.nan,
                "n": len(grp),
            }
        )
    return pd.DataFrame(out).assign(symbol=sym)


def window_edge(
    d: pd.DataFrame, liq: str, var: str, h: int, q: float = 0.1, sign: int = +1
) -> pd.DataFrame:
    """Per-event signed returns of trading displacement inside one window.

    sign=+1 fades the displacement (bet on reversion); sign=-1 follows it (bet
    on continuation).  Returns one row per event so downstream controls can
    resample, stratify and split by year.
    """
    sub = d[d["liq"] == liq][[var, f"fwd_{h}", "year", "month", "ny_minute", "atr"]].dropna()
    lo_c, hi_c = sub[var].quantile(q), sub[var].quantile(1 - q)
    lo = sub[sub[var] <= lo_c].assign(side=+1)
    hi = sub[sub[var] >= hi_c].assign(side=-1)
    ev = pd.concat([lo, hi])
    ev["ret_atr"] = sign * ev["side"] * ev[f"fwd_{h}"]
    return ev


def evaluate(ev: pd.DataFrame, h: int, cost_atr: float, label: str) -> dict:
    r = ev["ret_atr"].to_numpy()
    gross, t = nw_tstat(r, lags=h)
    net = gross - cost_atr
    yr = ev.groupby("year")["ret_atr"].mean()
    return {
        "label": label,
        "n": len(r),
        "gross_atr": gross,
        "t_nw": t,
        "cost_atr": cost_atr,
        "net_atr": net,
        "yr_min": yr.min(),
        "yr_max": yr.max(),
        "yr_pos_frac": float((yr > 0).mean()),
        "n_years": len(yr),
        "hit": float((r > 0).mean()),
    }


def placebo(ev_full: pd.DataFrame, d: pd.DataFrame, liq: str, var: str, h: int,
            sign: int, n_iter: int = 300, seed: int = 11) -> float:
    """Stratified placebo: reshuffle the displacement within month x half-hour.

    Keeps the seasonal structure of the window intact and asks only whether the
    displacement value carries information beyond "this bar happened at 09:45
    in March".
    """
    rng = np.random.default_rng(seed)
    sub = d[d["liq"] == liq][[var, f"fwd_{h}", "year", "month", "ny_minute", "atr"]].dropna().copy()
    cell = (sub["month"].astype(str) + "_" + (sub["ny_minute"] // 30).astype(str)).to_numpy()
    order = np.arange(len(sub))
    idx = [order[cell == c] for c in np.unique(cell)]

    obs = ev_full["ret_atr"].mean()
    vals = sub[var].to_numpy()
    fwd = sub[f"fwd_{h}"].to_numpy()
    q = 0.1
    null = np.empty(n_iter)
    for i in range(n_iter):
        s = vals.copy()
        for arr in idx:
            s[arr] = rng.permutation(s[arr])
        lo_c, hi_c = np.quantile(s, q), np.quantile(s, 1 - q)
        r = np.concatenate([sign * fwd[s <= lo_c], -sign * fwd[s >= hi_c]])
        null[i] = r.mean()
    return float((np.abs(null) >= abs(obs)).mean())


def run(timeframe: str = "M15") -> None:
    base = _os.path.join(_REPO, "results")
    spreads, results = [], []

    candidates = [
        # (window, variable, horizon, sign, description)
        ("ny_open", "r_atr_4", 16, -1, "NY-open continuation"),
        ("ny_open", "r_atr_4", 4, -1, "NY-open continuation (short hold)"),
        ("post", "r_atr_4", 4, +1, "Post-close reversion"),
        ("ny_close", "r_atr_4", 16, +1, "NY-close reversion"),
    ]

    for sym in dataio.ALL_SYMBOLS:
        try:
            d = F.build(dataio.load(sym, timeframe))
        except FileNotFoundError:
            continue
        sa = spread_audit(d)
        spreads.append(sa)
        cost_by_liq = sa.set_index("liq")["spread_atr"].to_dict()

        for liq, var, h, sign, desc in candidates:
            ev = window_edge(d, liq, var, h, sign=sign)
            if len(ev) < 300:
                continue
            # round trip = two spreads crossed, plus a conservative half-spread
            # of slippage on entry, which is the cheapest honest assumption.
            cost = 2.5 * cost_by_liq.get(liq, np.nan)
            res = evaluate(ev, h, cost, desc)
            res["symbol"] = sym
            res["family"] = dataio.family_of(sym)
            res["liq"] = liq
            res["var"] = var
            res["h"] = h
            res["p_placebo"] = placebo(ev, d, liq, var, h, sign)
            # mirror control: identical rule, opposite side
            ev_m = window_edge(d, liq, var, h, sign=-sign)
            res["mirror_gross"] = ev_m["ret_atr"].mean()
            results.append(res)
        print(f"[ok] {sym}", flush=True)

    pd.concat(spreads, ignore_index=True).to_csv(f"{base}/stage3_spreads.csv", index=False)
    pd.DataFrame(results).to_csv(f"{base}/stage3_candidates.csv", index=False)
    print("done")


if __name__ == "__main__":
    import sys

    run(sys.argv[1] if len(sys.argv) > 1 else "M15")
