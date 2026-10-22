"""
Krohn, Mueller & Whelan (JF 2024) FX fixing reversal — replication on FTMO broker data.

Pre-registered design, EURUSD, M5 bars, 2021-01-04 -> 2026-07-29.

Paper's claim: USD appreciates into each fix and depreciates after.
In EURUSD terms  (EURUSD up == USD down):
    pre-fix  leg -> SHORT EURUSD
    post-fix leg -> LONG  EURUSD

Legs tested (paper's Section V definitions, New York time):
    ECB    fix trade:  short EURUSD 02:00 -> 08:15, long EURUSD 08:15 -> 17:00
    London fix trade:  short EURUSD 02:00 -> 11:00, long EURUSD 11:00 -> 17:00

Clock handling — the trap this codebase has hit before:
  MT5 epochs here are SERVER WALL CLOCK, not true UTC.  A naive loader
  subtracts a fixed 3h, which is wrong all EU winter (server is +2) and wrong
  again for the ~4 weeks/yr when EU and US DST are misaligned.  We instead
  localize to Europe/Athens (== the FTMO EET/EEST server clock) and convert.
  Note the European fixes land at a FIXED server time (Athens, Frankfurt and
  London all shift together): ECB 15:15 srv, London 18:00 srv.  Only the
  NY-anchored boundaries drift.

Costs: per-bar spread from the broker feed, taken AT the entry and exit bar
(never a median — see post-window-spread-is-skewed).  Crossing the spread once
per leg is modelled as 0.5*spread_entry + 0.5*spread_exit off the mid.
Commission is parameterised because data/raw/specs.csv is corrupted for EURUSD.
"""
from __future__ import annotations
import os as _os
_REPO = _os.path.dirname(_os.path.abspath(__file__))
_DATA = _os.environ.get("BROKER_DATA_DIR", _os.path.join(_REPO, "data", "raw"))
import numpy as np
import pandas as pd

RAW = _os.path.join(_DATA, "bars_EURUSD_M5.csv")
POINT = 1e-5          # 5-digit EURUSD
PIP = 1e-4
SERVER_TZ = "Europe/Athens"
NY = "America/New_York"

# commission scenarios, round-turn per leg, in pips
COMMISSIONS = {"spread only": 0.0, "$3/lot RT (0.3p)": 0.3, "$7/lot RT (0.7p)": 0.7}


def load() -> pd.DataFrame:
    d = pd.read_csv(RAW)
    t = pd.to_datetime(d["time"], unit="s")          # server wall clock, naive
    t = t.dt.tz_localize(SERVER_TZ, ambiguous="NaT", nonexistent="NaT")
    d = d.assign(t=t).dropna(subset=["t"]).set_index("t").sort_index()
    d = d[~d.index.duplicated(keep="last")]
    d["ny"] = d.index.tz_convert(NY)
    d["spread_px"] = d["spread"] * POINT
    return d


def boundary_bars(d: pd.DataFrame, hh: int, mm: int, tol_min: int = 20) -> pd.DataFrame:
    """First bar at-or-after hh:mm New York on each NY date, within tolerance."""
    ny = d["ny"]
    mins = ny.dt.hour * 60 + ny.dt.minute
    target = hh * 60 + mm
    ok = (mins >= target) & (mins < target + tol_min)
    sel = d[ok].copy()
    sel["date"] = sel["ny"].dt.date
    # keep the earliest qualifying bar per NY date
    sel = sel.sort_index().groupby("date", as_index=False).first()
    return sel.set_index("date")


