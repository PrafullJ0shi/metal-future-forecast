"""Flip detection, the interval gate, the cooldown, pending confirmation and the Atom feeds."""

import json
from xml.etree import ElementTree as ET

from app import alerts as AL
from app import enrich

NS = {"a": "http://www.w3.org/2005/Atom"}


def blk(verdict, p, lo, hi, mark=3500.0):
    return {"label": "Gold", "verdict": verdict, "p_long": p, "ci_low": lo, "ci_high": hi, "mark": mark,
            "n_long": 10, "n_short": 12}


def step(state, ts, **blocks):
    return AL.process(state, blocks, ts)


T0, T1, T2, T3, T4 = ("2026-11-25T10:00:00Z", "2026-11-25T10:30:00Z", "2026-11-25T11:00:00Z",
                      "2026-11-25T15:00:00Z", "2026-11-25T15:30:00Z")


def test_interval_clear_means_both_ends_on_one_side():
    assert AL.interval_clear(0.55, 0.8) and AL.interval_clear(0.1, 0.45)
    assert not AL.interval_clear(0.4, 0.7) and not AL.interval_clear(None, 0.7)
    assert not AL.interval_clear(0.5, 0.8)  # touching 0.50 still crosses


def test_first_sweep_records_the_verdict_and_pings_nothing():
    st = step(AL.empty_state(), T0, gold=blk("SHORT", 0.2, 0.1, 0.3))
    assert st["events"] == [] and st["last"]["gold"]["verdict"] == "SHORT"


def test_first_sweep_can_use_the_v1_history_verdict():
    st = AL.process(AL.empty_state(), {"gold": blk("LONG", 0.7, 0.6, 0.9)}, T0, {"gold": "SHORT"})
    assert len(st["events"]) == 1 and st["events"][0]["confirmed"] is True


def test_no_event_when_the_verdict_holds():
    st = step(AL.empty_state(), T0, gold=blk("SHORT", 0.2, 0.1, 0.3))
    st = step(st, T1, gold=blk("SHORT", 0.25, 0.1, 0.35))
    assert st["events"] == []


def test_confirmed_flip_needs_a_clear_interval():
    st = step(AL.empty_state(), T0, gold=blk("SHORT", 0.2, 0.1, 0.3))
    st = step(st, T1, gold=blk("LONG", 0.7, 0.6, 0.9))
    ev = st["events"][-1]
    assert (ev["from"], ev["to"], ev["confirmed"], ev["suppressed"]) == ("SHORT", "LONG", True, False)
    assert ev["title"] == "Gold flipped SHORT to LONG" and "not financial advice" in ev["text"]
    assert ev["id"] == "gold-20261125T103000Z"


def test_weak_flip_is_logged_but_not_a_ping_then_confirmed_when_the_interval_clears():
    st = step(AL.empty_state(), T0, gold=blk("SHORT", 0.2, 0.1, 0.3))
    st = step(st, T1, gold=blk("LONG", 0.62, 0.35, 0.9))          # crosses 0.50
    assert st["events"][-1]["confirmed"] is False and "gold" in st["pending"]
    assert AL.pushable(st["events"]) == []
    st = step(st, T2, gold=blk("LONG", 0.66, 0.55, 0.9))          # same verdict, interval now clear
    ev = st["events"][-1]
    assert ev["confirmed"] is True and ev["reason"] == "interval cleared" and ev["from"] == "SHORT"
    assert ev["title"] == "Gold LONG is now firmly held" and "gold" not in st["pending"]


def test_pending_is_dropped_if_the_verdict_moves_on():
    st = step(AL.empty_state(), T0, gold=blk("SHORT", 0.2, 0.1, 0.3))
    st = step(st, T1, gold=blk("LONG", 0.62, 0.35, 0.9))
    st = step(st, T2, gold=blk("NEUTRAL", 0.5, 0.3, 0.7))
    assert "gold" not in st["pending"]
    assert [e["to"] for e in st["events"]] == ["LONG", "NEUTRAL"]
    assert AL.pushable(st["events"]) == []


