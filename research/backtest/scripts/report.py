"""Write the backtest write-up, the site's notes.json and the README backtest section from summary.json.

Every number in the prose comes from research/backtest/data/summary.json, so re-running the pipeline
re-writes the text. The judgement calls (what counts as an edge) are fixed rules stated in the text.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BT = ROOT / "research" / "backtest"
S = json.loads((BT / "data" / "summary.json").read_text())
NAMES = {"signal": "Follow the signal", "long_only": "Long-only", "short_only": "Short-only", "fade": "Fade the signal",
         "hold": "Buy and hold", "short": "Always short"}
WIN = {"listing": "Since listing (daily bars)", "oos_d": "Since listing, before ranking month (daily, out-of-sample)",
       "max_h": "Hourly max (all 1h candles)", "oos_h": "Hourly, before ranking month (out-of-sample)",
       "90d": "Last 90 days (hourly)", "30d": "Last 30 days (hourly, in-sample)"}
INS = {"yes": "in-sample", "partial": "last 30 days in-sample", "no": "out-of-sample"}
METAL = {"gold": "Gold", "silver": "Silver"}


def pct(x, d=1, sign=True):
    if x is None:
        return "–"
    return f"{x * 100:+.{d}f}%" if sign else f"{x * 100:.{d}f}%"


def num(x, d=2):
    return "–" if x is None else f"{x:.{d}f}"


def bp(x):
    return "–" if x is None else f"{x * 1e4:.2f} bp"


def day(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%d %b %Y")


def verdict_lines():
    lines, head = [], []
    for k, m in S["metals"].items():
        o = m["windows"]["oos_d"]["strategies"]
        L = m["windows"]["listing"]["strategies"]
        mv = m["windows"]["oos_d"]["metal_return"]
        best_base = max(o["hold"]["total_return"], o["short"]["total_return"])
        base_name = "always short" if o["short"]["total_return"] >= o["hold"]["total_return"] else "buy and hold"
        edge = o["signal"]["total_return"] - best_base
        g = m["grids"]["daily"]
        best = next(r for r in g["rows"] if [r["long"], r["short"]] == g["best_on_tune"])
        live = next(r for r in g["rows"] if r["live"])
        mix = m["signal_mix"]
        beat = edge > 0 and (o["signal"]["sharpe_like"] or 0) > max(o["hold"]["sharpe_like"] or -9, o["short"]["sharpe_like"] or -9)
        lines.append(
            f"<b>{METAL[k]}, out-of-sample ({day(m['windows']['oos_d']['start_ms'])} to {day(m['windows']['oos_d']['end_ms'])}):</b> "
            f"the signal made {pct(o['signal']['total_return'])} (Sharpe-like {num(o['signal']['sharpe_like'])}, max drawdown {pct(o['signal']['max_drawdown'])}) "
            f"while {k} moved {pct(mv)}. Buy and hold made {pct(o['hold']['total_return'])}, always short {pct(o['short']['total_return'])}. "
            f"Against the better baseline ({base_name}) that is {pct(edge)}: "
            + ("a real gap, but on one market path." if beat else "no edge over simply picking a side.")
        )
        lines.append(
            f"<b>{METAL[k]}, why:</b> the cohort was short {pct(mix['short'], 0, False)} of days, long {pct(mix['long'], 0, False)}, flat {pct(mix['flat'], 0, False)}. "
            f"In a falling market a mostly-short reading earns most of what always-short earns; the question is whether its long and flat days helped. "
            f"Short-only legs made {pct(o['short_only']['total_return'])}, long-only legs {pct(o['long_only']['total_return'])}, and fading the signal {pct(o['fade']['total_return'])}."
        )
        lines.append(
            f"<b>{METAL[k]}, thresholds:</b> the best pair on the tune half was {best['long']:.2f} / {best['short']:.2f}; on the test half it made {pct(best['test']['total_return'])}, "
            f"against {pct(live['test']['total_return'])} for the live 0.60 / 0.40. Five pairs, no winner that survives the split cleanly, so the live thresholds stay."
        )
        head.append(f"{METAL[k]}: signal {pct(L['signal']['total_return'])} vs hold {pct(L['hold']['total_return'])} and always short {pct(L['short']['total_return'])} since listing")
    lines.append("<b>Biases that flatter these numbers:</b> the cohort, its month PnL and its equity are today's, applied to every past day (survivorship). "
                 "Wallets that blew up before today never vote. The last 30 days are in-sample by construction, which is why the out-of-sample cut stops before them.")
    lines.append("<b>Biases that hurt them:</b> the backfill can only refresh once a day on yesterday's average position, while the live site refreshes every 30 minutes. "
                 "Positions opened and closed between two funding hours never show up.")
    lines.append("<b>Verdict:</b> treat the call as a positioning read, not a trading system. The honest test is the forward one: stored live snapshots, same rules, no hindsight (v2, P1).")
    return "; ".join(head) + ".", lines


def strat_table(m, wn):
    w = m["windows"][wn]
    out = ["| Strategy | Return | Max DD | Sharpe-like | Hit rate | Avg per bar in market | In market | Trades | Fees | Funding |",
           "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for k, lab in NAMES.items():
        s = w["strategies"][k]
        b = "**" if k == "signal" else ""
        out.append(f"| {b}{lab}{b} | {b}{pct(s['total_return'])}{b} | {pct(s['max_drawdown'])} | {num(s['sharpe_like'])} | {pct(s['hit_rate'], 1, False)} | "
                   f"{bp(s['avg_return_per_bar_in_market'])} | "
                   f"{pct(s['time_in_market'], 0, False)} | {s['trades']} | {pct(s['fees'], 2)} | {pct(s['funding'], 2)} |")
    return "\n".join(out)


def windows_table(m):
    out = ["| Window | Span | Bars | Sample | Metal | Signal | Hold | Always short | Signal Sharpe-like |",
           "| :--- | :--- | ---: | :--- | ---: | ---: | ---: | ---: | ---: |"]
    for wn, lab in WIN.items():
        w = m["windows"][wn]
        st = w["strategies"]
        out.append(f"| {lab} | {day(w['start_ms'])} to {day(w['end_ms'])} | {w['bars']} | {INS[w['in_sample']]} | {pct(w['metal_return'])} | "
                   f"**{pct(st['signal']['total_return'])}** | {pct(st['hold']['total_return'])} | {pct(st['short']['total_return'])} | {num(st['signal']['sharpe_like'])} |")
    return "\n".join(out)


def regime_table(m, wn):
    w = m["windows"][wn]
    out = ["| Regime | Days | Metal | Signal | Signal hit rate | Long / short calls | Hold | Always short |",
           "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for g in ("up", "down", "sideways"):
        r = w["regimes"][g]
        if not r:
            continue
        out.append(f"| {g} | {r['bars']} | {pct(r['metal_move'])} | {pct(r['signal']['return'])} | {pct(r['signal']['hit_rate'], 0, False)} | "
                   f"{pct(r['share_long'], 0, False)} / {pct(r['share_short'], 0, False)} | {pct(r['hold']['return'])} | {pct(r['short']['return'])} |")
    return "\n".join(out)


def grid_table(m, gname):
    g = m["grids"][gname]
    out = [f"Tune {day(g['tune_start_ms'])} to {day(g['split_ms'])}, test {day(g['split_ms'])} to {day(g['end_ms'])}. Best on tune: {g['best_on_tune'][0]:.2f} / {g['best_on_tune'][1]:.2f}.", "",
           "| Long / short at | Tune return | Tune Sharpe-like | Test return | Test Sharpe-like | Full return | In market |",
           "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in g["rows"]:
        tag = " (live)" if r["live"] else ""
        tag += " ★" if [r["long"], r["short"]] == g["best_on_tune"] else ""
        out.append(f"| {r['long']:.2f} / {r['short']:.2f}{tag} | {pct(r['tune']['total_return'])} | {num(r['tune']['sharpe_like'])} | {pct(r['test']['total_return'])} | "
                   f"{num(r['test']['sharpe_like'])} | {pct(r['full']['total_return'])} | {pct(r['full']['time_in_market'], 0, False)} |")
    return "\n".join(out)


HZ_WINS = [("hourly", "max_h", "Hourly bars, all (1 May to now)"), ("hourly", "oos_h", "Hourly, before ranking month (out-of-sample)"),
           ("hourly", "90d", "Hourly, last 90 days"), ("hourly", "30d", "Hourly, last 30 days (in-sample)"),
           ("daily", "listing", "Daily bars, since listing"), ("daily", "oos_d", "Daily, since listing to before ranking month (out-of-sample)")]


def bps(x):
    return "–" if x is None else f"{x * 1e4:+.1f} bp"


def hz_table(m, g, wn):
    H = m["horizons"][g][wn]
    out = ["| Horizon | Trades | Hit rate | Avg gross | Avg net | Always-short avg net | Always-long avg net | Total return | Max DD | Long / short calls | Verdict |",
           "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |"]
    for lab, r in H.items():
        s_ = r["signal"]
        if not s_["trades"]:
            out.append(f"| {lab} | 0 | – | – | – | – | – | – | – | – | never in the market |")
            continue
        verdict = "loses money" if s_["avg_net"] < 0 else ("beats both baselines" if s_["avg_net"] > max(r["short"].get("avg_net") or -1, r["long"].get("avg_net") or -1) else "makes money, a baseline did better")
        out.append(f"| {lab} | {s_['trades']} | {pct(s_['hit_rate'], 0, False)} | {bps(s_['avg_gross'])} | **{bps(s_['avg_net'])}** | {bps(r['short'].get('avg_net'))} | "
                   f"{bps(r['long'].get('avg_net'))} | {pct(s_['total_return'])} | {pct(s_['max_drawdown'])} | {s_['n_long']} / {s_['n_short']} | {verdict} |")
    return "\n".join(out)


def hz_text(m, k):
    out = []
    for g, wn in (("hourly", "max_h"), ("daily", "listing")):
        H = m["horizons"][g][wn]
        los = [l for l, r in H.items() if r["signal"]["trades"] and r["signal"]["avg_net"] < 0]
        win = [l for l, r in H.items() if r["signal"]["trades"] and r["signal"]["avg_net"] >= 0]
        out.append(f"{METAL[k]}, {g} bars: loses money after costs at {', '.join(los) or 'no horizon'}; positive at {', '.join(win) or 'no horizon'}")
    return "; ".join(out) + "."


def reach_table():
    I = S["inputs"]
    out = ["| Input | From (UTC) | To (UTC) | Notes |", "| :--- | :--- | :--- | :--- |"]
    for coin, c in I["market"].items():
        out.append(f"| `{coin}` 1h candles | {c['candles_1h']['from']} | {c['candles_1h']['to']} | {c['candles_1h']['n']} candles; the API keeps only the latest 5,000 |")
        out.append(f"| `{coin}` 1d candles | {c['candles_1d']['from']} | {c['candles_1d']['to']} | {c['candles_1d']['n']} candles, since listing |")
        out.append(f"| `{coin}` funding | {c['funding']['from']} | {c['funding']['to']} | {c['funding']['n']} hourly rates |")
    w = I["wallets"]
    h = w["history"]
    out.append(f"| Wallet metal positions | {w['history_from']} | {w['history_to']} | `userFunding`: {h.get('complete', 0)} wallets read in full. Daily figures to {w['daily_rows_until'][:10]}, then one funding hour (12:00 UTC) per day. |")
    out.append(f"| Wallets assumed flat | – | – | {h.get('assumed_flat', 0)} wallets with no xyz account and no metal position today (not read) |")
    if h.get("missing") or h.get("incomplete"):
        out.append(f"| Wallets not read | – | – | {h.get('missing', 0) + h.get('incomplete', 0)} wallets with an xyz account left out (no vote) |")
    out.append(f"| Cohort, month PnL, equity | {w['cohort_built_at_utc']} | same | today only, applied to every past day |")
    out.append("| Wallet fills | – | – | not used: `userFillsByTime` keeps the 10,000 latest fills, two to four days for the busiest wallets |")
    return "\n".join(out)


def hz_readme():
    out = ["| Metal | Horizon | Trades | Hit rate | Avg net per trade | Always-short avg net | Total return | Max DD |", "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for k in ("gold", "silver"):
        for lab, r in S["metals"][k]["horizons"]["hourly"]["max_h"].items():
            s_ = r["signal"]
            out.append(f"| {METAL[k]} | {lab} | {s_['trades']} | {pct(s_['hit_rate'], 0, False)} | **{bps(s_['avg_net'])}** | {bps(r['short'].get('avg_net'))} | {pct(s_['total_return'])} | {pct(s_['max_drawdown'])} |")
    return "\n".join(out)


def main():
    headline, lines = verdict_lines()
    notes = {"headline": "Rebuilt from every cohort wallet's metal positions since listing. " + headline + " Read the out-of-sample row before getting excited.",
             "verdict": lines}
    (ROOT / "site" / "backtest" / "notes.json").write_text(json.dumps(notes, indent=1))
    plain = [re.sub(r"</?b>", "**", x) for x in lines]
    g, s_ = S["metals"]["gold"], S["metals"]["silver"]
    md = f"""# Backtest: would following the cohort have paid?

