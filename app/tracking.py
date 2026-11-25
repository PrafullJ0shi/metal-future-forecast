"""Flow box, top versus worst-performing cohort, whale tape, and liquidations.

Network calls (fetch_fills) are here; the maths lives in flow.py and tape.py.
State is kept in data/cohort.json under the keys "tracker_positions",
"flow_log", and "tape", which the existing workflow already commits.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from . import config
from . import flow as F
from . import tape as T

log = logging.getLogger("tracking")

HOUR_MS = 3_600_000


def ts_ms(ts_utc: Optional[str]) -> Optional[int]:
    from datetime import datetime
    if not ts_utc:
        return None
    try:
        return int(datetime.fromisoformat(ts_utc.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def iso_from_ms(ms: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clock_ist(ms: Optional[int]) -> Optional[str]:
    from datetime import datetime, timezone
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%H:%M UTC")


def leaderboard_meta(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """address -> {all_time_pnl, month_pnl} from the public leaderboard."""
    out = {}
    for row in rows:
        a = str(row.get("ethAddress") or "").lower()
        if not a:
            continue
        try:
            wp = dict(row.get("windowPerformances") or [])
        except (TypeError, ValueError):
            wp = {}
        out[a] = {
            "all_time_pnl": F._f((wp.get("allTime") or {}).get("pnl"), None),
            "month_pnl": F._f((wp.get("month") or {}).get("pnl"), None),
        }
    return out


def positions_with_carry(observed: list[dict[str, Any]], prev: Optional[dict[str, Any]]) -> dict[str, float]:
    """{address: szi}. A wallet whose poll failed keeps its last known size,
    so a failed request is never read as a closed position."""
    prev = prev or {}
    out = {}
    for r in observed:
        a = r.get("address")
        if not a:
            continue
        if r.get("poll_error"):
            if a in prev:
                out[a] = prev[a]
            continue
        out[a] = round(F._f(r.get("szi")), 5)
    return out


def changed_wallets(
    cohorts: dict[str, dict[str, float]],
    prev: dict[str, dict[str, float]],
    mark: float,
    min_usd: float,
    cap: int,
) -> list[tuple[str, str, float, float]]:
    """(address, cohort, prev_szi, cur_szi) for wallets whose size moved by at least min_usd, largest first."""
    out = []
    for name, cur in cohorts.items():
        pv = prev.get(name) or {}
        for a, c in cur.items():
            if a not in pv:
                continue
            p = F._f(pv[a])
            if abs(c - p) * mark >= min_usd:
                out.append((a, name, p, c))
    out.sort(key=lambda x: abs(x[3] - x[2]), reverse=True)
    return out[:cap]


def liquidation_scan_list(roster: list[str], already: set[str], absorbers: dict[str, int],
                          start_at: int) -> tuple[list[str], int]:
    """Wallets to scan for liquidation fills: known absorbers first, then a round-robin."""
    members = set(roster)
    out = [a for a, _ in sorted(absorbers.items(), key=lambda kv: kv[1], reverse=True)
           if a in members and a not in already][: config.LIQ_SCAN_ABSORBERS]
    n = len(roster)
    i = start_at % n if n else 0
    steps = 0
    while n and len(out) < config.LIQ_SCAN_TOTAL and steps < n:
        a = roster[i]
        if a not in already and a not in out:
            out.append(a)
        i = (i + 1) % n
        steps += 1
    return out, i


async def fetch_fills(client, addresses: list[str], start_ms: int) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for a in addresses:
        try:
            out[a] = await client.user_fills_by_time(a, start_ms)
        except Exception as exc:  # noqa: BLE001 — one wallet must not fail the sweep
            log.warning("userFillsByTime failed for %s: %s", a, exc)
    return out


async def run_tracking(
    *,
    client,
    coin: str,
    smart_observed: list[dict[str, Any]],
    contrast_observed: list[dict[str, Any]],
    smart_traders: list[dict[str, Any]],
    contrast_traders: list[dict[str, Any]],
    lb_rows: list[dict[str, Any]],
    mark: Optional[float],
    state: dict[str, Any],
    history: list[dict[str, Any]],
    oi_now: Optional[float],
    candles_15m: list[dict[str, Any]],
    now_ms: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (public block for signal.json intel, new state keys for cohort.json)."""
    t_start = time.monotonic()
    px = F._f(mark)
    prev_tp = state.get("tracker_positions") or {}
    prev_pos = {"smart": prev_tp.get("smart"), "contrast": prev_tp.get("contrast")}
    t_prev = ts_ms(prev_tp.get("ts_utc"))
    if not prev_pos["smart"] and (state.get("last_positions") or {}).get("positions"):
        # First run after the upgrade: the previous smart snapshot already exists.
        lp = state["last_positions"]
        prev_pos["smart"] = {a: F._szi(v) for a, v in lp["positions"].items()}
        t_prev = ts_ms(lp.get("ts_utc"))
    cur = {
        "smart": positions_with_carry(smart_observed, prev_pos["smart"]),
        "contrast": positions_with_carry(contrast_observed, prev_pos["contrast"]),
    }

    # Metadata for cards.
    lbm = leaderboard_meta(lb_rows)
    meta: dict[str, dict[str, Any]] = {}
    for name, traders in (("smart", smart_traders), ("contrast", contrast_traders)):
        for i, r in enumerate(traders):
            a = r["address"]
            m = lbm.get(a, {})
            meta[a] = {
                "cohort": name,
                "rank": i + 1,
                "rank_of": len(traders),
                "all_time_pnl": m.get("all_time_pnl"),
                "month_pnl": m.get("month_pnl"),
            }
    rows_by: dict[str, dict[str, Any]] = {}
    for r in smart_observed + contrast_observed:
        szi = F._f(r.get("szi"))
        rows_by[r["address"]] = {**r, "_side": "LONG" if szi > 0 else ("SHORT" if szi < 0 else "FLAT")}

    # Fills for wallets that traded since the last snapshot, plus a liquidation scan.
    tape = dict(state.get("tape") or {})
    fills: dict[str, list[dict[str, Any]]] = {}
    moved = []
    scan: list[str] = []
    start = now_ms - int(config.FILL_LOOKBACK_H * HOUR_MS)
    if px > 0:
        moved = changed_wallets(cur, prev_pos, px, config.FILL_FETCH_MIN_USD, config.FILL_FETCH_MAX)
        fills = await fetch_fills(client, [m[0] for m in moved], start)
        roster = [r["address"] for r in smart_traders] + [r["address"] for r in contrast_traders]
        scan, next_at = liquidation_scan_list(roster, set(fills), tape.get("absorbers") or {},
                                             int(tape.get("scan_next") or 0))
        tape["scan_next"] = next_at
        fills.update(await fetch_fills(client, scan, start))
    log.info("Fills fetched: %s moved wallets, %s scanned for liquidations", len(moved), len(scan))

    orders_by = {a: T.orders_from_fills(fs, coin) for a, fs in fills.items()}
    runs_by = {a: T.worked_runs(os_) for a, os_ in orders_by.items()}
    runs_by = {a: r for a, r in runs_by.items() if r}

    changes = [{"address": a, "cohort": c, "prev": p, "cur": q, "row": rows_by.get(a), "meta": meta.get(a)}
               for a, c, p, q in moved]
    pos_ev = T.position_events(changes, t_prev=t_prev, t_now=now_ms, mark=px,
                               orders_by_wallet=orders_by, runs_by_wallet=runs_by) if px > 0 else []
    run_ev = T.run_events(runs_by, meta, rows_by)
    ord_ev = T.order_events(orders_by, meta)
    liq_new = T.liquidations_from_fills(fills, coin)
    tracked = set(meta)
    for e in liq_new:
        e["tracked"] = e["user"] in tracked
        e["cohort"] = (meta.get(e["user"]) or {}).get("cohort")
        e.pop("tids_all", None)

    absorbers = dict(tape.get("absorbers") or {})
    for e in liq_new:
        for v in e.get("via") or []:
            if v != e["user"]:
                absorbers[v] = absorbers.get(v, 0) + 1
    absorbers = dict(sorted(absorbers.items(), key=lambda kv: kv[1], reverse=True)[:40])
    observing_since = tape.get("observing_since") or now_ms
    whales = T.merge_events(tape.get("whales") or [], pos_ev + run_ev + ord_ev, now_ms, cap=400)
    for e in whales:
        # Entries replayed from stored snapshots carry no rank or PnL: add them where known.
        if e.get("rank") is None and e.get("address") in meta:
            m = meta[e["address"]]
            e.update({k: m.get(k) for k in ("cohort", "rank", "rank_of", "all_time_pnl", "month_pnl")})
    liqs = T.merge_events(tape.get("liquidations") or [], liq_new, now_ms, cap=600)
    new_tape = {"observing_since": observing_since, "whales": whales, "liquidations": liqs,
                "absorbers": absorbers, "scan_next": tape.get("scan_next", 0)}

    # Flow log.
    steps = {
        "s": F.flow_step(prev_pos["smart"], cur["smart"], px),
        "c": F.flow_step(prev_pos["contrast"], cur["contrast"], px),
    }
    flow_log = state.get("flow_log") or []
    if not flow_log and t_prev and prev_pos["smart"]:
        # Seed the baseline snapshot as a row with totals only.
        flow_log = F.append_log(flow_log, t_prev, None, {
            "s": F.flow_step(None, prev_pos["smart"], px),
            "c": F.flow_step(None, prev_pos["contrast"], px) if prev_pos["contrast"] else None,
        })
    flow_log = F.append_log(flow_log, now_ms, t_prev, steps)

    # Windows and sentences.
    prices = [(int(c["t"]), F._f(c["c"])) for c in candles_15m]
    if px > 0:
        prices.append((now_ms, px))
    windows: dict[str, Any] = {}
    for h in F.WINDOWS_H:
        lab = F.WINDOW_LABELS[h]
        ws = F.window_flow(flow_log, "s", now_ms, h)
        wc = F.window_flow(flow_log, "c", now_ms, h)
        for w in (ws, wc):
            if w.get("available"):
                w["base_ist"] = clock_ist(w["base_ms"])
                w["move"] = F._round(F.price_move(prices, w["base_ms"], w["end_ms"]), 5)
        phrase = WINDOW_PHRASE[h]
        windows[lab] = {
            "label": lab,
            "hours": h,
            "available": bool(ws.get("available") or wc.get("available")),
            "smart": ws,
            "contrast": wc,
            "compare": F.compare_sentence(phrase, ws, wc),
            "smart_headline": F.headline("The top cohort", ws, ws.get("move")),
            "contrast_headline": F.headline("The worst-performing cohort", wc, wc.get("move")),
            "smart_sentence": F.window_sentence("The top cohort", ws, ws.get("base_ist") or "the start") if ws.get("available") else ws.get("reason"),
        }
    default = next((l for l in ("4h", "1h") if windows.get(l, {}).get("available")), "4h")

    def cohort_now(name: str, key: str) -> dict[str, Any]:
        t = F.side_totals(cur[name], px) if px > 0 else {}
        return {**t, "short_share": F._round(F.short_share(t))}

    smart_now = cohort_now("smart", "s")
    contrast_now = cohort_now("contrast", "c")
    w12 = windows["12h"]["smart"]

    # Liquidations.
    pts = []
    for h in history:
        t = ts_ms(h.get("ts_utc"))
        if t and h.get("oi") and h.get("mark"):
            pts.append({"_ms": t, "oi": h["oi"], "mark": h["mark"]})
    if oi_now and px > 0:
        pts.append({"_ms": now_ms, "oi": oi_now, "mark": px})
    proxy = T.oi_proxy(pts, now_ms)
    wave = T.liquidation_wave(liqs, now_ms, observing_since)
    if proxy.get("latest", {}) and proxy["latest"].get("flag") and proxy["latest"]["t"] == now_ms:
        wave["proxy_flag"] = True
    else:
        wave["proxy_flag"] = False
    wave["status"] = ("WAVE" if wave["wave"] else ("PROXY WAVE" if wave["proxy_flag"] else "NO WAVE"))

    def pub_liq(e):
        return {k: e.get(k) for k in ("t", "user", "side", "ntl", "px", "mark", "method", "own", "tracked", "cohort")} | {
            "via_n": len(e.get("via") or []), "clock": clock_ist(e.get("t"))}

    def pub_whale(e):
        return {**e, "clock": clock_ist(e.get("t"))}

    block = {
        "coin": coin,
        "version": "1.1",
        "built_ms": now_ms,
        "cohorts": {
            "smart": {
                "name": "Top cohort",
                "definition": "The top 500 wallets by one-month perp PnL on the public leaderboard "
                              "(equity at least $10,000, month volume at most 100x equity).",
                "members": len(cur["smart"]),
                **smart_now,
            },
            "contrast": {
                "name": "Worst-performing cohort",
                "definition": "The 500 wallets with the largest one-month losses on the public leaderboard, "
                              "with the same equity floor and turnover cap.",
                "members": len(cur["contrast"]),
                **contrast_now,
            },
        },
        "flow": {"windows": windows, "order": [F.WINDOW_LABELS[h] for h in F.WINDOWS_H], "default": default},
        "explain": {
            "short_share": smart_now.get("short_share"),
            "short_share_12h_ago": w12.get("short_share_before") if w12.get("available") else None,
            "long_ntl": smart_now.get("long_ntl"),
            "short_ntl": smart_now.get("short_ntl"),
            "n_long": smart_now.get("n_long"),
            "n_short": smart_now.get("n_short"),
        },
        "whales": [pub_whale(e) for e in whales[:40]],
        "whale_rules": {
            "position_usd": T.WHALE_POS_USD,
            "order_usd": T.WHALE_ORDER_USD,
            "worked_usd": T.TWAP_MIN_USD,
            "worked_orders": T.TWAP_MIN_ORDERS,
            "worked_minutes": T.TWAP_MIN_MINUTES,
            "worked_max_share": T.TWAP_MAX_ORDER_SHARE,
            "worked_max_gap_min": T.TWAP_MAX_GAP_MIN,
        },
        "liquidations": {
            "events": [pub_liq(e) for e in liqs[:40]],
            "count_7d": len(liqs),
            "usd_7d": round(sum(F._f(e.get("ntl")) for e in liqs), 2),
            "wave": wave,
            "hourly": T.hourly_series(liqs, now_ms, 48),
            "oi_proxy": proxy,
            "observing_since_ms": observing_since,
        },
        "fills": {"wallets_moved": len(moved), "wallets_scanned": len(scan), "wallets_fetched": len(fills),
                  "lookback_h": config.FILL_LOOKBACK_H, "min_move_usd": config.FILL_FETCH_MIN_USD},
        "limits": [
            "Hyperliquid's public info API has no market-wide liquidation feed. Liquidations are those visible in "
            "the fills of the 1,000 tracked wallets: their own, or ones their resting orders absorbed. Seen notional "
            "is a lower bound.",
            "The open-interest proxy cannot tell a liquidation from a voluntary close; it is an upper bound on "
            "forced selling or buying during that step.",
            "Flows compare snapshots taken about every 30 minutes. A position opened and closed between two "
            "snapshots is invisible, and a trimmed position means part of it was cut within one step.",
            "Fills are fetched only for wallets whose size in this metal moved by at least "
            f"${config.FILL_FETCH_MIN_USD:,.0f} since the last snapshot (at most {config.FILL_FETCH_MAX} per sweep), "
            f"looking back {config.FILL_LOOKBACK_H:g} hours, plus {config.LIQ_SCAN_TOTAL} wallets a sweep scanned for "
            "liquidation fills (wallets that absorbed liquidations before, then a round-robin through both cohorts).",
            "The worst-performing cohort is ranked by leaderboard month PnL (whole account), while the top cohort uses "
            "perp-only month PnL; wallets that change rank between sweeps are left out of that step's flow.",
        ],
        "fetch_sec": round(time.monotonic() - t_start, 1),
    }
    new_state = {
        "tracker_positions": {"ts_utc": iso_from_ms(now_ms), "mark": px, "smart": cur["smart"], "contrast": cur["contrast"]},
        "flow_log": flow_log,
        "tape": new_tape,
    }
    return block, new_state


WINDOW_PHRASE = {1: "hour", 4: "4 hours", 8: "8 hours", 12: "12 hours", 24: "24 hours", 48: "48 hours", 168: "week"}
