"""Stage 1 of the displacement study: does the conditional distribution move?

No strategy, no thresholds, no optimisation.  For each (symbol, displacement
variable, horizon) we bucket bars by displacement decile and read off the
forward return distribution.  The question is only whether the buckets differ,
and if so in which direction.

Three guards are baked in rather than bolted on afterwards:

  * Newey-West t-stats.  Overlapping forward windows make raw OLS/naive t-stats
    badly overstated at h > 1.
  * Per-year breakdown printed alongside the pooled number.  A pooled lift that
    sits above every per-year lift is the signature of regime confounding, not
    of an edge.
  * time-of-day x month stratified placebo.  Displacement is heavily seasonal
    (an extreme move in the Asian session is a different animal from one at the
    New York open), so the null has to hold that seasonality fixed.
"""

from __future__ import annotations
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_DATA = _os.environ.get("BROKER_DATA_DIR", _os.path.join(_REPO, "data", "raw"))

import numpy as np
import pandas as pd

import dataio
import features as F


def nw_tstat(x: np.ndarray, lags: int) -> tuple[float, float]:
    """Mean and Newey-West t-stat of a series of overlapping observations."""
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 30:
        return (np.nan, np.nan)
    mu = x.mean()
    e = x - mu
    gamma0 = (e @ e) / n
    var = gamma0
    for L in range(1, min(lags, n - 1) + 1):
        cov = (e[L:] @ e[:-L]) / n
        var += 2.0 * (1.0 - L / (lags + 1.0)) * cov
    if var <= 0:
        return (mu, np.nan)
    return (mu, mu / np.sqrt(var / n))


def decile_table(d: pd.DataFrame, var: str, h: int, nq: int = 10) -> pd.DataFrame:
    """Forward-return distribution by displacement decile."""
    col = f"fwd_{h}"
    sub = d[[var, col, "year"]].dropna()
    if len(sub) < 2000:
        return pd.DataFrame()
    try:
        q = pd.qcut(sub[var], nq, labels=False, duplicates="drop")
    except ValueError:
        return pd.DataFrame()
    sub = sub.assign(bucket=q)

    rows = []
    for b, grp in sub.groupby("bucket"):
        mu, t = nw_tstat(grp[col].to_numpy(), lags=h)
        rows.append(
            {
                "bucket": int(b),
                "n": len(grp),
                "disp_mid": grp[var].median(),
                "mean_fwd": mu,
                "t_nw": t,
                "median_fwd": grp[col].median(),
                "std_fwd": grp[col].std(),
                "skew_fwd": grp[col].skew(),
                "hit_up": (grp[col] > 0).mean(),
            }
        )
    return pd.DataFrame(rows).sort_values("bucket").reset_index(drop=True)


def spread_slope(tab: pd.DataFrame) -> dict:
    """Summarise a decile table as one number: the top-minus-bottom spread.

    Positive spread = high displacement is followed by higher forward returns
    = CONTINUATION.  Negative = REVERSION.  The sign is the whole hypothesis.
    """
    if tab.empty or len(tab) < 4:
        return {"spread": np.nan, "mono": np.nan}
    lo, hi = tab.iloc[0], tab.iloc[-1]
    # Spearman rank correlation of bucket vs mean forward return: how monotone
    # is the relationship, as opposed to just driven by the two tails.
    ranks = pd.Series(tab["mean_fwd"].to_numpy()).rank()
    r = ranks.corr(pd.Series(tab["bucket"].to_numpy()).rank())
    return {
        "spread": hi["mean_fwd"] - lo["mean_fwd"],
        "top_mean": hi["mean_fwd"],
        "top_t": hi["t_nw"],
        "bot_mean": lo["mean_fwd"],
        "bot_t": lo["t_nw"],
        "mono": r,
    }