> Not financial advice. A reconstruction with known biases, written down below. Bag holders, read the limits first.

**Short answer.** {headline} The out-of-sample rows are the ones to read.

## Question and rules

Would trading the live call (LONG at P(long) of 0.60 or more, SHORT at 0.40 or less, flat otherwise) have made money on `xyz:GOLD` and `xyz:SILVER` after fees and funding, and does it beat buy-and-hold or always-short? Rules, fixed before any metal result was looked at (all inherited from the BTC project):

- **Cohort and weights.** Exactly the live ones: today's top 500 wallets, today's month PnL and equity, the live weight formula.
- **Information.** For each UTC day D, P(long) is computed from each wallet's position on day D-1. Older history exists only as daily figures, so the backfill refreshes at 00:00 UTC; the live site refreshes every 30 minutes.
- **Trading.** One unit of notional, no leverage, no slippage. Taker fee on every change of position (`xyz:GOLD` 0.09%, `xyz:SILVER` 0.009% in growth mode) and every hour of funding paid or received.
- **Bars.** Daily bars since listing (longest), and hourly bars over the latest 5,000 hourly candles (the API keeps no more). The signal is the same on both; hourly bars only change how returns and drawdowns are measured within the day.
- **Sample marking.** The cohort was ranked on the last 30 days, so those days are **in-sample**. Every window that ends before them is marked out-of-sample.
- **Regimes.** Each bar is labelled by its trailing 7-day log return divided by its own volatility over the same days: up above +0.5, down below -0.5, sideways otherwise. Past prices only.
- **Threshold grid.** Five symmetric pairs from 0.55 / 0.45 to 0.75 / 0.25, chosen in advance. The out-of-sample span is split in time order: the first half tunes, the second half tests.

