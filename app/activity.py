"""The last hour of top-wallet activity, per metal. Pure functions, no network.

The sweep keeps a short log of who held what (data/cohort.json, key "pos_log", about three hours of
snapshots). Comparing the snapshot nearest to one hour ago with the current one gives, per wallet, what
happened: opened, added, trimmed, closed or flipped. The aggregate flows reuse flow.flow_step, so the
numbers agree with the Flows tab.

Resolution is the sweep interval (about 30 minutes): "seen" is the first sweep that showed the new size,
not the minute of the trade. A position opened and closed between two sweeps is invisible.
"""

from __future__ import annotations

from typing import Any, Optional

from . import flow as F

HOUR_MS = 3_600_000
DUST_USD = 1_000.0          # same floor as the Who-moved table
LOG_KEEP_MS = 3 * HOUR_MS
LOG_MAX = 10
MIN_SPAN_MS = 20 * 60_000   # a base snapshot younger than this says nothing about "the hour"
TOP_ITEMS = 12


def classify_move(p: float, c: float) -> Optional[str]:
    """opened / closed / flipped / added / trimmed for a signed size change p -> c, else None."""
    if p == c:
        return None
    if p == 0:
        return "opened"
    if c == 0:
        return "closed"
    if (p > 0) != (c > 0):
        return "flipped"
    return "added" if abs(c) > abs(p) else "trimmed"


def side_of(kind: str, p: float, c: float) -> str:
    """The side the move is about. Opened, added and flipped: the side held now. Closed and trimmed: the side that shrank."""
    s = c if kind in ("opened", "added", "flipped") else p
    return "LONG" if s > 0 else "SHORT"


def entry_from(rows: list[dict[str, Any]], t_ms: int, mark: Optional[float]) -> dict[str, Any]:
    """One log row: non-zero sizes of wallets polled fine, plus the wallets whose poll failed (unknown, not closed)."""
    held, bad = {}, []
    for r in rows:
        a = r.get("address")
        if not a:
            continue
        if r.get("poll_error"):
            bad.append(a)
            continue
        szi = float(r.get("szi") or 0.0)
        if szi:
            held[a] = round(szi, 5)
    return {"t": int(t_ms), "mark": mark, "p": held, "bad": bad}


def prune(log: list[dict[str, Any]], now_ms: int) -> list[dict[str, Any]]:
    keep = [e for e in log if now_ms - e["t"] <= LOG_KEEP_MS]
    return keep[-LOG_MAX:]


def pick_base(log: list[dict[str, Any]], now_ms: int, window_ms: int = HOUR_MS) -> Optional[dict[str, Any]]:
    """The earlier snapshot closest to one window ago, at least 20 minutes old."""
    cands = [e for e in log if now_ms - e["t"] >= MIN_SPAN_MS]
    if not cands:
        return None
    return min(cands, key=lambda e: abs((now_ms - e["t"]) - window_ms))


def fmt_usd(x: float) -> str:
    a = abs(x)
    s = "+" if x > 0 else "−" if x < 0 else ""
    if a >= 1e6:
        return f"{s}${a / 1e6:.1f}M"
    if a >= 1e3:
        return f"{s}${a / 1e3:.0f}k" if a >= 1e4 else f"{s}${a / 1e3:.1f}k"
    return f"{s}${a:.0f}"


def _plural(n: int, word: str) -> str:
    return f"{n} wallet{'s' if n != 1 else ''} {word}"


PHRASE = {
    ("opened", "LONG"): "opened longs", ("opened", "SHORT"): "opened shorts",
    ("added", "LONG"): "added longs", ("added", "SHORT"): "added shorts",
    ("trimmed", "LONG"): "trimmed longs", ("trimmed", "SHORT"): "trimmed shorts",
    ("closed", "LONG"): "closed longs", ("closed", "SHORT"): "closed shorts",
    ("flipped", "LONG"): "flipped long", ("flipped", "SHORT"): "flipped short",
}


def summarise(groups: dict[tuple[str, str], dict[str, float]], span_min: Optional[int], metal: str, partial: bool) -> str:
    head = "last hour" if not partial or span_min is None else f"last {span_min} min"
    if not groups:
        return f"{head}: quiet. Nobody in the top 500 moved their {metal} by $1k or more."
    ranked = sorted(groups.items(), key=lambda kv: kv[1]["usd"], reverse=True)[:3]
    bits = []
    for (kind, side), g in ranked:
        n = int(g["n"])
        amt = f" ({fmt_usd(g['usd'])})" if kind != "flipped" else ""
        if kind in ("trimmed", "closed"):
            amt = f" ({fmt_usd(-g['usd'])})"
        bits.append(_plural(n, PHRASE[(kind, side)]) + amt)
    return f"{head}: " + ", ".join(bits)


