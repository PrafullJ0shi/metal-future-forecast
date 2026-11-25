"""Whale orders, orders worked over time, liquidations, and liquidation waves.

Pure functions, no I/O. Inputs are Hyperliquid `userFills` rows of tracked
wallets, consecutive position snapshots, and stored open-interest history.

Public data limits (stated on the page as well): the info API has no
market-wide liquidation feed. Liquidations are counted only when a tracked
wallet's own fills carry a `liquidation` record, either because the tracked
wallet was liquidated or because its resting order absorbed someone else's
liquidation. An open-interest drop during a sharp price move is reported as a
separate, clearly labelled proxy.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Optional, Sequence

HOUR_MS = 3_600_000
MIN_MS = 60_000

# Whale thresholds (USD notional). Metal books are about a tenth of BTC's, so the
# BTC project's USD 1m bars are scaled to USD 250k.
WHALE_POS_USD = 250_000.0        # one wallet's position change between two snapshots
WHALE_ORDER_USD = 250_000.0      # one order (all fills sharing an oid)
# Worked order (TWAP-like): same-side orders from one wallet.
TWAP_MIN_USD = 250_000.0
TWAP_MIN_ORDERS = 5
TWAP_MIN_MINUTES = 15.0
TWAP_MAX_ORDER_SHARE = 0.5       # no single order may carry more than half
TWAP_MAX_GAP_MIN = 45.0          # a pause longer than this ends the run
# Liquidation wave.
WAVE_WINDOW_MS = HOUR_MS
WAVE_MIN_USD = 250_000.0
WAVE_K = 5.0
WAVE_MIN_EVENTS = 3
# Open-interest proxy (one stored step of at most this length).
OI_STEP_MAX_MS = 75 * MIN_MS
OI_DROP_MIN = 0.015              # 1.5% fall in open interest
OI_RET_MIN = 0.010               # 1.0% price move in the same step
OI_Z_DROP = -3.0
OI_Z_RET = 2.0
OI_Z_MIN_PAIRS = 24

TAPE_MAX_MS = 7 * 24 * HOUR_MS


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return default if (math.isnan(x) or math.isinf(x)) else x
    except (TypeError, ValueError):
        return default


def fill_ntl(f: dict[str, Any]) -> float:
    return abs(_f(f.get("px")) * _f(f.get("sz")))


def fill_sign(f: dict[str, Any]) -> int:
    """+1 for a buy (adds long / reduces short), -1 for a sell."""
    return 1 if f.get("side") == "B" else -1


# ---------------------------------------------------------------------------
# Liquidations
# ---------------------------------------------------------------------------


def liquidations_from_fills(fills_by_wallet: dict[str, Sequence[dict[str, Any]]], coin: str) -> list[dict[str, Any]]:
    """Liquidation events visible in tracked wallets' fills.

    A fill with a `liquidation` record belongs to one liquidation order of
    `liquidatedUser`. If the tracked wallet *is* that user, the liquidated side
    is the side being closed. Otherwise the tracked wallet was the
    counterparty: if it bought, the liquidated wallet was selling, so a long
    was liquidated. Fills are deduplicated by trade id and grouped per
    (liquidated user, block time).
    """
    groups: dict[str, dict[str, Any]] = {}
    seen_tid: set = set()
    for wallet, fills in fills_by_wallet.items():
        for f in fills:
            liq = f.get("liquidation")
            if not liq or f.get("coin") != coin:
                continue
            tid = f.get("tid")
            if tid is not None and tid in seen_tid:
                continue
            seen_tid.add(tid)
            user = str(liq.get("liquidatedUser") or "").lower()
            if not user:
                continue
            own = user == wallet
            if own:
                start = _f(f.get("startPosition"))
                side = "LONG" if start > 0 else ("SHORT" if start < 0 else
                                                 ("LONG" if "Long" in str(f.get("dir")) else "SHORT"))
            else:
                side = "LONG" if f.get("side") == "B" else "SHORT"
            t = int(f.get("time") or 0)
            key = f"{user}:{t // 1000}"
            g = groups.setdefault(key, {
                "key": key, "t": t, "user": user, "side": side, "coin": coin,
                "ntl": 0.0, "sz": 0.0, "_pxsz": 0.0, "mark": _f(liq.get("markPx")) or None,
                "method": liq.get("method"), "via": [], "own": False, "tids": [],
            })
            n = fill_ntl(f)
            g["ntl"] += n
            g["sz"] += abs(_f(f.get("sz")))
            g["_pxsz"] += n
            g["own"] = g["own"] or own
            if wallet not in g["via"]:
                g["via"].append(wallet)
            if tid is not None:
                g["tids"].append(tid)
    out = []
    for g in groups.values():
        g["px"] = round(g["_pxsz"] / g["sz"], 2) if g["sz"] else None
        del g["_pxsz"]
        g["ntl"] = round(g["ntl"], 2)
        g["sz"] = round(g["sz"], 6)
        out.append(g)
    out.sort(key=lambda e: e["t"], reverse=True)
    return out


def merge_events(stored: Sequence[dict[str, Any]], new: Sequence[dict[str, Any]], now_ms: int,
                 cap: int = 600) -> list[dict[str, Any]]:
    """Union by key; for liquidations, add only fills whose trade id is new."""
    by_key = {e["key"]: dict(e) for e in stored if e.get("key")}
    for e in new:
        k = e.get("key")
        if k not in by_key:
            by_key[k] = dict(e)
            continue
        old = by_key[k]
        if "tids" in e and "tids" in old:
            old_t = set(old["tids"])
            fresh = [t for t in e["tids"] if t not in old_t]
            if fresh and e["tids"]:
                share = len(fresh) / len(e["tids"])
                old["ntl"] = round(old["ntl"] + e["ntl"] * share, 2)
                old["tids"] = (old["tids"] + fresh)[-50:]
            for v in e.get("via", []):
                if v not in old.get("via", []):
                    old.setdefault("via", []).append(v)
            old["own"] = old.get("own") or e.get("own")
        else:
            by_key[k] = {**old, **e}
    out = [e for e in by_key.values() if e.get("t", 0) >= now_ms - TAPE_MAX_MS]
    out.sort(key=lambda e: e.get("t", 0), reverse=True)
    return out[:cap]


def liquidation_wave(events: Sequence[dict[str, Any]], now_ms: int, observing_since: Optional[int]) -> dict[str, Any]:
    """Flag a wave when the last hour's seen liquidated notional is far above the recent hourly norm.

    norm = seen notional over the prior observed period (up to 7 days,
    excluding the last hour) divided by its length in hours.
    wave = last hour >= max(WAVE_MIN_USD, WAVE_K * norm) and >= WAVE_MIN_EVENTS events.
    """
    t0 = now_ms - WAVE_WINDOW_MS
    recent = [e for e in events if e.get("t", 0) > t0]
    l1 = sum(_f(e.get("ntl")) for e in recent)
    longs = sum(_f(e.get("ntl")) for e in recent if e.get("side") == "LONG")
    start = max(now_ms - TAPE_MAX_MS, observing_since or now_ms)
    prior_h = max(0.0, (t0 - start) / HOUR_MS)
    prior = [e for e in events if start <= e.get("t", 0) <= t0]
    prior_sum = sum(_f(e.get("ntl")) for e in prior)
    norm = prior_sum / prior_h if prior_h >= 1.0 else None
    threshold = max(WAVE_MIN_USD, WAVE_K * norm) if norm is not None else WAVE_MIN_USD
    wave = l1 >= threshold and len(recent) >= WAVE_MIN_EVENTS
    side = None
    if l1 > 0:
        side = "LONG" if longs >= l1 / 2 else "SHORT"
    return {
        "wave": wave,
        "last_hour_usd": round(l1, 2),
        "last_hour_events": len(recent),
        "last_hour_long_usd": round(longs, 2),
        "last_hour_short_usd": round(l1 - longs, 2),
        "dominant_side": side,
        "norm_hourly_usd": None if norm is None else round(norm, 2),
        "threshold_usd": round(threshold, 2),
        "ratio": None if not norm else round(l1 / norm, 2),
        "observed_hours": round((now_ms - start) / HOUR_MS, 1),
    }


def hourly_series(events: Sequence[dict[str, Any]], now_ms: int, hours: int = 48) -> list[list]:
    """[[hour_start_ms, long_usd, short_usd], ...] oldest first."""
    end = (now_ms // HOUR_MS + 1) * HOUR_MS
    start = end - hours * HOUR_MS
    buckets = {start + i * HOUR_MS: [0.0, 0.0] for i in range(hours)}
    for e in events:
        t = e.get("t", 0)
        if not (start <= t < end):
            continue
        b = start + ((t - start) // HOUR_MS) * HOUR_MS
        buckets[b][0 if e.get("side") == "LONG" else 1] += _f(e.get("ntl"))
    return [[k, round(v[0], 2), round(v[1], 2)] for k, v in sorted(buckets.items())]


def robust_z(x: float, sample: Sequence[float]) -> Optional[float]:
    """(x - median) / (1.4826 * MAD); None when the sample is degenerate."""
    if len(sample) < 3:
        return None
    med = statistics.median(sample)
    mad = statistics.median(abs(s - med) for s in sample)
    if mad <= 0:
        return None
    return (x - med) / (1.4826 * mad)


def oi_proxy(points: Sequence[dict[str, Any]], now_ms: int) -> dict[str, Any]:
    """Open-interest drop with a sharp price move, step by step.

    points: [{"_ms", "oi" (coin units), "mark"}], oldest first, including now.
    A step is flagged when OI falls by at least OI_DROP_MIN while price moves
    at least OI_RET_MIN, or (with enough history) when both moves are extreme
    in robust z terms. Falling price marks long liquidations as the likely
    cause; rising price marks shorts. Closed positions also lower OI, so the
    estimate is an upper bound, not a count of liquidations.
    """
    pts = [p for p in points if p.get("oi") and p.get("mark") and p.get("_ms")]
    pts.sort(key=lambda p: p["_ms"])
    steps = []
    for a, b in zip(pts, pts[1:]):
        dt = b["_ms"] - a["_ms"]
        if dt <= 0 or dt > OI_STEP_MAX_MS:
            continue
        d_oi = b["oi"] / a["oi"] - 1.0
        ret = b["mark"] / a["mark"] - 1.0
        steps.append({"t": b["_ms"], "d_oi": d_oi, "ret": ret,
                      "usd": max(0.0, (a["oi"] - b["oi"]) * b["mark"])})
    recent = [s for s in steps if s["t"] >= now_ms - TAPE_MAX_MS]
    flagged = []
    for i, s in enumerate(recent):
        prior = recent[:i]
        z_oi = robust_z(s["d_oi"], [p["d_oi"] for p in prior]) if len(prior) >= OI_Z_MIN_PAIRS else None
        z_ret = robust_z(s["ret"], [p["ret"] for p in prior]) if len(prior) >= OI_Z_MIN_PAIRS else None
        rule = s["d_oi"] <= -OI_DROP_MIN and abs(s["ret"]) >= OI_RET_MIN
        zrule = z_oi is not None and z_ret is not None and z_oi <= OI_Z_DROP and abs(z_ret) >= OI_Z_RET
        s["z_oi"] = None if z_oi is None else round(z_oi, 2)
        s["z_ret"] = None if z_ret is None else round(z_ret, 2)
        s["flag"] = bool(rule or zrule)
        if s["flag"]:
            flagged.append({
                "t": s["t"], "d_oi": round(s["d_oi"], 5), "ret": round(s["ret"], 5),
                "usd": round(s["usd"], 2), "side": "LONG" if s["ret"] < 0 else "SHORT",
            })
    last = recent[-1] if recent else None
    return {
        "available": bool(recent),
        "steps": len(recent),
        "latest": None if not last else {
            "t": last["t"], "d_oi": round(last["d_oi"], 5), "ret": round(last["ret"], 5),
            "z_oi": last.get("z_oi"), "z_ret": last.get("z_ret"), "flag": last.get("flag", False),
            "usd": round(last["usd"], 2),
        },
        "flagged": flagged[-20:],
        "rule": f"open interest down at least {OI_DROP_MIN * 100:.1f}% while price moves at least "
                f"{OI_RET_MIN * 100:.1f}% within one stored step, or a robust z-score of the open-interest change "
                f"at or below {str(OI_Z_DROP).replace('-', chr(0x2212)).replace('.0', '')} with the price move's z-score at least {OI_Z_RET:g} in size.",
    }


# ---------------------------------------------------------------------------
# Whale orders and orders worked over time
# ---------------------------------------------------------------------------


def orders_from_fills(fills: Sequence[dict[str, Any]], coin: str) -> list[dict[str, Any]]:
    """Group one wallet's fills into orders (shared oid), oldest first.

    Fills that carry a liquidation record are excluded: absorbing someone
    else's liquidation, or being liquidated, is not a decision to trade.
    """
    by_oid: dict[Any, dict[str, Any]] = {}
    for f in fills:
        if f.get("coin") != coin:
            continue
        if f.get("liquidation"):
            continue
        oid = f.get("oid")
        o = by_oid.setdefault(oid, {
            "oid": oid, "t0": int(f["time"]), "t1": int(f["time"]), "sign": fill_sign(f),
            "ntl": 0.0, "sz": 0.0, "n_fills": 0, "crossed": 0, "twap_id": f.get("twapId"),
            "dir": f.get("dir"), "start": _f(f.get("startPosition")),
        })
        o["t0"] = min(o["t0"], int(f["time"]))
        o["t1"] = max(o["t1"], int(f["time"]))
        o["ntl"] += fill_ntl(f)
        o["sz"] += abs(_f(f.get("sz")))
        o["n_fills"] += 1
        o["crossed"] += 1 if f.get("crossed") else 0
        if f.get("twapId") is not None:
            o["twap_id"] = f.get("twapId")
    out = sorted(by_oid.values(), key=lambda o: o["t0"])
    for o in out:
        o["px"] = o["ntl"] / o["sz"] if o["sz"] else None
    return out


def large_orders(orders: Sequence[dict[str, Any]], min_usd: float = WHALE_ORDER_USD) -> list[dict[str, Any]]:
    return [o for o in orders if o["ntl"] >= min_usd]


def worked_runs(orders: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect one large order worked over time.

    Native TWAP slices (fills that carry a twapId) are grouped by that id.
    Otherwise a run is a maximal sequence of same-side orders with no
    opposite-side order between them and no pause longer than
    TWAP_MAX_GAP_MIN. A run qualifies when it has at least TWAP_MIN_ORDERS
    orders, lasts at least TWAP_MIN_MINUTES, totals at least TWAP_MIN_USD,
    and no single order carries more than TWAP_MAX_ORDER_SHARE of it.
    """
    runs: list[dict[str, Any]] = []
    native: dict[Any, list] = {}
    rest = []
    for o in orders:
        if o.get("twap_id") is not None:
            native.setdefault(o["twap_id"], []).append(o)
        else:
            rest.append(o)
    for tid, os_ in native.items():
        r = _summarise_run(os_, "native")
        r["twap_id"] = tid
        if r["ntl"] >= TWAP_MIN_USD:
            runs.append(r)
    cur: list = []
    for o in rest:
        if cur and (o["sign"] != cur[-1]["sign"] or (o["t0"] - cur[-1]["t1"]) > TWAP_MAX_GAP_MIN * MIN_MS):
            _maybe_run(cur, runs)
            cur = []
        cur.append(o)
    _maybe_run(cur, runs)
    runs.sort(key=lambda r: r["t1"])
    return runs


