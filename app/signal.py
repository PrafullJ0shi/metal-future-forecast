"""Pure maths for the metal consensus reading (identical to the BTC project). No I/O."""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional

from . import config


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def skill_weight(month_pnl: float) -> float:
    """log(1 + max(0, month PnL in USD))."""
    return math.log1p(max(0.0, month_pnl))


def equity_shrink(equity: float, full: float = config.EQUITY_FULL_WEIGHT) -> float:
    """Linear shrink toward 0 below `full` USD of equity."""
    if equity <= 0 or full <= 0:
        return 0.0
    return min(1.0, equity / full)


def conviction(notional: float, equity: float, cap: float = config.CONVICTION_CAP) -> float:
    """|metal notional| / equity, capped."""
    if equity <= 0:
        return 0.0
    return min(cap, abs(notional) / equity)


def trader_weight(
    month_pnl: float,
    equity: float,
    notional: float,
) -> float:
    return skill_weight(month_pnl) * equity_shrink(equity) * conviction(notional, equity)


def beta_ppf(p: float, a: float, b: float) -> float:
    """Inverse of the regularised incomplete beta (no SciPy)."""
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    # Binary search on the regularised incomplete beta Ix(a, b).
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if _betainc(mid, a, b) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _betainc(x: float, a: float, b: float) -> float:
    """Regularised incomplete beta I_x(a, b) via continued fraction."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    ln_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    if x < (a + 1.0) / (a + b + 2.0):
        return _betainc_cf(x, a, b, ln_beta)
    return 1.0 - _betainc_cf(1.0 - x, b, a, ln_beta)


def _betainc_cf(x: float, a: float, b: float, ln_beta: float) -> float:
    # Lentz continued fraction for the incomplete beta.
    front = math.exp(a * math.log(x) + b * math.log(1.0 - x) - ln_beta) / a
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1.0)
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        num = m * (b - m) * x / ((a + m2 - 1.0) * (a + m2))
        d = 1.0 + num * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + num / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        num = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1.0))
        d = 1.0 + num * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + num / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return front * h


@dataclass
class PositionRow:
    address: str
    display_name: Optional[str]
    side: str  # LONG, SHORT
    size: float  # signed coin units (szi)
    abs_size: float
    entry: Optional[float]
    leverage_type: Optional[str]
    leverage: Optional[float]
    unrealized_pnl: Optional[float]
    notional: float
    equity: float
    month_pnl: float
    weight: float


@dataclass
class SignalResult:
    p_long: Optional[float]
    ci_low: Optional[float]
    ci_high: Optional[float]
    beta_ci_low: Optional[float]
    beta_ci_high: Optional[float]
    verdict: str
    n_traders: int
    n_long: int
    n_short: int
    n_flat: int
    notional_long: float
    notional_short: float
    weight_long: float
    weight_short: float
    top_positions: list[PositionRow] = field(default_factory=list)
    size_buckets: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


def classify_side(szi: float) -> str:
    if szi > 0:
        return "LONG"
    if szi < 0:
        return "SHORT"
    return "FLAT"


def bootstrap_interval(
    signed_weights: Iterable[tuple[int, float]],
    n: int = config.BOOTSTRAP_N,
    seed: int = config.BOOTSTRAP_SEED,
    level: float = config.CI_LEVEL,
) -> tuple[Optional[float], Optional[float]]:
    """Percentile interval for weighted P(long) by resampling traders."""
    items = [(s, w) for s, w in signed_weights if w > 0 and s != 0]
    if not items:
        return None, None
    rng = random.Random(seed)
    k = len(items)
    samples: list[float] = []
    for _ in range(n):
        w_long = 0.0
        w_short = 0.0
        for __ in range(k):
            s, w = items[rng.randrange(k)]
            if s > 0:
                w_long += w
            else:
                w_short += w
        denom = w_long + w_short
        if denom <= 0:
            continue
        samples.append(w_long / denom)
    if len(samples) < 20:
        return None, None
    samples.sort()
    alpha = (1.0 - level) / 2.0
    lo_i = int(alpha * (len(samples) - 1))
    hi_i = int((1.0 - alpha) * (len(samples) - 1))
    return samples[lo_i], samples[hi_i]


def beta_interval(
    n_long: int,
    n_short: int,
    a0: float = config.BETA_PRIOR_A,
    b0: float = config.BETA_PRIOR_B,
    level: float = config.CI_LEVEL,
) -> tuple[Optional[float], Optional[float]]:
    """Equal-tailed interval of Beta(a0 + longs, b0 + shorts). Flats ignored."""
    if n_long + n_short <= 0:
        return None, None
    a = a0 + n_long
    b = b0 + n_short
    low_p = (1.0 - level) / 2.0
    high_p = 1.0 - low_p
    return beta_ppf(low_p, a, b), beta_ppf(high_p, a, b)


def verdict_from_p(p_long: Optional[float]) -> str:
    if p_long is None:
        return "NEUTRAL"
    if p_long >= config.P_LONG_THRESHOLD:
        return "LONG"
    if p_long <= config.P_SHORT_THRESHOLD:
        return "SHORT"
    return "NEUTRAL"


# Notional buckets in USD for the size breakdown.
SIZE_BUCKETS = (
    ("under 100k", 0.0, 100_000.0),
    ("100k–1m", 100_000.0, 1_000_000.0),
    ("1m–10m", 1_000_000.0, 10_000_000.0),
    ("10m+", 10_000_000.0, float("inf")),
)


def size_breakdown(rows: Iterable[PositionRow]) -> list[dict[str, Any]]:
    out = []
    rows = list(rows)
    for label, lo, hi in SIZE_BUCKETS:
        long_n = short_n = 0
        long_ntl = short_ntl = 0.0
        for r in rows:
            if r.notional < lo or r.notional >= hi:
                continue
            if r.side == "LONG":
                long_n += 1
                long_ntl += r.notional
            elif r.side == "SHORT":
                short_n += 1
                short_ntl += r.notional
        out.append(
            {
                "label": label,
                "long_count": long_n,
                "short_count": short_n,
                "notional_long": long_ntl,
                "notional_short": short_ntl,
            }
        )
    return out


def compute_signal(
    traders: list[dict[str, Any]],
    top_n: int = 20,
) -> SignalResult:
    """
    traders: dicts with address, display_name, month_pnl, equity,
    szi, notional, entry, leverage_type, leverage, unrealized_pnl.
    Missing or zero szi counts as flat (no vote).
    """
    notes: list[str] = []
    rows: list[PositionRow] = []
    n_long = n_short = n_flat = 0
    notional_long = notional_short = 0.0
    weight_long = weight_short = 0.0
    signed: list[tuple[int, float]] = []

    for t in traders:
        equity = _f(t.get("equity"))
        month_pnl = _f(t.get("month_pnl"))
        szi = _f(t.get("szi"))
        notional = abs(_f(t.get("notional")))
        if notional == 0 and szi != 0:
            # fall back later; mark keeps notional honest when provided
            notional = abs(szi) * abs(_f(t.get("mark"), 0.0))
        side = classify_side(szi)
        w = trader_weight(month_pnl, equity, notional) if side != "FLAT" else 0.0
        if side == "LONG":
            n_long += 1
            notional_long += notional
            weight_long += w
            signed.append((1, w))
        elif side == "SHORT":
            n_short += 1
            notional_short += notional
            weight_short += w
            signed.append((-1, w))
        else:
            n_flat += 1
        if side != "FLAT":
            rows.append(
                PositionRow(
                    address=str(t.get("address") or ""),
                    display_name=t.get("display_name"),
                    side=side,
                    size=szi,
                    abs_size=abs(szi),
                    entry=(_f(t["entry"]) if t.get("entry") is not None else None),
                    leverage_type=t.get("leverage_type"),
                    leverage=(_f(t["leverage"]) if t.get("leverage") is not None else None),
                    unrealized_pnl=(
                        _f(t["unrealized_pnl"]) if t.get("unrealized_pnl") is not None else None
                    ),
                    notional=notional,
                    equity=equity,
                    month_pnl=month_pnl,
                    weight=w,
                )
            )

    denom = weight_long + weight_short
    if denom <= 0:
        p_long = None
        notes.append("No weighted votes in the cohort; verdict is NEUTRAL.")
    else:
        p_long = weight_long / denom

    ci_low, ci_high = bootstrap_interval(signed)
    beta_lo, beta_hi = beta_interval(n_long, n_short)
    rows.sort(key=lambda r: r.notional, reverse=True)

    if p_long is not None and ci_low is not None and ci_high is not None:
        if ci_low <= 0.5 <= ci_high:
            notes.append("The 95% bootstrap interval includes 0.5; the point verdict is weakly held.")

    return SignalResult(
        p_long=p_long,
        ci_low=ci_low,
        ci_high=ci_high,
        beta_ci_low=beta_lo,
        beta_ci_high=beta_hi,
        verdict=verdict_from_p(p_long),
        n_traders=len(traders),
        n_long=n_long,
        n_short=n_short,
        n_flat=n_flat,
        notional_long=notional_long,
        notional_short=notional_short,
        weight_long=weight_long,
        weight_short=weight_short,
        top_positions=rows[:top_n],
        size_buckets=size_breakdown(rows),
        notes=notes,
    )
