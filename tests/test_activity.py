"""Last-hour activity: per-wallet moves, the summary line, window choice and the sweep log."""

import math

from app import activity as ACT

MIN = 60_000
NOW = 1_800_000_000_000
MARK = 1000.0


def row(addr, szi, err=False):
    r = {"address": addr, "szi": szi}
    if err:
        r["poll_error"] = True
    return r


def snap(minutes_ago, held, mark=MARK, bad=()):
    return {"t": NOW - minutes_ago * MIN, "mark": mark, "p": dict(held), "bad": list(bad)}


def test_classify_move_covers_every_kind():
    assert ACT.classify_move(0, 5) == "opened" and ACT.classify_move(0, -5) == "opened"
    assert ACT.classify_move(5, 0) == "closed" and ACT.classify_move(-5, 0) == "closed"
    assert ACT.classify_move(5, -2) == "flipped" and ACT.classify_move(-5, 2) == "flipped"
    assert ACT.classify_move(5, 8) == "added" and ACT.classify_move(-5, -8) == "added"
    assert ACT.classify_move(5, 2) == "trimmed" and ACT.classify_move(-5, -2) == "trimmed"
    assert ACT.classify_move(3, 3) is None and ACT.classify_move(0, 0) is None


def test_side_of_is_the_side_that_moved():
    assert ACT.side_of("opened", 0, -3) == "SHORT"
    assert ACT.side_of("closed", 3, 0) == "LONG"
    assert ACT.side_of("trimmed", -5, -2) == "SHORT"
    assert ACT.side_of("flipped", 5, -2) == "SHORT"


def test_entry_from_keeps_nonzero_and_flags_failed_polls():
    e = ACT.entry_from([row("a", 2.0), row("b", 0.0), row("c", 9, err=True)], NOW, MARK)
    assert e["p"] == {"a": 2.0} and e["bad"] == ["c"] and e["t"] == NOW


def test_prune_keeps_three_hours():
    log = [snap(400, {}), snap(170, {}), snap(60, {})]
    assert [e["t"] for e in ACT.prune(log, NOW)] == [NOW - 170 * MIN, NOW - 60 * MIN]


def test_pick_base_prefers_the_snapshot_nearest_one_hour_and_skips_fresh_ones():
    log = [snap(95, {}), snap(65, {}), snap(35, {}), snap(10, {})]
    assert ACT.pick_base(log, NOW)["t"] == NOW - 65 * MIN
    assert ACT.pick_base([snap(10, {})], NOW) is None
    assert ACT.pick_base([], NOW) is None


def test_build_without_history_is_unavailable_but_logs_the_snapshot():
    block, log = ACT.build([], [row("a", 1.0)], MARK, NOW)
    assert block["available"] is False and "20 minutes" in block["reason"] and block["items"] == []
    assert len(log) == 1 and log[0]["p"] == {"a": 1.0}


def test_build_classifies_each_wallet_and_sums_the_flows():
    base = snap(60, {"B": -10.0, "C": 8.0, "D": -4.0, "E": 5.0, "F": 2.0}, mark=990.0)
    rows = [row("A", 3.0), row("B", -16.0), row("C", 2.0), row("D", 0.0), row("E", -3.0), row("F", 2.0005)]
    block, _ = ACT.build([base], rows, MARK, NOW, metal="gold")
    kinds = {i["address"]: (i["kind"], i["side"]) for i in block["items"]}
    assert kinds == {"A": ("opened", "LONG"), "B": ("added", "SHORT"), "C": ("trimmed", "LONG"),
                     "D": ("closed", "SHORT"), "E": ("flipped", "SHORT")}   # F moved less than $1k
    assert block["counts"] == {"opened": 1, "added": 1, "trimmed": 1, "closed": 1, "flipped": 1}
    # USD at today's mark: A +3000 long in; B +6000 short in; C -6000 long out; D +4000 short out;
    # E: close 5 long (5000 long out) and open 3 short (3000 short in)
    assert block["long_in_usd"] == 3000 and block["long_out_usd"] == 11000
    assert block["short_in_usd"] == 9000 and block["short_out_usd"] == 4000
    assert block["net_toward_long_usd"] == (3000 - 11000) - (9000 - 4000)
    assert block["gross_moved_usd"] == 27000
    assert block["flip_to_short"] == 1 and block["flip_to_long"] == 0
    assert math.isclose(block["price_move"], 1000 / 990 - 1)
    assert [i["address"] for i in block["items"]][:2] == ["E", "B"]   # biggest dollar move first (a flip counts both legs)
    assert block["span_min"] == 60 and block["partial"] is False


