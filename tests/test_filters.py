from app.sweep import filter_leaderboard
from app.hl_client import window_pnl_from_portfolio


def _row(address, equity, pnl, vlm, name=None):
    return {
        "ethAddress": address,
        "accountValue": str(equity),
        "displayName": name,
        "windowPerformances": [
            ["day", {"pnl": "0", "roi": "0", "vlm": "0"}],
            ["week", {"pnl": "0", "roi": "0", "vlm": "0"}],
            ["month", {"pnl": str(pnl), "roi": "0.1", "vlm": str(vlm)}],
            ["allTime", {"pnl": "0", "roi": "0", "vlm": "0"}],
        ],
    }


def test_filters_equity_pnl_and_turnover():
    rows = [
        _row("0xAAA", 9_999, 50_000, 10_000),          # equity too low
        _row("0xBBB", 20_000, 0, 10_000),               # pnl not > 0
        _row("0xCCC", 20_000, -1, 10_000),              # negative pnl
        _row("0xDDD", 20_000, 50_000, 20_000 * 101),    # turnover 101
        _row("0xEEE", 20_000, 10_000, 20_000 * 100),    # turnover exactly 100, kept
        _row("0xFFF", 50_000, 80_000, 100_000),         # kept, highest pnl
        _row("0x111", 50_000, 40_000, 100_000),         # kept
    ]
    out = filter_leaderboard(rows)
    addrs = [r["address"] for r in out]
    assert addrs == ["0xfff", "0x111", "0xeee"]
    assert out[0]["leaderboard_month_pnl"] == 80_000


def test_perp_month_from_portfolio():
    payload = [
        ["month", {"pnlHistory": [[1, "999"]], "accountValueHistory": [], "vlm": "0"}],
        ["perpMonth", {"pnlHistory": [[1, "0"], [2, "12345.5"]], "accountValueHistory": [], "vlm": "1"}],
    ]
    assert window_pnl_from_portfolio(payload, "perpMonth") == 12345.5
    assert window_pnl_from_portfolio(payload, "month") == 999
    assert window_pnl_from_portfolio([], "perpMonth") is None
