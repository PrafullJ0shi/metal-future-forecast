"""Tilt, crowding and the wallets-to-flip maths."""

import math

from app import config, v2


def block(p_long, wl, ws, n_long=None, n_short=None, verdict=None, lo=None, hi=None, mark=None, voters=None,
          top=None, nl=1e6, ns=1e6):
    return {"p_long": p_long, "verdict": verdict or v2.verdict_of(p_long), "ci_low": lo, "ci_high": hi, "mark": mark,
            "weight_long": wl, "weight_short": ws, "n_long": n_long, "n_short": n_short, "voters": voters,
            "top_positions": top or [], "notional_long": nl, "notional_short": ns}


def test_lean_is_p_long_rescaled():
    assert v2.lean(0.0) == -1 and v2.lean(0.5) == 0 and v2.lean(1.0) == 1
    assert v2.lean(None) is None


def test_money_lean_uses_dollars_and_handles_empty():
    assert v2.money_lean(300, 100) == 0.5
    assert v2.money_lean(0, 0) is None


def test_ratio_series_joins_on_timestamp_and_uses_live_marks():
    gold = [[1, 3000], [2, 3100], [3, 3200]]
    silver = [[2, 31], [3, 32], [4, 33]]
    s = v2.ratio_series(gold, silver)
    assert [t for t, _ in s] == [2, 3]
    assert math.isclose(s[0][1], 100.0)
    live = v2.ratio_series(gold, silver, live_gold=3300, live_silver=30)
    assert math.isclose(live[-1][1], 110.0) and math.isclose(live[0][1], 100.0)


def test_ratio_block_percentile_and_changes():
    series = [[i, 60 + i] for i in range(40)]  # steadily rising
    b = v2.ratio_block(series)
    assert b["now"] == 99 and b["pct_rank"] == 1.0 and b["max"] == 99 and b["min"] == 60
    assert math.isclose(b["change_7d"], 99 / 92 - 1)
    assert v2.ratio_block([]) == {"now": None, "series": []}


def test_tilt_read_cases():
    assert v2.tilt_read("LONG", "LONG", 0.1) == "both_long"
    assert v2.tilt_read("SHORT", "SHORT", -0.1) == "both_short"
    assert v2.tilt_read("LONG", "SHORT", 1.0) == "gold_over_silver"
    assert v2.tilt_read("SHORT", "LONG", -1.0) == "silver_over_gold"
    assert v2.tilt_read("NEUTRAL", "NEUTRAL", 0.05) == "even"
    assert v2.tilt_read("NEUTRAL", "NEUTRAL", None) == "no_data"
    # same verdict but a big gap still says who is leaning harder, only when verdicts differ is it a spread
    assert v2.tilt_read("SHORT", "SHORT", 0.6) == "both_short"
    assert v2.tilt_read("NEUTRAL", "SHORT", 0.5) == "gold_over_silver"


def test_tilt_block_direction_and_note():
    g = block(0.8, 8, 2, mark=3500, verdict="LONG")
    s = block(0.2, 2, 8, mark=40, verdict="SHORT")
    t = v2.tilt(g, s, [[1, 3400], [2, 3500]], [[1, 40], [2, 40]])
    assert t["read"] == "gold_over_silver" and t["direction"] == "higher"
    assert math.isclose(t["gap"], 1.2)
    assert t["ratio"]["now"] == 3500 / 40
    assert "not a forecast" in t["note"]


def test_tilt_without_candles_still_gives_a_live_ratio():
    t = v2.tilt(block(0.5, 1, 1, mark=3000), block(0.5, 1, 1, mark=30))
    assert t["ratio"]["now"] == 100 and t["ratio"]["series"] == []


def test_wallets_to_move_is_greedy_and_exact():
    # shorts 10 + 5 + 1, longs 4. p = 4 / 20 = 0.20 (SHORT).
    wl, ws = [4.0], [10.0, 5.0, 1.0]
    assert v2.wallets_to_move(wl, ws, "short") == 0
    # p must exceed 0.40: remove the 10 -> 4/10 = 0.40 (not strictly above), remove the 5 -> 4/5 = 0.80
    assert v2.wallets_to_move(wl, ws, "not_short") == 2
    # reach 0.60: still two wallets (4/5 = 0.8 >= 0.6, but after one it is exactly 0.4)
    assert v2.wallets_to_move(wl, ws, "long") == 2
    # a lone wallet on a side: closing it flips everything
    assert v2.wallets_to_move([1.0], [9.0], "not_short") == 1
    assert v2.wallets_to_move([], [], "long") is None


