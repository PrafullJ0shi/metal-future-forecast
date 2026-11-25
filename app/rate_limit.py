"""Token-bucket limiter for Hyperliquid info-API weights (1,200 / minute)."""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from . import config


class WeightBucket:
    def __init__(
        self,
        capacity: int = config.WEIGHT_CAPACITY,
        refill_per_minute: float = config.WEIGHT_REFILL_PER_MINUTE,
    ) -> None:
        self.capacity = float(capacity)
        self.refill_per_second = float(refill_per_minute) / 60.0
        self.tokens = float(capacity)
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.updated
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)
            self.updated = now

    async def acquire(self, weight: int) -> None:
        weight = float(weight)
        while True:
            async with self._lock:
                self._refill()
                if self.tokens >= weight:
                    self.tokens -= weight
                    return
                deficit = weight - self.tokens
                wait = deficit / self.refill_per_second
            await asyncio.sleep(min(max(wait, 0.05), 2.0))


class Backoff:
    """Exponential sleep used after HTTP 429 or transient failures."""

    def __init__(self, base: float = 2.0, cap: float = 45.0) -> None:
        self.base = base
        self.cap = cap

    def delay(self, attempt: int) -> float:
        return min(self.cap, self.base * (2 ** max(0, attempt)))
