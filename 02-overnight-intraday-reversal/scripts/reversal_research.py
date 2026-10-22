import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_DATA = _os.environ.get("BROKER_DATA_DIR", _os.path.join(_REPO, "data", "raw"))
#!/usr/bin/env python3
"""
Does the overnight -> intraday reversal (Della Corte et al., CO-OC) exist on
FTMO index CFDs?

Builds New York cash-session daily bars from the exported M5 CSVs
(09:30-16:00 NY = 16:30-23:00 broker server time, verified constant +7h)
and measures:

  1. TS-SIGN   time-series: fade the sign of the overnight gap
  2. TS-THRESH same, but only when the gap exceeds a threshold
  3. IBS       fade a stretched close within the prior session's range
  4. XS        cross-sectional: rank indices by overnight gap, long worst /
               short best (this is the paper's actual construction)

Everything is reported gross AND net of the median observed spread.
"""
import csv, datetime, statistics, math, os, sys
from collections import defaultdict

RAW = _DATA
SYMS = ["US100.cash", "US500.cash", "US30.cash", "GER40.cash"]
SESS_OPEN = (16, 30)      # server time == 09:30 New York
SESS_CLOSE = (23, 0)      # server time == 16:00 New York


def load_sessions(sym):
    """M5 bars -> one NY-session bar per date."""
    path = f"{RAW}/bars_{sym}_M5.csv"
    day = defaultdict(list)
    spreads = []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            t = datetime.datetime.utcfromtimestamp(int(r["time"]))
            if t.weekday() >= 5:
                continue
            hm = (t.hour, t.minute)
            if not (SESS_OPEN <= hm < SESS_CLOSE):
                continue
            day[t.date()].append((t, float(r["open"]), float(r["high"]),
                                  float(r["low"]), float(r["close"])))
            spreads.append(float(r["spread"]))
    out = {}
    for d, bars in day.items():
        if len(bars) < 50:          # half-day / holiday: skip
            continue
        bars.sort()
        out[d] = dict(o=bars[0][1], h=max(b[2] for b in bars),
                      l=min(b[3] for b in bars), c=bars[-1][4])
    med_spread_pts = statistics.median(spreads) if spreads else 0.0
    return out, med_spread_pts


def tstat(xs):
    n = len(xs)
    if n < 3:
        return 0.0
    m = statistics.mean(xs)
    s = statistics.stdev(xs)
    return m / (s / math.sqrt(n)) if s > 0 else 0.0


def report(name, rets, cost_frac=0.0):
    """rets: list of signed strategy returns as fractions."""
    net = [r - cost_frac for r in rets]
    if len(net) < 10:
        print(f"  {name:34s}  too few observations ({len(net)})")
        return
    wins = [r for r in net if r > 0]
    loss = [r for r in net if r <= 0]
    wr = 100.0 * len(wins) / len(net)
    mean = statistics.mean(net)
    sd = statistics.stdev(net)
    sharpe = (mean / sd * math.sqrt(252)) if sd > 0 else 0.0
    avg_w = statistics.mean(wins) if wins else 0.0
    avg_l = abs(statistics.mean(loss)) if loss else 0.0
    payoff = (avg_w / avg_l) if avg_l > 0 else float("inf")
    base_wr = 100.0 / (1.0 + payoff) if payoff != float("inf") else 0.0
    print(f"  {name:34s}  n={len(net):5d}  WR={wr:5.1f}%  payoff={payoff:4.2f}  "
          f"baselineWR={base_wr:5.1f}%  edge={wr-base_wr:+5.1f}pts  "
          f"mean={mean*100:+6.3f}%  t={tstat(net):5.2f}  Sharpe={sharpe:5.2f}")


