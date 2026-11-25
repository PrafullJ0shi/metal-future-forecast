"""Position flow between consecutive cohort snapshots, and the contrast cohort.

Pure functions, no I/O. A "step" compares two snapshots of per-wallet signed
size (coin units) and splits the change into opened / added / closed /
trimmed for each side. Sizes are valued at the current mark, so a step counts
trades, not price moves.
"""

from __future__ import annotations

import math
from typing import Any, Optional, Sequence

HOUR_MS = 3_600_000
# Timeframes offered by the flow box, in hours.
WINDOWS_H = (1, 4, 8, 12, 24, 48, 168)
WINDOW_LABELS = {1: "1h", 4: "4h", 8: "8h", 12: "12h", 24: "24h", 48: "48h", 168: "1w"}
# Keep a little more than the longest window.
FLOW_LOG_MAX_MS = 8 * 24 * HOUR_MS
# A size change worth less than this (USD) is treated as rounding noise.
DUST_USD = 1.0
# Index layout of one stored step vector.
F_KEYS = ("oL", "aL", "cL", "tL", "oS", "aS", "cS", "tS")
CONTRAST_N = 500


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return default if (math.isnan(x) or math.isinf(x)) else x
    except (TypeError, ValueError):
        return default


def _szi(v: Any) -> float:
    return _f(v[0] if isinstance(v, list) else v)


# ---------------------------------------------------------------------------
# Contrast cohort
# ---------------------------------------------------------------------------


def contrast_candidates(
    rows: Sequence[dict[str, Any]],
    *,
    min_equity: float,
    max_turnover: float,
    exclude: set[str],
    n: int = CONTRAST_N,
) -> list[dict[str, Any]]:
    """The worst one-month performers on the public leaderboard.

    Same equity floor and turnover cap as the top cohort; month PnL must be
    negative. Sorted by month PnL ascending (rank 1 = largest loss).
    """
    out = []
    for row in rows:
        addr = str(row.get("ethAddress") or "").lower()
        if not addr or addr in exclude:
            continue
        equity = _f(row.get("accountValue"))
        try:
            month = dict(row.get("windowPerformances") or []).get("month") or {}
        except (TypeError, ValueError):
            month = {}
        pnl = _f(month.get("pnl"))
        vlm = _f(month.get("vlm"))
        if equity < min_equity or pnl >= 0:
            continue
        if equity <= 0 or vlm / equity > max_turnover:
            continue
        out.append({
            "address": addr,
            "display_name": row.get("displayName"),
            "leaderboard_equity": equity,
            "leaderboard_month_pnl": pnl,
            "turnover": vlm / equity,
        })
    out.sort(key=lambda r: r["leaderboard_month_pnl"])
    return out[:n]


# ---------------------------------------------------------------------------
# One step between two snapshots
# ---------------------------------------------------------------------------


def split_change(p: float, c: float) -> dict[str, float]:
    """Split one wallet's size change p -> c (signed coin units) by side.

    A flip closes the old side in full and opens the new side in full.
    Returned amounts are non-negative coin units.
    """
    out = dict.fromkeys(F_KEYS, 0.0)
    if p == c:
        return out
    if p > 0:
        if c >= p:
            out["aL"] = c - p
        elif c > 0:
            out["tL"] = p - c
        else:
            out["cL"] = p
    elif p < 0:
        if c <= p:
            out["aS"] = p - c
        elif c < 0:
            out["tS"] = c - p
        else:
            out["cS"] = -p
    if p <= 0 < c:
        out["oL"] = c
    if c < 0 <= p:
        out["oS"] = -c
    return out