def _maybe_run(cur: list, runs: list) -> None:
    if len(cur) < TWAP_MIN_ORDERS:
        return
    r = _summarise_run(cur, "pattern")
    if r["ntl"] < TWAP_MIN_USD or r["minutes"] < TWAP_MIN_MINUTES or r["max_share"] > TWAP_MAX_ORDER_SHARE:
        return
    runs.append(r)


def _summarise_run(os_: Sequence[dict[str, Any]], kind: str) -> dict[str, Any]:
    ntl = sum(o["ntl"] for o in os_)
    sz = sum(o["sz"] for o in os_)
    t0 = min(o["t0"] for o in os_)
    t1 = max(o["t1"] for o in os_)
    gaps = [(b["t0"] - a["t1"]) / MIN_MS for a, b in zip(os_, os_[1:])]
    return {
        "kind": kind,
        "sign": os_[0]["sign"],
        "orders": len(os_),
        "fills": sum(o["n_fills"] for o in os_),
        "ntl": round(ntl, 2),
        "sz": round(sz, 6),
        "vwap": round(ntl / sz, 2) if sz else None,
        "t0": t0,
        "t1": t1,
        "minutes": round((t1 - t0) / MIN_MS, 1),
        "median_gap_min": round(statistics.median(gaps), 2) if gaps else None,
        "max_share": round(max(o["ntl"] for o in os_) / ntl, 3) if ntl else 1.0,
        "taker_share": round(sum(o["crossed"] for o in os_) / max(1, sum(o["n_fills"] for o in os_)), 3),
        "first_oid": os_[0]["oid"],
        "effect": run_effect(os_),
    }


