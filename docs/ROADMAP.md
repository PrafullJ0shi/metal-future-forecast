# Roadmap: v2

A plan, not a schedule, and not a promise of profit. **P1** first, then **P2**, then **P3**. Some items only make sense after the live sweep has stored enough history; those say so.

## Principles

- The verdict stays a function of the cohort's positions in each metal. New context sits beside it, never on top of it.
- Public data only, documented methods, limits written next to results.
- Fun in the chrome, crisp in the data (see [DESIGN.md](../DESIGN.md)).
- Stay inside 1,200 weight per minute and a 30-minute cron.

## P1: Forward test from live snapshots

The current backtest is rebuilt from daily position history (userFunding), with today's cohort applied to the past. The live sweep stores a clean, timestamped P(long) every 30 minutes. After 60 days of stored snapshots, re-run the same tables (Table 1 to Table 4) on the stored readings only. That is the first test with no survivorship bias. Pre-registered: thresholds 0.60 / 0.40, the same costs, and hourly refresh instead of the daily refresh the backfill is limited to.

## P1: Gold-silver ratio view (built on the v2 branch: Pair check)

Both markets live on the same dex, so the cohort's *relative* tilt (net gold notional minus net silver notional, scaled by equity) is cheap to compute. Show it as a third reading next to the two verdicts, labelled as positioning, not a ratio forecast.

## P2: Wider market set

The xyz dex also lists other commodities. Add a market only if it has a live, non-delisted perp and enough cohort holders (at least 20 voting wallets on most sweeps). PAXG stays reference-only unless the cohort's gold money moves there.

## P2: Fill-depth upgrade for the backtest

Older position history is only served as daily averages, so the backfill can refresh the signal once a day at best, and the 10,000-fill cap rules out rebuilding it from fills. Cache hourly positions and fills on every sweep so the archive grows forward, and the next backtest can run on hourly refreshes.

## P2: Cohort turnover chart

How many of today's top 500 were in last week's top 500? A falling overlap means the "smart money" label is mostly luck. Store the member list hash per day and plot overlap.

## P3: Sentiment context

A file hook for public sentiment about gold and silver (same contract as the BTC project's reserved X panel). Context only; it never changes the verdict.

## P3: Alerts (built on the v2 branch: Atom feeds, alerts.json, browser pings)

A small, opt-in webhook when a verdict flips and the bootstrap interval no longer crosses 0.50. Off by default.

## Also on the v2 branch: Crowd check

A concentration and flip-risk meter for each metal (see the changelog). It uses the same weights as the verdict and never changes it.
