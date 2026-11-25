"""Turn raw downloads into the compact, committed inputs the analysis reads.

raw/market.json, raw/accounts.json, raw/positions/*.json
    ->  data/inputs/{market,wallets,wallet_paths,reach}.json

wallet_paths: for every cohort wallet whose userFunding history was read in full, the wallet's
average signed xyz:GOLD / xyz:SILVER position for each UTC day from listing to the fetch time
(days with no row = flat). For the most recent days Hyperliquid serves hourly rows only; fetch_positions
reads one funding hour (12:00 UTC) per such day, which stands in for that day's figure.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from app import config  # noqa: E402

BT = ROOT / "research" / "backtest"
RAW = BT / "raw"
INP = BT / "data" / "inputs"
DAY = 86_400_000
COIN_KEY = {m["coin"]: k for k, m in config.METALS.items()}


def iso(ms):
    import datetime as dt
    return None if ms is None else dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def main():
    INP.mkdir(parents=True, exist_ok=True)
    mk = json.loads((RAW / "market.json").read_text())
    accounts = json.loads((RAW / "accounts.json").read_text())
    cohort = json.loads(config.COHORT_JSON.read_text())
    listing = min(mk["coins"][c]["funding"][0][0] for c in ("xyz:GOLD", "xyz:SILVER")) - DAY
    (INP / "market.json").write_text(json.dumps(mk, separators=(",", ":")))

    paths, hourly_from = {}, []
    daily_last = []
    for w in accounts:
        f = RAW / "positions" / f"{w['address']}.json"
        w["history"] = "missing"
        if not f.exists():
            continue
        d = json.loads(f.read_text())
        if not d.get("complete"):
            w["history"] = "incomplete"
            continue
        w["history"] = "complete"
        per = {k: defaultdict(list) for k in config.METALS}
        for t, coin, szi, ns, usdc, rate in d["metal_rows"]:
            k = COIN_KEY.get(coin)
            if k is None:
                continue
            day = t - t % DAY
            if ns:  # pre-aggregated daily row: szi is that day's figure
                per[k][day].append(("d", szi, ns))
                daily_last.append(t)
            else:
                per[k][day].append(("h", szi, 1))
                hourly_from.append(t)
        days = {}
        for k, dd in per.items():
            out = {}
            for day, rows in dd.items():
                daily = [r for r in rows if r[0] == "d"]
                if daily:
                    out[day] = daily[-1][1]
                else:
                    out[day] = sum(r[1] for r in rows) / len(rows)  # mean over the hours it was open
            days[k] = {str(day): round(v, 6) for day, v in sorted(out.items()) if v != 0}
        paths[w["address"]] = {"first_row_ms": d["first_row_ms"], "rows": d["rows"], "pages": d["pages"], "days": days}
    (INP / "wallet_paths.json").write_text(json.dumps(paths, separators=(",", ":")))
    wl = {"fetched_ms": mk["fetched_ms"], "listing_ms": listing, "cohort_built_at_utc": cohort.get("built_at_utc"),
          "wallets": [{k: w.get(k) for k in ("address", "month_pnl", "equity", "equity_main", "equity_xyz", "szi", "history")}
                      for w in accounts]}
    (INP / "wallets.json").write_text(json.dumps(wl, separators=(",", ":")))

    reach = {"market": {}, "wallets": {}}
    for coin, c in mk["coins"].items():
        reach["market"][coin] = {
            "candles_1h": {"n": len(c["c1h"]), "from": iso(c["c1h"][0][0]), "to": iso(c["c1h"][-1][0]),
                           "limit": "candleSnapshot serves only the latest 5,000 candles per interval"},
            "candles_1d": {"n": len(c["c1d"]), "from": iso(c["c1d"][0][0]), "to": iso(c["c1d"][-1][0])},
            "funding": {"n": len(c["funding"]), "from": iso(c["funding"][0][0]), "to": iso(c["funding"][-1][0])},
        }
    kinds = defaultdict(int)
    for w in accounts:
        kinds[w["history"]] += 1
    reach["wallets"] = {
        "cohort": len(accounts),
        "cohort_built_at_utc": cohort.get("built_at_utc"),
        "history": dict(kinds),
        "history_source": "userFunding (one row per open position per funding hour; older rows served as daily aggregates)",
        "history_from": iso(listing),
        "history_to": iso(mk["fetched_ms"]),
        "daily_rows_until": iso(max(daily_last)) if daily_last else None,
        "sampled_days_from": iso(min(hourly_from) - min(hourly_from) % DAY) if hourly_from else None,
        "sampled_hour": "12:00 UTC (recent days are served hourly only; one hour per day is read)",
        "wallets_ever_in": {k: sum(1 for p in paths.values() if p["days"][k]) for k in config.METALS},
        "blind_spot": "positions opened and closed between two funding hours never show up",
        "today_only": ["leaderboard rank and month PnL", "account equity", "cohort membership"],
    }
    (INP / "reach.json").write_text(json.dumps(reach, indent=1))
    print(json.dumps(reach["wallets"], indent=1))


if __name__ == "__main__":
    main()