def run_effect(os_: Sequence[dict[str, Any]]) -> Optional[str]:
    """What the run did to the position, by notional: e.g. "Close Short" or "Open Long"."""
    by: dict[str, float] = {}
    for o in os_:
        d = str(o.get("dir") or "")
        if d:
            by[d] = by.get(d, 0.0) + o["ntl"]
    return max(by, key=by.get) if by else None


def run_method(r: dict[str, Any]) -> str:
    if r["kind"] == "native":
        return "native TWAP"
    return "TWAP-like, taker slices" if r.get("taker_share", 0) >= 0.5 else "passive accumulation, resting orders"


def action_of(prev: float, cur: float) -> Optional[tuple[str, str]]:
    """(verb, side) for a position change, e.g. ("added", "LONG")."""
    if prev == cur:
        return None
    if prev == 0:
        return ("opened", "LONG" if cur > 0 else "SHORT")
    if cur == 0:
        return ("closed", "LONG" if prev > 0 else "SHORT")
    if (prev > 0) != (cur > 0):
        return ("flipped to", "LONG" if cur > 0 else "SHORT")
    side = "LONG" if cur > 0 else "SHORT"
    return ("added to" if abs(cur) > abs(prev) else "trimmed", side)


def vwap_between(orders: Sequence[dict[str, Any]], t0: int, t1: int, sign_: int) -> Optional[float]:
    sel = [o for o in orders if t0 < o["t1"] <= t1 and o["sign"] == sign_]
    sz = sum(o["sz"] for o in sel)
    return round(sum(o["ntl"] for o in sel) / sz, 2) if sz else None