## How far each input reaches

{reach_table()}

Weight covered: the wallets read hold {pct(g['known_weight_share'], 0, False)} of the cohort's static vote weight (skill times equity). The rest have no xyz account today; a wallet needs xyz margin to hold these markets, so they are counted as flat, which is the same as no vote.

## Gold (`xyz:GOLD`)

Wallets voting per day: median {g['voters']['median']:.0f}, range {g['voters']['min']} to {g['voters']['max']}. Signal mix since listing: long {pct(g['signal_mix']['long'], 0, False)}, short {pct(g['signal_mix']['short'], 0, False)}, flat {pct(g['signal_mix']['flat'], 0, False)}.

**Windows**

{windows_table(g)}

**All strategies, out-of-sample (daily bars)**

{strat_table(g, 'oos_d')}

**All strategies, since listing (daily bars)**

{strat_table(g, 'listing')}

**Regimes, since listing**

{regime_table(g, 'listing')}

**Threshold grid (daily bars)**

{grid_table(g, 'daily')}

![Gold equity curves](figures/equity_gold.png)

## Silver (`xyz:SILVER`)

Wallets voting per day: median {s_['voters']['median']:.0f}, range {s_['voters']['min']} to {s_['voters']['max']}. Signal mix since listing: long {pct(s_['signal_mix']['long'], 0, False)}, short {pct(s_['signal_mix']['short'], 0, False)}, flat {pct(s_['signal_mix']['flat'], 0, False)}.