def build(prev_log: list[dict[str, Any]], rows: list[dict[str, Any]], mark: Optional[float], now_ms: int,
          window_ms: int = HOUR_MS, metal: str = "gold") -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Returns (block for signal.json, new log). rows are the top cohort's flattened metal rows."""
    cur = entry_from(rows, now_ms, mark)
    log = prune([e for e in (prev_log or []) if e["t"] < now_ms] + [cur], now_ms)
    base = pick_base(log[:-1], now_ms, window_ms)
    if not base or not mark or mark <= 0:
        return ({"available": False,
                 "reason": "Building history: the last-hour view needs a snapshot that is at least 20 minutes old.",
                 "items": [], "counts": {}, "summary": "last hour: building history."}, log)

    unknown = set(base["bad"]) | set(cur["bad"])
    universe = (set(base["p"]) | set(cur["p"])) - unknown
    prev_full = {a: base["p"].get(a, 0.0) for a in universe}
    cur_full = {a: cur["p"].get(a, 0.0) for a in universe}
    span_ms = now_ms - base["t"]
    partial = span_ms < 0.75 * window_ms or span_ms > 1.5 * window_ms
    span_min = round(span_ms / 60_000)

    # Per wallet. "seen" is the first snapshot after the base that shows a different size.
    chain = [e for e in log if e["t"] >= base["t"]]
    items, groups = [], {}
    for a in sorted(universe):
        p, c = prev_full[a], cur_full[a]
        kind = classify_move(p, c)
        if not kind or abs(c - p) * mark < DUST_USD:
            continue
        side = side_of(kind, p, c)
        usd = abs(c - p) * mark
        seen = now_ms
        for before, after in zip(chain, chain[1:]):
            if after["p"].get(a, 0.0) != before["p"].get(a, 0.0):
                seen = after["t"]
                break
        items.append({"address": a, "kind": kind, "side": side, "prev": p, "cur": c, "usd": round(usd, 2),
                      "delta_usd": round((c - p) * mark, 2), "now_usd": round(abs(c) * mark, 2), "seen_ms": seen})
        g = groups.setdefault((kind, side), {"n": 0, "usd": 0.0})
        g["n"] += 1
        g["usd"] += usd
    items.sort(key=lambda i: i["usd"], reverse=True)

    step = F.flow_step(prev_full, cur_full, mark) or {}
    fl = step.get("flows") or dict.fromkeys(F.F_KEYS, 0.0)
    long_in, long_out = fl["oL"] + fl["aL"], fl["tL"] + fl["cL"]
    short_in, short_out = fl["oS"] + fl["aS"], fl["tS"] + fl["cS"]
    now_tot, base_tot = F.side_totals(cur_full, mark), F.side_totals(prev_full, mark)

    def share(t):
        g = t["long_ntl"] + t["short_ntl"]
        return None if g <= 0 else t["long_ntl"] / g

    counts = {k: sum(1 for i in items if i["kind"] == k) for k in ("opened", "added", "trimmed", "closed", "flipped")}
    price_move = None
    if base.get("mark"):
        price_move = mark / base["mark"] - 1.0
    block = {
        "available": True,
        "base_ms": base["t"], "now_ms": now_ms, "span_min": span_min, "partial": partial,
        "resolution_note": "Seen means the first sweep (about every 30 minutes) that showed the new size.",
        "counts": counts,
        "wallets_moved": len(items),
        "long_in_usd": round(long_in, 2), "long_out_usd": round(long_out, 2),
        "short_in_usd": round(short_in, 2), "short_out_usd": round(short_out, 2),
        "net_toward_long_usd": round((long_in - long_out) - (short_in - short_out), 2),
        "gross_moved_usd": round(long_in + long_out + short_in + short_out, 2),
        "flip_to_long": sum(1 for i in items if i["kind"] == "flipped" and i["side"] == "LONG"),
        "flip_to_short": sum(1 for i in items if i["kind"] == "flipped" and i["side"] == "SHORT"),
        "split_now": {"long_share": share(now_tot), "n_long": now_tot["n_long"], "n_short": now_tot["n_short"]},
        "split_then": {"long_share": share(base_tot), "n_long": base_tot["n_long"], "n_short": base_tot["n_short"]},
        "price_move": price_move,
        "summary": summarise(groups, span_min, metal, partial),
        "items": items[:TOP_ITEMS],
        "skipped_unreadable": len(unknown),
    }
    return block, log