def position_events(
    changes: Sequence[dict[str, Any]],
    *,
    t_prev: Optional[int],
    t_now: int,
    mark: float,
    orders_by_wallet: dict[str, list[dict[str, Any]]],
    runs_by_wallet: dict[str, list[dict[str, Any]]],
    min_usd: float = WHALE_POS_USD,
) -> list[dict[str, Any]]:
    """Whale cards from snapshot diffs.

    changes: [{"address", "cohort", "prev", "cur", "row": observed row, "meta": {...}}]
    Change notional is |cur - prev| * mark (trades, not price moves).
    """
    out = []
    for ch in changes:
        p, c = _f(ch.get("prev")), _f(ch.get("cur"))
        d_ntl = abs(c - p) * mark
        if d_ntl < min_usd:
            continue
        act = action_of(p, c)
        if not act:
            continue
        verb, side = act
        row = ch.get("row") or {}
        meta = ch.get("meta") or {}
        trade_sign = 1 if c > p else -1
        orders = orders_by_wallet.get(ch["address"], [])
        lo = t_prev if t_prev else t_now - 2 * HOUR_MS
        px = vwap_between(orders, lo, t_now, trade_sign)
        worked = None
        for r in runs_by_wallet.get(ch["address"], []):
            if r["sign"] == trade_sign and r["t1"] > lo:
                worked = {k: r[k] for k in ("kind", "orders", "minutes", "ntl", "vwap", "t0", "t1", "taker_share")}
                worked["method"] = run_method(r)
        t_evt = max((o["t1"] for o in orders if lo < o["t1"] <= t_now and o["sign"] == trade_sign), default=t_now)
        out.append({
            "key": f"pos:{ch['address']}:{t_now}",
            "kind": "position",
            "t": t_evt,
            "t_snap": t_now,
            "t_prev": t_prev,
            "address": ch["address"],
            "cohort": ch.get("cohort"),
            "rank": meta.get("rank"),
            "rank_of": meta.get("rank_of"),
            "verb": verb,
            "side": side,
            "change_usd": round(d_ntl, 2),
            "before_usd": round(abs(p) * mark, 2),
            "now_usd": round(abs(c) * mark, 2),
            "before_side": "LONG" if p > 0 else ("SHORT" if p < 0 else "FLAT"),
            "px": px,
            "px_source": "fills" if px else "mark",
            "mark": round(mark, 2),
            "leverage": row.get("leverage"),
            "leverage_type": row.get("leverage_type"),
            "margin_usd": row.get("margin_used"),
            "upnl_usd": row.get("unrealized_pnl"),
            "roe": row.get("roe"),
            "all_time_pnl": meta.get("all_time_pnl"),
            "month_pnl": meta.get("month_pnl"),
            "worked": worked,
        })
    return out


