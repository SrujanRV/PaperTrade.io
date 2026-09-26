"""
config.py — Central configuration for the PaperTrade backend.
All tunable constants live here so nothing is hard-coded elsewhere.
"""

from zoneinfo import ZoneInfo

# ── Price-feed polling ──────────────────────────────────────────────────────
PRICE_CACHE_TTL_SECONDS: int = 10        # Cache TTL to respect yfinance rate limits
YFINANCE_BATCH_SIZE: int = 10            # Max tickers per yfinance download call
YFINANCE_HISTORY_PERIOD: str = "2d"      # Period used when fetching OHLCV history
YFINANCE_HISTORY_INTERVAL: str = "1m"    # Interval for that history pull

# ── Market hours (local exchange time) ─────────────────────────────────────
MARKET_SESSIONS = {
    "NSE": {
        "tz": ZoneInfo("Asia/Kolkata"),
        "open":  (9, 15),   # 09:15 IST
        "close": (15, 30),  # 15:30 IST
        "weekdays": range(0, 5),  # Mon–Fri
    },
    "BSE": {
        "tz": ZoneInfo("Asia/Kolkata"),
        "open":  (9, 15),
        "close": (15, 30),
        "weekdays": range(0, 5),
    },
    "NYSE": {
        "tz": ZoneInfo("America/New_York"),
        "open":  (9, 30),   # 09:30 ET
        "close": (16, 0),   # 16:00 ET
        "weekdays": range(0, 5),
    },
    "NASDAQ": {
        "tz": ZoneInfo("America/New_York"),
        "open":  (9, 30),
        "close": (16, 0),
        "weekdays": range(0, 5),
    },
    "CME": {
        "tz": ZoneInfo("America/Chicago"),
        # CME Globex: Sunday 17:00 CT - Friday 16:00 CT with daily halt 16:00-17:00 CT Mon-Thu
        "daily_break": ((16, 0), (17, 0)),
        "weekend_close_day": 4,  # Friday
        "weekend_close_time": (16, 0),
        "weekend_open_day": 6,   # Sunday
        "weekend_open_time": (17, 0),
    },
}

# ── Exchange detection ──────────────────────────────────────────────────────
# Maps yfinance symbol suffix → canonical exchange name used in MARKET_SESSIONS
SUFFIX_TO_EXCHANGE: dict[str, str] = {
    ".NS": "NSE",
    ".BO": "BSE",
}
# US tickers (no suffix) → default exchange label
US_DEFAULT_EXCHANGE = "NASDAQ"

# ── SSE ────────────────────────────────────────────────────────────────────
SSE_PING_INTERVAL_SECONDS: int = 15     # Keepalive ping interval
SSE_PUSH_INTERVAL_SECONDS: int = 5      # Push interval (5-10s as per spec)

# ── CORS (development) ─────────────────────────────────────────────────────
CORS_ORIGINS: list[str] = [
    "http://localhost:5173",   # Vite dev server
    "http://localhost:3000",
]
