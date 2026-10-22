import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_DATA = _os.environ.get("BROKER_DATA_DIR", _os.path.join(_REPO, "data", "raw"))
#!/usr/bin/env python3
"""
Gap-fade with a gap-fill target: the high-win-rate geometry.

Entry  : at the NY open, fade an overnight gap larger than a threshold
Target : a fraction of the way back to the previous session close
Stop   : a multiple of the gap size beyond the entry
Timeout: flat at the NY close

The intrabar path is walked on M5 bars. When a bar contains BOTH the target
and the stop, the STOP is assumed to fill first - the pessimistic assumption,
because bar data cannot say which came first.
"""
import csv, datetime, statistics, math
from collections import defaultdict

RAW = _DATA
SYMS = ["US100.cash", "US500.cash", "US30.cash", "GER40.cash"]
SESS_OPEN, SESS_CLOSE = (16, 30), (23, 0)


def load(sym):
    day = defaultdict(list)
    spreads = []
    with open(f"{RAW}/bars_{sym}_M5.csv") as fh:
        for r in csv.DictReader(fh):
            t = datetime.datetime.utcfromtimestamp(int(r["time"]))
            if t.weekday() >= 5:
                continue
            if not (SESS_OPEN <= (t.hour, t.minute) < SESS_CLOSE):
                continue
            day[t.date()].append((t, float(r["open"]), float(r["high"]),
                                  float(r["low"]), float(r["close"])))
            spreads.append(float(r["spread"]))
    out = {}
    for d, b in day.items():
        if len(b) < 50:
            continue
        b.sort()
        out[d] = b
    return out, (statistics.median(spreads) if spreads else 0.0)


def simulate(bars, entry, direction, target, stop):
    """direction +1 long / -1 short. Returns (exit_price, outcome)."""
    for _, o, h, l, c in bars:
        hit_stop = (l <= stop) if direction > 0 else (h >= stop)
        hit_tgt = (h >= target) if direction > 0 else (l <= target)
        if hit_stop and hit_tgt:
            return stop, "stop"          # pessimistic tie-break
        if hit_stop:
            return stop, "stop"
        if hit_tgt:
            return target, "target"
    return bars[-1][4], "timeout"


def run(sym, gap_pct_thresh, fill_frac, stop_mult, atr_floor=True):
    sess, sp_pts = load(sym)
    dates = sorted(sess)
    px = statistics.median([sess[d][-1][4] for d in dates])
    cost = (sp_pts * 0.01) / px

    # gap threshold as a percentile of |gap|
    gaps_all = []
    for i in range(1, len(dates)):
        prev_c = sess[dates[i - 1]][-1][4]
        op = sess[dates[i]][0][1]
        gaps_all.append(abs(op / prev_c - 1.0))
    thr = sorted(gaps_all)[int(gap_pct_thresh * len(gaps_all))]

    rets, outcomes = [], []
    for i in range(1, len(dates)):
        prev_c = sess[dates[i - 1]][-1][4]
        bars = sess[dates[i]]
        op = bars[0][1]
        g = op / prev_c - 1.0
        if abs(g) < thr:
            continue
        d = -1 if g > 0 else 1                     # fade
        gap_abs = abs(op - prev_c)
        target = op + d * gap_abs * fill_frac      # back toward prev close
        stop = op - d * gap_abs * stop_mult
        ex, out = simulate(bars, op, d, target, stop)
        rets.append(d * (ex - op) / op - cost)
        outcomes.append(out)
    return rets, outcomes, thr


def stats(name, rets):
    if len(rets) < 20:
        print(f"  {name:46s} too few ({len(rets)})")
        return None
    wins = [r for r in rets if r > 0]
    loss = [r for r in rets if r <= 0]
    wr = 100 * len(wins) / len(rets)
    mean = statistics.mean(rets)
    sd = statistics.stdev(rets)
    aw = statistics.mean(wins) if wins else 0
    al = abs(statistics.mean(loss)) if loss else 0
    payoff = aw / al if al > 0 else float("inf")
    base = 100 / (1 + payoff) if payoff != float("inf") else 0
    t = mean / (sd / math.sqrt(len(rets))) if sd > 0 else 0
    print(f"  {name:46s} n={len(rets):4d} WR={wr:5.1f}% payoff={payoff:4.2f} "
          f"base={base:5.1f}% edge={wr-base:+5.1f} mean={mean*100:+6.3f}% t={t:5.2f}")
    return wr, payoff, mean, t, len(rets)


if __name__ == "__main__":
    print("Fade the overnight gap, target a partial fill, stop beyond the open.")
    print("Gap threshold = 75th percentile of |gap| (the top-25% filter that")
    print("was consistently positive across all four indices).\n")
    for sym in SYMS:
        print(f"================ {sym} ================")
        for fill in (0.5, 0.75, 1.0):
            for smult in (1.0, 1.5, 2.0):
                r, o, thr = run(sym, 0.75, fill, smult)
                stats(f"fill={fill:.2f}gap stop={smult:.1f}gap", r)
        print()
