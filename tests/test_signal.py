from app.signal import (
    beta_interval,
    bootstrap_interval,
    compute_signal,
    conviction,
    equity_shrink,
    skill_weight,
    trader_weight,
    verdict_from_p,
)


def test_skill_weight_zero_and_positive():
    assert skill_weight(0) == 0
    assert skill_weight(-100) == 0
    assert abs(skill_weight(math_e_arg()) - __import__("math").log1p(1_000_000)) < 1e-12


def math_e_arg() -> float:
    return 1_000_000.0


def test_equity_shrink():
    assert equity_shrink(0) == 0
    assert equity_shrink(50_000) == 0.5
    assert equity_shrink(100_000) == 1.0
    assert equity_shrink(500_000) == 1.0


def test_conviction_cap():
    assert conviction(0, 100_000) == 0
    assert conviction(50_000, 100_000) == 0.5
    assert conviction(1_000_000, 100_000) == 3.0


def test_trader_weight_product():
    w = trader_weight(month_pnl=1_000_000, equity=50_000, notional=25_000)
    expected = skill_weight(1_000_000) * 0.5 * 0.5
    assert abs(w - expected) < 1e-12


def test_verdict_thresholds():
    assert verdict_from_p(None) == "NEUTRAL"
    assert verdict_from_p(0.60) == "LONG"
    assert verdict_from_p(0.59) == "NEUTRAL"
    assert verdict_from_p(0.40) == "SHORT"
    assert verdict_from_p(0.41) == "NEUTRAL"


def test_all_longs_give_p_one():
    traders = [
        {
            "address": f"0x{i:040x}",
            "month_pnl": 100_000,
            "equity": 200_000,
            "szi": 1.0,
            "notional": 50_000,
        }
        for i in range(10)
    ]
    s = compute_signal(traders)
    assert s.n_long == 10 and s.n_short == 0 and s.n_flat == 0
    assert s.p_long == 1.0
    assert s.verdict == "LONG"
    assert s.ci_low is not None and s.ci_high == 1.0


def test_flats_do_not_vote():
    traders = [
        {"address": "0x1", "month_pnl": 1e6, "equity": 1e6, "szi": 0, "notional": 0},
        {"address": "0x2", "month_pnl": 1e6, "equity": 1e6, "szi": 2, "notional": 80_000},
        {"address": "0x3", "month_pnl": 1e6, "equity": 1e6, "szi": -1, "notional": 20_000},
    ]
    s = compute_signal(traders)
    assert s.n_flat == 1
    assert s.n_long == 1 and s.n_short == 1
    # longs have 4x the notional, same skill and equity, so P(long) > 0.5
    assert s.p_long is not None and s.p_long > 0.5


def test_bootstrap_reproducible():
    items = [(1, 2.0), (-1, 1.0), (1, 1.5), (-1, 0.5)] * 5
    a = bootstrap_interval(items)
    b = bootstrap_interval(items)
    assert a == b
    assert a[0] is not None and a[0] <= a[1]


def test_beta_interval_contains_mean():
    lo, hi = beta_interval(30, 10)
    mean = (1 + 30) / (2 + 40)
    assert lo is not None and lo < mean < hi


def test_empty_cohort_is_neutral():
    s = compute_signal([])
    assert s.verdict == "NEUTRAL"
    assert s.p_long is None
    assert s.n_traders == 0
