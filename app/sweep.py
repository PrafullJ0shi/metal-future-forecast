"""Build the cohort, poll GOLD and SILVER positions, write signal.json and history files.

Same pipeline as hyperliquid-btc-signal: leaderboard -> filters -> `portfolio`
perpMonth -> top 500 -> `clearinghouseState` -> weighted P(long). The only
structural change: metals live on the HIP-3 builder dex "xyz", which keeps a
separate margin account, so each wallet is read twice (validator dex for the
main account, xyz for the metal positions) and equity is the sum of both.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from typing import Any, Optional

from . import alerts as AL
from . import config
from . import enrich as ENRICH
from . import flow as FL
from . import market as MK
from . import store as ST
from . import tape as TP
from .hl_client import (
    HyperliquidClient,
    account_value,
    ctx_from_ctxs,
    extract_position,
    window_from_row,
    window_pnl_from_portfolio,
)
from .signal import compute_signal, trader_weight
from .timeutil import iso_utc, now_utc
from .tracking import run_tracking

log = logging.getLogger("sweep")


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def filter_leaderboard(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for row in rows:
        equity = _float(row.get("accountValue"))
        month = window_from_row(row, "month")
        pnl = _float(month.get("pnl"))
        vlm = _float(month.get("vlm"))
        if equity < config.MIN_EQUITY or pnl <= config.MIN_MONTH_PNL:
            continue
        turnover = (vlm / equity) if equity > 0 else float("inf")
        if turnover > config.MAX_TURNOVER:
            continue
        kept.append({
            "address": str(row.get("ethAddress") or "").lower(),
            "display_name": row.get("displayName"),
            "leaderboard_equity": equity,
            "leaderboard_month_pnl": pnl,
            "leaderboard_month_roi": _float(month.get("roi")),
            "leaderboard_month_vlm": vlm,
            "turnover": turnover,
        })
    kept.sort(key=lambda r: r["leaderboard_month_pnl"], reverse=True)
    return kept


async def _map_progress(label: str, items: list[Any], worker) -> list[Any]:
    total = len(items)
    results: list[Any] = [None] * total
    started = time.monotonic()
    done = 0
    lock = asyncio.Lock()

    async def run(i: int, item: Any) -> None:
        nonlocal done
        results[i] = await worker(item)
        async with lock:
            done += 1
            if done == total or done % 100 == 0:
                log.info("%s %s/%s in %.1fs", label, done, total, time.monotonic() - started)

    await asyncio.gather(*(run(i, item) for i, item in enumerate(items)))
    return results


def cohort_is_fresh(cohort: Optional[dict[str, Any]]) -> bool:
    if not cohort or not cohort.get("traders") or not cohort.get("built_at_unix"):
        return False
    return (time.time() - float(cohort["built_at_unix"])) < config.PORTFOLIO_TTL_SEC


async def build_cohort(client: HyperliquidClient, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    pool = candidates[: config.CANDIDATE_POOL]
    log.info("Scoring %s candidates with portfolio (perpMonth)", len(pool))

    async def one(row: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = await client.portfolio(row["address"])
            return {**row, "perp_month_pnl": window_pnl_from_portfolio(payload, "perpMonth"), "portfolio_ok": True}
        except Exception as exc:  # noqa: BLE001 — one wallet must not fail the sweep
            log.warning("portfolio failed for %s: %s", row["address"], exc)
            return {**row, "perp_month_pnl": None, "portfolio_ok": False}

    scored = await _map_progress("portfolio", pool, one)
    eligible = [r for r in scored if r.get("portfolio_ok") and r.get("perp_month_pnl") is not None
                and r["perp_month_pnl"] > config.MIN_MONTH_PNL]
    eligible.sort(key=lambda r: r["perp_month_pnl"], reverse=True)
    built = now_utc()
    return {
        "built_at_unix": built.timestamp(),
        "built_at_utc": iso_utc(built),
        "source": "portfolio.perpMonth",
        "candidate_count": len(pool),
        "eligible_count": len(eligible),
        "traders": eligible[: config.TOP_N],
        "filters": {"min_equity": config.MIN_EQUITY, "min_month_pnl": config.MIN_MONTH_PNL,
                    "max_turnover": config.MAX_TURNOVER, "candidate_pool": config.CANDIDATE_POOL,
                    "top_n": config.TOP_N},
    }


async def poll_accounts(client: HyperliquidClient, traders: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    """One row per wallet: equity across both dexes and the position in each metal."""
    dexes = sorted({m["dex"] for m in config.METALS.values() if m["dex"]})

    async def one(row: dict[str, Any]) -> dict[str, Any]:
        err = None
        main_eq = 0.0
        states: dict[str, Any] = {}
        try:
            main_eq = account_value(await client.clearinghouse_state(row["address"]))
            for dx in dexes:
                states[dx] = await client.clearinghouse_state(row["address"], dex=dx)
        except Exception as exc:  # noqa: BLE001
            log.warning("clearinghouseState failed for %s: %s", row["address"], exc)
            err = str(exc)
        dex_eq = sum(account_value(s) for s in states.values())
        equity = (main_eq + dex_eq) if not err else (row.get("leaderboard_equity") or 0.0)
        out = {
            "address": row["address"],
            "display_name": row.get("display_name"),
            "month_pnl": row.get("perp_month_pnl") if row.get("perp_month_pnl") is not None else row.get("leaderboard_month_pnl"),
            "equity": equity,
            "equity_main": main_eq,
            "equity_builder": dex_eq,
            "turnover": row.get("turnover"),
            "poll_error": bool(err),
            "positions": {},
        }
        for key, m in config.METALS.items():
            out["positions"][key] = extract_position(states.get(m["dex"]) or {}, m["coin"])
        return out

    log.info("Polling clearinghouseState (validator + %s) for %s wallets (%s)", ",".join(dexes), len(traders), label)
    return await _map_progress(label, traders, one)


def metal_rows(accounts: list[dict[str, Any]], metal: str, mark: Optional[float]) -> list[dict[str, Any]]:
    """Flatten one metal's positions into the row shape compute_signal and run_tracking read."""
    out = []
    for a in accounts:
        p = a["positions"].get(metal) or {}
        out.append({k: v for k, v in a.items() if k != "positions"} | p | {"mark": mark})
    return out


