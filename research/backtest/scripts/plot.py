"""Figures for the backtest write-up (PNG, dark theme to match the site)."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
BT = ROOT / "research" / "backtest"
FIG = BT / "figures"
SITE = ROOT / "site" / "backtest"

BG, PANEL, GRID, TXT, SUB = "#140D08", "#1E140D", "#3A2819", "#EEF1F4", "#8A9299"
C = {"signal_gold": "#F5B700", "signal_silver": "#EEF1F4", "hold": "#6FA8DC", "short": "#FF6B6B",
     "long_only": "#7BD88F", "short_only": "#C77DFF", "fade": "#8A9299"}
NAMES = {"signal": "Follow the signal", "long_only": "Long-only", "short_only": "Short-only", "fade": "Fade the signal",
         "hold": "Buy and hold", "short": "Always short"}

plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": PANEL, "axes.edgecolor": GRID, "axes.labelcolor": TXT,
                     "xtick.color": SUB, "ytick.color": SUB, "text.color": TXT, "grid.color": GRID, "font.size": 10,
                     "axes.grid": True, "grid.linewidth": .6, "legend.frameon": False, "savefig.facecolor": BG})


def dts(ts):
    return [dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc) for t in ts]


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    B = json.loads((SITE / "backtest.json").read_text())
    for metal in ("gold", "silver"):
        M = B["metals"][metal]
        ser, summ = M["series"]["daily"], M["summary"]
        fig, ax = plt.subplots(figsize=(11, 4.6), dpi=130)
        x = dts(ser["t"])
        for k in ("hold", "short", "long_only", "short_only", "fade", "signal"):
            col = C[f"signal_{metal}"] if k == "signal" else C[k]
            ax.plot(x, [v * 100 for v in ser["curves"][k]], color=col, lw=2.6 if k == "signal" else 1.3,
                    ls="--" if k == "fade" else "-", label=NAMES[k])
        ax.axhline(0, color=SUB, lw=.8)
        w30 = summ["windows"]["oos_d"]["end_ms"]
        ax.axvspan(dts([w30])[0], x[-1], color="#F5B700", alpha=.08, lw=0)
        ax.text(dts([w30])[0], ax.get_ylim()[1], "  in-sample: cohort ranked on this month", va="top", color=SUB, fontsize=8)
        ax.set_ylabel("Cumulative return, %")
        ax.set_title(f"Fig. B1 ({metal}). Equity curves since listing, daily bars, after fees and funding", loc="left", color=TXT)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        ax.legend(ncol=3, fontsize=8, loc="upper left")
        fig.tight_layout()
        fig.savefig(FIG / f"equity_{metal}.png")
        plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(11, 5.6), dpi=130, sharex=False)
    for ax, metal in zip(axes, ("gold", "silver")):
        ser = B["metals"][metal]["series"]["daily"]
        x = dts(ser["t"])
        ax.plot(x, ser["p"], color=C[f"signal_{metal}"], lw=1.2)
        for y in (.4, .6):
            ax.axhline(y, color=SUB, ls="--", lw=.8)
        ax.set_ylim(0, 1)
        ax.set_ylabel(f"{metal} P(long)")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    axes[0].set_title("Fig. B2. Reconstructed daily P(long) with the 0.40 / 0.60 thresholds", loc="left")
    fig.tight_layout()
    fig.savefig(FIG / "p_long.png")
    plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(11, 5), dpi=130)
    for ax, metal in zip(axes, ("gold", "silver")):
        ser = B["metals"][metal]["series"]["daily"]
        x = dts(ser["t"])
        ax.fill_between(x, ser["voters_long"], color="#7BD88F", alpha=.8, step="mid", lw=0, label="wallets long")
        ax.fill_between(x, [-v for v in ser["voters_short"]], color="#FF6B6B", alpha=.8, step="mid", lw=0, label="wallets short")
        ax.axhline(0, color=SUB, lw=.8)
        ax.set_ylabel(metal)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        ax.legend(fontsize=8, loc="upper left")
    axes[0].set_title("Fig. B3. Cohort wallets holding each metal, by day (longs up, shorts down)", loc="left")
    fig.tight_layout()
    fig.savefig(FIG / "voters.png")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), dpi=130)
    for ax, metal in zip(axes, ("gold", "silver")):
        g = B["metals"][metal]["summary"]["grids"]["daily"]["rows"]
        labels = [f"{r['long']:.2f}/{r['short']:.2f}" for r in g]
        xs = range(len(g))
        ax.bar([i - .2 for i in xs], [r["tune"]["total_return"] * 100 for r in g], .4, color="#FFE08A", label="tune half")
        ax.bar([i + .2 for i in xs], [r["test"]["total_return"] * 100 for r in g], .4, color="#C0C6CC", label="test half")
        ax.set_xticks(list(xs), labels, fontsize=8)
        ax.axhline(0, color=SUB, lw=.8)
        ax.set_title(f"{metal}: return by threshold pair", loc="left", fontsize=10)
        ax.legend(fontsize=8)
    fig.suptitle("Fig. B4. Threshold sensitivity on daily bars, tune half vs test half (both before the ranking month)", x=.01, ha="left")
    fig.tight_layout()
    fig.savefig(FIG / "threshold_grid.png")
    plt.close(fig)
    print("figures written to", FIG)


if __name__ == "__main__":
    sys.exit(main())