def test_failed_poll_is_not_read_as_a_close():
    base = snap(60, {"A": 5.0, "B": 5.0})
    block, _ = ACT.build([base], [row("A", 5.0, err=True), row("B", 5.0)], MARK, NOW)
    assert block["items"] == [] and block["skipped_unreadable"] == 1
    base_bad = snap(60, {"B": 5.0}, bad=["A"])
    block, _ = ACT.build([base_bad], [row("A", 4.0), row("B", 5.0)], MARK, NOW)
    assert block["items"] == []   # A was unreadable an hour ago: no honest comparison


def test_seen_time_is_the_first_sweep_that_showed_the_change():
    log = [snap(60, {"A": 1.0}), snap(30, {"A": 4.0}), snap(0.0001, {})]
    log = log[:2]
    block, _ = ACT.build(log, [row("A", 4.0)], MARK, NOW)
    item = block["items"][0]
    assert item["kind"] == "added" and item["seen_ms"] == NOW - 30 * MIN
    # a change that only shows up in the current snapshot is seen now
    block2, _ = ACT.build([snap(60, {"A": 1.0})], [row("A", 4.0)], MARK, NOW)
    assert block2["items"][0]["seen_ms"] == NOW


def test_young_base_marks_the_view_partial_and_says_so():
    block, _ = ACT.build([snap(25, {"A": 1.0})], [row("A", 3.0)], MARK, NOW, metal="silver")
    assert block["available"] and block["partial"] is True and block["span_min"] == 25
    assert block["summary"].startswith("last 25 min:")


def test_split_now_and_then():
    base = snap(60, {"A": 1.0, "B": -3.0})
    block, _ = ACT.build([base], [row("A", 3.0), row("B", -3.0)], MARK, NOW)
    assert block["split_then"]["long_share"] == 0.25 and block["split_now"]["long_share"] == 0.5
    assert (block["split_now"]["n_long"], block["split_now"]["n_short"]) == (1, 1)


def test_summary_line_reads_like_the_brief():
    # four wallets add 300 units each at $1,000 = +$1.2M of longs
    base = snap(60, {"D": 1.0, "E": 1.0, "F": 4.0, "G": 4.0, "C": -2.0})
    rows = [row("D", 301.0), row("E", 301.0), row("F", 304.0), row("G", 304.0), row("C", -2.0)]
    block, _ = ACT.build([base], rows, MARK, NOW, metal="gold")
    assert block["summary"] == "last hour: 4 wallets added longs (+$1.2M)"
    flipped = ACT.build([snap(60, {"X": 2.0, "D": 1.0})], [row("X", -3.0), row("D", 301.0)], MARK, NOW)[0]["summary"]
    assert flipped == "last hour: 1 wallet added longs (+$300k), 1 wallet flipped short"


def test_summary_when_quiet_and_for_cuts():
    block, _ = ACT.build([snap(60, {"A": 1.0})], [row("A", 1.0)], MARK, NOW, metal="silver")
    assert block["summary"] == "last hour: quiet. Nobody in the top 500 moved their silver by $1k or more."
    cut = ACT.build([snap(60, {"A": 5.0})], [row("A", 0.0)], MARK, NOW)[0]["summary"]
    assert cut == "last hour: 1 wallet closed longs (−$5.0k)"


def test_fmt_usd():
    assert ACT.fmt_usd(1_200_000) == "+$1.2M" and ACT.fmt_usd(-2500) == "−$2.5k"
    assert ACT.fmt_usd(15_000) == "+$15k" and ACT.fmt_usd(0) == "$0" and ACT.fmt_usd(900) == "+$900"


def test_new_log_replaces_a_same_timestamp_snapshot_and_stays_bounded():
    log = [snap(i * 10, {}) for i in range(1, 25)]
    _, new = ACT.build(log, [row("A", 1.0)], MARK, NOW)
    assert len(new) <= ACT.LOG_MAX and new[-1]["t"] == NOW
    _, again = ACT.build(new, [row("A", 2.0)], MARK, NOW)
    assert sum(1 for e in again if e["t"] == NOW) == 1


def test_three_sweeps_through_a_json_round_trip_like_cohort_json():
    import json
    rows1 = [row("A", 1.0), row("B", -2.0)]
    rows2 = [row("A", 1.0), row("B", -2.0), row("C", 3.0)]
    rows3 = [row("A", 4.0), row("B", -2.0), row("C", 3.0)]
    t = lambda m: NOW - m * MIN
    _, log = ACT.build([], rows1, MARK, t(62))
    log = json.loads(json.dumps(log))
    _, log = ACT.build(log, rows2, MARK, t(31))
    log = json.loads(json.dumps(log))
    block, log = ACT.build(log, rows3, MARK, NOW)
    assert block["available"] and block["span_min"] == 62
    assert {(i["address"], i["kind"]) for i in block["items"]} == {("A", "added"), ("C", "opened")}
    seen = {i["address"]: i["seen_ms"] for i in block["items"]}
    assert seen["C"] == t(31) and seen["A"] == NOW
    assert len(log) == 3
