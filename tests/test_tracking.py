from app import flow as F
from app import tape as T

HOUR = 3_600_000
MIN = 60_000


# --- flow: splitting one wallet's change -----------------------------------

def test_split_change_cases():
    assert F.split_change(0, 2)["oL"] == 2
    assert F.split_change(1, 3)["aL"] == 2
    assert F.split_change(3, 1)["tL"] == 2
    assert F.split_change(3, 0)["cL"] == 3
    assert F.split_change(0, -2)["oS"] == 2
    assert F.split_change(-1, -3)["aS"] == 2
    assert F.split_change(-3, -1)["tS"] == 2
    assert F.split_change(-3, 0)["cS"] == 3
    flip = F.split_change(2, -1)
    assert flip["cL"] == 2 and flip["oS"] == 1 and flip["aL"] == 0 and flip["tL"] == 0
    flip2 = F.split_change(-2, 5)
    assert flip2["cS"] == 2 and flip2["oL"] == 5
    assert all(v == 0 for v in F.split_change(1.5, 1.5).values())


def test_flow_step_values_at_mark_and_ignores_churn():
    prev = {"0xaaaaaaaa": 1.0, "0xbbbbbbbb": -2.0, "0xgone0000": 5.0}
    cur = {"0xaaaaaaaa": 1.5, "0xbbbbbbbb": -1.0, "0xnew00000": 9.0}
    st = F.flow_step(prev, cur, 100.0)
    fl = st["flows"]
    assert fl["aL"] == 50.0           # +0.5 BTC long at 100
    assert fl["tS"] == 100.0          # short cut by 1 BTC
    assert fl["oL"] == 0 and fl["cL"] == 0  # churned wallets are not flows
    assert st["compared"] == 2
    assert sorted(st["traded"]) == ["aaaaaa", "bbbbbb"]
    assert st["totals"]["long_ntl"] == 1050.0
    assert st["totals"]["short_ntl"] == 100.0


def test_flow_step_counts_trades_not_price():
    prev = {"0x1": 2.0}
    cur = {"0x1": 2.0}
    st = F.flow_step(prev, cur, 50_000.0)
    assert all(v == 0 for v in st["flows"].values())
    assert st["traded"] == []


def test_pack_roundtrip():
    st = F.flow_step({"0xab": 1.0}, {"0xab": -1.0}, 10.0)
    back = F.unpack_step(F.pack_step(st))
    assert back["flows"]["cL"] == 10.0 and back["flows"]["oS"] == 10.0
    assert back["totals"]["short_ntl"] == 10.0


def _log(sizes_by_step, step_ms=30 * MIN, t0=0, mark=100.0):
    log, prev, tp = [], None, None
    for i, pos in enumerate(sizes_by_step):
        t = t0 + i * step_ms
        log = F.append_log(log, t + 10 * 24 * HOUR, tp, {"s": F.flow_step(prev, pos, mark), "c": None})
        prev, tp = pos, t + 10 * 24 * HOUR
    return log


def test_window_sums_steps_and_split():
    # 9 snapshots, 30 minutes apart: 4 hours.
    seq = [{"0xa": 1.0, "0xb": -3.0}] + [{"0xa": 1.0 + i, "0xb": -3.0} for i in range(1, 9)]
    log = _log(seq)
    now = log[-1]["t"]
    w4 = F.window_flow(log, "s", now, 4)
    assert w4["available"]
    assert w4["longs_in"] == 800.0 and w4["longs_out"] == 0
    assert w4["longs_net"] == 800.0 and w4["shorts_net"] == 0
    assert w4["direction"] == "LONG"
    assert w4["short_share_before"] == 0.75            # 300 of 400 at the start
    assert abs(w4["short_share_after"] - 300 / 1200) < 1e-4
    w1 = F.window_flow(log, "s", now, 1)
    assert w1["longs_net"] == 200.0 and w1["steps"] == 2
    w8 = F.window_flow(log, "s", now, 8)
    assert not w8["available"] and "Building history" in w8["reason"]


