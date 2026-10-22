import os as _os
_REPO = _os.path.dirname(_os.path.abspath(__file__))
_DATA = _os.environ.get("BROKER_DATA_DIR", _os.path.join(_REPO, "data", "raw"))
"""
FX fixing reversal — interactive version.

In VS Code: select the project venv as interpreter, then press Shift+Enter on
each `# %%` cell.  Plots render in the pane beside the code.
Running it as a plain script instead writes the same charts to ./figs/.
"""
# %%
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, _REPO)
from fixstudy import PIP, build_legs, load, tstat            # noqa: E402

FIGS = Path(_os.path.join(_REPO, "figs"))
FIGS.mkdir(exist_ok=True)
INTERACTIVE = hasattr(sys, "ps1") or "ipykernel" in sys.modules

plt.rcParams.update({"figure.figsize": (11, 5), "axes.grid": True,
                     "grid.alpha": .3, "font.size": 10})


def show(fig, name):
    fig.savefig(FIGS / f"{name}.png", dpi=140, bbox_inches="tight")
    plt.show() if INTERACTIVE else plt.close(fig)


d = load()
print(f"{len(d):,} M5 bars   {d['ny'].min()} -> {d['ny'].max()}  (NY time)")

# %% [markdown]
# ## 1. The money chart — is there a W at all?
# Average cumulative EURUSD path across the NY day. The paper predicts the USD
# peaks at each fix, i.e. EURUSD should trough at 08:15 and 11:00 NY.

# %%
d["nym"] = d["ny"].dt.hour * 60 + d["ny"].dt.minute
d["nyd"] = d["ny"].dt.date
d["ret"] = d["close"].diff()

prof = d.groupby("nym")["ret"].mean() / PIP
order = np.r_[np.arange(17 * 60, 24 * 60), np.arange(0, 17 * 60)]
prof = prof.reindex(order).fillna(0)
cum = prof.cumsum()

fig, ax = plt.subplots()
ax.plot(range(len(cum)), cum.values, lw=1.4, color="#2b6cb0")
ax.axhline(0, color="k", lw=.8)
for lbl, hhmm, c in [("Tokyo fix 20:55", 20 * 60 + 55, "#d69e2e"),
                     ("ECB fix 08:15", 8 * 60 + 15, "#e53e3e"),
                     ("London fix 11:00", 11 * 60, "#38a169"),
                     ("rollover 17:00", 17 * 60, "#718096")]:
    pos = list(order).index(hhmm)
    ax.axvline(pos, color=c, ls="--", lw=1.2)
    ax.text(pos + 4, ax.get_ylim()[1] * .92, lbl, color=c, fontsize=8, rotation=90,
            va="top")
ticks = range(0, len(order), 120)
ax.set_xticks(list(ticks))
ax.set_xticklabels([f"{order[t]//60:02d}:{order[t]%60:02d}" for t in ticks])
ax.set_xlabel("New York time (day starts at 17:00 rollover)")
ax.set_ylabel("cumulative mean EURUSD move, pips")
ax.set_title("Average intraday EURUSD path, 2021-2026 — the paper predicts "
             "troughs at the ECB and London fixes")
show(fig, "01_intraday_path")

# %% [markdown]
# ## 2. Per-year gross, split before pooling

# %%
ecb = build_legs(d, (2, 0), (8, 15), (17, 0))
lon = build_legs(d, (2, 0), (11, 0), (17, 0))

fig, ax = plt.subplots()
w = .38
yrs = sorted(ecb["year"].unique())
for i, (name, legs, c) in enumerate([("ECB fix", ecb, "#e53e3e"),
                                     ("London fix", lon, "#38a169")]):
    m = [legs.loc[legs.year == y, "gross"].mean() / PIP for y in yrs]
    ax.bar(np.arange(len(yrs)) + (i - .5) * w, m, w, label=name, color=c, alpha=.85)
ax.axhline(0, color="k", lw=.8)
ax.axhline(6.0, color="#2b6cb0", ls=":", lw=1.5,
           label="paper's gross claim (~6 pips/day)")
ax.set_xticks(range(len(yrs)))
ax.set_xticklabels([int(y) for y in yrs])
ax.set_ylabel("mean gross, pips/day")
ax.set_title("Gross combined return by year — signs alternate, no year significant")
ax.legend()
show(fig, "02_by_year")

# %% [markdown]
# ## 3. Cost reality — the spread you actually pay, by hour

# %%
d["nyh"] = d["ny"].dt.hour
g = d.groupby("nyh")["spread"].agg(["mean", "median",
                                    lambda s: s.quantile(.9)]) / 10  # pts -> pips
g.columns = ["mean", "median", "p90"]

