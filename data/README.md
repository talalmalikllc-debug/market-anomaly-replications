# Data

Raw price data is **not** included: it is a licensed broker feed and runs to
hundreds of megabytes. Everything in `results/`, `figures/` and the notebook is
reproducible without it.

To re-run the pipeline from scratch, export bars from MetaTrader 5 as one CSV per
symbol and timeframe, named `bars_<SYMBOL>_<TF>.csv` (for example
`bars_US100.cash_M5.csv`), with this header:

```
time,open,high,low,close,tick_volume,spread,real_volume
1609718400,12911.10,12973.00,12535.75,12701.75,278601,0,0
```

* `time`: bar open, Unix seconds on the **broker's wall clock** (EET/EEST for the
  feed used here). The loaders convert to UTC and New York time through the tz
  database.
* `spread`: the bar's quoted spread in broker points. It is used for per-event
  transaction costs.

Put the files in `data/raw/`, or point the code at another folder:

```bash
export BROKER_DATA_DIR=/path/to/export
```

Source used for the published results: MetaTrader 5 demo-server export, 2021-01 to 2026-07.
