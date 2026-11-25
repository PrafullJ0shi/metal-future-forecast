"""v2 readings that sit beside the verdict, never on top of it.

tilt()      gold versus silver: the price ratio and how differently the cohort leans on each metal.
crowding()  how concentrated a metal's vote is, and how many wallets closing would flip the call.

Pure functions: no network, no files. The sweep feeds them the voters it already has.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Optional

from . import config

LONG_T = config.P_LONG_THRESHOLD
SHORT_T = config.P_SHORT_THRESHOLD


def _num(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def lean(p_long: Optional[float]) -> Optional[float]:
    """P(long) rescaled to -1 (all weight short) .. +1 (all weight long)."""
    p = _num(p_long)
    return None if p is None else 2.0 * p - 1.0


def money_lean(notional_long: Any, notional_short: Any) -> Optional[float]:
    """Net notional over gross notional, -1 .. +1. Dollars, not weights."""
    nl, ns = _num(notional_long) or 0.0, _num(notional_short) or 0.0
    gross = nl + ns
    return None if gross <= 0 else (nl - ns) / gross


# ---------------------------------------------------------------- ratio

def ratio_series(gold_daily: Iterable[Any], silver_daily: Iterable[Any], days: int = config.RATIO_WINDOW_DAYS,
                 live_gold: Optional[float] = None, live_silver: Optional[float] = None) -> list[list[float]]:
    """Gold / silver on matching daily closes: [[t_ms, ratio], ...]. The last point uses live marks if given."""
    g = {int(t): float(c) for t, c in gold_daily if c}
    s = {int(t): float(c) for t, c in silver_daily if c}
    ts = sorted(set(g) & set(s))[-days:]
    out = [[t, g[t] / s[t]] for t in ts if s[t] > 0]
    if out and live_gold and live_silver and live_silver > 0:
        out[-1] = [out[-1][0], live_gold / live_silver]
    return out


def _pct_rank(values: list[float], x: float) -> Optional[float]:
    if not values:
        return None
    return sum(1 for v in values if v <= x) / len(values)


def _change(series: list[list[float]], days: int) -> Optional[float]:
    if len(series) <= days or series[-1][1] <= 0:
        return None
    base = series[-1 - days][1]
    return series[-1][1] / base - 1.0 if base > 0 else None


def ratio_block(series: list[list[float]]) -> dict[str, Any]:
    if not series:
        return {"now": None, "series": []}
    vals = [r for _, r in series]
    now = vals[-1]
    return {
        "now": now,
        "mean": sum(vals) / len(vals),
        "min": min(vals), "max": max(vals),
        "pct_rank": _pct_rank(vals, now),
        "change_7d": _change(series, 7),
        "change_30d": _change(series, 30),
        "days": len(vals),
        "series": [[int(t), round(r, 3)] for t, r in series],
    }


# ---------------------------------------------------------------- tilt

TILT_READS = {
    "both_long": ("Both metals tilt long",
                  "The weighted money is long gold and long silver. Nobody is running a spread here."),
    "both_short": ("Both metals tilt short",
                   "The weighted money is short gold and short silver. A rough day for the shiny stuff."),
    "gold_over_silver": ("Gold favoured over silver",
                         "The crew leans more long (or less short) on gold than on silver. As a spread that points to a higher ratio."),
    "silver_over_gold": ("Silver favoured over gold",
                         "The crew leans more long (or less short) on silver than on gold. As a spread that points to a lower ratio."),
    "even": ("Gold and silver lean about the same",
             "No spread story. Read each metal on its own card."),
    "no_data": ("Not enough votes for a pair read", "At least one metal has no weighted votes right now."),
}


def tilt_read(verdict_gold: str, verdict_silver: str, gap: Optional[float]) -> str:
    """Pick the one-line reading. gap = lean(gold) - lean(silver)."""
    if gap is None:
        return "no_data"
    if abs(gap) >= config.TILT_EVEN_BAND and verdict_gold != verdict_silver:
        return "gold_over_silver" if gap > 0 else "silver_over_gold"
    if verdict_gold == verdict_silver == "LONG":
        return "both_long"
    if verdict_gold == verdict_silver == "SHORT":
        return "both_short"
    if abs(gap) >= config.TILT_EVEN_BAND:
        return "gold_over_silver" if gap > 0 else "silver_over_gold"
    return "even"


def tilt(gold: dict[str, Any], silver: dict[str, Any], gold_daily: Iterable[Any] = (),
         silver_daily: Iterable[Any] = ()) -> dict[str, Any]:
    lg, ls = lean(gold.get("p_long")), lean(silver.get("p_long"))
    mg = money_lean(gold.get("notional_long"), gold.get("notional_short"))
    ms = money_lean(silver.get("notional_long"), silver.get("notional_short"))
    gap = None if lg is None or ls is None else lg - ls
    money_gap = None if mg is None or ms is None else mg - ms
    code = tilt_read(gold.get("verdict", "NEUTRAL"), silver.get("verdict", "NEUTRAL"), gap)
    headline, text = TILT_READS[code]
    series = ratio_series(gold_daily, silver_daily, live_gold=_num(gold.get("mark")),
                          live_silver=_num(silver.get("mark")))
    rb = ratio_block(series)
    if not series:
        mk_g, mk_s = _num(gold.get("mark")), _num(silver.get("mark"))
        if mk_g and mk_s:
            rb["now"] = mk_g / mk_s
    return {
        "lean": {"gold": lg, "silver": ls},
        "money_lean": {"gold": mg, "silver": ms},
        "gap": gap,
        "money_gap": money_gap,
        "direction": None if gap is None else ("higher" if gap > 0 else "lower" if gap < 0 else "flat"),
        "read": code,
        "headline": headline,
        "text": text,
        "ratio": rb,
        "note": "Positioning of the cohort, not a forecast of the ratio.",
    }


# ---------------------------------------------------------------- crowding

def _p(wl: float, ws: float) -> Optional[float]:
    d = wl + ws
    return None if d <= 0 else wl / d


def verdict_of(p: Optional[float]) -> str:
    if p is None:
        return "NEUTRAL"
    return "LONG" if p >= LONG_T else "SHORT" if p <= SHORT_T else "NEUTRAL"


def wallets_to_move(weights_long: list[float], weights_short: list[float], target: str) -> Optional[int]:
    """Fewest wallets that must close, heaviest first, for P(long) to reach the target.

    target "above_short" / "below_long" mean "to the other side of that threshold"; the simple ones are
    "long" (p >= 0.60), "short" (p <= 0.40), "not_short" (p > 0.40), "not_long" (p < 0.60).
    Closing wallets on the side that is winning is the move that shifts p the most, so greedy is exact.
    """
    wl, ws = sorted(weights_long, reverse=True), sorted(weights_short, reverse=True)
    if not wl and not ws:
        return None
    WL, WS = sum(wl), sum(ws)

    def ok(p: Optional[float]) -> bool:
        if p is None:
            return False
        return {"long": p >= LONG_T, "short": p <= SHORT_T, "not_short": p > SHORT_T, "not_long": p < LONG_T}[target]

    if ok(_p(WL, WS)):
        return 0
    # to push p up remove shorts; to push it down remove longs
    pool, up = (ws, True) if target in ("long", "not_short") else (wl, False)
    cur_l, cur_s = WL, WS
    for k, w in enumerate(pool, start=1):
        if up:
            cur_s -= w
        else:
            cur_l -= w
        if ok(_p(max(cur_l, 0.0), max(cur_s, 0.0))):
            return k
    return None


def voters_from_block(block: dict[str, Any]) -> tuple[list[tuple[str, float]], bool]:
    """Voters as (side, weight). Exact when the sweep stored them; otherwise rebuilt from top_positions.

    The rebuild knows the 20 biggest positions by notional and the side totals; the other voters are
    spread evenly over the remaining weight. That is an estimate and the caller is told so.
    """
    stored = block.get("voters")
    if stored:
        return [(str(s), float(w)) for s, w, *_ in stored], True
    known = [(str(r["side"]), float(r["weight"])) for r in (block.get("top_positions") or [])
             if r.get("side") in ("LONG", "SHORT") and _num(r.get("weight")) is not None]
    n_l, n_s = int(block.get("n_long") or 0), int(block.get("n_short") or 0)
    out = list(known)
    for side, n_total, w_total in (("LONG", n_l, _num(block.get("weight_long")) or 0.0),
                                   ("SHORT", n_s, _num(block.get("weight_short")) or 0.0)):
        have = [w for s, w in known if s == side]
        rest_n = max(0, n_total - len(have))
        rest_w = max(0.0, w_total - sum(have))
        if rest_n:
            out += [(side, rest_w / rest_n)] * rest_n
    return out, (n_l + n_s) <= len(known)


def crowding(block: dict[str, Any]) -> dict[str, Any]:
    voters, exact = voters_from_block(block)
    wl = [w for s, w in voters if s == "LONG" and w > 0]
    ws = [w for s, w in voters if s == "SHORT" and w > 0]
    ranked = sorted([(w, "LONG") for w in wl] + [(w, "SHORT") for w in ws], reverse=True)
    allw = [w for w, _ in ranked]
    total = sum(allw)
    n = len(allw)
    p = _p(sum(wl), sum(ws))
    verdict = verdict_of(p)

    def share(k: int) -> Optional[float]:
        return None if total <= 0 else sum(allw[:k]) / total

    eff = None if total <= 0 else 1.0 / sum((w / total) ** 2 for w in allw)

    k_neutral = k_opposite = None
    if verdict == "SHORT":
        k_neutral = wallets_to_move(wl, ws, "not_short")
        k_opposite = wallets_to_move(wl, ws, "long")
    elif verdict == "LONG":
        k_neutral = wallets_to_move(wl, ws, "not_long")
        k_opposite = wallets_to_move(wl, ws, "short")
    elif verdict == "NEUTRAL" and n:
        a, b = wallets_to_move(wl, ws, "long"), wallets_to_move(wl, ws, "short")
        cands = [x for x in (a, b) if x is not None]
        k_neutral = min(cands) if cands else None
    removed = None
    if k_neutral and total > 0 and verdict in ("SHORT", "LONG"):
        pool = ws if verdict == "SHORT" else wl
        removed = sum(sorted(pool, reverse=True)[:k_neutral]) / total
    lo, hi = _num(block.get("ci_low")), _num(block.get("ci_high"))
    crosses = lo is not None and hi is not None and lo <= 0.5 <= hi

    flags = {
        "fragile": k_neutral is not None and k_neutral <= config.FLIP_FRAGILE_K,
        "whale": (share(1) or 0.0) >= config.WHALE_SHARE,
        "weak_interval": bool(crosses),
        "thin_book": n < config.THIN_BOOK_VOTERS,
    }
    score = sum(flags.values())
    level, line = LEVELS[min(score, 3)]
    return {
        "level": level,
        "score": score,
        "flags": flags,
        "line": line,
        "voters": n,
        "exact": exact,
        "top1_share": share(1), "top3_share": share(3), "top5_share": share(5),
        "effective_voters": eff,
        "verdict": verdict,
        "k_to_neutral": k_neutral,
        "k_to_opposite": k_opposite,
        "k_weight_share": removed,
        "top_shares": [round(w / total, 4) for w in allw[:8]] if total > 0 else [],
        "top_sides": [side for _, side in ranked[:8]] if total > 0 else [],
        "ci_crosses_half": bool(crosses),
        "rules": ("Four flags, one point each: a call that flips if 2 or fewer wallets close, one wallet "
                  "holding 25% or more of the vote, a 95% interval that crosses 0.50, fewer than 20 voters."),
    }


LEVELS = {
    0: ("STURDY", "Spread across many hands. One wallet closing will not move it."),
    1: ("SOLID", "One soft spot. Fine, but know which one."),
    2: ("WOBBLY", "Two soft spots. A couple of wallets can shift this call."),
    3: ("JELLY", "Mostly goo. One whale sneezes and the call flips."),
}