def run_events(runs_by_wallet: dict[str, list[dict[str, Any]]], meta_by_wallet: dict[str, dict[str, Any]],
               rows_by_wallet: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for a, runs in runs_by_wallet.items():
        meta = meta_by_wallet.get(a, {})
        row = rows_by_wallet.get(a, {})
        for r in runs:
            out.append({
                "key": f"run:{a}:{r['twap_id'] if r.get('twap_id') is not None else r['first_oid']}",
                "kind": "worked",
                "t": r["t1"],
                "address": a,
                "cohort": meta.get("cohort"),
                "rank": meta.get("rank"),
                "rank_of": meta.get("rank_of"),
                "side": "BUY" if r["sign"] > 0 else "SELL",
                "method": run_method(r),
                "effect": r.get("effect"),
                **{k: r[k] for k in ("orders", "fills", "ntl", "vwap", "t0", "t1", "minutes",
                                     "median_gap_min", "max_share", "taker_share")},
                "pos_side_now": row.get("_side"),
                "pos_usd_now": row.get("notional"),
                "all_time_pnl": meta.get("all_time_pnl"),
                "month_pnl": meta.get("month_pnl"),
            })
    return out


def order_events(orders_by_wallet: dict[str, list[dict[str, Any]]], meta_by_wallet: dict[str, dict[str, Any]],
                 min_usd: float = WHALE_ORDER_USD) -> list[dict[str, Any]]:
    out = []
    for a, orders in orders_by_wallet.items():
        meta = meta_by_wallet.get(a, {})
        for o in large_orders(orders, min_usd):
            out.append({
                "key": f"ord:{a}:{o['oid']}",
                "kind": "order",
                "t": o["t1"],
                "address": a,
                "cohort": meta.get("cohort"),
                "rank": meta.get("rank"),
                "rank_of": meta.get("rank_of"),
                "side": "BUY" if o["sign"] > 0 else "SELL",
                "dir": o.get("dir"),
                "ntl": round(o["ntl"], 2),
                "px": round(o["px"], 2) if o.get("px") else None,
                "fills": o["n_fills"],
                "taker": o["crossed"] > 0,
                "all_time_pnl": meta.get("all_time_pnl"),
                "month_pnl": meta.get("month_pnl"),
            })
    return out
