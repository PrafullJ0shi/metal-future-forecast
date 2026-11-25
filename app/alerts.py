"""Verdict-flip alerts for a static site: no server, no secrets, no paid service.

The sweep calls process() with the new readings. It returns the updated state (data/alerts.json) and
write_outputs() turns it into per-metal Atom feeds plus the JSON the page polls for browser notifications.

A flip is a change of verdict since the last sweep. It only becomes an alert ("confirmed") when the 95%
bootstrap interval no longer crosses 0.50. A flip into NEUTRAL can never be confirmed: a NEUTRAL call sits
between 0.40 and 0.60, so its interval almost always straddles 0.50. Those, and flips that are still
weakly held, are logged and shown on the page, never pushed. A weak flip that later tightens while the
verdict holds is confirmed then ("interval cleared").
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree as ET

from . import config

NS = "http://www.w3.org/2005/Atom"
VERDICTS = ("LONG", "SHORT", "NEUTRAL")
DISCLAIMER = "A descriptive reading of public positions, not financial advice and not a prediction."


def parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def interval_clear(ci_low: Optional[float], ci_high: Optional[float]) -> bool:
    """True when the whole 95% interval sits on one side of 0.50."""
    if ci_low is None or ci_high is None:
        return False
    return ci_high < 0.5 or ci_low > 0.5


def empty_state() -> dict[str, Any]:
    return {"version": 1, "updated_utc": None, "last": {}, "pending": {}, "events": []}


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict) and data.get("version") == 1:
            return {**empty_state(), **data}
    except (OSError, json.JSONDecodeError):
        pass
    return empty_state()


def _fmt_px(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    return f"${x:,.1f}" if x >= 1000 else f"${x:,.2f}" if x >= 100 else f"${x:,.3f}"


def _event(metal: str, label: str, ts: str, frm: str, to: str, b: dict[str, Any], confirmed: bool,
           reason: str, suppressed: bool = False) -> dict[str, Any]:
    lo, hi, p = b.get("ci_low"), b.get("ci_high"), b.get("p_long")
    rng = f"95% interval {lo:.2f} to {hi:.2f}" if lo is not None and hi is not None else "no interval"
    head = f"{label} flipped {frm} to {to}" if reason != "interval cleared" else f"{label} {to} is now firmly held"
    body = (f"P(long) {p:.2f}, {rng}. Mark {_fmt_px(b.get('mark'))}. "
            f"{b.get('n_long', 0)} long and {b.get('n_short', 0)} short wallets in the top 500. {DISCLAIMER}") if p is not None \
        else f"No weighted votes. {DISCLAIMER}"
    return {
        "id": f"{metal}-{ts.replace('-', '').replace(':', '')}",
        "metal": metal, "label": label, "ts_utc": ts, "from": frm, "to": to,
        "p_long": p, "ci_low": lo, "ci_high": hi, "mark": b.get("mark"),
        "confirmed": confirmed, "suppressed": suppressed, "reason": reason,
        "title": head, "text": body,
    }


def process(state: dict[str, Any], blocks: dict[str, dict[str, Any]], ts: str,
            fallback_prev: Optional[dict[str, Optional[str]]] = None) -> dict[str, Any]:
    """Compare each metal's new block with the last verdict seen. Returns a new state.

    blocks: {"gold": signal block, ...} with verdict, p_long, ci_low, ci_high, mark, n_long, n_short, label.
    fallback_prev: verdicts from the v1 history file, used once when there is no stored verdict yet.
    """
    st = json.loads(json.dumps(state))  # deep copy; state is plain JSON
    st.setdefault("last", {}); st.setdefault("pending", {}); st.setdefault("events", [])
    now = parse_ts(ts)
    for metal, b in blocks.items():
        verdict = b.get("verdict") or "NEUTRAL"
        label = b.get("label") or metal.title()
        prev = (st["last"].get(metal) or {}).get("verdict") or (fallback_prev or {}).get(metal)
        clear = interval_clear(b.get("ci_low"), b.get("ci_high"))
        new_events: list[dict[str, Any]] = []

        if prev and prev != verdict:
            confirmed = clear and verdict != "NEUTRAL"
            reason = "interval clear of 0.50" if confirmed else (
                "flip into NEUTRAL" if verdict == "NEUTRAL" else "interval still crosses 0.50")
            new_events.append(_event(metal, label, ts, prev, verdict, b, confirmed, reason))
            if verdict != "NEUTRAL" and not confirmed:
                st["pending"][metal] = {"from": prev, "to": verdict, "since": ts}
            else:
                st["pending"].pop(metal, None)
        else:
            pend = st["pending"].get(metal)
            if pend:
                if pend["to"] != verdict:
                    st["pending"].pop(metal, None)
                elif clear:
                    new_events.append(_event(metal, label, ts, pend["from"], verdict, b, True, "interval cleared"))
                    st["pending"].pop(metal, None)

        for ev in new_events:
            if ev["confirmed"]:
                recent = [e for e in st["events"] if e["metal"] == metal and e["confirmed"] and not e["suppressed"]
                          and now - parse_ts(e["ts_utc"]) < timedelta(hours=config.ALERT_COOLDOWN_H)]
                if recent:
                    ev["suppressed"] = True
                    ev["reason"] += "; cooldown"
            st["events"].append(ev)
        st["last"][metal] = {"verdict": verdict, "p_long": b.get("p_long"), "ts_utc": ts}
    st["events"] = sorted(st["events"], key=lambda e: e["ts_utc"])[-config.ALERT_MAX_EVENTS:]
    st["updated_utc"] = ts
    return st


def pushable(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if e.get("confirmed") and not e.get("suppressed")]


def build_atom(state: dict[str, Any], metal: Optional[str], site_url: str = config.SITE_URL) -> bytes:
    """One Atom 1.0 feed. metal=None is the combined feed. Only pushable events are entries."""
    events = [e for e in pushable(state.get("events", [])) if metal in (None, e["metal"])]
    events = sorted(events, key=lambda e: e["ts_utc"], reverse=True)[:config.ALERT_FEED_ENTRIES]
    name = "all" if metal is None else metal
    title = ("Metal Future Forecast: gold and silver flips" if metal is None
             else f"Metal Future Forecast: {metal} verdict flips")
    ET.register_namespace("", NS)
    feed = ET.Element(f"{{{NS}}}feed")
    ET.SubElement(feed, f"{{{NS}}}title").text = title
    ET.SubElement(feed, f"{{{NS}}}subtitle").text = (
        "A confirmed flip: the verdict changed and the 95% bootstrap interval no longer crosses 0.50. "
        "Not financial advice.")
    ET.SubElement(feed, f"{{{NS}}}id").text = f"tag:prafullj0shi.github.io,2026:mff:feed:{name}"
    ET.SubElement(feed, f"{{{NS}}}updated").text = (events[0]["ts_utc"] if events else state.get("updated_utc")
                                                    or "1970-01-01T00:00:00Z")
    ET.SubElement(feed, f"{{{NS}}}link", {"rel": "self", "type": "application/atom+xml",
                                          "href": f"{site_url}feed/{name}.xml"})
    ET.SubElement(feed, f"{{{NS}}}link", {"rel": "alternate", "type": "text/html", "href": site_url})
    author = ET.SubElement(feed, f"{{{NS}}}author")
    ET.SubElement(author, f"{{{NS}}}name").text = "Metal Future Forecast"
    for e in events:
        ent = ET.SubElement(feed, f"{{{NS}}}entry")
        ET.SubElement(ent, f"{{{NS}}}title").text = e["title"]
        ET.SubElement(ent, f"{{{NS}}}id").text = f"tag:prafullj0shi.github.io,2026:mff:{e['id']}"
        ET.SubElement(ent, f"{{{NS}}}updated").text = e["ts_utc"]
        ET.SubElement(ent, f"{{{NS}}}link", {"rel": "alternate", "type": "text/html", "href": f"{site_url}#signal"})
        ET.SubElement(ent, f"{{{NS}}}category", {"term": e["metal"]})
        ET.SubElement(ent, f"{{{NS}}}summary").text = e["text"]
    ET.indent(feed)
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(feed, encoding="utf-8")


def write_outputs(state: dict[str, Any], *, data_path: Path = config.ALERTS_JSON,
                  site_path: Path = config.SITE_ALERTS_JSON, feed_dir: Path = config.FEED_DIR,
                  site_url: str = config.SITE_URL) -> None:
    text = json.dumps(state, separators=(",", ":"))
    for p in (data_path, site_path):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    feed_dir.mkdir(parents=True, exist_ok=True)
    for metal in ("gold", "silver", None):
        (feed_dir / f"{'all' if metal is None else metal}.xml").write_bytes(build_atom(state, metal, site_url))
