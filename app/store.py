"""JSON files for the site and the workflow. One history file per metal."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from . import config

SLIM_KEYS = ("ts_utc", "mark", "p_long", "ci_low", "ci_high", "verdict",
             "n_long", "n_short", "n_flat", "notional_long", "notional_short", "oi", "funding")


def history_paths(metal: str) -> tuple[Path, Path]:
    name = f"history_{metal}.json"
    return config.DATA_DIR / name, config.SITE_DATA_DIR / name


def _round(v: Any) -> Any:
    if isinstance(v, float):
        if v != 0 and abs(v) < 0.01:
            return float(f"{v:.6g}")
        return round(v, 6)
    return v


def history_text(history: list[dict[str, Any]]) -> str:
    """One compact row per line, so each sweep's git diff is one line per metal."""
    lines = [json.dumps({k: _round(v) for k, v in h.items()}, separators=(",", ":")) for h in history]
    return "[\n" + ",\n".join(lines) + "\n]\n"


def load_history(metal: str) -> list[dict[str, Any]]:
    for path in history_paths(metal):
        if path.exists():
            try:
                data = json.loads(path.read_text())
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                continue
    return []


def write_history(metal: str, history: list[dict[str, Any]]) -> None:
    text = history_text(history[-config.HISTORY_MAX_POINTS:])
    for path in history_paths(metal):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def write_signal(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, separators=(",", ":"))
    for path in (config.SIGNAL_JSON, config.SITE_SIGNAL_JSON):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def load_signal() -> Optional[dict[str, Any]]:
    for path in (config.SIGNAL_JSON, config.SITE_SIGNAL_JSON):
        if path.exists():
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
    return None


def write_cohort(cohort: dict[str, Any]) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.COHORT_JSON.write_text(json.dumps(cohort, separators=(",", ":")))


def load_cohort() -> Optional[dict[str, Any]]:
    if not config.COHORT_JSON.exists():
        return None
    try:
        return json.loads(config.COHORT_JSON.read_text())
    except json.JSONDecodeError:
        return None