def test_window_wallets_traded_unique():
    seq = [{"0xaaaaaa1": 0.0}, {"0xaaaaaa1": 1.0}, {"0xaaaaaa1": 2.0}, {"0xaaaaaa1": 1.0}]
    log = _log(seq)
    w = F.window_flow(log, "s", log[-1]["t"], 1.5)
    assert w["wallets_traded"] == 1
    assert w["flows"]["oL"] == 100.0 and w["flows"]["aL"] == 100.0 and w["flows"]["tL"] == 100.0


def test_window_tolerates_irregular_cadence():
    log = _log([{"0xa": 1.0}, {"0xa": 2.0}, {"0xa": 3.0}], step_ms=55 * MIN)
    w = F.window_flow(log, "s", log[-1]["t"], 1)
    assert w["available"] and w["steps"] == 1


def test_contrast_candidates_worst_first_and_filtered():
    def row(a, eq, pnl, vlm):
        return {"ethAddress": a, "accountValue": str(eq),
                "windowPerformances": [["month", {"pnl": str(pnl), "vlm": str(vlm)}]]}
    rows = [row("0xA", 50_000, -10_000, 1e6), row("0xB", 50_000, -90_000, 1e6), row("0xC", 5_000, -1e6, 0),
            row("0xD", 50_000, 5_000, 0), row("0xE", 50_000, -50_000, 1e8), row("0xF", 50_000, -20_000, 0)]
    out = F.contrast_candidates(rows, min_equity=10_000, max_turnover=100, exclude={"0xf"}, n=10)
    assert [r["address"] for r in out] == ["0xb", "0xa"]


def test_compare_sentence_opposite():
    a = {"available": True, "toward_long": 5e6}
    b = {"available": True, "toward_long": -2e6}
    s = F.compare_sentence("4 hours", a, b)
    assert "top cohort moved toward long" in s and "worst-performing cohort moved toward short" in s
    assert "opposite" in s


def test_fmt_usd():
    assert F.fmt_usd(18_370_000) == "$18.37m"
    assert F.fmt_usd(-930_000) == "$930k"
    assert F.fmt_usd(1.2e9) == "$1.20b"


# --- tape: liquidations -----------------------------------------------------

def _fill(**kw):
    base = {"coin": "BTC", "px": "60000", "sz": "1", "side": "B", "time": 1_000_000, "oid": 1,
            "tid": 1, "crossed": True, "startPosition": "0", "dir": "Open Long", "twapId": None}
    base.update(kw)
    return base


def test_liquidation_side_counterparty_and_own():
    liq = {"liquidatedUser": "0xvictim", "markPx": "59990", "method": "market"}
    fills = {
        "0xmaker": [_fill(side="B", tid=10, liquidation=liq, sz="2")],
        "0xmaker2": [_fill(side="B", tid=10, liquidation=liq, sz="2")],  # same trade seen twice
        "0xshorty": [_fill(side="B", tid=11, time=2_000_000, startPosition="-3", dir="Close Short",
                           liquidation={"liquidatedUser": "0xshorty", "markPx": "61000", "method": "market"})],
    }
    ev = T.liquidations_from_fills(fills, "BTC")
    by = {e["user"]: e for e in ev}
    assert by["0xvictim"]["side"] == "LONG"      # counterparty bought, so a long was sold off
    assert by["0xvictim"]["ntl"] == 120_000.0     # deduplicated by trade id
    assert by["0xshorty"]["side"] == "SHORT" and by["0xshorty"]["own"]


def test_merge_events_adds_only_new_trades():
    a = [{"key": "k", "t": 10, "ntl": 100.0, "tids": [1], "via": ["x"]}]
    b = [{"key": "k", "t": 10, "ntl": 200.0, "tids": [1, 2], "via": ["y"]}]
    m = T.merge_events(a, b, now_ms=20)
    assert m[0]["ntl"] == 200.0 and sorted(m[0]["tids"]) == [1, 2] and set(m[0]["via"]) == {"x", "y"}


