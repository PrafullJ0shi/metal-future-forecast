"""Asia/Calcutta formatting. A trailing Z or numeric offset is converted, not copied."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def format_ist(dt: Optional[datetime] = None) -> str:
    """Example: 24 Nov 2026, 10:32 PM IST (UTC+5:30)."""
    if dt is None:
        dt = now_utc()
    local = to_ist(dt)
    return local.strftime("%d %b %Y, %I:%M %p").lstrip("0").replace(" 0", " ") + " IST (UTC+5:30)"


def iso_utc(dt: Optional[datetime] = None) -> str:
    if dt is None:
        dt = now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
