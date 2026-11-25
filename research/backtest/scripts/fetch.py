"""Step 1 of the backtest download: market history and today's cohort accounts.

Outputs (research/backtest/raw/, git-ignored; prepare.py writes the compact committed copy):
  market.json    1h and 1d candles and full funding history for xyz:GOLD, xyz:SILVER, PAXG
  accounts.json  today's equity (validator dex + xyz dex), month PnL and metal positions of the top-500 cohort

Step 2 is fetch_positions.py (each wallet's metal position history from userFunding).

Hyperliquid limits that set how far back each input reaches:
  * candleSnapshot serves only the most recent 5,000 candles per interval
    (1h -> about 208 days; 1d -> since listing).
  * fundingHistory pages 500 rows at a time back to listing.
  * userFillsByTime keeps only the 10,000 most recent fills of a wallet (all coins), which for the
    busiest cohort wallets is two to four days, so fills are not used for history.

Run from the repo root: python research/backtest/scripts/fetch.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.hl_client import HyperliquidClient, account_value, extract_position  # noqa: E402

BT = ROOT / "research" / "backtest"
RAW = BT / "raw"
log = logging.getLogger("fetch")
COINS = ["xyz:GOLD", "xyz:SILVER", "PAXG"]


async def candles_all(client, coin: str, interval: str, now_ms: int) -> list[dict]:
    """Page backwards until the API stops returning older candles."""
    out: dict[int, dict] = {}
    end = now_ms
    for _ in range(20):
        page = await client.candles(coin, interval, 0, end)
        new = [c for c in page if int(c["t"]) not in out]
        if not new:
            break
        for c in page:
            out[int(c["t"])] = c
        first = min(int(c["t"]) for c in page)
        if first >= end:
            break
        end = first - 1
    return [out[k] for k in sorted(out)]


async def funding_all(client, coin: str, now_ms: int) -> list[dict]:
    out, start = [], 0
    for _ in range(200):
        page = await client._info_items({"type": "fundingHistory", "coin": coin, "startTime": start, "endTime": now_ms},
                                        config.WEIGHT_FUNDING, 20)
        if not page:
            break
        out.extend(page)
        last = int(page[-1]["time"])
        if len(page) < 500:
            break
        start = last + 1
    return out


async def fetch_market(client, now_ms: int) -> dict:
    mk = {"fetched_ms": now_ms, "coins": {}}
    for coin in COINS:
        c1h = await candles_all(client, coin, "1h", now_ms)
        c1d = await candles_all(client, coin, "1d", now_ms)
        fund = await funding_all(client, coin, now_ms)
        log.info("%s: %s 1h (from %s), %s 1d, %s funding", coin, len(c1h), c1h[0]["t"] if c1h else None, len(c1d), len(fund))
        mk["coins"][coin] = {
            "c1h": [[int(c["t"]), float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"]), float(c["v"])] for c in c1h],
            "c1d": [[int(c["t"]), float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"]), float(c["v"])] for c in c1d],
            "funding": [[int(r["time"]), float(r["fundingRate"])] for r in fund],
        }
    return mk


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    RAW.mkdir(parents=True, exist_ok=True)
    cohort = json.loads(config.COHORT_JSON.read_text())
    traders = cohort["traders"]
    now_ms = int(time.time() * 1000)
    async with HyperliquidClient() as client:
        if (RAW / "market.json").exists():
            mk = json.loads((RAW / "market.json").read_text())
            now_ms = mk["fetched_ms"]
        else:
            mk = await fetch_market(client, now_ms)
            (RAW / "market.json").write_text(json.dumps(mk, separators=(",", ":")))
        sem = asyncio.Semaphore(6)

        async def account(row):
            async with sem:
                main_s = await client.clearinghouse_state(row["address"])
                xyz_s = await client.clearinghouse_state(row["address"], dex="xyz")
            pos = {k: extract_position(xyz_s, m["coin"])["szi"] for k, m in config.METALS.items()}
            return {"address": row["address"], "display_name": row.get("display_name"),
                    "month_pnl": row.get("perp_month_pnl"), "equity_main": account_value(main_s),
                    "equity_xyz": account_value(xyz_s), "szi": pos}

        acc_path = RAW / "accounts.json"
        if acc_path.exists():
            wallets = json.loads(acc_path.read_text())
        else:
            wallets = await asyncio.gather(*(account(r) for r in traders))
            for w in wallets:
                w["equity"] = w["equity_main"] + w["equity_xyz"]
            acc_path.write_text(json.dumps(wallets))
        log.info("Accounts: %s wallets, %s with an xyz balance or metal position", len(wallets),
                 sum(1 for w in wallets if w["equity_xyz"] > 0 or any(w["szi"].values())))
    log.info("done")


if __name__ == "__main__":
    asyncio.run(main())