def test_wave_relative_to_norm():
    now = 200 * HOUR
    quiet = [{"t": now - (10 + i) * HOUR, "ntl": 50_000.0, "side": "LONG"} for i in range(100)]
    burst = [{"t": now - i * 5 * MIN, "ntl": 600_000.0, "side": "LONG"} for i in range(4)]
    w = T.liquidation_wave(quiet + burst, now, observing_since=now - 150 * HOUR)
    assert w["wave"] and w["dominant_side"] == "LONG"
    assert w["last_hour_usd"] == 2_400_000.0
    calm = T.liquidation_wave(quiet, now, observing_since=now - 150 * HOUR)
    assert not calm["wave"]
    few = T.liquidation_wave(quiet + burst[:2], now, observing_since=now - 150 * HOUR)
    assert not few["wave"]  # too few events even if large


def test_hourly_series_buckets():
    now = 10 * HOUR + 5
    s = T.hourly_series([{"t": 9 * HOUR + 1, "ntl": 5.0, "side": "SHORT"}], now, 3)
    assert len(s) == 3 and s[-2] == [9 * HOUR, 0.0, 5.0]


def test_robust_z():
    assert T.robust_z(10, [1, 2, 3, 4, 5]) > 3
    assert T.robust_z(1, [2, 2, 2]) is None


def test_oi_proxy_flags_drop_with_sharp_move():
    pts = [{"_ms": i * 30 * MIN, "oi": 30_000.0, "mark": 60_000.0} for i in range(5)]
    pts.append({"_ms": 5 * 30 * MIN, "oi": 29_000.0, "mark": 59_000.0})
    out = T.oi_proxy(pts, 5 * 30 * MIN)
    assert out["latest"]["flag"] and out["flagged"][-1]["side"] == "LONG"
    assert out["flagged"][-1]["usd"] == 1_000 * 59_000.0
    pts[-1]["mark"] = 60_100.0  # OI drop without a sharp move: not flagged
    assert not T.oi_proxy(pts, 5 * 30 * MIN)["latest"]["flag"]


# --- tape: whales and worked orders ------------------------------------------

def test_orders_group_by_oid_and_skip_liquidation_fills():
    fills = [_fill(oid=1, tid=1, sz="10"), _fill(oid=1, tid=2, sz="10", time=1_000_500),
             _fill(oid=2, tid=3, liquidation={"liquidatedUser": "0xz"})]
    os_ = T.orders_from_fills(fills, "BTC")
    assert len(os_) == 1 and os_[0]["ntl"] == 1_200_000.0 and os_[0]["n_fills"] == 2
    assert T.large_orders(os_)[0]["oid"] == 1


def test_worked_run_pattern_detected():
    # 8 buy orders of 3 BTC every 4 minutes: $1.44M over 28 minutes.
    fills = [_fill(oid=i, tid=i, sz="3", time=i * 4 * MIN) for i in range(8)]
    runs = T.worked_runs(T.orders_from_fills(fills, "BTC"))
    assert len(runs) == 1
    r = runs[0]
    assert r["kind"] == "pattern" and r["orders"] == 8 and r["sign"] == 1
    assert r["minutes"] == 28.0 and abs(r["ntl"] - 1_440_000) < 1e-6
    assert r["median_gap_min"] == 4.0


def test_worked_run_rejects_one_big_order_and_interruptions():
    big = [_fill(oid=0, tid=0, sz="30", time=0)] + [_fill(oid=i, tid=i, sz="1", time=i * 4 * MIN) for i in range(1, 6)]
    assert T.worked_runs(T.orders_from_fills(big, "BTC")) == []   # one order > 50%
    mixed = [_fill(oid=i, tid=i, sz="3", time=i * 4 * MIN, side="B" if i != 3 else "A") for i in range(8)]
    assert T.worked_runs(T.orders_from_fills(mixed, "BTC")) == []  # a sell breaks the run
    slow = [_fill(oid=i, tid=i, sz="3", time=i * 50 * MIN) for i in range(8)]
    assert T.worked_runs(T.orders_from_fills(slow, "BTC")) == []   # pauses longer than 45 min