**Windows**

{windows_table(s_)}

**All strategies, out-of-sample (daily bars)**

{strat_table(s_, 'oos_d')}

**All strategies, since listing (daily bars)**

{strat_table(s_, 'listing')}

**Regimes, since listing**

{regime_table(s_, 'listing')}

**Threshold grid (daily bars)**

{grid_table(s_, 'daily')}

![Silver equity curves](figures/equity_silver.png)

## Holding horizons: is it a short-term or a long-term signal?

Method: every N hours (aligned to the UTC clock; weekly entries to the Unix week, so Thursday 00:00 UTC) the latest call is read and traded for exactly N hours, then closed. One unit of notional, round-trip fee (0.18% gold, 0.018% silver) and funding while held. A trade must finish inside the window. "Hit rate" is the share of trades with the right direction before costs. The always-short and always-long columns use the same schedule, so they show what the horizon itself pays. Hourly candles exist only from 1 May 2026, so 1h, 4h and 12h can only be measured there; daily bars reach back to listing but cannot see anything shorter than a day. The call itself refreshes once a day in this backtest (positions of the day before), so a 1h trade re-reads the same call 24 times a day: that is a test of timing inside the day, not of a faster signal.

![Horizons](figures/horizons.png)

""" + "\n".join(f"### {METAL[k]}\n\n" + "\n\n".join(f"**{lab}**\n\n{hz_table(S['metals'][k], g, wn)}" for g, wn, lab in HZ_WINS) + "\n" for k in ("gold", "silver")) + """
**Reading it.** """ + " ".join(hz_text(S["metals"][k], k) for k in ("gold", "silver")) + """ Where the signal's average net per trade is below zero the horizon loses money; where always-short on the same schedule does better, the call added nothing in a falling market.

