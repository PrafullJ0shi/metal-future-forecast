"""Async client for Hyperliquid public endpoints only."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from . import config
from .rate_limit import Backoff, WeightBucket


class HyperliquidClient:
    def __init__(self) -> None:
        self.bucket = WeightBucket()
        self.backoff = Backoff()
        self._sem = asyncio.Semaphore(config.MAX_CONCURRENCY)
        headers = {
            "User-Agent": config.USER_AGENT,
            "Accept": "application/json",
        }
        self._http = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(config.HTTP_TIMEOUT, connect=20.0),
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "HyperliquidClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _request(
        self,
        method: str,
        url: str,
        *,
        weight: int = 0,
        json_body: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> httpx.Response:
        last_error: Optional[Exception] = None
        for attempt in range(config.MAX_RETRIES):
            if weight:
                await self.bucket.acquire(weight)
            async with self._sem:
                try:
                    response = await self._http.request(
                        method,
                        url,
                        json=json_body,
                        headers=headers,
                    )
                except httpx.HTTPError as exc:
                    last_error = exc
                    await asyncio.sleep(self.backoff.delay(attempt))
                    continue
            if response.status_code in config.RETRY_STATUS:
                last_error = RuntimeError(
                    f"{response.status_code} from {url} (attempt {attempt + 1})"
                )
                # 429: honour Retry-After if present, else backoff.
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    await asyncio.sleep(min(float(retry_after), 60.0))
                else:
                    await asyncio.sleep(self.backoff.delay(attempt))
                continue
            if response.status_code >= 400:
                raise RuntimeError(
                    f"{response.status_code} from {url}: {response.text[:300]}"
                )
            return response
        raise RuntimeError(f"exhausted retries for {url}: {last_error}")

    async def fetch_leaderboard(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """GET the stats-data leaderboard, using If-None-Match when cached."""
        config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        etag = None
        meta: dict[str, Any] = {}
        if config.LEADERBOARD_META.exists():
            try:
                meta = json.loads(config.LEADERBOARD_META.read_text())
                etag = meta.get("etag")
            except json.JSONDecodeError:
                meta = {}
        headers: dict[str, str] = {}
        if etag and config.LEADERBOARD_CACHE.exists():
            headers["If-None-Match"] = etag
        # This host is not the weighted info API; do not spend bucket tokens.
        response = await self._request("GET", config.LEADERBOARD_URL, headers=headers or None)
        fetched_at = time.time()
        if response.status_code == 304 and config.LEADERBOARD_CACHE.exists():
            data = json.loads(config.LEADERBOARD_CACHE.read_text())
            meta = {**meta, "fetched_at": fetched_at, "not_modified": True}
            config.LEADERBOARD_META.write_text(json.dumps(meta, indent=2))
            return data.get("leaderboardRows") or [], meta
        # httpx does not expose 304 if we used request that follows... 304 is valid
        data = response.json()
        config.LEADERBOARD_CACHE.write_text(json.dumps(data))
        new_meta = {
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
            "fetched_at": fetched_at,
            "bytes": len(response.content),
            "not_modified": False,
        }
        config.LEADERBOARD_META.write_text(json.dumps(new_meta, indent=2))
        return data.get("leaderboardRows") or [], new_meta

    async def info(self, body: dict[str, Any], weight: int) -> Any:
        response = await self._request(
            "POST",
            config.INFO_URL,
            weight=weight,
            json_body=body,
            headers={"Content-Type": "application/json"},
        )
        return response.json()

    async def portfolio(self, address: str) -> Any:
        return await self.info({"type": "portfolio", "user": address}, config.WEIGHT_PORTFOLIO)

    async def clearinghouse_state(self, address: str, dex: Optional[str] = None) -> Any:
        """Perp account on one dex. HIP-3 builder dexes (e.g. "xyz") keep separate margin."""
        body: dict[str, Any] = {"type": "clearinghouseState", "user": address}
        if dex:
            body["dex"] = dex
        return await self.info(body, config.WEIGHT_CLEARINGHOUSE)

    async def meta_and_asset_ctxs(self, dex: Optional[str] = None) -> Any:
        body: dict[str, Any] = {"type": "metaAndAssetCtxs"}
        if dex:
            body["dex"] = dex
        return await self.info(body, config.WEIGHT_META_AND_CTXS)

    async def perp_dexs(self) -> Any:
        return await self.info({"type": "perpDexs"}, config.WEIGHT_ALL_MIDS)

    async def all_mids(self) -> Any:
        return await self.info({"type": "allMids"}, config.WEIGHT_ALL_MIDS)

    async def _info_items(self, body: dict[str, Any], base: int, per: int) -> list[Any]:
        """Endpoints that cost a base weight plus one unit per `per` items returned."""
        data = await self.info(body, base)
        items = data if isinstance(data, list) else []
        extra = len(items) // per
        if extra:
            await self.bucket.acquire(min(extra, config.WEIGHT_CAPACITY))
        return items

    async def candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        return await self._info_items(
            {"type": "candleSnapshot",
             "req": {"coin": coin, "interval": interval, "startTime": int(start_ms), "endTime": int(end_ms)}},
            config.WEIGHT_CANDLES, 60,
        )

    async def funding_history(self, coin: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        """All hourly funding rows in [start, end], following 500-row pages."""
        out: list[dict[str, Any]] = []
        page_start = int(start_ms)
        for _ in range(40):
            page = await self._info_items(
                {"type": "fundingHistory", "coin": coin, "startTime": page_start, "endTime": int(end_ms)},
                config.WEIGHT_FUNDING, 20,
            )
            if not page:
                break
            out.extend(page)
            last = int(page[-1]["time"])
            if len(page) < 500 or last >= end_ms:
                break
            page_start = last + 1
        return out

    async def user_fills(self, address: str) -> list[dict[str, Any]]:
        """Most recent fills (up to 2,000) for one wallet."""
        return await self._info_items(
            {"type": "userFills", "user": address, "aggregateByTime": True},
            config.WEIGHT_FILLS, 20,
        )

    async def user_fills_by_time(self, address: str, start_ms: int, end_ms: Optional[int] = None) -> list[dict[str, Any]]:
        """Fills in [start, end] for one wallet (one page, up to 2,000 rows, aggregated by time)."""
        body: dict[str, Any] = {"type": "userFillsByTime", "user": address,
                                "startTime": int(start_ms), "aggregateByTime": True}
        if end_ms is not None:
            body["endTime"] = int(end_ms)
        return await self._info_items(body, config.WEIGHT_FILLS, 20)


def window_from_row(row: dict[str, Any], name: str) -> dict[str, str]:
    raw = row.get("windowPerformances") or []
    try:
        return dict(raw).get(name) or {}
    except Exception:
        return {}


def window_pnl_from_portfolio(portfolio: Any, name: str = "perpMonth") -> Optional[float]:
    if not isinstance(portfolio, list):
        return None
    for item in portfolio:
        if not (isinstance(item, list) and len(item) == 2 and item[0] == name):
            continue
        hist = (item[1] or {}).get("pnlHistory") or []
        if not hist:
            return 0.0
        try:
            return float(hist[-1][1])
        except (TypeError, ValueError, IndexError):
            return None
    return None


def ctx_from_ctxs(payload: Any, coin: str) -> Optional[dict[str, Any]]:
    """The asset context (funding, openInterest, markPx, premium, ...) for one coin."""
    if not (isinstance(payload, list) and len(payload) >= 2):
        return None
    universe = (payload[0] or {}).get("universe") or []
    for i, asset in enumerate(universe):
        if asset.get("name") == coin:
            try:
                return {**dict(payload[1][i]), "maxLeverage": asset.get("maxLeverage"),
                        "isDelisted": bool(asset.get("isDelisted"))}
            except (IndexError, TypeError, ValueError):
                return None
    return None


def mark_from_ctxs(payload: Any, coin: str) -> Optional[float]:
    ctx = ctx_from_ctxs(payload, coin)
    try:
        return float(ctx["markPx"]) if ctx else None
    except (KeyError, TypeError, ValueError):
        return None


def account_value(state: Any) -> float:
    try:
        return float(((state or {}).get("marginSummary") or {}).get("accountValue") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def extract_position(state: dict[str, Any], coin: str) -> dict[str, Any]:
    """One coin's perp position from a clearinghouseState payload (equity is set by the caller)."""
    found: dict[str, Any] = {
        "szi": 0.0, "notional": 0.0, "entry": None, "leverage_type": None, "leverage": None,
        "unrealized_pnl": None, "liquidation_px": None, "margin_used": None, "roe": None,
    }
    for item in (state or {}).get("assetPositions") or []:
        pos = (item or {}).get("position") or {}
        if pos.get("coin") != coin:
            continue
        try:
            szi = float(pos.get("szi") or 0)
        except (TypeError, ValueError):
            szi = 0.0
        try:
            notional = abs(float(pos.get("positionValue") or 0))
        except (TypeError, ValueError):
            notional = 0.0
        lev = pos.get("leverage") or {}
        found.update({
            "szi": szi,
            "notional": notional,
            "entry": _opt_float(pos.get("entryPx")),
            "leverage_type": lev.get("type") if isinstance(lev, dict) else None,
            "leverage": _opt_float(lev.get("value") if isinstance(lev, dict) else lev),
            "unrealized_pnl": _opt_float(pos.get("unrealizedPnl")),
            "liquidation_px": _opt_float(pos.get("liquidationPx")),
            "margin_used": _opt_float(pos.get("marginUsed")),
            "roe": _opt_float(pos.get("returnOnEquity")),
        })
        break
    return found


def _opt_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