def test_flip_into_neutral_is_never_an_alert():
    st = step(AL.empty_state(), T0, gold=blk("LONG", 0.8, 0.7, 0.9))
    st = step(st, T1, gold=blk("NEUTRAL", 0.55, 0.52, 0.58))     # even a tight interval: NEUTRAL cannot confirm
    ev = st["events"][-1]
    assert ev["confirmed"] is False and ev["reason"] == "flip into NEUTRAL"


def test_cooldown_logs_but_does_not_ping_a_second_flip_for_the_same_metal():
    st = step(AL.empty_state(), T0, gold=blk("SHORT", 0.2, 0.1, 0.3))
    st = step(st, T1, gold=blk("LONG", 0.7, 0.6, 0.9))
    st = step(st, T2, gold=blk("SHORT", 0.2, 0.1, 0.3))          # 30 minutes later
    assert [e["suppressed"] for e in st["events"]] == [False, True]
    assert len(AL.pushable(st["events"])) == 1
    st = step(st, T3, gold=blk("LONG", 0.7, 0.6, 0.9))           # hours later, past the cooldown
    assert st["events"][-1]["suppressed"] is False and len(AL.pushable(st["events"])) == 2


def test_metals_are_independent():
    st = step(AL.empty_state(), T0, gold=blk("SHORT", 0.2, 0.1, 0.3), silver=blk("LONG", 0.8, 0.7, 0.9))
    st = step(st, T1, gold=blk("LONG", 0.7, 0.6, 0.9), silver=blk("LONG", 0.8, 0.7, 0.9))
    assert [e["metal"] for e in st["events"]] == ["gold"]


def test_events_are_capped(monkeypatch):
    monkeypatch.setattr(AL.config, "ALERT_MAX_EVENTS", 3)
    st, v = AL.empty_state(), "SHORT"
    for i in range(8):
        v = "LONG" if v == "SHORT" else "SHORT"
        ts = f"2026-11-{10 + i:02d}T10:00:00Z"
        st = step(st, ts, gold=blk(v, 0.7 if v == "LONG" else 0.2, 0.6 if v == "LONG" else 0.1, 0.9 if v == "LONG" else 0.3))
    assert len(st["events"]) == 3


def test_state_round_trips_and_a_corrupt_file_resets(tmp_path):
    st = step(AL.empty_state(), T0, gold=blk("SHORT", 0.2, 0.1, 0.3))
    p = tmp_path / "alerts.json"
    p.write_text(json.dumps(st))
    assert AL.load_state(p)["last"]["gold"]["verdict"] == "SHORT"
    p.write_text("{not json")
    assert AL.load_state(p) == AL.empty_state()
    assert AL.load_state(tmp_path / "missing.json") == AL.empty_state()


def test_atom_feed_is_well_formed_filtered_and_escaped():
    st = step(AL.empty_state(), T0, gold=blk("SHORT", 0.2, 0.1, 0.3), silver=blk("LONG", 0.8, 0.7, 0.9))
    gold = blk("LONG", 0.7, 0.6, 0.9); gold["label"] = "Gold <&>"
    st = step(st, T1, gold=gold, silver=blk("SHORT", 0.3, 0.1, 0.45))
    st["events"][0]["text"] += ' "quotes" & <tags>'
    root = ET.fromstring(AL.build_atom(st, "gold"))
    assert root.tag == "{http://www.w3.org/2005/Atom}feed"
    entries = root.findall("a:entry", NS)
    assert len(entries) == 1
    assert entries[0].find("a:title", NS).text == "Gold <&> flipped SHORT to LONG"
    assert 'quotes' in entries[0].find("a:summary", NS).text
    assert entries[0].find("a:id", NS).text.startswith("tag:")
    assert root.find("a:author/a:name", NS).text
    assert root.find("a:id", NS).text.endswith(":gold")
    both = ET.fromstring(AL.build_atom(st, None))
    assert len(both.findall("a:entry", NS)) == 2
    assert ET.fromstring(AL.build_atom(st, "silver")).find("a:entry/a:category", NS).get("term") == "silver"


