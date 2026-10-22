#!/usr/bin/env python3
"""Build the figures for studies 02 and 03 from their saved results.

Study 01 writes its own figures (01-fx-fixing-reversal/fixstudy_cells.py).
Study 02's numbers are parsed from its console logs; study 03 reads its CSVs.
Neither needs the broker export.

    python figures/make_figures.py
"""
from __future__ import annotations
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "figures"
S2 = ROOT / "02-overnight-intraday-reversal" / "results" / "logs"
S3 = ROOT / "03-displacement-and-intraday-momentum" / "results"

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, AQUA, YELLOW, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#a3a29c"
IDX = ["US100.cash", "US500.cash", "US30.cash", "GER40.cash"]
SHORT = {s: s.replace(".cash", "") for s in IDX}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "font.size": 10, "axes.titlesize": 10.5, "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "legend.frameon": False,
})

ROW = re.compile(r"WR=\s*([\d.]+)%.*?base(?:lineWR)?=\s*([\d.]+)%.*?edge=\s*([+-]?[\d.]+)")


def parse_sections(path):
    """{section header: [(label, WR, baseline WR, edge), ...]} from a study-02 log."""
    out, cur = {}, None
    for line in path.read_text().splitlines():
        h = re.match(r"=+ (.+?) +=+", line.strip())
        if h:
            cur = h.group(1).split("  ")[0].strip()
            out[cur] = []
            continue
        m = ROW.search(line)
        if cur and m:
            label = line.split(" n=")[0].strip()
            out[cur].append((label, float(m.group(1)), float(m.group(2)), float(m.group(3))))
    return out


def fig_geometry():
    """Win rate is bought with geometry: WR vs the driftless baseline it pays for free."""
    secs = parse_sections(S2 / "gapfill_research.log")
    fig, ax = plt.subplots(figsize=(6.6, 5.4))
    cols = dict(zip(IDX, [BLUE, ORANGE, AQUA, YELLOW]))
    for s in IDX:
        rows = secs[s]
        ax.scatter([r[2] for r in rows], [r[1] for r in rows], s=42, color=cols[s],
                   label=SHORT[s], zorder=3, edgecolor=SURFACE, linewidth=1.5)
    lo, hi = 43, 66
    ax.plot([lo, hi], [lo, hi], color=INK, lw=1.2, zorder=2)
    ax.text(63.5, 64.6, "edge = 0", rotation=38, color=INK2, fontsize=9)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("break-even win rate 1/(1+payoff) (%)")
    ax.set_ylabel("realised win rate (%)")
    ax.set_title("Gap-fade brackets: high win rates are bought with geometry,\nnot earned (36 target × stop × index cells)")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG / "02_winrate_vs_geometry.png", dpi=180)
    plt.close(fig)


