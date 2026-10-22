import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_DATA = _os.environ.get("BROKER_DATA_DIR", _os.path.join(_REPO, "data", "raw"))
#!/usr/bin/env python3
"""
Where does the gap-fade edge actually concentrate?

DISCOVERY IS RESTRICTED TO 2021-01-01 .. 2024-12-31.
2025+ is held back and never touched here.

Conditioners tested:
  - gap direction (fade gap-down = buy dip, vs fade gap-up = sell rip)
  - volatility state (realised vol percentile of the prior 20 sessions)
  - day of week
  - holding window (full session vs first N hours)
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


def simulate(bars, entry, d, target, stop, max_bars=None):
    use = bars if max_bars is None else bars[:max_bars]
    for _, o, h, l, c in use:
        hs = (l <= stop) if d > 0 else (h >= stop)
        ht = (h >= target) if d > 0 else (l <= target)
        if hs: return stop
        if ht: return target
    return use[-1][4]


def stats(name, rets):
    if len(rets) < 25:
        print(f"    {name:44s} n={len(rets):4d}  (too few)"); return
    w = [r for r in rets if r > 0]; l = [r for r in rets if r <= 0]
    wr = 100*len(w)/len(rets); m = statistics.mean(rets); sd = statistics.stdev(rets)
    aw = statistics.mean(w) if w else 0; al = abs(statistics.mean(l)) if l else 0
    po = aw/al if al > 0 else float("inf")
    base = 100/(1+po) if po != float("inf") else 0
    t = m/(sd/math.sqrt(len(rets))) if sd > 0 else 0
    flag = "  <<<" if (wr-base) > 4 and t > 1.5 else ""
    print(f"    {name:44s} n={len(rets):4d} WR={wr:5.1f}% payoff={po:4.2f} "
          f"base={base:5.1f}% edge={wr-base:+5.1f} mean={m*100:+6.3f}% t={t:5.2f}{flag}")


def build(sym, fill, smult, gap_q=0.75, max_bars=None):
    sess, sp = load(sym)
    dates = [d for d in sorted(sess) if d <= IS_END]
    px = statistics.median([sess[d][-1][4] for d in dates])
    cost = (sp*0.01)/px
    gaps = []
    for i in range(1, len(dates)):
        gaps.append(abs(sess[dates[i]][0][1]/sess[dates[i-1]][-1][4] - 1))
    thr = sorted(gaps)[int(gap_q*len(gaps))]

    rows = []
    for i in range(21, len(dates)):
        prev_c = sess[dates[i-1]][-1][4]
        bars = sess[dates[i]]; op = bars[0][1]
        g = op/prev_c - 1
        if abs(g) < thr: continue
        d = -1 if g > 0 else 1
        ga = abs(op - prev_c)
        ex = simulate(bars, op, d, op + d*ga*fill, op - d*ga*smult, max_bars)
        ret = d*(ex-op)/op - cost
        # realised vol of the prior 20 sessions (close-to-close)
        cl = [sess[dates[k]][-1][4] for k in range(i-21, i)]
        rv = statistics.stdev([cl[k+1]/cl[k]-1 for k in range(len(cl)-1)])
        rows.append(dict(ret=ret, dir=d, dow=dates[i].weekday(), rv=rv, date=dates[i]))
    return rows


if __name__ == "__main__":
    FILL, SMULT = 0.75, 1.5
    print(f"Gap fade, target={FILL}xgap, stop={SMULT}xgap, gap>75th pct")
    print(f"DISCOVERY WINDOW: 2021 .. {IS_END}  (2025+ untouched)\n")
    pooled = []
    for sym in SYMS:
        rows = build(sym, FILL, SMULT)
        print(f"================ {sym}  ({len(rows)} signals) ================")
        stats("ALL", [r["ret"] for r in rows])
        stats("fade gap-DOWN only (buy the dip)", [r["ret"] for r in rows if r["dir"] > 0])
        stats("fade gap-UP only (sell the rip)", [r["ret"] for r in rows if r["dir"] < 0])
        rvs = sorted(r["rv"] for r in rows)
        hi = rvs[int(0.66*len(rvs))]; lo = rvs[int(0.33*len(rvs))]
        stats("high realised vol (top third)", [r["ret"] for r in rows if r["rv"] >= hi])
        stats("low realised vol (bottom third)", [r["ret"] for r in rows if r["rv"] <= lo])
        for dw, nm in ((0,"Mon"),(1,"Tue"),(2,"Wed"),(3,"Thu"),(4,"Fri")):
            stats(f"{nm} only", [r["ret"] for r in rows if r["dow"] == dw])
        pooled += rows
        print()

    print("================ POOLED across all four indices ================")
    stats("ALL", [r["ret"] for r in pooled])
    stats("fade gap-DOWN only", [r["ret"] for r in pooled if r["dir"] > 0])
    stats("fade gap-UP only", [r["ret"] for r in pooled if r["dir"] < 0])
    rvs = sorted(r["rv"] for r in pooled); hi = rvs[int(0.66*len(rvs))]
    stats("high vol", [r["ret"] for r in pooled if r["rv"] >= hi])
    stats("gap-DOWN + high vol", [r["ret"] for r in pooled if r["dir"] > 0 and r["rv"] >= hi])

    print("\n================ holding-window scan (pooled, gap-DOWN only) ================")
    for mb, lbl in ((12,"first 1h"), (24,"first 2h"), (36,"first 3h"), (None,"full session")):
        p = []
        for sym in SYMS:
            p += [r["ret"] for r in build(sym, FILL, SMULT, max_bars=mb) if r["dir"] > 0]
        stats(lbl, p)
