# Changelog

All notable changes. Dates are UTC.

## v1.0.0 (2026-11-25)

First release, ported from [hyperliquid-btc-signal](https://github.com/PrafullJ0shi/hyperliquid-btc-signal) with the same pipeline and formula.

- **Markets.** `xyz:GOLD` and `xyz:SILVER` on the trade[XYZ] HIP-3 builder dex, checked with `perpDexs` and `metaAndAssetCtxs`. Every other builder dex's GOLD/SILVER is delisted; `PAXG` is shown as a labelled reference only.
- **Signal.** Weighted P(long), 95% bootstrap interval, Beta headcount interval and LONG / SHORT / NEUTRAL verdict for each metal, side by side. Equity is the validator-dex account plus the xyz account, because builder dexes keep separate margin.
- **Flows.** Past-window flow box (1h to 1w), top versus worst-performing cohort, whale tape, liquidations seen in tracked fills, and the open-interest proxy. Whale bars scaled to USD 250k for the smaller metal books.
- **Backtest.** Signal rebuilt from every cohort wallet's metal position history since listing (userFunding), daily and hourly bars, 30d / 90d / hourly-max / since-listing windows with out-of-sample cuts, regime splits, long-only and short-only legs, threshold grid with a tune/test split, fees and funding, and a write-up in [research/backtest](research/backtest).
- **Site.** New cartoon-foundry design (see [DESIGN.md](DESIGN.md)): molten goo wordmark, blob panels, two mascots, crisp SVG charts.
- **Workflow.** Ready-to-paste cron workflow in [docs/github-workflow-sweep.yml](docs/github-workflow-sweep.yml).