def build_legs(d: pd.DataFrame, t0, t1, t2) -> pd.DataFrame:
    """t0 -> t1 short EURUSD (long USD); t1 -> t2 long EURUSD (short USD)."""
    b0 = boundary_bars(d, *t0)
    b1 = boundary_bars(d, *t1)
    b2 = boundary_bars(d, *t2)
    idx = b0.index.intersection(b1.index).intersection(b2.index)
    b0, b1, b2 = b0.loc[idx], b1.loc[idx], b2.loc[idx]

    out = pd.DataFrame(index=idx)
    # MT5 bar prices are BID.  ask = bid + spread.
    out["b0"], out["b1"], out["b2"] = b0["open"], b1["open"], b2["open"]
    out["s0"], out["s1"], out["s2"] = b0["spread_px"], b1["spread_px"], b2["spread_px"]
    m0 = out["b0"] + out["s0"] / 2
    m1 = out["b1"] + out["s1"] / 2
    m2 = out["b2"] + out["s2"] / 2

    # GROSS on mid-to-mid — the paper's basis, sign-adjusted so that a correct
    # paper prediction scores positive.
    out["pre_gross"] = -(m1 - m0)                    # short EURUSD (long USD)
    out["post_gross"] = (m2 - m1)                    # long  EURUSD (short USD)
    out["gross"] = out["pre_gross"] + out["post_gross"]

    # EXECUTABLE, bid/ask.  Short: in at bid(t0), out at ask(t1).
    #                       Long:  in at ask(t1), out at bid(t2).
    # Both legs therefore cross the spread at the FIX bar, so cost = 2 * s1.
    out["pre_exec"] = -((out["b1"] + out["s1"]) - out["b0"])
    out["post_exec"] = out["b2"] - (out["b1"] + out["s1"])
    out["exec"] = out["pre_exec"] + out["post_exec"]
    out["pre_cost"] = out["s1"]
    out["post_cost"] = out["s1"]
    out["cost"] = 2 * out["s1"]

    out["year"] = pd.to_datetime(pd.Series(idx, index=idx)).dt.year
    return out.dropna()