def fig_continuation_decay():
    secs = parse_sections(S2 / "continuation_check.log")
    hold = ["1h hold", "2h hold", "3h hold", "full session"]
    sets = [("POOLED gap-DOWN only (short)", BLUE, "gap down → short"),
            ("POOLED gap-UP only (long)", ORANGE, "gap up → long"),
            ("POOLED both directions", GRAY, "both directions")]
    fig, ax = plt.subplots(figsize=(7, 4))
    x = np.arange(len(hold))
    for key, c, lab in sets:
        e = [next(r[3] for r in secs[h] if r[0] == key) for h in hold]
        ax.plot(x, e, color=c, lw=2, marker="o", ms=7, label=lab)
    ax.axhline(0, color=INK2, lw=0.9)
    ax.set_xticks(x, hold)
    ax.set_ylabel("edge over break-even win rate (pts)")
    ax.set_title("The one live lead is continuation, and it decays within the first hour\n(4 indices pooled, gaps above the 75th percentile, 2021–2024)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG / "02_gap_continuation_decay.png", dpi=180)
    plt.close(fig)


def fig_dev_vs_holdout():
    d = pd.read_csv(S3 / "stage4_sweep.csv")
    fig, ax = plt.subplots(figsize=(6.6, 5.4))
    sig = d.dev_t.abs() >= 1.96
    ax.scatter(d.dev_t[~sig], d.hold_t[~sig], s=22, color=GRAY, alpha=0.8, label="dev |t| < 1.96", zorder=2)
    ax.scatter(d.dev_t[sig], d.hold_t[sig], s=34, color=BLUE, label=f"dev |t| ≥ 1.96 (n = {sig.sum()})", zorder=3,
               edgecolor=SURFACE, linewidth=1.2)
    lim = max(d.dev_t.abs().max(), d.hold_t.abs().max()) * 1.08
    ax.plot([-lim, lim], [-lim, lim], color=INK, lw=1, ls="--", label="holdout = dev")
    for v in (-1.96, 1.96):
        ax.axhline(v, color=INK2, lw=0.8, ls=":")
        ax.axvline(v, color=INK2, lw=0.8, ls=":")
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_xlabel("development-sample t-stat (gross)")
    ax.set_ylabel("2025–26 holdout t-stat (gross)")
    keep = (np.sign(d.dev_t[sig]) == np.sign(d.hold_t[sig])) & (d.hold_t[sig].abs() >= 1.96)
    ax.set_title(f"Dev-significant specs do not survive the holdout\n({keep.sum()} of {sig.sum()} keep sign and significance)")
    ax.legend(loc="upper left", fontsize=8.5)
    fig.tight_layout()
    fig.savefig(FIG / "03_dev_vs_holdout.png", dpi=180)
    plt.close(fig)


def fig_costs():
    d = pd.read_csv(S3 / "stage6_costed.csv")
    lab = [f"{r.label}\n{r.symbol}" for r in d.itertuples()]
    y = np.arange(len(d))[::-1]
    fig, ax = plt.subplots(figsize=(8, 0.62 * len(d) + 1.6))
    ax.barh(y + 0.19, d.gross_atr, 0.36, color=GRAY, label="gross", zorder=2)
    ax.barh(y - 0.19, d.net_atr, 0.36, color=BLUE, label="net of per-event spread", zorder=2)
    ax.axvline(0, color=INK2, lw=0.9)
    ax.set_yticks(y, lab, fontsize=8.5)
    ax.set_xlabel("mean return per event (ATR)")
    ax.grid(axis="y", visible=False)
    ax.set_title("Charging each event its own spread turns every survivor negative or marginal")
    ax.legend(loc="upper center", ncol=2, bbox_to_anchor=(0.5, -0.12))
    fig.tight_layout()
    fig.savefig(FIG / "03_gross_vs_net.png", dpi=180)
    plt.close(fig)


def fig_gao():
    d = pd.read_csv(S3 / "stage4_gao.csv")
    sy = [s.replace(".cash", "") for s in d.symbol]
    x = np.arange(len(d))
    fig, ax = plt.subplots(figsize=(7.4, 4))
    ax.bar(x - 0.19, d.t_r1, 0.36, color=BLUE, label=r"$r_{1}$: first half-hour", zorder=2)
    ax.bar(x + 0.19, d.t_rnm1, 0.36, color=ORANGE, label=r"$r_{n-1}$: second-to-last half-hour", zorder=2)
    for v in (-1.96, 1.96):
        ax.axhline(v, color=INK2, lw=0.8, ls=":")
    ax.axhline(0, color=INK2, lw=0.9)
    ax.set_xticks(x, sy)
    ax.set_ylabel("OLS t-stat of slope (univariate)")
    ax.set_title(r"Gao et al. (2018): $r_{n}=\alpha+\beta_1 r_1+\beta_2 r_{n-1}+\varepsilon$ on CFDs"
                 "\n" r"$r_1$ is never positive; $r_{n-1}$ is, on US indices, but flips sign in the 2025–26 holdout")
    ax.legend(fontsize=8.5, loc="upper right")
    fig.tight_layout()
    fig.savefig(FIG / "03_gao_replication.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    FIG.mkdir(exist_ok=True)
    fig_geometry()
    fig_continuation_decay()
    fig_dev_vs_holdout()
    fig_costs()
    fig_gao()
    print("wrote", sorted(p.name for p in FIG.glob("*.png")))
