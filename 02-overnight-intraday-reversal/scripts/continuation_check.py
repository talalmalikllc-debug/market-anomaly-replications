import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_DATA = _os.environ.get("BROKER_DATA_DIR", _os.path.join(_REPO, "data", "raw"))
#!/usr/bin/env python3
"""
The conditioning study threw up one strongly significant result - and it was
the wrong sign for mean reversion: fading a gap-down inside the first hour
lost money at t = -2.54. Inverted, that is a CONTINUATION signal.

This tests it directly, IS only (2021 .. 2024-12-31), 2025+ untouched.
Entry at the NY open in the DIRECTION of the gap, flat after N hours.
"""
import csv, datetime, statistics, math
from collections import defaultdict

RAW = _DATA
SYMS = ["US100.cash", "US500.cash", "US30.cash", "GER40.cash"]
SESS_OPEN, SESS_CLOSE = (16, 30), (23, 0)
IS_END = datetime.date(2024, 12, 31)


def load(sym):
    day = defaultdict(list); sp = []
    with open(f"{RAW}/bars_{sym}_M5.csv") as fh:
        for r in csv.DictReader(fh):
            t = datetime.datetime.utcfromtimestamp(int(r["time"]))
            if t.weekday() >= 5: continue
            if not (SESS_OPEN <= (t.hour, t.minute) < SESS_CLOSE): continue
            day[t.date()].append((t, float(r["open"]), float(r["high"]),
                                  float(r["low"]), float(r["close"])))
            sp.append(float(r["spread"]))
    return ({d: sorted(b) for d, b in day.items() if len(b) >= 50},
            statistics.median(sp) if sp else 0.0)


def stats(name, rets):
    if len(rets) < 25:
        print(f"    {name:40s} n={len(rets):4d}  (too few)"); return
    w = [r for r in rets if r > 0]; l = [r for r in rets if r <= 0]
    wr = 100*len(w)/len(rets); m = statistics.mean(rets); sd = statistics.stdev(rets)
    aw = statistics.mean(w) if w else 0; al = abs(statistics.mean(l)) if l else 0
    po = aw/al if al > 0 else float("inf")
    base = 100/(1+po) if po != float("inf") else 0
    t = m/(sd/math.sqrt(len(rets))) if sd > 0 else 0
    flag = "  <<<" if (wr-base) > 3 and t > 2.0 else ""
    print(f"    {name:40s} n={len(rets):4d} WR={wr:5.1f}% payoff={po:4.2f} "
          f"base={base:5.1f}% edge={wr-base:+5.1f} mean={m*100:+6.3f}% t={t:5.2f}{flag}")


def run(sym, hours, gap_q, side):
    sess, sp = load(sym)
    dates = [d for d in sorted(sess) if d <= IS_END]
    px = statistics.median([sess[d][-1][4] for d in dates])
    cost = (sp*0.01)/px
    gaps = [abs(sess[dates[i]][0][1]/sess[dates[i-1]][-1][4]-1) for i in range(1, len(dates))]
    thr = sorted(gaps)[int(gap_q*len(gaps))]
    nb = None if hours is None else int(hours*12)
    out = []
    for i in range(1, len(dates)):
        prev_c = sess[dates[i-1]][-1][4]
        bars = sess[dates[i]]; op = bars[0][1]
        g = op/prev_c - 1
        if abs(g) < thr: continue
        d = 1 if g > 0 else -1                     # CONTINUATION
        if side == "up" and d < 0: continue
        if side == "down" and d > 0: continue
        use = bars if nb is None else bars[:nb]
        out.append(d*(use[-1][4]-op)/op - cost)
    return out


if __name__ == "__main__":
    print("GAP CONTINUATION at the NY open. IS only, 2021 .. 2024-12-31.")
    print("Gap must exceed the 75th percentile of |gap|.\n")
    for hours in (1, 2, 3, None):
        lbl = "full session" if hours is None else f"{hours}h hold"
        print(f"================ {lbl} ================")
        pooled, pu, pd = [], [], []
        for sym in SYMS:
            a = run(sym, hours, 0.75, "both")
            stats(sym, a); pooled += a
            pu += run(sym, hours, 0.75, "up")
            pd += run(sym, hours, 0.75, "down")
        stats("POOLED both directions", pooled)
        stats("POOLED gap-UP only (long)", pu)
        stats("POOLED gap-DOWN only (short)", pd)
        print()