def flow_step(
    prev: Optional[dict[str, Any]],
    cur: dict[str, Any],
    mark: Optional[float],
) -> Optional[dict[str, Any]]:
    """Aggregate flow for wallets present in both snapshots.

    prev / cur: {address: szi} (or {address: [szi, ...]}).
    Returns USD amounts (size * current mark), the count and short ids of
    wallets that traded, and the side totals of the current snapshot.
    """
    px = _f(mark)
    if px <= 0:
        return None
    totals = side_totals(cur, px)
    if not prev:
        return {"flows": None, "totals": totals}
    agg = dict.fromkeys(F_KEYS, 0.0)
    traded: list[str] = []
    common = 0
    for a, cv in cur.items():
        if a not in prev:
            continue
        common += 1
        p, c = _szi(prev[a]), _szi(cv)
        if abs(c - p) * px < DUST_USD:
            continue
        parts = split_change(p, c)
        for k in F_KEYS:
            agg[k] += parts[k] * px
        traded.append(a[2:8] if a.startswith("0x") else a[:6])
    return {
        "flows": {k: round(v, 2) for k, v in agg.items()},
        "traded": traded,
        "compared": common,
        "totals": totals,
    }


def side_totals(pos: dict[str, Any], px: float) -> dict[str, float]:
    long_ntl = short_ntl = 0.0
    n_long = n_short = 0
    for v in pos.values():
        s = _szi(v)
        if s > 0:
            long_ntl += s * px
            n_long += 1
        elif s < 0:
            short_ntl += -s * px
            n_short += 1
    return {
        "long_ntl": round(long_ntl, 2),
        "short_ntl": round(short_ntl, 2),
        "n_long": n_long,
        "n_short": n_short,
        "members": len(pos),
    }


def pack_step(step: Optional[dict[str, Any]]) -> Optional[list]:
    """Compact list form stored in cohort.json flow_log."""
    if not step:
        return None
    t = step["totals"]
    fl = step.get("flows")
    return [
        [fl[k] for k in F_KEYS] if fl else None,
        step.get("traded") or [],
        step.get("compared") or 0,
        t["long_ntl"], t["short_ntl"], t["n_long"], t["n_short"], t["members"],
    ]


def unpack_step(v: Optional[list]) -> Optional[dict[str, Any]]:
    if not v:
        return None
    fl = dict(zip(F_KEYS, v[0])) if v[0] else None
    return {
        "flows": fl,
        "traded": v[1],
        "compared": v[2],
        "totals": {"long_ntl": v[3], "short_ntl": v[4], "n_long": v[5], "n_short": v[6], "members": v[7]},
    }


def append_log(
    log: list[dict[str, Any]],
    t_ms: int,
    tp_ms: Optional[int],
    steps: dict[str, Optional[dict[str, Any]]],
    src: str = "live",
) -> list[dict[str, Any]]:
    """Add one row ({t, tp, src, s, c}) and drop rows older than FLOW_LOG_MAX_MS."""
    row = {"t": int(t_ms), "tp": int(tp_ms) if tp_ms else None, "src": src}
    for key, step in steps.items():
        row[key] = pack_step(step)
    out = [r for r in log if r.get("t") != row["t"]] + [row]
    out.sort(key=lambda r: r["t"])
    return [r for r in out if r["t"] >= t_ms - FLOW_LOG_MAX_MS]


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------


def window_tolerance_ms(hours: float) -> int:
    """How far the baseline snapshot may sit from exactly `hours` ago."""
    return int(max(25 * 60_000, 0.15 * hours * HOUR_MS))


def short_share(totals: Optional[dict[str, Any]]) -> Optional[float]:
    if not totals:
        return None
    tot = _f(totals.get("long_ntl")) + _f(totals.get("short_ntl"))
    return _f(totals.get("short_ntl")) / tot if tot > 0 else None


def _gap_reason(have_h: float, hours: float, base_t: Optional[int], target: float, tol: int) -> str:
    """Why a window is unavailable, in plain words."""
    if have_h < 1 / 60:
        return "Building history: the first snapshot is stored; flows start with the next sweep."
    if base_t is not None and have_h * HOUR_MS >= hours * HOUR_MS - tol:
        off = round(abs(base_t - target) / 60_000)
        return (f"No sweep was stored close enough to {_dur(hours)} ago (nearest {off} min off, "
                f"at most {round(tol / 60_000)} min allowed); sweeps run on an irregular schedule.")
    return f"Building history: {_dur(have_h)} of {_dur(hours)} stored."