class FillsCache:
    """Both metals' tracking passes ask for the same wallets' fills; fetch each wallet once."""

    def __init__(self, client: HyperliquidClient) -> None:
        self._client = client
        self._memo: dict[str, list[dict[str, Any]]] = {}

    async def user_fills_by_time(self, address: str, start_ms: int, end_ms: Optional[int] = None):
        if address not in self._memo:
            self._memo[address] = await self._client.user_fills_by_time(address, start_ms, end_ms)
        return [f for f in self._memo[address] if int(f.get("time") or 0) >= start_ms]

    def __getattr__(self, name: str):
        return getattr(self._client, name)


def position_changes(prev: Optional[dict[str, Any]], rows: list[dict[str, Any]], mark: Optional[float]) -> dict[str, Any]:
    """Opened / closed / flipped / resized since the previous sweep, top cohort only."""
    prev_pos = (prev or {}).get("positions") or {}
    if not prev_pos or not mark:
        return {"available": False, "reason": "First sweep: nothing to compare with yet.", "items": []}
    items = []
    counts = {"opened": 0, "closed": 0, "flipped": 0, "added": 0, "trimmed": 0}
    for r in rows:
        if r.get("poll_error") or r["address"] not in prev_pos:
            continue
        p, c = float(prev_pos[r["address"]]), float(r.get("szi") or 0.0)
        if abs(c - p) * mark < 1000:
            continue
        if p == 0:
            kind = "opened"
        elif c == 0:
            kind = "closed"
        elif (p > 0) != (c > 0):
            kind = "flipped"
        elif abs(c) > abs(p):
            kind = "added"
        else:
            kind = "trimmed"
        counts[kind] += 1
        w = trader_weight(r.get("month_pnl") or 0.0, r.get("equity") or 0.0, abs(c) * mark)
        items.append({"address": r["address"], "kind": kind, "prev": p, "cur": c,
                      "delta_usd": (c - p) * mark, "side_now": "LONG" if c > 0 else ("SHORT" if c < 0 else "FLAT"),
                      "weight_now": w})
    items.sort(key=lambda x: abs(x["delta_usd"]), reverse=True)
    return {"available": True, "since_utc": prev.get("ts_utc"), "counts": counts, "items": items[:15]}


