# Overnight–intraday reversal on index CFDs — measured, not assumed

Data: exported M5 bars, NY cash session (16:30–23:00 server = 09:30–16:00 New York),
US100 / US500 / US30 / GER40. All numbers net of the median observed spread.

**Sample windows, stated exactly.** `reversal_research.py` and `gapfill_research.py`
(sections 1–3) use every available session, 2021 → 2026-07. `conditioning_research.py`
and `continuation_check.py` (sections 4–5) are restricted to **2021 → 2024-12-31**
and never read 2025 onward. Because the first two scripts saw the later data, no
section of this study should be treated as an untouched out-of-sample test.

Scripts: `scripts/reversal_research.py`, `scripts/gapfill_research.py`,
`scripts/conditioning_research.py`, `scripts/continuation_check.py`.
Full console output: `results/logs/`.

---

## 1. The reversal effect exists, but it is small

Correlation between the overnight gap and the following intraday return —
negative on every instrument, exactly as Della Corte et al. report for equity
index futures:

| Instrument | corr(overnight gap, next intraday return) |
|---|---|
| US100 | −0.0525 |
| US500 | −0.0739 |
| US30  | −0.0788 |
| GER40 | −0.0659 |

Fading the gap and holding open→close, filtered to the largest 25% of gaps,
was positive on all four (edge +5.2 to +8.1 points over the geometric baseline,
Sharpe 1.1–1.9). That is a genuine, if modest, signal.

**But the win rate of that shape is 48–50%.** It is a symmetric-payoff trade.

## 2. Every 60%-win-rate geometry has NEGATIVE edge

Tightening the target to half the gap does deliver the requested win rate, and
destroys the edge. `baseline` is the win rate the TP/SL geometry pays for free
on a driftless path:

| Instrument | target | stop | **WR** | payoff | baseline WR | **edge** |
|---|---|---|---|---|---|---|
| US100 | 0.50×gap | 2.0×gap | **62.0%** | 0.58 | 63.4% | **−1.4** |
| US500 | 0.50×gap | 2.0×gap | **62.4%** | 0.58 | 63.4% | **−1.0** |
| US30  | 0.50×gap | 2.0×gap | **59.7%** | 0.60 | 62.5% | **−2.8** |
| US100 | 0.50×gap | 1.0×gap | 58.7% | 0.63 | 61.3% | −2.5 |
| US30  | 0.50×gap | 1.5×gap | 58.5% | 0.60 | 62.5% | −4.0 |

A 62% win rate that loses money. This is the geometry identity in action:
win rate is set by where you place the target, and carries no information on
its own.

## 3. The cross-sectional version does not transfer

The paper's actual construction — rank instruments by overnight return, long the
losers, short the winners — fails here:

| Book | WR | edge | t |
|---|---|---|---|
| US100+US500+US30, net | 48.7% | −1.5 | −0.78 |
| all four, net | 49.8% | −1.3 | −0.67 |

Reason: the three US indices are near-identical assets. Cross-sectional reversal
needs dispersion, and there is almost none. The paper's universe (DJIA, NASDAQ,
NIKKEI 225, S&P400, S&P500) had a Japanese index supplying real dispersion.
A four-index CFD lineup cannot reproduce that.

## 4. Conditioning found nothing

Pooled across all four instruments, gap-fade with a 0.75×gap target:

    ALL                  n=830  edge −0.0  t=−0.01

Splits by direction, realised-volatility tercile, and day of week produced no
cell that was both economically and statistically meaningful. The best-looking
cells (US30 Wednesday +9.5, GER40 Monday +10.9) have n≈30–45, t≈0.9–1.1, and
**contradict each other across instruments** — Monday is −12.0 on US30 and
+10.9 on GER40. That is the signature of noise, not structure. Twenty
day-of-week cells were tested; a couple at t≈1 is what chance produces.

## 5. The one real signal points the other way

The strongest result in the entire study has the wrong sign for mean reversion.
Entering **in the direction** of a large gap and holding one hour:

| Set | n | WR | payoff | baseline | edge | t |
|---|---|---|---|---|---|---|
| **Pooled, gap-DOWN → short, 1h** | 431 | 53.8% | 1.15 | 46.6% | **+7.2** | **2.30** |
| US30 alone, both directions, 1h | 250 | 56.8% | 1.11 | 47.3% | +9.5 | 2.36 |
| Pooled, gap-UP → long, 1h | 423 | 53.4% | 0.86 | 53.6% | −0.2 | −0.07 |

And it decays coherently with holding time — +7.2 at 1h, +1.5 at 2h, +0.8 at 3h,
−4.2 over the full session — which is at least a plausible opening-hour
microstructure story rather than a random spike.

**Caveat that matters:** pooling four ~95%-correlated instruments badly inflates
the t-statistic. The effective independent sample is far below 431; a fair
estimate puts the true t nearer 1.3–1.5. This is a lead, not a finding.

---

## Conclusion

There is no configuration in this data that delivers **both** a 60% win rate
**and** positive edge. The reversal edge that exists lives at ~49% win rate;
every geometry that lifts the win rate to 60% pushes edge negative.

No strategy was built on it. A 62%-win-rate system with −1.4 points of edge looks
excellent for a few weeks and then bleeds, because the win rate was bought with geometry.