def window_flow(log: Sequence[dict[str, Any]], key: str, now_ms: int, hours: float) -> dict[str, Any]:
    """Sum the steps of one cohort over the last `hours`.

    The baseline is the stored snapshot closest to now - hours (within the
    tolerance); every step after it is summed. The window is reported as
    unavailable ("building history") when no snapshot is close enough.
    """
    rows = sorted((r for r in log if r.get(key)), key=lambda r: r["t"])
    label = WINDOW_LABELS.get(int(hours), f"{hours:g}h")
    if not rows:
        return {"window": label, "available": False, "reason": "Building history."}
    latest = rows[-1]
    target = latest["t"] - hours * HOUR_MS
    tol = window_tolerance_ms(hours)
    # Usable baselines: a stored snapshot (row t), or the start (tp) of a step with flows.
    # Every step after the baseline must carry flows, or the window is incomplete.
    snap_times = sorted({r["t"] for r in rows} | {r["tp"] for r in rows if r.get("tp") and r[key][0]})
    last_gap = max((r["t"] for r in rows if not r[key][0]), default=None)
    usable = [t for t in snap_times if last_gap is None or t >= last_gap]
    have_h = (latest["t"] - usable[0]) / HOUR_MS if usable else 0.0
    base_t = min(usable, key=lambda t: abs(t - target)) if usable else None
    if base_t is None or abs(base_t - target) > tol or base_t >= latest["t"]:
        return {
            "window": label,
            "available": False,
            "reason": _gap_reason(have_h, hours, base_t, target, tol),
            "have_hours": round(have_h, 2),
        }
    steps = [r for r in rows if r["t"] > base_t]
    agg = dict.fromkeys(F_KEYS, 0.0)
    traded: set[str] = set()
    sources = set()
    complete = True
    for r in steps:
        st = unpack_step(r[key])
        if not st or not st["flows"]:
            complete = False
            continue
        for k in F_KEYS:
            agg[k] += _f(st["flows"].get(k))
        traded.update(st["traded"])
        sources.add(r.get("src", "live"))
    base_row = next((r for r in rows if r["t"] == base_t), None)
    after = unpack_step(latest[key])["totals"]
    before = unpack_step(base_row[key])["totals"] if base_row else None
    longs = agg["oL"] + agg["aL"] - agg["cL"] - agg["tL"]
    shorts = agg["oS"] + agg["aS"] - agg["cS"] - agg["tS"]
    if before is None:
        # First row's baseline is not stored as a row: back it out from the flows.
        before = {
            "long_ntl": max(0.0, after["long_ntl"] - longs),
            "short_ntl": max(0.0, after["short_ntl"] - shorts),
        }
    toward_long = longs - shorts
    return {
        "window": label,
        "available": True,
        "hours": hours,
        "base_ms": base_t,
        "end_ms": latest["t"],
        "span_hours": round((latest["t"] - base_t) / HOUR_MS, 2),
        "steps": len(steps),
        "complete": complete,
        "sources": sorted(sources),
        "flows": {k: round(v, 2) for k, v in agg.items()},
        "longs_in": round(agg["oL"] + agg["aL"], 2),
        "longs_out": round(agg["cL"] + agg["tL"], 2),
        "shorts_in": round(agg["oS"] + agg["aS"], 2),
        "shorts_out": round(agg["cS"] + agg["tS"], 2),
        "longs_net": round(longs, 2),
        "shorts_net": round(shorts, 2),
        "toward_long": round(toward_long, 2),
        "direction": "LONG" if toward_long > 0 else ("SHORT" if toward_long < 0 else "NONE"),
        "wallets_traded": len(traded),
        "short_share_before": _round(short_share(before)),
        "short_share_after": _round(short_share(after)),
        "long_ntl": after["long_ntl"],
        "short_ntl": after["short_ntl"],
    }