def main():
    data, costs = {}, {}
    for s in SYMS:
        try:
            data[s], sp = load_sessions(s)
            # spread is in points; convert to a fraction of price using the
            # median session close. Round trip crosses the spread once.
            px = statistics.median([v["c"] for v in data[s].values()])
            costs[s] = (sp * 0.01) / px
            print(f"{s:12s} {len(data[s]):5d} sessions  "
                  f"{min(data[s]):%Y-%m-%d} -> {max(data[s]):%Y-%m-%d}  "
                  f"median spread {sp:.0f} pts = {costs[s]*100:.4f}% round trip")
        except FileNotFoundError:
            print(f"{s}: no data")

    for s in SYMS:
        if s not in data:
            continue
        d = data[s]
        dates = sorted(d)
        print(f"\n================ {s} ================")

        overnight, intraday, ibs_prev = [], [], []
        for i in range(1, len(dates)):
            p, t = d[dates[i - 1]], d[dates[i]]
            overnight.append(t["o"] / p["c"] - 1.0)     # close(t-1) -> open(t)
            intraday.append(t["c"] / t["o"] - 1.0)      # open(t)   -> close(t)
            rng = p["h"] - p["l"]
            ibs_prev.append((p["c"] - p["l"]) / rng if rng > 0 else 0.5)

        # correlation of overnight gap with the following intraday return
        n = len(overnight)
        mo, mi = statistics.mean(overnight), statistics.mean(intraday)
        so, si = statistics.stdev(overnight), statistics.stdev(intraday)
        cov = sum((overnight[k]-mo)*(intraday[k]-mi) for k in range(n))/(n-1)
        corr = cov/(so*si) if so > 0 and si > 0 else 0.0
        print(f"  corr(overnight gap, following intraday return) = {corr:+.4f}"
              f"   [negative = reversal]")

        c = costs.get(s, 0.0)
        # 1. fade the sign of the overnight gap
        r = [(-1 if overnight[k] > 0 else 1) * intraday[k] for k in range(n)]
        report("TS-SIGN fade gap (gross)", r, 0.0)
        report("TS-SIGN fade gap (net)", r, c)

        # 2. only when the gap is large
        gaps = sorted(abs(g) for g in overnight)
        for q, lbl in ((0.50, "top50%"), (0.75, "top25%"), (0.90, "top10%")):
            thr = gaps[int(q * len(gaps))]
            r2 = [(-1 if overnight[k] > 0 else 1) * intraday[k]
                  for k in range(n) if abs(overnight[k]) >= thr]
            report(f"TS-THRESH gap {lbl} (net)", r2, c)

        # 3. IBS on the previous session
        r3 = [(1 if ibs_prev[k] < 0.2 else -1) * intraday[k]
              for k in range(n) if ibs_prev[k] < 0.2 or ibs_prev[k] > 0.8]
        report("IBS <0.2 long / >0.8 short (net)", r3, c)

    # 4. cross-sectional, US indices only (identical session)
    for label, group in (("US100+US500+US30", ["US100.cash", "US500.cash", "US30.cash"]),
                         ("all four", SYMS)):
        group = [g for g in group if g in data]
        common = sorted(set.intersection(*[set(data[g]) for g in group]))
        print(f"\n============ CROSS-SECTIONAL: {label} "
              f"({len(group)} instruments, {len(common)} common sessions) ============")
        rets = []
        for i in range(1, len(common)):
            prev, cur = common[i - 1], common[i]
            ov, ind = {}, {}
            for g in group:
                ov[g] = data[g][cur]["o"] / data[g][prev]["c"] - 1.0
                ind[g] = data[g][cur]["c"] / data[g][cur]["o"] - 1.0
            avg = statistics.mean(ov.values())
            w = {g: -(ov[g] - avg) for g in group}
            gross = sum(abs(v) for v in w.values())
            if gross == 0:
                continue
            w = {g: v / gross for g, v in w.items()}      # scale to $1 gross
            rets.append(sum(w[g] * ind[g] for g in group))
        avg_cost = statistics.mean([costs[g] for g in group])
        report("XS reversal (gross)", rets, 0.0)
        report("XS reversal (net)", rets, avg_cost)


if __name__ == "__main__":
    main()
