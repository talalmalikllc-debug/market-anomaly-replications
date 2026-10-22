"""Stage 2: what moderates the sign?

Stage 1 says the unconditional effect flips with horizon — fast displacement
reverts over 1-2 bars, slow displacement continues over 16-32.  Both are far
too small to trade.  The literature says the interesting variation is not in
the horizon but in the liquidity state while the displacement was forming:

  * Della Corte, Kosowski, Liu & Wang (2022): displacement built up while the
    market is effectively closed reverses hard once liquidity returns.  Sharpe
    5.5 on equity index futures, and it survives in commodities and currencies.
  * Gao, Han, Li & Zhou (2018): displacement built up in the first half hour of
    an active session *continues* into the close.
  * Mesfin (2026): displacement measured within a liquid session on a single
    bar carries almost nothing, ~1 point gross against a 2 point cost floor.

Those are not contradictory results, they are the same result at three
different points on a liquidity axis.  This stage tests that directly.
"""

from __future__ import annotations
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_DATA = _os.environ.get("BROKER_DATA_DIR", _os.path.join(_REPO, "data", "raw"))

import numpy as np
import pandas as pd

import dataio
import features as F
from study import nw_tstat, long_short_leg

LIQ_ORDER = ["asia", "london", "ny_open", "ny_mid", "ny_close", "post"]


def by_liquidity(d: pd.DataFrame, var: str, h: int, q: float = 0.1) -> pd.DataFrame:
    """Fade edge, split by the liquidity window the displacement formed in."""
    rows = []
    for liq in LIQ_ORDER:
        sub = d[d["liq"] == liq]
        legs = long_short_leg(sub, var, h, q)
        if len(legs) < 200:
            continue
        mu, t = nw_tstat(legs, lags=h)
        rows.append({"liq": liq, "n": len(legs), "fade_atr": mu, "t_nw": t})
    return pd.DataFrame(rows)


def by_vol_regime(d: pd.DataFrame, var: str, h: int, q: float = 0.1) -> pd.DataFrame:
    """Fade edge, split by trailing realised-volatility tercile.

    Nagel (2012) and Della Corte et al. both find reversal pays most when
    intermediaries are constrained, proxied by high volatility.  If the effect
    here is liquidity provision, it must be stronger in the high tercile.
    """
    atr_rel = d["atr"] / d["atr"].rolling(500, min_periods=200).mean()
    terc = pd.qcut(atr_rel, 3, labels=["low", "mid", "high"], duplicates="drop")
    rows = []
    for lab in ["low", "mid", "high"]:
        sub = d[terc == lab]
        legs = long_short_leg(sub, var, h, q)
        if len(legs) < 200:
            continue
        mu, t = nw_tstat(legs, lags=h)
        rows.append({"vol": lab, "n": len(legs), "fade_atr": mu, "t_nw": t})
    return pd.DataFrame(rows)


def overnight_reversal(d: pd.DataFrame) -> dict:
    """The Della Corte CO-OC test, adapted to one instrument at a time.

    Formation: the close-to-open jump across the daily maintenance break,
    in ATR units.  Realisation: the following session's open-to-close return.
    A negative slope means overnight displacement reverses intraday.
    """
    sess = d.groupby("session", sort=False)
    first = sess.first()
    last = sess.last()
    o = first["open"]
    c = last["close"]
    atr0 = first["atr"]
    prev_c = c.shift(1)

    co = (o - prev_c) / atr0          # overnight displacement, ATR units
    oc = (c - o) / atr0               # intraday realisation, ATR units
    df = pd.DataFrame({"co": co, "oc": oc}).dropna()
    if len(df) < 200:
        return {}

    # decile fade: short the top-decile overnight gaps, long the bottom decile
    lo_c, hi_c = df["co"].quantile(0.1), df["co"].quantile(0.9)
    legs = np.concatenate(
        [
            df.loc[df["co"] <= lo_c, "oc"].to_numpy(),
            -df.loc[df["co"] >= hi_c, "oc"].to_numpy(),
        ]
    )
    mu, t = nw_tstat(legs, lags=1)

    beta = np.polyfit(df["co"], df["oc"], 1)[0]
    corr = df["co"].corr(df["oc"])
    return {
        "n_sessions": len(df),
        "beta_oc_on_co": beta,
        "corr": corr,
        "fade_atr": mu,
        "fade_t": t,
        "n_events": len(legs),
    }


def run(timeframe: str = "M15") -> None:
    liq_rows, vol_rows, on_rows = [], [], []
    for sym in dataio.ALL_SYMBOLS:
        try:
            d = F.build(dataio.load(sym, timeframe))
        except FileNotFoundError:
            continue

        for var in ["r_atr_4", "d_vwap", "d_ema20", "d_eq", "streak"]:
            for h in [1, 4, 16]:
                t1 = by_liquidity(d, var, h)
                t1 = t1.assign(symbol=sym, var=var, h=h)
                liq_rows.append(t1)
                t2 = by_vol_regime(d, var, h)
                t2 = t2.assign(symbol=sym, var=var, h=h)
                vol_rows.append(t2)

        r = overnight_reversal(d)
        if r:
            on_rows.append({"symbol": sym, "family": dataio.family_of(sym), **r})
        print(f"[ok] {sym}", flush=True)

    base = _os.path.join(_REPO, "results")
    pd.concat(liq_rows, ignore_index=True).to_csv(f"{base}/stage2_liq_{timeframe}.csv", index=False)
    pd.concat(vol_rows, ignore_index=True).to_csv(f"{base}/stage2_vol_{timeframe}.csv", index=False)
    pd.DataFrame(on_rows).to_csv(f"{base}/stage2_overnight_{timeframe}.csv", index=False)
    print("done")


if __name__ == "__main__":
    import sys

    run(sys.argv[1] if len(sys.argv) > 1 else "M15")