def _dur(h: float) -> str:
    if h < 1:
        return f"{max(0, round(h * 60))} min"
    if h >= 48 and h % 24 == 0:
        return f"{h / 24:g} days"
    return f"{h:.1f} h".replace(".0 h", " h")


def _round(x: Optional[float], nd: int = 4) -> Optional[float]:
    return None if x is None else round(x, nd)


def fmt_usd(x: float) -> str:
    """$18.37m, $930k, $1.20b (the plate's style). Sign is not included."""
    a = abs(x)
    if a >= 1e9:
        return f"${a / 1e9:.2f}b"
    if a >= 1e6:
        return f"${a / 1e6:.2f}m"
    if a >= 1e3:
        return f"${a / 1e3:.0f}k"
    return f"${a:.0f}"


def price_move(prices: Sequence[tuple[int, float]], t0: int, t1: int) -> Optional[float]:
    """Relative price change between the samples nearest t0 and t1."""
    if not prices:
        return None
    p0 = min(prices, key=lambda x: abs(x[0] - t0))
    p1 = min(prices, key=lambda x: abs(x[0] - t1))
    if abs(p0[0] - t0) > 2 * HOUR_MS or abs(p1[0] - t1) > 2 * HOUR_MS or p0[1] <= 0:
        return None
    return p1[1] / p0[1] - 1.0


# Price moves smaller than this are described as flat.
FLAT_MOVE = 0.003


def headline(name: str, w: dict[str, Any], move: Optional[float]) -> str:
    """One plain sentence: what the cohort did, set against the price move."""
    if not w.get("available"):
        r = w.get("reason", "Building history.")
        return f"{name}: {r[0].lower() + r[1:]}"
    tl = w["toward_long"]
    if abs(tl) < 1.0:
        return f"{name} did not change its positioning."
    side = "long" if tl > 0 else "short"
    if move is None or abs(move) < FLAT_MOVE:
        ctx = "while price was flat"
    elif move < 0:
        ctx = "into a falling price"
    else:
        ctx = "into a rising price"
    return f"{name} moved {fmt_usd(tl)} toward {side} {ctx}."


def window_sentence(name: str, w: dict[str, Any], base_label: str) -> str:
    """'The top cohort is $18.37M more long than at 05:05: $30.20M went into longs, $11.83M came out.'"""
    if not w.get("available"):
        return w.get("reason", "Building history.")

    def side(word: str, net: float, i: float, o: float) -> str:
        if i < 1.0 and o < 1.0:
            return f"no {word} were opened, added, trimmed, or closed"
        return (f"it is {fmt_usd(net)} {'more' if net >= 0 else 'less'} {word[:-1]} than at {base_label}: "
                f"{fmt_usd(i)} went into {word} and {fmt_usd(o)} came out")

    s = (f"{name}: {side('longs', w['longs_net'], w['longs_in'], w['longs_out'])}; "
         f"{side('shorts', w['shorts_net'], w['shorts_in'], w['shorts_out'])}.")
    return s


def compare_sentence(label: str, a: dict[str, Any], b: dict[str, Any]) -> str:
    """'In the last 4 hours the top cohort moved toward long; the worst-performing cohort moved toward short.'"""
    def d(w):
        if not w.get("available"):
            return None
        if abs(w["toward_long"]) < 1.0:
            return "did not move"
        return "moved toward " + ("long" if w["toward_long"] > 0 else "short")
    da, db = d(a), d(b)
    if da is None and db is None:
        return "Neither cohort has a reading for this window yet."
    parts = []
    if da:
        parts.append(f"the top cohort {da}")
    if db:
        parts.append(f"the worst-performing cohort {db}")
    s = f"In the last {label} " + "; ".join(parts) + "."
    if da and db and da.startswith("moved") and db.startswith("moved") and da != db:
        s += " The two cohorts moved in opposite directions."
    return s[0].upper() + s[1:]
