"""Tunable constants. Documented in the README."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
SITE_DIR = ROOT / "site"
SITE_DATA_DIR = SITE_DIR / "data"
SIGNAL_JSON = DATA_DIR / "signal.json"
SITE_SIGNAL_JSON = SITE_DATA_DIR / "signal.json"
COHORT_JSON = DATA_DIR / "cohort.json"
LEADERBOARD_CACHE = CACHE_DIR / "leaderboard.json"
LEADERBOARD_META = CACHE_DIR / "leaderboard_meta.json"

LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
INFO_URL = "https://api.hyperliquid.xyz/info"
REPO_URL = "https://github.com/PrafullJ0shi/metal-future-forecast"
SITE_URL = "https://prafullj0shi.github.io/metal-future-forecast/"
USER_AGENT = f"metal-future-forecast/0.1 (+{REPO_URL})"

# Markets. Checked on 25 Nov 2026 with perpDexs + metaAndAssetCtxs:
# the validator dex lists PAXG (a gold-backed token, not spot gold) and the
# HIP-3 builder dex "xyz" (trade[XYZ]) lists xyz:GOLD and xyz:SILVER, both
# tracking USD spot per troy ounce. Every other builder dex's GOLD/SILVER is
# delisted. No validator-dex silver market exists.
METALS: dict[str, dict] = {
    "gold": {
        "coin": "xyz:GOLD",
        "dex": "xyz",
        "label": "Gold",
        "unit": "troy oz",
        "underlying": "USD spot price of one troy ounce of gold (XAU/USD), priced by trade[XYZ]",
        # Standard HIP-3 fee: 2x core. Gold is excluded from growth mode.
        "taker_fee": 0.0009,
        "reference": "PAXG",
    },
    "silver": {
        "coin": "xyz:SILVER",
        "dex": "xyz",
        "label": "Silver",
        "unit": "troy oz",
        "underlying": "USD spot price of one troy ounce of silver (XAG/USD), priced by trade[XYZ]",
        # Growth mode: at least 90% below the standard HIP-3 rate.
        "taker_fee": 0.00009,
        "reference": None,
    },
}
REFERENCE_COINS = {"PAXG": {"dex": None, "label": "PAXG (validator perp on a gold-backed token)"}}

# Cohort filters (identical to the BTC project)
MIN_EQUITY = 10_000.0
MIN_MONTH_PNL = 0.0
MAX_TURNOVER = 100.0
TOP_N = 500
CANDIDATE_POOL = 700

# Weights
EQUITY_FULL_WEIGHT = 100_000.0
CONVICTION_CAP = 3.0

# Verdict
P_LONG_THRESHOLD = 0.60
P_SHORT_THRESHOLD = 0.40

# Interval
BOOTSTRAP_N = 5000
BOOTSTRAP_SEED = 42
BETA_PRIOR_A = 1.0
BETA_PRIOR_B = 1.0
CI_LEVEL = 0.95

# Rate limits (official info API, per IP)
WEIGHT_CAPACITY = 1200
WEIGHT_REFILL_PER_MINUTE = 1200
WEIGHT_CLEARINGHOUSE = 2
WEIGHT_ALL_MIDS = 2
WEIGHT_PORTFOLIO = 20
WEIGHT_META_AND_CTXS = 20
WEIGHT_CANDLES = 20
WEIGHT_FUNDING = 20
WEIGHT_FILLS = 20
MAX_CONCURRENCY = 6
HTTP_TIMEOUT = 60.0
RETRY_STATUS = (429, 500, 502, 503, 504)
MAX_RETRIES = 6

# Refresh policy
PORTFOLIO_TTL_SEC = 60 * 60
HISTORY_MAX_POINTS = 1440
SIGNAL_HISTORY_POINTS = 48

# Market context
CANDLE_DAYS_1H = 35
CANDLE_DAYS_1D = 400
CANDLE_DAYS_15M = 16
FUNDING_DAYS = 30
CHART_CANDLES_1H = 168

# Flows (app/tracking.py)
CONTRAST_N = 500
FILL_FETCH_MIN_USD = 10_000.0
FILL_FETCH_MAX = 50
FILL_LOOKBACK_H = 4.0
LIQ_SCAN_ABSORBERS = 8
LIQ_SCAN_TOTAL = 16

REQUEST_TIMEOUT = HTTP_TIMEOUT

# v2: tilt, crowding and flip alerts
FEED_DIR = SITE_DIR / "feed"
ALERTS_JSON = DATA_DIR / "alerts.json"
SITE_ALERTS_JSON = SITE_DATA_DIR / "alerts.json"
ALERT_COOLDOWN_H = 3.0        # a second confirmed flip for the same metal inside this window is logged, not pinged
ALERT_MAX_EVENTS = 100        # events kept in alerts.json
ALERT_FEED_ENTRIES = 20       # entries per Atom feed
TILT_EVEN_BAND = 0.30         # |lean gap| below this reads as "about even"
RATIO_WINDOW_DAYS = 180
FLIP_FRAGILE_K = 2            # call flips if this many wallets or fewer close
WHALE_SHARE = 0.25            # one wallet holding this much of the vote is a whale call
THIN_BOOK_VOTERS = 20
