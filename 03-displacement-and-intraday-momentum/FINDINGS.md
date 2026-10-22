# Displacement Study

Does the forward return distribution change when price becomes unusually
displaced from a reference level — and if so, in which direction?

Tested on broker CFD data (MT5 export): US100 / US500 / US30 / GER40 / XAUUSD /
EURUSD / GBPJPY, M15, Jan 2021 – Jul 2026. Ten displacement variables, six
horizons, six liquidity windows.

## Answer

Both regimes are real. Which one you get is decided by the **liquidity window
the displacement forms in**, not by which reference level you measure it
against. Neither is tradable on this instrument set.

| stage | finding | why it dies |
|---|---|---|
| 1. unconditional | sign flips with horizon: reversion at 1–2 bars, continuation at 16–32 | 0.01–0.07 ATR, an order of magnitude under cost |
| 2–4. NY open, indices | continuation, US100 +0.25 ATR gross, t=2.08, all 6 years positive, placebo p=0.013 | every dev-significant spec collapses or flips sign in the 2025–26 holdout |
| 3, 6. post-close, FX | reversion, GBPJPY +0.56 ATR gross, t=13.7, placebo p<0.001 | per-event spread averages 1.29 ATR — net −0.73 ATR, t=−14.1 |
| 4. Gao et al. (2018) | first half-hour → last half-hour | does not replicate: t = −2.50 to −0.31, R² ≈ 0.001 |
| 5. Della Corte et al. (2022) | overnight → intraday cross-sectional reversal | structurally unavailable — see below |

## The load-bearing result

The overnight leg carries **~0% of daily variance** on these CFDs (US100: 28bp
overnight vs 137bp intraday). A 24/5 CFD has no market closure; the "open" is
the 17:00 NY maintenance break. Every published result that formation-loads on
close-to-open — Della Corte CO-OC, Lou–Polk–Skouras, Bogousslavsky — needs a
real closure with an auction at each end. On this panel CO-OC gives −0.03%/day
gross against their +0.238%/day.

Check the overnight variance share before porting any paper of that family.

## Two costing traps this found

- **specs.csv is unusable.** The description field contains an unquoted comma
  ("NASDAQ 100 Index, Spot CFD"), which shifts every later column and leaves the
  symbol column holding digit counts. `stage3.POINT` hardcodes point size from
  quoted digits instead.
- **Median spread understates thin-window cost by 3x.** Post-close spreads are
  heavily right-skewed and the trades that fire cluster in the wide tail. Charge
  each event the spread on its own signal bar.

## One bar-boundary bug worth remembering

An early run showed a strong late-session reversal on all seven symbols,
holdout t between −2.0 and −6.3. It was entirely an artifact of including the
bar stamped 16:00, which covers 16:00–16:15 and drags post-close prices into the
last half-hour return. With `ny_minute < 16*60` it vanishes and the sign flips.

## Layout

```
src/dataio.py    loading, resolution trimming, server/UTC/NY clocks
src/features.py  displacement variables and forward returns, all in ATR units
src/study.py     stage 1  unconditional decile tables, Newey-West, placebo
src/stage2.py    stage 2  conditioning on liquidity window and vol regime
src/stage3.py    stage 3  spread audit, cost hurdle, year stability, mirror control
src/stage4.py    stage 4  Gao et al. replication, dev/holdout sweep
src/stage5.py    stage 5  Della Corte cross-sectional CC/OO/OC/CO replication
src/stage6.py    stage 6  per-event costing of the last survivor
results/         result tables
```

Run any stage (see the repo README for the data setup):

```bash
python src/study.py M15
```

## Data caveat

Early history is coarser than the filename claims — US100/US500 M15 only becomes
true M15 in Sep 2021, GER40 in Jan 2022. `dataio.trim_to_resolution` cuts the
degraded head automatically. FX coverage is thin (EURUSD, GBPJPY only); a
broader export needs the MT5 GUI closed first, since a second portable instance
cannot start.
