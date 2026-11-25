"""Scalp corner: a short-term lean from the last hour. Pure functions.

This is a rule of thumb on one hour of data. It is not the main signal, it never changes the verdict, and
it is not advice. The score blends three things, each scaled to -1..+1 (positive leans long):

  flow      net top-wallet dollars added long minus added short (closing a long counts as a short-side move),
            as a share of the cohort's gross notional; ignored when the hour was too quiet to mean anything
  momentum  the 1h price move in units of the metal's normal hourly swing (24h realised vol)
  funding   a small contrarian nudge: rich positive funding means longs are paying to stay long

score = 0.55 * flow + 0.30 * momentum + 0.15 * funding. Lean at +/-0.25. Weights and scales are in config.py;
none of them was fitted to data, so no hit rate is claimed anywhere.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from . import config

HOURS_PER_YEAR = 24 * 365


def _num(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def flow_score(hour: dict[str, Any], gross_notional: Optional[float]) -> tuple[float, bool]:
    """(score, counted). Not counted when the hour is unavailable or too quiet."""
    if not hour.get("available"):
        return 0.0, False
    moved = _num(hour.get("gross_moved_usd")) or 0.0
    if moved < config.SCALP_MIN_FLOW_USD or not gross_notional or gross_notional <= 0:
        return 0.0, False
    net = _num(hour.get("net_toward_long_usd")) or 0.0
    return clamp(net / (config.SCALP_FLOW_FULL * gross_notional)), True


def momentum_score(move: Optional[float], realised_vol: Optional[float]) -> tuple[float, bool]:
    m = _num(move)
    if m is None:
        return 0.0, False
    vol = _num(realised_vol)
    sigma = (vol / math.sqrt(HOURS_PER_YEAR)) if vol and vol > 0 else 0.003  # fall back to 0.3% an hour
    return clamp(m / (config.SCALP_MOVE_FULL_Z * sigma)), True


def funding_score(funding_hourly: Optional[float]) -> tuple[float, bool]:
    f = _num(funding_hourly)
    if f is None:
        return 0.0, False
    return clamp(-f / config.SCALP_FUNDING_FULL), True


def confidence_word(score: float, flow: float, move: float, flow_ok: bool, move_ok: bool, lean: str) -> str:
    agree = flow_ok and move_ok and flow * move > 0 and min(abs(flow), abs(move)) >= 0.15
    clash = flow_ok and move_ok and flow * move < 0 and min(abs(flow), abs(move)) >= 0.3
    if lean == "SIT OUT":
        if clash or not (flow_ok or move_ok):
            return "low"          # unsure: the pieces disagree or there is not enough data
        return "high" if abs(score) < 0.1 else "medium"
    a = abs(score)
    if a >= 0.6 and agree:
        return "high"
    if a >= 0.4 or agree:
        return "medium"
    return "low"


def _usd(x: float) -> str:
    a = abs(x)
    return f"${a / 1e6:.1f}M" if a >= 1e6 else f"${a / 1e3:.0f}k" if a >= 1e3 else f"${a:.0f}"


def reasons(metal: str, hour: dict[str, Any], move: Optional[float], funding: Optional[float],
            parts: dict[str, tuple[float, bool]], lean: str) -> list[str]:
    """Up to three plain-slang reasons, biggest contributor first."""
    name = metal.lower()
    out: list[tuple[float, str]] = []
    fs, f_ok = parts["flow"]
    ms, m_ok = parts["move"]
    gs, g_ok = parts["funding"]
    net = _num(hour.get("net_toward_long_usd")) or 0.0
    fl_s, fl_l = hour.get("flip_to_short") or 0, hour.get("flip_to_long") or 0
    if f_ok:
        side = "long" if net > 0 else "short"
        txt = f"The big wallets net moved {_usd(net)} toward {side}s in the last hour." if abs(fs) > 0.1 else \
            f"The big wallets traded {_usd(_num(hour.get('gross_moved_usd')) or 0)} but it came out about even."
        if fl_s or fl_l:
            bits = []
            if fl_s: bits.append(f"{fl_s} flipped short")
            if fl_l: bits.append(f"{fl_l} flipped long")
            txt += " " + " and ".join(bits).capitalize() + "."
        out.append((abs(fs) * config.SCALP_W_FLOW, txt))
    else:
        out.append((0.05, "The big wallets barely touched their bags this hour, so there is no flow to follow."
                    if hour.get("available") else "Not enough history yet to read the last hour of wallet flow."))
    if m_ok:
        mv = _num(move) or 0.0
        word = "up" if mv > 0 else "down"
        agree = (fs * ms > 0) if f_ok else None
        strong = abs(ms) >= 0.15
        tail = (" The tape is running with the wallets." if agree and strong
                else " The tape is running against the wallets." if agree is False and abs(ms) >= 0.3 else "")
        out.append((abs(ms) * config.SCALP_W_MOVE, f"{name.capitalize()} is {word} {abs(mv) * 100:.2f}% over the hour.{tail}"))
    if g_ok and abs(gs) >= 0.4:
        fh = _num(funding) or 0.0
        who = "longs are paying" if fh > 0 else "shorts are paying"
        crowd = "long" if fh > 0 else "short"
        out.append((abs(gs) * config.SCALP_W_FUND,
                    f"Funding: {who} {abs(fh) * HOURS_PER_YEAR * 100:.0f}% a year, so the {crowd} side is getting crowded."))
    out.sort(key=lambda t: t[0], reverse=True)
    res = [t for _, t in out[:3]]
    if lean == "SIT OUT" and f_ok and m_ok and fs * ms < 0 and min(abs(fs), abs(ms)) >= 0.3:
        res.insert(0, "Wallets and price disagree. Classic chop, ser.")
        res = res[:3]
    return res


LEAN_LINE = {
    "SCALP LONG": "Short-term lean: long. One hour of data only.",
    "SCALP SHORT": "Short-term lean: short. One hour of data only.",
    "SIT OUT": "Short-term lean: nothing clear. Sit on hands.",
}


def lean(metal: str, hour: Optional[dict[str, Any]], market: Optional[dict[str, Any]],
         gross_notional: Optional[float]) -> dict[str, Any]:
    hour = hour or {"available": False}
    market = market or {}
    move = hour.get("price_move") if hour.get("available") else None
    f, f_ok = flow_score(hour, gross_notional)
    m, m_ok = momentum_score(move, market.get("realised_vol_24h"))
    g, g_ok = funding_score(market.get("funding_hourly"))
    parts = {"flow": (f, f_ok), "move": (m, m_ok), "funding": (g, g_ok)}
    score = config.SCALP_W_FLOW * f + config.SCALP_W_MOVE * m + config.SCALP_W_FUND * g
    clash = f_ok and m_ok and f * m < 0 and min(abs(f), abs(m)) >= 0.3
    if not hour.get("available") or not (f_ok or m_ok):
        verdict = "SIT OUT"
    elif clash:
        verdict = "SIT OUT"
    elif score >= config.SCALP_LEAN_AT:
        verdict = "SCALP LONG"
    elif score <= -config.SCALP_LEAN_AT:
        verdict = "SCALP SHORT"
    else:
        verdict = "SIT OUT"
    conf = confidence_word(score, f, m, f_ok, m_ok, verdict)
    return {
        "lean": verdict,
        "confidence": conf,
        "score": round(score, 4),
        "parts": {"flow": round(f, 4), "momentum": round(m, 4), "funding": round(g, 4)},
        "used": {"flow": f_ok, "momentum": m_ok, "funding": g_ok},
        "reasons": reasons(metal, hour, move, market.get("funding_hourly"), parts, verdict),
        "window_min": hour.get("span_min"),
        "price_move_1h": _num(move),
        "funding_hourly": _num(market.get("funding_hourly")),
        "line": LEAN_LINE[verdict],
        "disclaimer": ("A short-term lean from one hour of public data. It is not advice and not the main signal; "
                       "the verdict above is. No hit rate is claimed for it."),
    }