fig, ax = plt.subplots()
ax.plot(g.index, g["mean"], "o-", label="mean", color="#e53e3e")
ax.plot(g.index, g["median"], "s-", label="median", color="#2b6cb0")
ax.plot(g.index, g["p90"], "^-", label="p90", color="#d69e2e")
ax.axvline(17, color="#718096", ls="--", lw=1.5)
ax.text(17.2, ax.get_ylim()[1] * .8, "rollover / paper's exit", fontsize=8,
        color="#718096")
ax.set_xlabel("New York hour")
ax.set_ylabel("EURUSD spread, pips")
ax.set_title("Median hides the cost — the 17:00 exit is the worst minute of the day")
ax.legend()
show(fig, "03_spread_by_hour")

# %% [markdown]
# ## 4. Equity curves, gross vs executable

# %%
fig, ax = plt.subplots()
for name, legs, c in [("ECB fix", ecb, "#e53e3e"), ("London fix", lon, "#38a169")]:
    x = pd.to_datetime(pd.Series(legs.index, index=legs.index))
    ax.plot(x, (legs["gross"] / PIP).cumsum(), color=c, lw=1.3, label=f"{name} gross")
    ax.plot(x, (legs["exec"] / PIP).cumsum(), color=c, lw=1.1, ls="--", alpha=.7,
            label=f"{name} net (bid/ask)")
ax.axhline(0, color="k", lw=.8)
ax.set_ylabel("cumulative pips")
ax.set_title("Cumulative return — gross is flat, net bleeds the spread")
ax.legend(fontsize=8)
show(fig, "04_equity")

# %% [markdown]
# ## 5. The conditional claim, as a scatter
# Paper: the last hour before the fix should negatively predict the next window.

# %%
from fixstudy import boundary_bars                            # noqa: E402

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
for ax, (label, tfix, tend) in zip(
        axes, [("ECB fix 08:15", (8, 15), (17, 0)),
               ("London fix 11:00", (11, 0), (17, 0))]):
    f = boundary_bars(d, *tfix)
    p = boundary_bars(d, tfix[0] - 1, tfix[1])
    e = boundary_bars(d, *tend)
    idx = f.index.intersection(p.index).intersection(e.index)
    x = (f.loc[idx, "open"] - p.loc[idx, "open"]) / PIP
    y = (e.loc[idx, "open"] - f.loc[idx, "open"]) / PIP
    m = x.notna() & y.notna()
    x, y = x[m], y[m]
    b, a = np.polyfit(x, y, 1)
    r = np.corrcoef(x, y)[0, 1]
    ax.scatter(x, y, s=6, alpha=.28, color="#2b6cb0")
    xs = np.linspace(x.min(), x.max(), 50)
    ax.plot(xs, a + b * xs, color="#e53e3e", lw=2)
    ax.axhline(0, color="k", lw=.6); ax.axvline(0, color="k", lw=.6)
    ax.set_xlabel("last hour before fix, pips")
    ax.set_ylabel("next window, pips")
    ax.set_title(f"{label}\nbeta={b:+.3f}  corr={r:+.4f}  (n={len(x)})")
fig.suptitle("Conditional reversal: right sign, no magnitude", y=1.02)
show(fig, "05_conditional")

# %% [markdown]
# ## 6. Placebo — shift the fix anchor and see if anything changes

# %%
rows = []
for name, t0, tfix, t2 in [("ECB", (2, 0), (8, 15), (17, 0)),
                           ("London", (2, 0), (11, 0), (17, 0))]:
    for s in range(-3, 4):
        h = tfix[0] + s
        if not 0 <= h <= 23:
            continue
        g_ = build_legs(d, t0, (h, tfix[1]), t2)["gross"]
        rows.append({"fix": name, "shift": s, "pips": g_.mean() / PIP,
                     "t": tstat(g_), "real": s == 0})
pl = pd.DataFrame(rows)

fig, ax = plt.subplots()
for name, c in [("ECB", "#e53e3e"), ("London", "#38a169")]:
    sub = pl[pl.fix == name]
    ax.plot(sub["shift"], sub["pips"], "o-", color=c, label=name)
    r = sub[sub.real]
    ax.scatter(r["shift"], r["pips"], s=160, facecolors="none", edgecolors=c, lw=2.2)
ax.axhline(0, color="k", lw=.8)
ax.set_xlabel("hours the fix anchor is shifted (0 = the real fix, circled)")
ax.set_ylabel("mean gross combined, pips/day")
ax.set_title("Placebo — the true fix minute is not special")
ax.legend()
show(fig, "06_placebo")

print(pl.round(3).to_string(index=False))
print(f"\nfigures -> {FIGS}")