## Signal and participation

![Reconstructed P(long)](figures/p_long.png)

![Wallets long and short by day](figures/voters.png)

![Threshold grid](figures/threshold_grid.png)

## Verdict

""" + "\n".join(f"- {x}" for x in plain) + """

## Files

- `data/inputs/` compact inputs (market history, wallets, daily position paths, reach). Committed, so the analysis re-runs offline.
- `data/daily_gold.csv`, `data/daily_silver.csv`: one row per day with P(long), voters, signal, regime, funding and returns.
- `data/hourly_gold.csv`, `data/hourly_silver.csv`: the same signal on hourly bars.
- `data/strategies.csv`, `data/regimes.csv`, `data/threshold_grid.csv`, `data/summary.json`.
- `figures/*.png` (including `horizons.png`).
- `scripts/`: `fetch.py`, `fetch_positions.py`, `prepare.py`, `analyze.py`, `plot.py`, `report.py`, in that order.
"""
    (BT / "README.md").write_text(md)

    # README section.
    rows = []
    for k, m in S["metals"].items():
        for wn in ("oos_d", "listing", "max_h", "90d", "30d"):
            w = m["windows"][wn]
            st = w["strategies"]
            rows.append(f"| {METAL[k]} | {WIN[wn]} | {pct(w['metal_return'])} | **{pct(st['signal']['total_return'])}** | {pct(st['hold']['total_return'])} | "
                        f"{pct(st['short']['total_return'])} | {num(st['signal']['sharpe_like'])} | {pct(st['signal']['max_drawdown'])} | {pct(st['signal']['hit_rate'], 0, False)} |")
    sec = f"""<!-- BT -->
The live call, rebuilt day by day from every cohort wallet's `xyz:GOLD` and `xyz:SILVER` positions since the markets listed (via `userFunding`; fills only reach back a few days for busy wallets). Fees and funding included; the last 30 days are in-sample because the cohort was ranked on them.

| Metal | Window | Metal move | Signal | Buy and hold | Always short | Sharpe-like | Max DD | Hit rate |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

**Holding horizons** (hourly bars, 1 May to now, fees and funding in; full table for every window in the write-up):

{hz_readme()}

![Average net return per trade by holding horizon](research/backtest/figures/horizons.png)

{hz_text(S["metals"]["gold"], "gold")} {hz_text(S["metals"]["silver"], "silver")}

**Honest take.** {plain[0]} {plain[3]} Full write-up with regimes, long-only and short-only legs, the threshold grid and every bias: [research/backtest](research/backtest/README.md). Wagmi only if it holds up forward.

<p align="center"><img src="research/backtest/figures/equity_gold.png" alt="Gold: equity curves of the signal, buy and hold, always short, long-only, short-only and fade since listing" width="49%"> <img src="research/backtest/figures/equity_silver.png" alt="Silver: equity curves of the signal and baselines since listing" width="49%"></p>
<!-- /BT -->"""
    rd = (ROOT / "README.md").read_text()
    if "<!-- /BT -->" in rd:
        rd = re.sub(r"<!-- BT -->.*?<!-- /BT -->", lambda _: sec, rd, flags=re.S)
    else:
        rd = re.sub(r"<!-- BT -->.*?(?=\n## Run it locally)", lambda _: sec + "\n", rd, flags=re.S)
    (ROOT / "README.md").write_text(rd)
    print(headline)


if __name__ == "__main__":
    main()