def risk_summary(rows: list[dict[str, Any]], mark: Optional[float]) -> dict[str, Any]:
    """Leverage and distance to liquidation of the cohort's open positions in this metal."""
    lev = [r["leverage"] for r in rows if r.get("szi") and r.get("leverage")]
    dist = []
    for r in rows:
        if r.get("szi") and r.get("liquidation_px") and mark:
            dist.append(abs(r["liquidation_px"] / mark - 1.0))
    dist.sort()
    lev.sort()
    def med(xs):
        return xs[len(xs) // 2] if xs else None
    return {"median_leverage": med(lev), "max_leverage": lev[-1] if lev else None,
            "median_liq_distance": med(dist), "within_5pct": sum(1 for d in dist if d < 0.05),
            "with_liq_price": len(dist)}


def compact_positions(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {r["address"]: round(float(r.get("szi") or 0.0), 5) for r in rows if not r.get("poll_error")}


async def run_sweep(*, force_portfolio: bool = False) -> dict[str, Any]:
    started = time.monotonic()
    timings: dict[str, Any] = {}
    previous = ST.load_cohort() or {}
    async with HyperliquidClient() as client:
        t0 = time.monotonic()
        rows, lb_meta = await client.fetch_leaderboard()
        timings["leaderboard_sec"] = round(time.monotonic() - t0, 2)
        filtered = filter_leaderboard(rows)
        log.info("Leaderboard: %s rows, %s after filters", len(rows), len(filtered))

        cohort = None if force_portfolio else previous
        if cohort_is_fresh(cohort):
            log.info("Reusing cohort built %s (%s traders)", cohort.get("built_at_utc"), len(cohort["traders"]))
            timings["portfolio_sec"] = 0.0
        else:
            t1 = time.monotonic()
            cohort = await build_cohort(client, filtered)
            timings["portfolio_sec"] = round(time.monotonic() - t1, 2)
        traders = cohort["traders"]

        # Asset contexts for each dex we need.
        ctxs: dict[str, Any] = {}
        for dx in sorted({m["dex"] for m in config.METALS.values()} | {None}, key=lambda x: x or ""):
            try:
                ctxs[dx or ""] = await client.meta_and_asset_ctxs(dex=dx)
            except Exception as exc:  # noqa: BLE001
                log.warning("metaAndAssetCtxs (%s) failed: %s", dx, exc)

        t2 = time.monotonic()
        accounts = await poll_accounts(client, traders, "top cohort")
        timings["clearinghouse_sec"] = round(time.monotonic() - t2, 2)
        t2b = time.monotonic()
        contrast = FL.contrast_candidates(rows, min_equity=config.MIN_EQUITY, max_turnover=config.MAX_TURNOVER,
                                          exclude={t["address"] for t in traders}, n=config.CONTRAST_N)
        contrast_accounts = await poll_accounts(client, contrast, "worst cohort")
        timings["contrast_sec"] = round(time.monotonic() - t2b, 2)

        fills_client = FillsCache(client)
        issued = now_utc()
        now_ms = int(issued.timestamp() * 1000)
        metals_out: dict[str, Any] = {}
        prev_verdicts: dict[str, Optional[str]] = {}
        prev_metals = previous.get("metals") or {}
        new_metals_state: dict[str, Any] = {}
        for key, m in config.METALS.items():
            t3 = time.monotonic()
            ctx = ctx_from_ctxs(ctxs.get(m["dex"] or ""), m["coin"]) or {}
            mark = _float(ctx.get("markPx"), 0.0) or None
            rows_top = metal_rows(accounts, key, mark)
            rows_bad = metal_rows(contrast_accounts, key, mark)
            sig = compute_signal(rows_top, top_n=10 ** 6)  # every voter; trimmed to 20 below
            mk = await MK.fetch_market(client, m["coin"], now_ms)
            summary = MK.summarise(mk, ctx, mark, now_ms)
            history = ST.load_history(key)
            state = dict(prev_metals.get(key) or {})
            tracker_block, tracker_state = None, {}
            try:
                tracker_block, tracker_state = await run_tracking(
                    client=fills_client, coin=m["coin"], smart_observed=rows_top, contrast_observed=rows_bad,
                    smart_traders=traders, contrast_traders=contrast, lb_rows=rows, mark=mark, state=state,
                    history=history, oi_now=summary.get("open_interest"), candles_15m=mk.get("candles_15m") or [],
                    now_ms=now_ms,
                )
            except Exception as exc:  # noqa: BLE001 — the reading must still publish
                log.exception("%s tracking failed: %s", key, exc)
            body = sig.to_dict()
            # v2: the full voter list (side, weight, notional) feeds the crowding meter; the page still gets 20 rows.
            body["voters"] = [[r["side"], round(r["weight"], 6), round(r["notional"])] for r in body["top_positions"]]
            body["top_positions"] = body["top_positions"][:20]
            body.update({
                "metal": key,
                "coin": m["coin"],
                "dex": m["dex"],
                "label": m["label"],
                "underlying": m["underlying"],
                "taker_fee": m["taker_fee"],
                "mark": mark,
                "market": summary,
                "changes": position_changes(state.get("last_positions"), rows_top, mark),
                "risk": risk_summary(rows_top, mark),
                "flows": tracker_block,
                "n_builder_accounts": sum(1 for a in accounts if a["equity_builder"] > 0),
            })
            row = {"ts_utc": iso_utc(issued), "mark": mark, "p_long": body["p_long"], "ci_low": body["ci_low"],
                   "ci_high": body["ci_high"], "verdict": body["verdict"], "n_long": body["n_long"],
                   "n_short": body["n_short"], "n_flat": body["n_flat"], "notional_long": body["notional_long"],
                   "notional_short": body["notional_short"], "oi": summary.get("open_interest"),
                   "funding": summary.get("funding_hourly")}
            prev_verdicts[key] = history[-1].get("verdict") if history else None
            history = [h for h in history if h.get("ts_utc") != row["ts_utc"]] + [row]
            ST.write_history(key, history)
            body["history"] = history[-config.SIGNAL_HISTORY_POINTS:]
            metals_out[key] = body
            st = {k: tracker_state[k] for k in ("tracker_positions", "flow_log", "tape") if k in tracker_state}
            for k in ("tracker_positions", "flow_log", "tape"):
                if k not in st and state.get(k) is not None:
                    st[k] = state[k]
            st["last_positions"] = {"ts_utc": iso_utc(issued), "mark": mark, "positions": compact_positions(rows_top)}
            new_metals_state[key] = st
            timings[f"{key}_sec"] = round(time.monotonic() - t3, 2)
            log.info("%s: %s P(long)=%s CI=[%s, %s] L %s / S %s / F %s mark %s", m["label"], body["verdict"],
                     body["p_long"], body["ci_low"], body["ci_high"], body["n_long"], body["n_short"], body["n_flat"], mark)

        reference = {}
        for coin, meta in config.REFERENCE_COINS.items():
            ctx = ctx_from_ctxs(ctxs.get(meta["dex"] or ""), coin) or {}
            reference[coin] = {"label": meta["label"], "mark": _float(ctx.get("markPx"), 0.0) or None,
                               "funding_hourly": _float(ctx.get("funding"), 0.0),
                               "open_interest": _float(ctx.get("openInterest"), 0.0),
                               "day_volume_usd": _float(ctx.get("dayNtlVlm"), 0.0)}
            r = reference[coin]
            if r["mark"] and metals_out.get("gold", {}).get("mark"):
                r["basis_vs_gold"] = r["mark"] / metals_out["gold"]["mark"] - 1.0

    timings["sweep_sec"] = round(time.monotonic() - started, 2)
    payload = {
        "ts_utc": iso_utc(issued),
        "generated_ms": now_ms,
        "project": "Metal Future Forecast (Hyperliquid)",
        "repo": config.REPO_URL,
        "site": config.SITE_URL,
        "cohort": {
            "source": cohort.get("source"),
            "built_at_utc": cohort.get("built_at_utc"),
            "candidate_count": cohort.get("candidate_count"),
            "eligible_count": cohort.get("eligible_count"),
            "filters": cohort.get("filters"),
            "n_top": len(traders),
            "n_contrast": len(contrast),
        },
        "method": {
            "weight": "w = ln(1 + max(0, month_pnl)) * min(1, equity / 100000) * min(|metal notional| / equity, 3)",
            "p_long": "sum(long weights) / (sum(long weights) + sum(short weights))",
            "interval": "95% bootstrap percentile interval over traders (seed 42, 5000 resamples); Beta(1+longs, 1+shorts) also stored",
            "thresholds": {"long": config.P_LONG_THRESHOLD, "short": config.P_SHORT_THRESHOLD},
            "equity": "validator-dex account value + xyz builder-dex account value",
        },
        "metals": metals_out,
        "reference": reference,
        "leaderboard": {"url": config.LEADERBOARD_URL, "etag": lb_meta.get("etag"),
                        "last_modified": lb_meta.get("last_modified")},
        "timings": timings,
        "disclaimer": ("A descriptive reading of public positions, not financial advice and not a prediction. "
                       "It can be wrong. Do not trade on it."),
    }
    try:  # v2 readings must never stop a snapshot from publishing
        payload, alerts_state = ENRICH.apply(payload, prev_verdicts, AL.load_state(config.ALERTS_JSON))
        AL.write_outputs(alerts_state)
    except Exception as exc:  # noqa: BLE001
        log.exception("v2 enrich failed: %s", exc)
    ST.write_signal(payload)
    cohort = dict(cohort)
    cohort["metals"] = new_metals_state
    ST.write_cohort(cohort)
    return payload


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Metal Future Forecast sweep (GOLD and SILVER).")
    parser.add_argument("--force-portfolio", action="store_true",
                        help="Rebuild the 500-wallet cohort even if the cohort file is younger than one hour.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    payload = asyncio.run(run_sweep(force_portfolio=args.force_portfolio))
    print(json.dumps({k: {f: v[f] for f in ("coin", "verdict", "p_long", "ci_low", "ci_high", "n_long", "n_short", "mark")}
                      for k, v in payload["metals"].items()} | {"timings": payload["timings"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
