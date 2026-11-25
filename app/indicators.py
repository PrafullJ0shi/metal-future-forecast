"""Price-series maths: EMA, realised volatility, efficiency ratio, regime,
cross-correlation. Pure functions, no I/O."""

from __future__ import annotations

import math
from typing import Optional, Sequence


def ema(values: Sequence[float], span: int) -> list[Optional[float]]:
    """Exponential moving average with alpha = 2 / (span + 1).

    Seeded with the simple mean of the first `span` values; earlier slots are None.
    """
    out: list[Optional[float]] = [None] * len(values)
    if span <= 0 or len(values) < span:
        return out
    alpha = 2.0 / (span + 1.0)
    seed = sum(values[:span]) / span
    out[span - 1] = seed
    prev = seed
    for i in range(span, len(values)):
        prev = alpha * values[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def log_returns(prices: Sequence[float]) -> list[float]:
    return [
        math.log(prices[i] / prices[i - 1])
        for i in range(1, len(prices))
        if prices[i] > 0 and prices[i - 1] > 0
    ]


def stdev(values: Sequence[float]) -> Optional[float]:
    n = len(values)
    if n < 2:
        return None
    mu = sum(values) / n
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (n - 1))


def realized_vol(prices: Sequence[float], periods_per_year: float) -> Optional[float]:
    """Annualised standard deviation of log returns."""
    sd = stdev(log_returns(prices))
    if sd is None:
        return None
    return sd * math.sqrt(periods_per_year)


def efficiency_ratio(prices: Sequence[float]) -> Optional[float]:
    """Kaufman efficiency ratio: |P_n - P_0| / sum |P_t - P_{t-1}|, in [0, 1]."""
    if len(prices) < 3:
        return None
    path = sum(abs(prices[i] - prices[i - 1]) for i in range(1, len(prices)))
    if path <= 0:
        return 0.0
    return abs(prices[-1] - prices[0]) / path


def percentile_rank(sample: Sequence[float], value: float) -> Optional[float]:
    """Share of `sample` at or below `value`."""
    if not sample:
        return None
    return sum(1 for s in sample if s <= value) / len(sample)


def rolling_vol_series(prices: Sequence[float], window: int, periods_per_year: float) -> list[float]:
    out = []
    for end in range(window + 1, len(prices) + 1):
        v = realized_vol(prices[end - window - 1:end], periods_per_year)
        if v is not None:
            out.append(v)
    return out


def last_cross(fast: Sequence[Optional[float]], slow: Sequence[Optional[float]]) -> Optional[dict]:
    """Most recent index where sign(fast - slow) changed. Returns {index, kind}."""
    prev_sign = None
    found = None
    for i, (f, s) in enumerate(zip(fast, slow)):
        if f is None or s is None:
            continue
        sign = 1 if f > s else (-1 if f < s else 0)
        if sign == 0:
            continue
        if prev_sign is not None and sign != prev_sign:
            found = {"index": i, "kind": "bullish" if sign > 0 else "bearish"}
        prev_sign = sign
    return found


def ema_trend_state(price: float, e20: Optional[float], e50: Optional[float], e200: Optional[float]) -> str:
    """Stack order of price and EMAs as a plain label."""
    if None in (e20, e50, e200):
        return "INSUFFICIENT DATA"
    if price > e20 > e50 > e200:
        return "UPTREND (price > 20 > 50 > 200)"
    if price < e20 < e50 < e200:
        return "DOWNTREND (price < 20 < 50 < 200)"
    if price > e200:
        return "ABOVE 200, MIXED"
    return "BELOW 200, MIXED"


def classify_regime(
    rv_pct: Optional[float],
    er: Optional[float],
    ret_24h: Optional[float],
    slope_sign: int,
    *,
    hi_vol_pct: float = 0.85,
    trend_er: float = 0.30,
) -> dict:
    """Trending / ranging / high-vol from vol percentile and efficiency ratio."""
    if rv_pct is None or er is None:
        return {"label": "UNKNOWN", "detail": "Not enough candles."}
    if rv_pct >= hi_vol_pct:
        sub = "panic" if (ret_24h or 0) < 0 else "euphoria"
        return {
            "label": "HIGH-VOL",
            "sub": sub,
            "detail": f"24h realised vol is in the {rv_pct * 100:.0f}th percentile of the last 30 days ({sub}).",
        }
    if er >= trend_er:
        direction = "up" if slope_sign > 0 else ("down" if slope_sign < 0 else "flat")
        return {
            "label": "TRENDING",
            "sub": direction,
            "detail": f"Efficiency ratio {er:.2f} over 48h (>= {trend_er}); EMA-50 slope points {direction}.",
        }
    return {
        "label": "RANGING",
        "sub": None,
        "detail": f"Efficiency ratio {er:.2f} over 48h (< {trend_er}); price is chopping, not travelling.",
    }


def pearson(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    n = len(x)
    if n < 3 or n != len(y):
        return None
    mx = sum(x) / n
    my = sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    return sxy / math.sqrt(sxx * syy)


def cross_correlation(
    x: Sequence[Optional[float]],
    y: Sequence[Optional[float]],
    max_lag: int,
) -> list[dict]:
    """r_k = corr(x_t, y_{t+k}) for k in [-max_lag, max_lag], skipping None pairs.

    k > 0 means x moves first (x leads y); k < 0 means y moves first.
    """
    out = []
    n = len(x)
    for k in range(-max_lag, max_lag + 1):
        xs, ys = [], []
        for t in range(n):
            u = t + k
            if u < 0 or u >= n:
                continue
            a, b = x[t], y[u]
            if a is None or b is None:
                continue
            xs.append(a)
            ys.append(b)
        out.append({"lag": k, "r": pearson(xs, ys), "n": len(xs)})
    return out


def lead_score(ccf: Sequence[dict]) -> Optional[float]:
    """(sum_{k>0} r_k^2 - sum_{k<0} r_k^2) / sum_{k!=0} r_k^2, in [-1, 1]."""
    lead = sum((c["r"] or 0.0) ** 2 for c in ccf if c["lag"] > 0 and c["r"] is not None)
    lag = sum((c["r"] or 0.0) ** 2 for c in ccf if c["lag"] < 0 and c["r"] is not None)
    tot = lead + lag
    if tot <= 0:
        return None
    return (lead - lag) / tot
