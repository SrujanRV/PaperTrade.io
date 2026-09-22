"""
services/price_feed.py — Fetch and normalize live stock quotes via yfinance 1.x.

Fetch strategy:
  1. yf.download() period="5d", interval="1d"  → reliable even when market is closed
  2. When market open: additionally yf.download() period="1d", interval="2m" for live price

yfinance 1.x always returns a MultiIndex DataFrame (ticker, column) when multiple
tickers are passed, and a MultiIndex with a single ticker label when only one ticker
is passed (multi_level_index=True by default).  The _parse_symbol() helper handles
both shapes transparently.

PriceQuote fields:
    symbol, display_name, exchange, currency,
    price, prev_close, change, change_pct,
    day_high, day_low, volume,
    market_open, timestamp, error
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf

from config import (
    PRICE_CACHE_TTL_SECONDS,
    YFINANCE_BATCH_SIZE,
    SUFFIX_TO_EXCHANGE,
    US_DEFAULT_EXCHANGE,
    MARKET_SESSIONS,
)

logger = logging.getLogger(__name__)


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class PriceQuote:
    symbol: str
    display_name: str
    exchange: str
    currency: str
    price: float
    prev_close: float
    change: float
    change_pct: float
    day_high: float
    day_low: float
    volume: int
    market_open: bool
    timestamp: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── In-memory cache ───────────────────────────────────────────────────────────

@dataclass
class _CacheEntry:
    quote: PriceQuote
    fetched_at: float = field(default_factory=time.monotonic)

    def is_stale(self) -> bool:
        return (time.monotonic() - self.fetched_at) > PRICE_CACHE_TTL_SECONDS


_cache: dict[str, _CacheEntry] = {}


# ── Symbol helpers ────────────────────────────────────────────────────────────

def _detect_exchange(symbol: str) -> str:
    upper = symbol.upper()
    for suffix, exchange in SUFFIX_TO_EXCHANGE.items():
        if upper.endswith(suffix.upper()):
            return exchange
    return US_DEFAULT_EXCHANGE


def _detect_currency(exchange: str) -> str:
    return "INR" if exchange in ("NSE", "BSE") else "USD"


def _display_name(symbol: str) -> str:
    upper = symbol.upper()
    for suffix in SUFFIX_TO_EXCHANGE:
        if upper.endswith(suffix.upper()):
            return upper[: -len(suffix)]
    return upper


def is_market_open(exchange: str) -> bool:
    """Return True if the given exchange is currently in its trading session."""
    session = MARKET_SESSIONS.get(exchange)
    if not session:
        logger.warning("Unknown exchange %r — assuming open", exchange)
        return True

    now = datetime.now(tz=session["tz"])
    if now.weekday() not in session["weekdays"]:
        return False

    open_h,  open_m  = session["open"]
    close_h, close_m = session["close"]
    open_time  = now.replace(hour=open_h,  minute=open_m,  second=0, microsecond=0)
    close_time = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
    return open_time <= now < close_time


def _error_quote(symbol: str, reason: str) -> PriceQuote:
    exchange = _detect_exchange(symbol)
    return PriceQuote(
        symbol=symbol,
        display_name=_display_name(symbol),
        exchange=exchange,
        currency=_detect_currency(exchange),
        price=0.0, prev_close=0.0, change=0.0, change_pct=0.0,
        day_high=0.0, day_low=0.0, volume=0,
        market_open=is_market_open(exchange),
        timestamp=datetime.now(timezone.utc).isoformat(),
        error=reason,
    )


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        f = float(value)
        return f if f == f else fallback   # NaN guard
    except (TypeError, ValueError):
        return fallback


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


# ── DataFrame slice helper (handles MultiIndex from yfinance 1.x) ─────────────

def _slice_ticker(df: pd.DataFrame, symbol: str) -> pd.DataFrame | None:
    """
    Extract the per-symbol sub-DataFrame from a yf.download() result.

    yfinance 1.x always uses MultiIndex columns: (ticker, field).
    So df["AAPL"] gives a DataFrame with columns [Open, High, Low, Close, Volume].
    Returns None if the symbol is not present or the slice is empty.
    """
    if df is None or df.empty:
        return None

    try:
        # MultiIndex top-level is always the ticker symbol
        tickers_in_df = df.columns.get_level_values(0).unique().tolist()
        # Try case-insensitive match
        match = next((t for t in tickers_in_df if t.upper() == symbol.upper()), None)
        if match is None:
            return None
        sliced = df[match].copy()
        sliced = sliced.dropna(subset=["Close"])
        return sliced if not sliced.empty else None
    except Exception as exc:
        logger.debug("_slice_ticker(%s) failed: %s", symbol, exc)
        return None


# ── Core batch fetch ──────────────────────────────────────────────────────────

def _download(symbols: list[str], period: str, interval: str) -> pd.DataFrame | None:
    """Wrapper around yf.download with consistent kwargs for yfinance 1.x."""
    try:
        df = yf.download(
            tickers=symbols,
            period=period,
            interval=interval,
            group_by="ticker",          # (ticker, field) MultiIndex
            auto_adjust=True,
            progress=False,
            threads=True,
            multi_level_index=True,     # always MultiIndex, even for 1 ticker
        )
        return df if not df.empty else None
    except Exception as exc:
        logger.error("yf.download(%s, %s, %s) failed: %s", symbols, period, interval, exc)
        return None


def _fetch_batch(symbols: list[str]) -> dict[str, PriceQuote]:
    if not symbols:
        return {}

    now_utc = datetime.now(timezone.utc).isoformat()

    # ── Step 1: 5-day daily OHLCV — always available, even when market closed ─
    daily_df = _download(symbols, period="5d", interval="1d")

    # ── Step 2: intraday for open-market symbols ───────────────────────────────
    open_syms = [s for s in symbols if is_market_open(_detect_exchange(s))]
    intra_df = _download(open_syms, period="1d", interval="2m") if open_syms else None

    # ── Step 3: build PriceQuote per symbol ───────────────────────────────────
    results: dict[str, PriceQuote] = {}

    for symbol in symbols:
        exchange = _detect_exchange(symbol)
        currency = _detect_currency(exchange)
        display  = _display_name(symbol)
        mkt_open = is_market_open(exchange)

        try:
            daily = _slice_ticker(daily_df, symbol)
            if daily is None or len(daily) < 1:
                raise ValueError("No daily data — ticker may be invalid or delisted")

            # Base values from daily history
            price      = _safe_float(daily["Close"].iloc[-1])
            prev_close = _safe_float(daily["Close"].iloc[-2]) if len(daily) >= 2 else price
            day_high   = _safe_float(daily["High"].iloc[-1])
            day_low    = _safe_float(daily["Low"].iloc[-1])
            volume     = _safe_int(daily["Volume"].iloc[-1])

            # Override with live intraday price if market is open
            if mkt_open and intra_df is not None:
                intra = _slice_ticker(intra_df, symbol)
                if intra is not None and not intra.empty:
                    price    = _safe_float(intra["Close"].iloc[-1])
                    day_high = _safe_float(intra["High"].max())
                    day_low  = _safe_float(intra["Low"].min())
                    volume   = _safe_int(intra["Volume"].sum())

            if price == 0.0:
                raise ValueError("Price resolved to 0 — data may be unavailable")

            change     = round(price - prev_close, 4)
            change_pct = round((change / prev_close) * 100, 4) if prev_close else 0.0

            results[symbol] = PriceQuote(
                symbol=symbol,
                display_name=display,
                exchange=exchange,
                currency=currency,
                price=round(price, 4),
                prev_close=round(prev_close, 4),
                change=change,
                change_pct=change_pct,
                day_high=round(day_high, 4),
                day_low=round(day_low, 4),
                volume=volume,
                market_open=mkt_open,
                timestamp=now_utc,
                error=None,
            )

        except Exception as exc:
            logger.warning("Failed to build quote for %s: %s", symbol, exc)
            results[symbol] = _error_quote(symbol, str(exc))

    return results


# ── Public API ────────────────────────────────────────────────────────────────

def get_quotes(symbols: list[str], *, force_refresh: bool = False) -> list[PriceQuote]:
    """
    Return PriceQuote objects for the given symbols.

    Uses in-memory cache (TTL = PRICE_CACHE_TTL_SECONDS) to avoid hammering Yahoo.
    Stale / missing symbols are refetched in batches of YFINANCE_BATCH_SIZE.

    Args:
        symbols:       e.g. ["RELIANCE.NS", "AAPL", "TCS.NS"]
        force_refresh: bypass cache

    Returns:
        List of PriceQuote in the same order as input symbols.
    """
    if not symbols:
        return []

    symbols_upper = [s.upper() for s in symbols]
    to_fetch = [
        s for s in symbols_upper
        if force_refresh or s not in _cache or _cache[s].is_stale()
    ]

    if to_fetch:
        logger.info("Fetching %d symbol(s): %s", len(to_fetch), to_fetch)
        for i in range(0, len(to_fetch), YFINANCE_BATCH_SIZE):
            batch = to_fetch[i : i + YFINANCE_BATCH_SIZE]
            fresh = _fetch_batch(batch)
            for sym, quote in fresh.items():
                _cache[sym] = _CacheEntry(quote=quote)

    return [
        _cache[s].quote if s in _cache else _error_quote(s, "Not in cache")
        for s in symbols_upper
    ]


def get_quote(symbol: str, *, force_refresh: bool = False) -> PriceQuote:
    """Convenience wrapper for a single symbol."""
    return get_quotes([symbol], force_refresh=force_refresh)[0]


def clear_cache() -> None:
    """Wipe the in-memory price cache (useful in tests)."""
    _cache.clear()


# ── Search / Autocomplete ─────────────────────────────────────────────────────

_search_cache: dict[str, tuple[float, list[dict]]] = {}
_SEARCH_CACHE_TTL = 300.0  # 5 minutes cache

_US_EXCHANGES = {"NMS", "NYQ", "NGM", "NCM", "BTS", "ASE", "PCX", "PNK", "OQX", "OBB"}
_FOREIGN_SUFFIXES = (
    ".NS", ".BO", ".TO", ".DE", ".L", ".IL", ".AX", ".NE",
    ".PA", ".F", ".AS", ".SW", ".HK", ".SS", ".SZ", ".T", ".SI", ".MX"
)

def search_symbols(query: str, market: str = "US") -> list[dict]:
    """
    Search for tickers and companies via Yahoo Finance autocomplete,
    scoped strictly to the specified market ('IN' or 'US').
    """
    query_clean = query.strip()
    if not query_clean:
        return []

    market_upper = market.upper()
    cache_key = f"{market_upper}:{query_clean.lower()}"
    now = time.monotonic()
    if cache_key in _search_cache:
        cached_time, cached_results = _search_cache[cache_key]
        if now - cached_time < _SEARCH_CACHE_TTL:
            return cached_results

    url = (
        f"https://query1.finance.yahoo.com/v1/finance/search?"
        f"q={urllib.parse.quote(query_clean)}&quotesCount=15&newsCount=0"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("Yahoo Finance search failed for query %r: %s", query, exc)
        return []

    quotes = data.get("quotes", [])
    results: list[dict] = []

    for item in quotes:
        sym = item.get("symbol", "").upper()
        qtype = item.get("quoteType", "")
        if qtype not in ("EQUITY", "ETF"):
            continue

        name = item.get("shortname") or item.get("longname") or sym
        exch_disp = item.get("exchDisp", "")
        exch_code = item.get("exchange", "")

        if market_upper == "IN":
            if sym.endswith(".NS") or sym.endswith(".BO") or exch_code in ("NSI", "BSE"):
                exch = "BSE" if sym.endswith(".BO") or exch_code == "BSE" else "NSE"
                results.append({
                    "symbol": sym,
                    "name": name,
                    "exchange": exch,
                    "currency": "INR",
                })
        elif market_upper == "US":
            # US listed and not foreign suffix
            if (exch_code in _US_EXCHANGES or exch_disp in ("NASDAQ", "NYSE", "NYSE ARCA", "BATS", "AMEX")) and not any(sym.endswith(sfx) for sfx in _FOREIGN_SUFFIXES):
                exch = exch_disp if exch_disp in ("NASDAQ", "NYSE", "NYSE ARCA", "BATS", "AMEX") else "NASDAQ"
                results.append({
                    "symbol": sym,
                    "name": name,
                    "exchange": exch,
                    "currency": "USD",
                })

        if len(results) >= 8:
            break

    _search_cache[cache_key] = (now, results)
    return results


# ── Historical Candles & Previous Close ───────────────────────────────────────

_history_cache: dict[str, tuple[float, list[dict]]] = {}
_prev_close_cache: dict[str, tuple[float, dict]] = {}


def get_previous_close(ticker: str) -> dict:
    """
    Returns yesterday's closing price for the specified ticker.
    Uses yfinance 5d daily history and takes the prior session's close.
    """
    sym = ticker.strip().upper()
    now = time.monotonic()
    if sym in _prev_close_cache:
        cached_time, cached_data = _prev_close_cache[sym]
        if (now - cached_time) < 300:  # 5 min TTL
            return cached_data

    exchange = _detect_exchange(sym)
    currency = _detect_currency(exchange)

    prev_close = 0.0
    close_date = ""

    try:
        t = yf.Ticker(sym)
        hist = t.history(period="5d", interval="1d", auto_adjust=True)
        if hist is not None and not hist.empty:
            if len(hist) >= 2:
                prev_close = _safe_float(hist["Close"].iloc[-2])
                close_date = str(hist.index[-2].date())
            elif len(hist) == 1:
                prev_close = _safe_float(hist["Close"].iloc[-1])
                close_date = str(hist.index[-1].date())
    except Exception as exc:
        logger.warning("Failed to fetch historical prev_close for %s: %s", sym, exc)

    if prev_close <= 0:
        # Fallback to cached quote prev_close
        quote = get_quote(sym)
        if quote and quote.prev_close > 0:
            prev_close = quote.prev_close

    result = {
        "ticker": sym,
        "previous_close": round(prev_close, 4),
        "currency": currency,
        "date": close_date,
    }
    _prev_close_cache[sym] = (now, result)
    return result


def get_historical_candles(
    ticker: str,
    range_str: str = "1d",
    interval_str: str | None = None,
) -> list[dict]:
    """
    Returns OHLC candle data (open, high, low, close, volume, time) for a ticker.
    Supported ranges:
      - 1D: intraday candles (default 5m)
      - 1W: multi-day intraday candles (default 15m)
      - 1M: daily candles (default 1d)
    """
    sym = ticker.strip().upper()
    r = range_str.strip().lower()

    # Map range to yfinance period & default interval
    if r in ("1d", "day", "intraday"):
        period = "1d"
        interval = interval_str or "5m"
        ttl = 30  # 30s TTL for live intraday
    elif r in ("1w", "5d", "week"):
        period = "5d"
        interval = interval_str or "15m"
        ttl = 120  # 2m TTL
    elif r in ("1m", "1mo", "month"):
        period = "1mo"
        interval = interval_str or "1d"
        ttl = 300  # 5m TTL
    else:
        period = "1d"
        interval = interval_str or "5m"
        ttl = 30

    cache_key = f"{sym}:{period}:{interval}"
    now = time.monotonic()
    if cache_key in _history_cache:
        cached_time, cached_data = _history_cache[cache_key]
        if (now - cached_time) < ttl:
            return cached_data

    candles: list[dict] = []
    try:
        t = yf.Ticker(sym)
        df = t.history(period=period, interval=interval, auto_adjust=True)

        # Fallback: if period="1d" is empty (e.g. weekend or non-trading hours),
        # fetch 5d and take the most recent session
        if (df is None or df.empty) and period == "1d":
            df_fallback = t.history(period="5d", interval=interval, auto_adjust=True)
            if df_fallback is not None and not df_fallback.empty:
                last_date = df_fallback.index[-1].date()
                df = df_fallback[df_fallback.index.date == last_date]

        if df is not None and not df.empty:
            for idx, row in df.iterrows():
                close_val = _safe_float(row.get("Close"))
                if close_val <= 0:
                    continue

                open_val = _safe_float(row.get("Open"), close_val)
                high_val = _safe_float(row.get("High"), max(open_val, close_val))
                low_val = _safe_float(row.get("Low"), min(open_val, close_val))
                vol_val = _safe_int(row.get("Volume", 0))

                candles.append({
                    "time": int(idx.timestamp()),
                    "open": round(open_val, 4),
                    "high": round(high_val, 4),
                    "low": round(low_val, 4),
                    "close": round(close_val, 4),
                    "volume": vol_val,
                })
    except Exception as exc:
        logger.warning("Failed to fetch historical candles for %s (%s, %s): %s", sym, period, interval, exc)

    _history_cache[cache_key] = (now, candles)
    return candles