def test_empty_feed_is_still_valid_atom():
    root = ET.fromstring(AL.build_atom(AL.empty_state(), "gold"))
    assert root.find("a:updated", NS).text and root.findall("a:entry", NS) == []


def test_feed_keeps_only_the_newest_entries(monkeypatch):
    monkeypatch.setattr(AL.config, "ALERT_FEED_ENTRIES", 2)
    monkeypatch.setattr(AL.config, "ALERT_COOLDOWN_H", 0.0)
    st, v = AL.empty_state(), "SHORT"
    for i in range(5):
        v = "LONG" if v == "SHORT" else "SHORT"
        st = step(st, f"2026-11-{10 + i:02d}T10:00:00Z",
                  gold=blk(v, 0.7 if v == "LONG" else 0.2, 0.6 if v == "LONG" else 0.1, 0.9 if v == "LONG" else 0.3))
    ents = ET.fromstring(AL.build_atom(st, "gold")).findall("a:entry/a:updated", NS)
    assert [e.text for e in ents] == ["2026-11-14T10:00:00Z", "2026-11-13T10:00:00Z"]


def test_write_outputs_creates_json_and_three_feeds(tmp_path):
    st = step(AL.empty_state(), T0, gold=blk("SHORT", 0.2, 0.1, 0.3))
    AL.write_outputs(st, data_path=tmp_path / "d" / "alerts.json", site_path=tmp_path / "s" / "alerts.json",
                     feed_dir=tmp_path / "feed")
    assert (tmp_path / "d" / "alerts.json").exists() and (tmp_path / "s" / "alerts.json").exists()
    for n in ("gold", "silver", "all"):
        ET.fromstring((tmp_path / "feed" / f"{n}.xml").read_bytes())


def test_enrich_apply_adds_crowding_tilt_and_alert_summary():
    payload = json.loads(open("data/signal.json").read())
    out, state = enrich.apply(payload, {"gold": "LONG", "silver": "SHORT"}, AL.empty_state())
    assert set(out["metals"]["gold"]["crowding"]) >= {"level", "score", "k_to_neutral", "top_shares"}
    assert out["tilt"]["ratio"]["now"] and out["tilt"]["read"]
    assert out["alerts"]["feeds"]["gold"] == "feed/gold.xml"
    # gold went LONG -> SHORT on this snapshot with a clear interval: one confirmed alert
    assert [(e["metal"], e["confirmed"]) for e in state["events"]] == [("gold", True)]


def test_enrich_cli_runs_offline_on_a_copy_of_the_site(tmp_path):
    import shutil
    shutil.copytree("site", tmp_path / "site", ignore=shutil.ignore_patterns("fonts", "backtest"))
    assert enrich.main(["--site-dir", str(tmp_path / "site")]) == 0
    sig = json.loads((tmp_path / "site" / "data" / "signal.json").read_text())
    assert "tilt" in sig and "crowding" in sig["metals"]["silver"]
    ET.fromstring((tmp_path / "site" / "feed" / "all.xml").read_bytes())


def test_enrich_uses_stored_voters_and_reports_exact():
    payload = json.loads(open("data/signal.json").read())
    g = payload["metals"]["gold"]
    g["voters"] = [["SHORT", 5.0, 1e6]] * 4 + [["LONG", 1.0, 1e5]] * 2   # 20 short weight, 2 long weight
    out, _ = enrich.apply(payload, None, AL.empty_state())
    c = out["metals"]["gold"]["crowding"]
    assert c["exact"] is True and c["voters"] == 6
    # p = 2/22. Closing three 5.0 shorts leaves 2/7 = 0.29 (still SHORT); the fourth leaves only longs.
    assert c["k_to_neutral"] == 4
