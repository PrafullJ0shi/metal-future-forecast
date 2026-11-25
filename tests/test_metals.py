"""Metal-specific plumbing: builder-dex positions, equity across dexes, fills cache."""

import asyncio

from app import config
from app.hl_client import account_value, ctx_from_ctxs, extract_position
from app.sweep import FillsCache, metal_rows, position_changes


STATE = {
    "marginSummary": {"accountValue": "25000.0"},
    "assetPositions": [
        {"position": {"coin": "xyz:GOLD", "szi": "-10.5", "positionValue": "36900.0", "entryPx": "3550",
                      "leverage": {"type": "cross", "value": 10}, "unrealizedPnl": "400", "liquidationPx": None}},
        {"position": {"coin": "xyz:SILVER", "szi": "200", "positionValue": "8000", "entryPx": "41",
                      "leverage": {"type": "isolated", "value": 5}, "unrealizedPnl": "-200", "liquidationPx": "33.1"}},
    ],
}


def test_markets_are_the_listed_xyz_perps():
    assert config.METALS["gold"]["coin"] == "xyz:GOLD"
    assert config.METALS["silver"]["coin"] == "xyz:SILVER"
    assert all(m["dex"] == "xyz" for m in config.METALS.values())


def test_extract_position_per_coin():
    g = extract_position(STATE, "xyz:GOLD")
    s = extract_position(STATE, "xyz:SILVER")
    assert g["szi"] == -10.5 and g["notional"] == 36900.0 and g["leverage"] == 10
    assert s["szi"] == 200 and s["liquidation_px"] == 33.1
    assert extract_position(STATE, "GOLD")["szi"] == 0.0  # the bare name is not the builder-dex coin
    assert account_value(STATE) == 25000.0


def test_ctx_lookup_by_builder_name():
    payload = [{"universe": [{"name": "xyz:TSLA"}, {"name": "xyz:GOLD", "maxLeverage": 25}]},
               [{"markPx": "1"}, {"markPx": "3500", "funding": "0.00001"}]]
    c = ctx_from_ctxs(payload, "xyz:GOLD")
    assert c["markPx"] == "3500" and c["maxLeverage"] == 25


def test_metal_rows_flatten_positions():
    acc = [{"address": "0xa", "equity": 1.0, "positions": {"gold": {"szi": 2.0, "notional": 7000.0}}}]
    rows = metal_rows(acc, "gold", 3500.0)
    assert rows[0]["szi"] == 2.0 and rows[0]["mark"] == 3500.0 and "positions" not in rows[0]


def test_position_changes_kinds():
    prev = {"ts_utc": "2026-11-25T12:00:00Z", "positions": {"0xa": 0.0, "0xb": 5.0, "0xc": 5.0, "0xd": -2.0}}
    rows = [{"address": "0xa", "szi": 1.0}, {"address": "0xb", "szi": -5.0}, {"address": "0xc", "szi": 0.0},
            {"address": "0xd", "szi": -4.0}]
    out = position_changes(prev, rows, 3500.0)
    kinds = {i["address"]: i["kind"] for i in out["items"]}
    assert kinds == {"0xa": "opened", "0xb": "flipped", "0xc": "closed", "0xd": "added"}


def test_fills_cache_fetches_each_wallet_once():
    calls = []

    class Fake:
        async def user_fills_by_time(self, a, start, end=None):
            calls.append(a)
            return [{"time": 10, "coin": "xyz:GOLD"}, {"time": 20, "coin": "xyz:SILVER"}]

    fc = FillsCache(Fake())

    async def go():
        a = await fc.user_fills_by_time("0xa", 0)
        b = await fc.user_fills_by_time("0xa", 15)
        return a, b

    a, b = asyncio.run(go())
    assert calls == ["0xa"] and len(a) == 2 and len(b) == 1