def test_wallets_to_move_for_a_long_call():
    wl, ws = [8.0, 1.0], [1.0]
    assert v2.wallets_to_move(wl, ws, "not_long") == 1   # 1/2 = 0.5 < 0.6
    assert v2.wallets_to_move(wl, ws, "short") == 2      # 0 longs left -> p = 0


def voters(n_long_w, n_short_w):
    return [["LONG", w, 1e6] for w in n_long_w] + [["SHORT", w, 1e6] for w in n_short_w]


def test_crowding_sturdy_when_spread_out():
    b = block(None, 0, 0, voters=voters([1] * 30, [1] * 5), lo=0.7, hi=0.95)
    b["p_long"] = 30 / 35; b["verdict"] = "LONG"
    c = v2.crowding(b)
    assert c["level"] == "STURDY" and c["score"] == 0 and c["exact"] is True
    assert c["voters"] == 35 and math.isclose(c["top1_share"], 1 / 35)
    assert math.isclose(c["effective_voters"], 35.0)
    assert c["k_to_neutral"] > config.FLIP_FRAGILE_K


def test_crowding_jelly_with_a_whale_and_a_wide_interval():
    # one whale holds 60% of the vote, 4 small wallets, interval straddles 0.5, fewer than 20 voters
    b = block(None, 0, 0, voters=voters([1, 1], [6, 1, 1]), lo=0.1, hi=0.8)
    b["p_long"] = 2 / 10; b["verdict"] = "SHORT"
    c = v2.crowding(b)
    assert c["flags"] == {"fragile": True, "whale": True, "weak_interval": True, "thin_book": True}
    assert c["level"] == "JELLY" and c["score"] == 4
    assert c["k_to_neutral"] == 1
    assert math.isclose(c["k_weight_share"], 0.6)
    assert c["top_shares"][0] == 0.6


def test_crowding_neutral_uses_the_nearest_threshold():
    b = block(0.5, 0, 0, voters=voters([5, 1], [5, 1]), lo=0.3, hi=0.7)
    c = v2.crowding(b)
    assert c["verdict"] == "NEUTRAL" and c["k_to_neutral"] == 1 and c["k_to_opposite"] is None


def test_crowding_no_voters_does_not_blow_up():
    c = v2.crowding(block(None, 0, 0, n_long=0, n_short=0))
    assert c["voters"] == 0 and c["top1_share"] is None and c["k_to_neutral"] is None
    assert c["flags"]["thin_book"] is True


def test_crowding_rebuilds_from_top_positions_and_says_it_is_an_estimate():
    top = [{"side": "SHORT", "weight": 6.0}, {"side": "SHORT", "weight": 2.0}, {"side": "LONG", "weight": 2.0}]
    b = block(0.2, 4.0, 8.0, n_long=3, n_short=4, top=top)  # 4 unseen voters: 2 long (2.0 left), 2 short (0 left)
    c = v2.crowding(b)
    assert c["exact"] is False and c["voters"] == 5  # 3 known + 2 unseen longs at 1.0 each; unseen shorts have no weight left
    # exact flag is true only when every voter is in the known list
    full = block(0.2, 2.0, 8.0, n_long=1, n_short=2, top=top)
    assert v2.crowding(full)["exact"] is True


def test_top_shares_sum_to_at_most_one():
    b = block(0.4, 0, 0, voters=voters([3, 2], [4, 4, 1, 1, 1, 1, 1, 1, 1, 1, 1]), lo=0.2, hi=0.6)
    assert sum(v2.crowding(b)["top_shares"]) <= 1.0


def test_top_sides_line_up_with_top_shares():
    b = block(0.2, 0, 0, voters=voters([2], [6, 1, 1]), lo=0.1, hi=0.3)
    c = v2.crowding(b)
    assert c["top_sides"] == ["SHORT", "LONG", "SHORT", "SHORT"] and len(c["top_sides"]) == len(c["top_shares"])
