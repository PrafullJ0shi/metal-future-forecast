"""Scalp corner: the lean, the confidence word, the reasons, and that it never invents a number."""

import math

from app import config, scalp

GROSS = 10_000_000.0
ANNUAL_VOL = 0.20   # hourly sigma = 0.2 / sqrt(8760) = 0.2137%


def hour(net=0.0, gross=1_000_000.0, move=0.0, flip_s=0, flip_l=0, available=True, span=60):
    return {"available": available, "net_toward_long_usd": net, "gross_moved_usd": gross, "price_move": move,
            "flip_to_short": flip_s, "flip_to_long": flip_l, "span_min": span}


def mkt(vol=ANNUAL_VOL, funding=0.0):
    return {"realised_vol_24h": vol, "funding_hourly": funding}


def test_flow_score_scales_to_five_percent_of_gross_and_clamps():
    s, ok = scalp.flow_score(hour(net=250_000), GROSS)
    assert ok and math.isclose(s, 0.5)
    assert scalp.flow_score(hour(net=5_000_000), GROSS)[0] == 1.0
    assert scalp.flow_score(hour(net=-5_000_000), GROSS)[0] == -1.0


def test_quiet_hour_or_missing_data_is_not_counted():
    assert scalp.flow_score(hour(net=100_000, gross=100_000), GROSS) == (0.0, False)
    assert scalp.flow_score(hour(available=False), GROSS) == (0.0, False)
    assert scalp.flow_score(hour(net=1e6), 0) == (0.0, False)


def test_momentum_is_in_units_of_hourly_sigma_with_a_fallback():
    sigma = ANNUAL_VOL / math.sqrt(8760)
    s, ok = scalp.momentum_score(sigma * 1.0, ANNUAL_VOL)
    assert ok and math.isclose(s, 0.5)
    assert scalp.momentum_score(-sigma * 10, ANNUAL_VOL)[0] == -1.0
    s2, ok2 = scalp.momentum_score(0.003, None)           # fallback sigma 0.3%
    assert ok2 and math.isclose(s2, 0.5)
    assert scalp.momentum_score(None, ANNUAL_VOL) == (0.0, False)


def test_funding_is_a_contrarian_nudge():
    assert scalp.funding_score(config.SCALP_FUNDING_FULL)[0] == -1.0
    assert scalp.funding_score(-config.SCALP_FUNDING_FULL / 2)[0] == 0.5
    assert scalp.funding_score(None) == (0.0, False)


def test_weights_add_up_to_one():
    assert math.isclose(config.SCALP_W_FLOW + config.SCALP_W_MOVE + config.SCALP_W_FUND, 1.0)


def test_agreeing_flow_and_price_give_a_confident_scalp_long():
    sigma = ANNUAL_VOL / math.sqrt(8760)
    r = scalp.lean("Gold", hour(net=500_000, move=sigma * 2), mkt(), GROSS)
    assert r["lean"] == "SCALP LONG" and r["confidence"] == "high"
    assert math.isclose(r["score"], 0.55 * 1.0 + 0.30 * 1.0)
    assert r["used"] == {"flow": True, "momentum": True, "funding": True}
    assert 1 <= len(r["reasons"]) <= 3 and "toward longs" in r["reasons"][0]


def test_agreeing_short_side():
    sigma = ANNUAL_VOL / math.sqrt(8760)
    r = scalp.lean("Silver", hour(net=-500_000, move=-sigma * 2, flip_s=1), mkt(), GROSS)
    assert r["lean"] == "SCALP SHORT" and r["confidence"] == "high"
    assert any("1 flipped short" in x for x in r["reasons"])


def test_wallets_and_price_disagreeing_means_sit_out_with_low_confidence():
    sigma = ANNUAL_VOL / math.sqrt(8760)
    r = scalp.lean("Gold", hour(net=600_000, move=-sigma * 2), mkt(), GROSS)
    assert r["lean"] == "SIT OUT" and r["confidence"] == "low"
    assert "disagree" in r["reasons"][0]


def test_small_scores_sit_out():
    r = scalp.lean("Gold", hour(net=100_000, move=0.0), mkt(), GROSS)
    assert r["lean"] == "SIT OUT" and abs(r["score"]) < config.SCALP_LEAN_AT


def test_no_history_sits_out_and_says_so():
    r = scalp.lean("Gold", {"available": False}, mkt(), GROSS)
    assert r["lean"] == "SIT OUT" and r["confidence"] == "low"
    assert any("Not enough history" in x for x in r["reasons"])
    assert scalp.lean("Gold", None, None, None)["lean"] == "SIT OUT"


def test_quiet_hour_is_explained():
    r = scalp.lean("Silver", hour(net=0, gross=50_000, move=0.0), mkt(), GROSS)
    assert r["lean"] == "SIT OUT"
    assert any("barely touched" in x for x in r["reasons"])


def test_funding_alone_can_add_a_reason_but_not_flip_the_call():
    r = scalp.lean("Gold", hour(net=0, gross=0), mkt(funding=5e-5), GROSS)
    assert r["lean"] == "SIT OUT"
    assert any("Funding:" in x and "longs are paying" in x and "long side" in x for x in r["reasons"])


def test_confidence_word_rules():
    assert scalp.confidence_word(0.7, 0.8, 0.5, True, True, "SCALP LONG") == "high"
    assert scalp.confidence_word(0.45, 0.8, -0.1, True, True, "SCALP LONG") == "medium"
    assert scalp.confidence_word(0.26, 0.4, 0.0, True, False, "SCALP LONG") == "low"
    assert scalp.confidence_word(0.0, 0.0, 0.0, False, False, "SIT OUT") == "low"
    assert scalp.confidence_word(0.02, 0.0, 0.0, True, True, "SIT OUT") == "high"


def test_output_carries_the_honest_label_and_never_a_hit_rate():
    r = scalp.lean("Gold", hour(net=300_000, move=0.002), mkt(), GROSS)
    assert "not advice" in r["disclaimer"] and "not the main signal" in r["disclaimer"]
    assert "no hit rate is claimed" in r["disclaimer"].lower()
    assert not any(k in r for k in ("hit_rate", "win_rate", "accuracy"))


def test_enrich_adds_hour_driven_scalp_to_each_metal():
    import json
    from app import alerts as AL, enrich
    payload = json.loads(open("data/signal.json").read())
    payload["metals"]["gold"]["hour"] = {**hour(net=-1_500_000, gross=2_000_000, move=-0.004, flip_s=2)}
    out, _ = enrich.apply(payload, None, AL.empty_state())
    assert out["metals"]["gold"]["scalp"]["lean"] in ("SCALP SHORT", "SIT OUT")
    assert out["metals"]["silver"]["scalp"]["lean"] == "SIT OUT"     # no hour block on this snapshot
