"""Market context for one metal: candles, funding, open interest, trend and regime.

Network calls are in fetch_market; summarise() is pure.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any, Optional

from . import config
from . import indicators as IND

log = logging.getLogger("market")

DAY_MS = 86_400_000
HOUR_MS = 3_600_000


def _f(v: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


async def fetch_market(client, coin: str, now_ms: int) -> dict[str, Any]:
    out: dict[str, Any] = {"candles_1h": [], "candles_1d": [], "candles_15m": [], "funding": []}
    jobs = (
        ("candles_1h", lambda: client.candles(coin, "1h", now_ms - config.CANDLE_DAYS_1H * DAY_MS, now_ms)),
        ("candles_1d", lambda: client.candles(coin, "1d", now_ms - config.CANDLE_DAYS_1D * DAY_MS, now_ms)),
        ("candles_15m", lambda: client.candles(coin, "15m", now_ms - config.CANDLE_DAYS_15M * DAY_MS, now_ms)),
        ("funding", lambda: client.funding_history(coin, now_ms - config.FUNDING_DAYS * DAY_MS, now_ms)),
    )
    for key, job in jobs:
        try:
            out[key] = await job()
        except Exception as exc:  # noqa: BLE001 — context must not fail the sweep
            log.warning("%s %s failed: %s", coin, key, exc)
    log.info("%s market: %s 1h, %s 1d, %s 15m candles, %s funding rows", coin,
             len(out["candles_1h"]), len(out["candles_1d"]), len(out["candles_15m"]), len(out["funding"]))
    return out


def _change(closes: list[tuple[int, float]], now_ms: int, hours: float, px: float) -> Optional[float]:
    target = now_ms - hours * HOUR_MS
    base = None
    for t, c in closes:
        if t <= target:
            base = c
        else:
            break
    if base is None or base <= 0 or px <= 0:
        return None
    return px / base - 1.0


def summarise(market: dict[str, Any], ctx: dict[str, Any], mark: Optional[float], now_ms: int) -> dict[str, Any]:
    c1h = market.get("candles_1h") or []
    c1d = market.get("candles_1d") or []
    fund = market.get("funding") or []
    closes = [(int(c["t"]), float(c["c"])) for c in c1h]
    px = _f(mark, 0.0) or (closes[-1][1] if closes else 0.0)
    prices = [c for _, c in closes]

    e20 = IND.ema(prices, 20)[-1] if prices else None
    e50s = IND.ema(prices, 50) if prices else []
    e50 = e50s[-1] if e50s else None
    e200 = IND.ema(prices, 200)[-1] if prices else None
    slope = 0
    if len(e50s) > 6 and e50s[-1] is not None and e50s[-7] is not None:
        slope = 1 if e50s[-1] > e50s[-7] else (-1 if e50s[-1] < e50s[-7] else 0)
    rv_series = IND.rolling_vol_series(prices, 24, 24 * 365) if len(prices) > 30 else []
    rv_now = rv_series[-1] if rv_series else None
    rv_pct = IND.percentile_rank(rv_series[-720:], rv_now) if rv_now is not None else None
    er = IND.efficiency_ratio(prices[-49:]) if len(prices) >= 49 else None
    ret24 = _change(closes, now_ms, 24, px)
    regime = IND.classify_regime(rv_pct, er, ret24, slope)

    rates = [(int(r["time"]), float(r["fundingRate"])) for r in fund if r.get("fundingRate") is not None]
    def avg_since(h: float) -> Optional[float]:
        xs = [r for t, r in rates if t >= now_ms - h * HOUR_MS]
        return statistics.fmean(xs) if xs else None
    f_now = _f(ctx.get("funding"), None)
    oi = _f(ctx.get("openInterest"), None)
    prev_day = _f(ctx.get("prevDayPx"), None)

    return {
        "mark": px or None,
        "oracle": _f(ctx.get("oraclePx"), None),
        "premium": _f(ctx.get("premium"), None),
        "change_24h": (px / prev_day - 1.0) if prev_day and px else ret24,
        "change_7d": _change(closes, now_ms, 24 * 7, px),
        "change_30d": _change(closes, now_ms, 24 * 30, px),
        "funding_hourly": f_now,
        "funding_24h_avg": avg_since(24),
        "funding_7d_avg": avg_since(24 * 7),
        "funding_annualised": (f_now * 24 * 365) if f_now is not None else None,
        "open_interest": oi,
        "open_interest_usd": (oi * px) if (oi and px) else None,
        "day_volume_usd": _f(ctx.get("dayNtlVlm"), None),
        "max_leverage": ctx.get("maxLeverage"),
        "ema": {"e20": e20, "e50": e50, "e200": e200, "state": IND.ema_trend_state(px, e20, e50, e200) if px else None},
        "realised_vol_24h": rv_now,
        "regime": regime,
        "chart_1h": [[int(c["t"]), round(float(c["o"]), 4), round(float(c["h"]), 4), round(float(c["l"]), 4),
                      round(float(c["c"]), 4)] for c in c1h[-config.CHART_CANDLES_1H:]],
        "chart_1d": [[int(c["t"]), round(float(c["c"]), 4)] for c in c1d[-180:]],
        "funding_series": [[t, r] for t, r in rates[-24 * 14:]],
    }