def long_short_leg(d: pd.DataFrame, var: str, h: int, q: float = 0.1) -> np.ndarray:
    """Signed forward returns of a 'fade the displacement' portfolio.

    Short the top decile, long the bottom decile, so a POSITIVE result means
    reversion and a negative one means continuation.  One number per event,
    which is what the t-stat and the placebo both operate on.
    """
    col = f"fwd_{h}"
    sub = d[[var, col]].dropna()
    lo_c, hi_c = sub[var].quantile(q), sub[var].quantile(1 - q)
    lo = sub.loc[sub[var] <= lo_c, col].to_numpy()
    hi = -sub.loc[sub[var] >= hi_c, col].to_numpy()
    return np.concatenate([lo, hi])


def stratified_placebo(
    d: pd.DataFrame, var: str, h: int, n_iter: int = 200, seed: int = 7
) -> tuple[float, float]:
    """Null distribution of the fade spread, shuffling within tod x month cells.

    Shuffling globally would destroy the seasonal structure and make almost any
    signal look significant.  Shuffling *within* time-of-day x month cells keeps
    the seasonality and asks the sharper question: given when this bar happened,
    does the displacement value itself carry information?
    """
    rng = np.random.default_rng(seed)
    col = f"fwd_{h}"
    sub = d[[var, col, "liq", "month"]].dropna().copy()
    if len(sub) < 5000:
        return (np.nan, np.nan)
    cell = sub["liq"].astype(str) + "_" + sub["month"].astype(str)
    sub["cell"] = cell

    obs = long_short_leg(sub, var, h).mean()

    null = np.empty(n_iter)
    grouped = [g.index.to_numpy() for _, g in sub.groupby("cell", sort=False)]
    vals = sub[var].to_numpy()
    pos = {ix: i for i, ix in enumerate(sub.index.to_numpy())}
    idx_arrays = [np.array([pos[i] for i in g]) for g in grouped]

    work = sub.copy()
    for it in range(n_iter):
        shuffled = vals.copy()
        for arr in idx_arrays:
            shuffled[arr] = rng.permutation(shuffled[arr])
        work[var] = shuffled
        null[it] = long_short_leg(work, var, h).mean()

    p = float((np.abs(null) >= abs(obs)).mean())
    return (obs, p)


def run_symbol(symbol: str, timeframe: str = "M15") -> pd.DataFrame:
    raw = dataio.load(symbol, timeframe)
    d = F.build(raw)

    out = []
    for var in F.DISPLACEMENT_VARS:
        for h in F.HORIZONS:
            tab = decile_table(d, var, h)
            if tab.empty:
                continue
            s = spread_slope(tab)
            legs = long_short_leg(d, var, h)
            mu, t = nw_tstat(legs, lags=h)
            row = {
                "symbol": symbol,
                "timeframe": timeframe,
                "var": var,
                "h": h,
                "n_events": len(legs),
                "fade_mean_atr": mu,
                "fade_t_nw": t,
                **s,
            }
            # per-year stability of the fade leg
            years = sorted(d["year"].dropna().unique())
            yr_means = []
            for y in years:
                sl = long_short_leg(d[d["year"] == y], var, h)
                yr_means.append(np.nanmean(sl) if len(sl) > 50 else np.nan)
            row["yr_pos_frac"] = float(np.nanmean(np.array(yr_means) > 0))
            row["yr_min"] = float(np.nanmin(yr_means)) if yr_means else np.nan
            row["yr_max"] = float(np.nanmax(yr_means)) if yr_means else np.nan
            out.append(row)
    return pd.DataFrame(out)


if __name__ == "__main__":
    import sys

    tf = sys.argv[1] if len(sys.argv) > 1 else "M15"
    frames = []
    for sym in dataio.ALL_SYMBOLS:
        try:
            r = run_symbol(sym, tf)
            frames.append(r)
            print(f"[ok] {sym} {tf}: {len(r)} rows", flush=True)
        except FileNotFoundError:
            print(f"[skip] {sym} {tf}: no file", flush=True)
    res = pd.concat(frames, ignore_index=True)
    path = _os.path.join(_REPO, f"results/stage1_{tf}.csv")
    res.to_csv(path, index=False)
    print("wrote", path, len(res))