def test_native_twap_grouped_by_id():
    fills = [_fill(oid=i, tid=i, sz="5", time=i * MIN, twapId=77) for i in range(4)]
    runs = T.worked_runs(T.orders_from_fills(fills, "BTC"))
    assert len(runs) == 1 and runs[0]["kind"] == "native" and runs[0]["twap_id"] == 77


def test_action_of():
    assert T.action_of(0, 2) == ("opened", "LONG")
    assert T.action_of(2, 3) == ("added to", "LONG")
    assert T.action_of(-2, -1) == ("trimmed", "SHORT")
    assert T.action_of(-2, 0) == ("closed", "SHORT")
    assert T.action_of(2, -1) == ("flipped to", "SHORT")
    assert T.action_of(1, 1) is None


def test_position_event_card_fields():
    orders = T.orders_from_fills([_fill(oid=5, tid=5, sz="20", px="59294", time=5 * MIN)], "BTC")
    ev = T.position_events(
        [{"address": "0xw", "cohort": "smart", "prev": 100.0, "cur": 140.0,
          "row": {"leverage": 20, "leverage_type": "cross", "margin_used": 4e5, "unrealized_pnl": 1e4, "roe": 0.02},
          "meta": {"rank": 3, "rank_of": 500, "all_time_pnl": 1e7, "month_pnl": 2e6}}],
        t_prev=0, t_now=30 * MIN, mark=60_000.0, orders_by_wallet={"0xw": orders}, runs_by_wallet={},
    )
    e = ev[0]
    assert e["verb"] == "added to" and e["side"] == "LONG"
    assert e["before_usd"] == 6_000_000.0 and e["now_usd"] == 8_400_000.0 and e["change_usd"] == 2_400_000.0
    assert e["px"] == 59294.0 and e["px_source"] == "fills" and e["t"] == 5 * MIN
    assert e["rank"] == 3 and e["leverage_type"] == "cross"
    small = T.position_events([{"address": "0xw", "prev": 1.0, "cur": 2.0}], t_prev=0, t_now=1, mark=60_000.0,
                              orders_by_wallet={}, runs_by_wallet={})
    assert small == []


def test_window_unavailable_until_first_real_step():
    # A totals-only row (no previous snapshot) cannot anchor a window by itself.
    log = F.append_log([], 10 * HOUR, 9 * HOUR, {"s": None, "c": F.flow_step(None, {"0xa": 1.0}, 100.0)})
    w = F.window_flow(log, "c", 10 * HOUR, 1)
    assert not w["available"]
    log = F.append_log(log, 10 * HOUR + 30 * MIN, 10 * HOUR, {"s": None, "c": F.flow_step({"0xa": 1.0}, {"0xa": 2.0}, 100.0)})
    w = F.window_flow(log, "c", 10 * HOUR + 30 * MIN, 0.5)
    assert w["available"] and w["longs_net"] == 100.0
    assert not F.window_flow(log, "c", 10 * HOUR + 30 * MIN, 4)["available"]


def test_window_gap_reason_names_the_gap():
    from app import flow as FL
    H = 3_600_000
    t0 = 1_800_000_000_000
    z = FL.pack_step(FL.flow_step({"0xab": 1.0}, {"0xab": 1.0}, 10.0))
    rows = []
    for t in (t0, t0 + int(1.7 * H), t0 + int(2.2 * H)):
        rows.append({"t": t, "tp": rows[-1]["t"] if rows else None, "src": "live", "s": z, "c": None})
    w = FL.window_flow(rows, "s", rows[-1]["t"], 1)
    assert not w["available"]
    assert "close enough" in w["reason"]