def tstat(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 else np.nan


def summarise(name: str, legs: pd.DataFrame) -> None:
    n = len(legs)
    print(f"\n{'='*78}\n{name}   n={n} days   "
          f"{legs.index.min()} -> {legs.index.max()}\n{'='*78}")

    print("\n-- GROSS (mid-to-mid, no costs) — is the pattern even there? --")
    for lab, col in [("pre-fix  (short EURUSD)", "pre_gross"),
                     ("post-fix (long  EURUSD)", "post_gross"),
                     ("combined", "gross")]:
        v = legs[col]
        print(f"  {lab:26s} mean {v.mean()/PIP:+7.3f} pips   "
              f"t={tstat(v):+6.2f}   win% {100*(v>0).mean():5.1f}   "
              f"ann {v.mean()/PIP*252*PIP/1.10*100:+6.2f}%")

    print("\n-- per-event spread actually paid (crossed twice at the fix bar) --")
    v = legs["cost"] / PIP
    print(f"  both legs                  mean {v.mean():6.3f}p  median {v.median():6.3f}p  "
          f"p90 {v.quantile(.9):7.3f}p  p99 {v.quantile(.99):7.3f}p")
    for lab, col in [("spread @ 02:00 NY", "s0"), ("spread @ fix", "s1"),
                     ("spread @ 17:00 NY", "s2")]:
        w = legs[col] / PIP
        print(f"  {lab:26s} mean {w.mean():6.3f}p  median {w.median():6.3f}p  "
              f"p90 {w.quantile(.9):7.3f}p")

    print("\n-- NET (bid/ask executable), per commission scenario --")
    for cl, cpips in COMMISSIONS.items():
        net = legs["exec"] - 2 * cpips * PIP
        print(f"  {cl:18s} mean {net.mean()/PIP:+7.3f} pips  t={tstat(net):+6.2f}  "
              f"win% {100*(net>0).mean():5.1f}")

    print("\n-- GROSS by year (split before pooling) --")
    for y, g in legs.groupby("year"):
        print(f"  {int(y)}  n={len(g):4d}  pre {g.pre_gross.mean()/PIP:+7.3f}p  "
              f"post {g.post_gross.mean()/PIP:+7.3f}p  "
              f"comb {g.gross.mean()/PIP:+7.3f}p  t={tstat(g.gross):+6.2f}")


def conditional_test(d: pd.DataFrame, t_fix, t_end, label: str) -> None:
    """Paper's core conditional claim: return in the LAST HOUR before the fix
    negatively predicts the return over the following window."""
    fix = boundary_bars(d, *t_fix)
    pre1h = boundary_bars(d, t_fix[0] - 1, t_fix[1])
    end = boundary_bars(d, *t_end)
    idx = fix.index.intersection(pre1h.index).intersection(end.index)
    x = (fix.loc[idx, "open"] - pre1h.loc[idx, "open"]) / PIP     # last hour pre-fix
    y = (end.loc[idx, "open"] - fix.loc[idx, "open"]) / PIP       # next window
    m = x.notna() & y.notna()
    x, y = x[m], y[m]
    b, a = np.polyfit(x, y, 1)
    r = np.corrcoef(x, y)[0, 1]
    se = np.sqrt((1 - r**2) / (len(x) - 2)) * (y.std() / x.std())
    print(f"\n-- CONDITIONAL REVERSAL: {label}  n={len(x)} --")
    print(f"   next_window = {a:+.3f} {b:+.4f} * last_hour_pre_fix     "
          f"beta t={b/se:+.2f}   corr={r:+.4f}")
    print(f"   paper predicts beta < 0 (reversal). "
          f"{'CONSISTENT' if b < 0 else 'CONTRADICTS'}")


def placebo(d: pd.DataFrame, t0, t1, t2, shifts=(-3, -2, -1, 1, 2, 3)) -> None:
    """Same window shape anchored away from the fix. If placebos score like the
    real thing, the 'fix' is just a time-of-day effect."""
    print("\n-- PLACEBO: same structure, fix anchor shifted by N hours --")
    real = build_legs(d, t0, t1, t2)["gross"].mean() / PIP
    print(f"   real fix anchor      combined {real:+7.3f} pips")
    for s in shifts:
        h = t1[0] + s
        if not (0 <= h <= 23):
            continue
        try:
            g = build_legs(d, t0, (h, t1[1]), t2)["gross"]
            print(f"   anchor {h:02d}:{t1[1]:02d} NY ({s:+d}h)  "
                  f"combined {g.mean()/PIP:+7.3f} pips   t={tstat(g):+6.2f}")
        except Exception as e:                                    # noqa: BLE001
            print(f"   anchor shift {s:+d}h failed: {e}")


if __name__ == "__main__":
    d = load()
    print(f"loaded {len(d):,} M5 bars  {d.index.min()} -> {d.index.max()}  ({SERVER_TZ})")
    print(f"NY-time span: {d['ny'].min()} -> {d['ny'].max()}")

    ecb = build_legs(d, (2, 0), (8, 15), (17, 0))
    summarise("ECB FIX TRADE  02:00 -> 08:15 -> 17:00 NY", ecb)
    conditional_test(d, (8, 15), (17, 0), "ECB fix, last hour 07:15-08:15 vs 08:15-17:00")
    placebo(d, (2, 0), (8, 15), (17, 0))

    lon = build_legs(d, (2, 0), (11, 0), (17, 0))
    summarise("LONDON FIX TRADE  02:00 -> 11:00 -> 17:00 NY", lon)
    conditional_test(d, (11, 0), (17, 0), "London fix, last hour 10:00-11:00 vs 11:00-17:00")
    placebo(d, (2, 0), (11, 0), (17, 0))

    # NOT TESTED: the Tokyo fix trade (17:00 -> 20:55 -> 02:00 NY) crosses NY
    # midnight, so boundary_bars' calendar-date keying would pair the 02:00 exit
    # with the wrong session.  It needs session-date keying; deliberately left
    # out rather than reported wrong.

    ecb.to_csv(_os.path.join(_REPO, "results", "legs_ecb.csv"))
    lon.to_csv(_os.path.join(_REPO, "results", "legs_london.csv"))
    print("\nwrote legs_ecb.csv, legs_london.csv")
