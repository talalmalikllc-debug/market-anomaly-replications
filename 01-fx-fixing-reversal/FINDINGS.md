# FX fixing reversal on EURUSD, broker CFD data 2021–2026 — falsified

Test of Krohn, Mueller & Whelan (*JF* 2024), "Foreign Exchange Fixings and Returns
Around the Clock", on the broker data this account actually trades.

**Verdict: no predictive value. Do not build on it.** The effect is not decayed —
in this sample it is *absent*, gross, before any cost is applied.

## What was run

- `fixstudy.py`, EURUSD **M5**, **2021-01-04 → 2026-07-29**, n = **1,170 days**
- Legs exactly as the paper's Section V defines them, in New York time:
  - **ECB fix**: short EURUSD 02:00 → 08:15, long EURUSD 08:15 → 17:00
  - **London fix**: short EURUSD 02:00 → 11:00, long EURUSD 11:00 → 17:00
  - (short EURUSD == long USD, so a correct paper prediction scores positive)

## Headline

| | gross combined | t | paper's claim |
|---|---|---|---|
| ECB fix trade | **−0.43 pips/day** | −0.31 | +13.6%/yr ≈ **+6 pips/day** |
| London fix trade | **+0.04 pips/day** | +0.03 | +11.2%/yr (GBP) |

Gross is **zero**, not merely smaller. The paper's own gross figure is two orders
of magnitude away from what this data shows.

**Net, executable (bid/ask, per-event spreads):**

| commission | ECB | London |
|---|---|---|
| spread only | −2.87 pips  (t=−2.07) | −2.40 pips  (t=−1.76) |
| $3/lot RT | −3.47 pips  (t=−2.51) | −3.00 pips  (t=−2.20) |
| $7/lot RT | −4.27 pips  (t=−3.09) | −3.80 pips  (t=−2.79) |

## Why it fails — three independent checks, all negative

**1. Per-year signs are random.** London fix combined, by year:
`+1.16, −2.80, +3.94, +3.18, −4.38, −1.58` pips. No year reaches |t| > 1.4.
That is noise with a wide spread, not an edge with a bad patch.

**2. The conditional claim is empty.** The paper's core mechanism test is that the
last hour before the fix negatively predicts the following window. The sign does
come out negative — but:

```
ECB:     beta = -0.046   corr = -0.013   t = -0.44
London:  beta = -0.008   corr = -0.006   t = -0.20
```

Correlation of −0.01 is nothing. The "CONSISTENT" label the script prints is a
sign check only and should not be read as support.

**3. Placebo kills it.** Shifting the fix anchor ±1–3 hours produces combined
returns that are the same as, or *better than*, the true fix anchor:

```
ECB   real +0.43 down to -0.43;  shifted anchors range -3.00 .. -0.72
London real +0.04;               shifted anchors range -1.36 .. +0.65
```

There is nothing special about the fixing minute in this data. Whatever small
drift exists is broad time-of-day, not something specific to the fix.

## Cost reality

Crossing the spread twice at the fix bar: **mean 1.65 pips, median 0.40, p90 10.0**.
A back-of-envelope estimate of ~0.55 pips/leg understates the mean by 3x.
The spread distribution is bimodal — 2 points most of the time, 50 points in
~14% of bars — so the median badly understates the cost of trading at a fixed clock time.

The 17:00 NY exit lands **exactly on rollover**: mean spread 2.40 pips,
median 2.10, tick volume at its daily minimum. The paper's exit time is the worst
minute of the day to transact on a retail feed.

## Two data-pipeline bugs caught in the process

**A naive loader gets the clock wrong.** The research platform's loader subtracted a
**fixed** 3h from the server epoch. The server is Athens (EET/EEST): +2 all EU
winter, and misaligned with US DST for ~4 weeks a year. This study localises to
`Europe/Athens` and converts, verified by NY 17:00 → server 00:00/23:00 with the
rollover spread and volume trough landing exactly there.

Useful consequence: Athens, Frankfurt and London all shift together, so **the
European fixes sit at a fixed server time** — ECB 15:15, London 18:00. Only the
NY-anchored boundaries drift.

**`data/raw/specs.csv` is corrupted.** The symbol column reads
`2,2,2,2,2,5,GBPJPY` — EURUSD has no row at all. Any backtest engine run on EURUSD
would silently take a fallback contract spec. **Re-export before running an engine on FX.** This study sidesteps it
by computing in price/pip terms directly.

## Data limits

- The target window was 2020 onward; EURUSD **M5 begins 2021-01-04**. M1 only reaches back to
  2024-05-29 (800k-row export cap), so M5 was used — which is also the paper's own
  sampling frequency, so nothing is lost.
- Source: the raw MT5 export `data/raw/bars_EURUSD_M5.csv`, which carries the per-bar
  `spread` column — that is what the per-event cost model reads.

## Not tested

The **Tokyo fix** leg (17:00 → 20:55 → 02:00 NY) crosses NY midnight, and
`boundary_bars` keys on calendar date, which would pair the exit with the wrong
session. Left out deliberately rather than reported wrong. If it is ever wanted it
needs session-date keying — but given the ECB and London results, and that the
paper itself shows the Tokyo leg going negative for EUR from ~2013, it is not
worth the hour.

## What not to do next

Do not tune the exit off 17:00 to dodge the rollover spread. Gross is zero; moving
the boundary until net turns positive is in-sample curve-fitting. The signal has to exist before the cost discussion is worth having,
and it does not.
