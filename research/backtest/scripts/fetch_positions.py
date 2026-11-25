"""Rebuild each cohort wallet's xyz:GOLD / xyz:SILVER position history from `userFunding`.

Why this source: `userFillsByTime` only serves a wallet's 10,000 most recent fills (all coins), so for
the busiest wallets fills reach back just a few days. `userFunding` instead returns one row per open
position per funding interval, with the signed position size (`szi`) at that time. Hyperliquid serves
older rows pre-aggregated per UTC day (`nSamples` = hours the position was open that day, `szi` the
day's figure) and recent rows hourly. A coin that is missing from a day while the wallet has rows for
other coins means no open position at any funding hour that day, so the history is complete for
positions held across at least one funding hour, from the market listing to now.

Output: raw/positions/<addr>.json with only the metal rows plus the time span actually read.
Run from the repo root after fetch.py has written raw/market.json and raw/accounts.json.
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
from app.hl_client import HyperliquidClient  # noqa: E402
from app.signal import equity_shrink, skill_weight  # noqa: E402

RAW = ROOT / "research" / "backtest" / "raw"
POS = RAW / "positions"
METAL_COINS = ("xyz:GOLD", "xyz:SILVER")
MAX_PAGES = 400
DAY = 86_400_000
# Rows before this stamp are served as daily aggregates; after it, hourly (one row per position per hour).
# Paging the hourly part costs up to 24x more, so for those days we read a single funding hour (12:00 UTC).
HOURLY_FROM = 1794873600000  # 2026-11-17T00:00Z, read off the API on 2026-11-25
SAMPLE_HOUR = 12 * 3_600_000
log = logging.getLogger("positions")


async def funding_rows(client, address: str, start_ms: int, end_ms: int) -> dict:
    seen, metal, pages, n_rows = set(), [], 0, 0
    start, last_t, first_t = start_ms, None, None
    while pages < MAX_PAGES:
        page = await client._info_items({"type": "userFunding", "user": address, "startTime": start, "endTime": HOURLY_FROM - 1},
                                        config.WEIGHT_FILLS, 20)
        pages += 1
        if pages % 20 == 0:
            log.info("  %s page %s at %s", address[:10], pages, time.strftime("%Y-%m-%d", time.gmtime(int(page[-1]["time"]) / 1000)) if page else "-")
        if not page:
            break
        new = 0
        for r in page:
            d = r.get("delta") or {}
            key = (int(r["time"]), d.get("coin"))
            if key in seen:
                continue
            seen.add(key)
            new += 1
            n_rows += 1
            t = int(r["time"])
            first_t = t if first_t is None else min(first_t, t)
            last_t = t if last_t is None else max(last_t, t)
            if d.get("coin") in METAL_COINS:
                metal.append([t, d["coin"], float(d.get("szi") or 0), d.get("nSamples"),
                              float(d.get("usdc") or 0), float(d.get("fundingRate") or 0)])
        if len(page) < 500:
            break
        page_last = max(int(r["time"]) for r in page)
        # Daily rows share one timestamp, so restart at the same stamp and de-duplicate,
        # unless the whole page sat on it (then step past it).
        start = page_last if new and page_last > start else page_last + 1
        if len(seen) > 400_000:
            seen = {k for k in seen if k[0] >= page_last}
    # Recent days: one sampled funding hour per day.
    complete = pages < MAX_PAGES
    for day in range(HOURLY_FROM, end_ms, DAY):
        t = day + SAMPLE_HOUR
        if t > end_ms:
            break
        page = await client._info_items({"type": "userFunding", "user": address, "startTime": t, "endTime": t + 3_599_999},
                                        config.WEIGHT_FILLS, 20)
        pages += 1
        if len(page) >= 500:
            complete = False
        for r in page:
            d = r.get("delta") or {}
            n_rows += 1
            if d.get("coin") in METAL_COINS:
                metal.append([int(r["time"]), d["coin"], float(d.get("szi") or 0), None,
                              float(d.get("usdc") or 0), float(d.get("fundingRate") or 0)])
    metal.sort()
    return {"pages": pages, "sampled_hour_utc": 12, "hourly_from_ms": HOURLY_FROM, "rows": n_rows, "first_row_ms": first_t, "last_row_ms": last_t,
            "complete": complete, "metal_rows": metal}


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    POS.mkdir(parents=True, exist_ok=True)
    mk = json.loads((RAW / "market.json").read_text())
    now_ms = mk["fetched_ms"]
    listing = min(mk["coins"][c]["funding"][0][0] for c in METAL_COINS) - 86_400_000
    wallets = json.loads((RAW / "accounts.json").read_text())
    # Wallets with an xyz balance or open metal position first, then the rest; heaviest voters first.
    wallets.sort(key=lambda w: (not (w["equity_xyz"] > 0 or any(w["szi"].values())),
                                -skill_weight(w["month_pnl"] or 0) * equity_shrink(w["equity"])))
    sem = asyncio.Semaphore(4)
    done, t0 = 0, time.monotonic()

    async def one(w):
        nonlocal done
        path = POS / f"{w['address']}.json"
        if not path.exists():
            async with sem:
                r = await funding_rows(client, w["address"], listing, now_ms)
            
            r.update(address=w["address"], start_ms=listing, end_ms=now_ms)
            path.write_text(json.dumps(r, separators=(",", ":")))
        done += 1
        if done % 10 == 0:
            log.info("positions %s/%s in %.0fs", done, len(wallets), time.monotonic() - t0)

    async with HyperliquidClient() as client:
        await asyncio.gather(*(one(w) for w in wallets))
    log.info("done")


if __name__ == "__main__":
    asyncio.run(main())
