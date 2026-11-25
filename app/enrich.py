"""Glue between the sweep and the v2 readings. Offline: it only reads and writes local files.

The sweep calls apply(); `python -m app.enrich` runs the same step on an existing signal.json, which is
how the panels are previewed without touching the Hyperliquid API.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Optional

from . import alerts as AL
from . import config
from . import v2

log = logging.getLogger("enrich")


def apply(payload: dict[str, Any], prev_verdicts: Optional[dict[str, Optional[str]]] = None,
          alerts_state: Optional[dict[str, Any]] = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Add crowding per metal and the pair tilt to the payload; return (payload, new alerts state)."""
    metals = payload["metals"]
    for key, block in metals.items():
        block["crowding"] = v2.crowding(block)
    if {"gold", "silver"} <= set(metals):
        g, s = metals["gold"], metals["silver"]
        payload["tilt"] = v2.tilt(g, s, (g.get("market") or {}).get("chart_1d") or [],
                                  (s.get("market") or {}).get("chart_1d") or [])
    state = AL.process(alerts_state or AL.empty_state(), metals, payload["ts_utc"], prev_verdicts)
    payload["alerts"] = {
        "updated_utc": state["updated_utc"],
        "last": state["last"],
        "pending": state["pending"],
        "feeds": {"gold": "feed/gold.xml", "silver": "feed/silver.xml", "all": "feed/all.xml"},
        "json": "data/alerts.json",
    }
    return payload, state


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Add v2 readings (tilt, crowding, alerts) to an existing signal.json. Offline.")
    ap.add_argument("--site-dir", type=Path, default=config.SITE_DIR, help="site folder to read and write (default: ./site)")
    ap.add_argument("--data-dir", type=Path, default=None, help="data folder for alerts state (default: <site-dir>/data)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    site = args.site_dir
    sig_path = site / "data" / "signal.json"
    payload = json.loads(sig_path.read_text())
    data_dir = args.data_dir or (site / "data")
    state = AL.load_state(data_dir / "alerts.json")
    prev = {}
    for k in payload["metals"]:
        try:
            hist = json.loads((site / "data" / f"history_{k}.json").read_text())
            prev[k] = hist[-2]["verdict"] if len(hist) >= 2 else None
        except (OSError, json.JSONDecodeError, KeyError, IndexError):
            prev[k] = None
    payload, state = apply(payload, prev, state)
    sig_path.write_text(json.dumps(payload, separators=(",", ":")))
    AL.write_outputs(state, data_path=data_dir / "alerts.json", site_path=site / "data" / "alerts.json",
                     feed_dir=site / "feed")
    log.info("wrote %s, alerts.json and feed/*.xml under %s", sig_path.name, site)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
