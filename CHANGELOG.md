# Changelog

All notable changes. Dates are UTC.

## Unreleased (v2 branch)

- **Pair check.** Gold and silver side by side: a see-saw tipped by the gap between the two P(long) readings, both leans on one -1 to +1 scale, the gold/silver price ratio over 180 daily closes with its percentile, and a one-line read. Positioning only, never a ratio forecast.
- **Crowd check.** Per metal: how much of the vote the biggest wallets hold, the number of equal voters it is worth, how many wallets must close to change the call, and four plain soft-spot flags that make a four-step jelly meter (STURDY, SOLID, WOBBLY, JELLY). The sweep now stores each voter's side, weight and notional so this is exact.
- **Flip alerts.** Opt-in and free on a static site: an Atom feed per metal (and one for both) plus `data/alerts.json`, written by the sweep, and a browser-notification switch that polls the JSON every five minutes while the page is open. A flip only pings when the 95% interval clears 0.50; weak flips, flips into NEUTRAL and flips inside a 3-hour cooldown are logged, not pushed.
- **Long vs short and the last hour.** Per metal: a two-sided bar of wallets and of USD notional (shorts left, longs right), and a last-hour view built from a short log of who held what (`pos_log` in `data/cohort.json`): opened / added / trimmed / closed / flipped with wallet short-ids, USD size and time seen, plus a one-line summary. Aggregates reuse `flow.flow_step`, so they match the Flows tab. Resolution is the sweep interval (about 30 minutes).
- **Scalp corner.** A short-term lean per metal (SCALP LONG, SCALP SHORT or SIT OUT) with a confidence word and up to three plain reasons, from last-hour wallet flow, the 1h price move and funding. Labelled short-term, not advice and not the main signal; weights are not fitted and no hit rate is claimed.
- `python -m app.enrich` adds the v2 readings to an existing `signal.json` offline.

## v1.0.0 (2026-11-25)

First release, ported from [hyperliquid-btc-signal](https://github.com/PrafullJ0shi/hyperliquid-btc-signal) with the same pipeline and formula.

- **Markets.** `xyz:GOLD` and `xyz:SILVER` on the trade[XYZ] HIP-3 builder dex, checked with `perpDexs` and `metaAndAssetCtxs`. Every other builder dex's GOLD/SILVER is delisted; `PAXG` is shown as a labelled reference only.
- **Signal.** Weighted P(long), 95% bootstrap interval, Beta headcount interval and LONG / SHORT / NEUTRAL verdict for each metal, side by side. Equity is the validator-dex account plus the xyz account, because builder dexes keep separate margin.
- **Flows.** Past-window flow box (1h to 1w), top versus worst-performing cohort, whale tape, liquidations seen in tracked fills, and the open-interest proxy. Whale bars scaled to USD 250k for the smaller metal books.
- **Backtest.** Signal rebuilt from every cohort wallet's metal position history since listing (userFunding), daily and hourly bars, 30d / 90d / hourly-max / since-listing windows with out-of-sample cuts, regime splits, long-only and short-only legs, threshold grid with a tune/test split, fees and funding, and a write-up in [research/backtest](research/backtest).
- **Site.** New cartoon-foundry design (see [DESIGN.md](DESIGN.md)): molten goo wordmark, blob panels, two mascots, crisp SVG charts.
- **Workflow.** Ready-to-paste cron workflow in [docs/github-workflow-sweep.yml](docs/github-workflow-sweep.yml).
