#!/usr/bin/env python3
"""
test_price_feed.py — Phase 1 smoke test for the price feed layer.

Run from the backend/ directory:
    python test_price_feed.py

Checks:
  1. Indian NSE stocks (RELIANCE.NS, TCS.NS, INFY.NS)
  2. US stocks (AAPL, TSLA, GOOGL)
  3. Mixed batch in a single call
  4. Market-open status for NSE and NASDAQ
  5. Invalid ticker handling
  6. Cache hit (second call should return immediately)
"""

from __future__ import annotations

import io
import json
import sys
import time
from datetime import datetime, timezone

# Force UTF-8 output on Windows (avoids UnicodeEncodeError with box-drawing / emoji)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Make sure we can import from the backend root
import os
sys.path.insert(0, os.path.dirname(__file__))

from services.price_feed import get_quotes, get_quote, is_market_open, clear_cache

SEPARATOR = "─" * 65

def _fmt_quote(q) -> str:
    sign = "+" if q.change >= 0 else ""
    status = "🟢 OPEN" if q.market_open else "🔴 CLOSED"
    err    = f"  ⚠ ERROR: {q.error}" if q.error else ""
    return (
        f"  [{q.exchange}] {q.display_name:<12} "
        f"{q.currency} {q.price:>10,.2f}  "
        f"({sign}{q.change_pct:.2f}%)  "
        f"Market: {status}"
        f"{err}"
    )


def section(title: str):
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


def test_indian_stocks():
    section("1. Indian NSE stocks")
    symbols = ["RELIANCE.NS", "TCS.NS", "INFY.NS"]
    quotes = get_quotes(symbols)
    for q in quotes:
        print(_fmt_quote(q))
    assert all(q.currency == "INR" for q in quotes), "Indian stocks must have INR currency"
    assert all(q.exchange == "NSE" for q in quotes), "NSE tickers must map to NSE exchange"
    failed = [q.symbol for q in quotes if q.error]
    if failed:
        print(f"  ⚠  Fetch errors (may be market-closed stale data): {failed}")
    else:
        print("  ✅  All Indian tickers fetched successfully")


def test_us_stocks():
    section("2. US stocks")
    symbols = ["AAPL", "TSLA", "GOOGL"]
    quotes = get_quotes(symbols)
    for q in quotes:
        print(_fmt_quote(q))
    assert all(q.currency == "USD" for q in quotes), "US stocks must have USD currency"
    failed = [q.symbol for q in quotes if q.error]
    if failed:
        print(f"  ⚠  Fetch errors: {failed}")
    else:
        print("  ✅  All US tickers fetched successfully")


def test_mixed_batch():
    section("3. Mixed batch (Indian + US together)")
    clear_cache()
    symbols = ["RELIANCE.NS", "AAPL", "TCS.NS", "TSLA"]
    t0 = time.monotonic()
    quotes = get_quotes(symbols)
    elapsed = time.monotonic() - t0
    for q in quotes:
        print(_fmt_quote(q))
    print(f"\n  Batch fetch took {elapsed:.2f}s for {len(symbols)} symbols")


def test_cache():
    section("4. Cache hit (should be instant)")
    symbols = ["RELIANCE.NS", "AAPL"]
    get_quotes(symbols)           # populate cache
    t0 = time.monotonic()
    get_quotes(symbols)           # should hit cache
    elapsed = time.monotonic() - t0
    print(f"  Cache hit for {symbols} took {elapsed*1000:.1f}ms  (expect <5ms)")
    assert elapsed < 0.1, f"Cache hit too slow: {elapsed:.3f}s"
    print("  ✅  Cache working correctly")


def test_market_status():
    section("5. Market open/closed status")
    exchanges = ["NSE", "BSE", "NYSE", "NASDAQ"]
    for exch in exchanges:
        open_flag = is_market_open(exch)
        icon = "🟢 OPEN" if open_flag else "🔴 CLOSED"
        print(f"  {exch:<10} {icon}")
    now_utc = datetime.now(timezone.utc)
    print(f"\n  Current UTC time: {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}")


def test_invalid_ticker():
    section("6. Invalid ticker handling")
    q = get_quote("DEFINITELY_NOT_A_REAL_STOCK_XYZ123", force_refresh=True)
    print(f"  Symbol: {q.symbol}")
    print(f"  Error:  {q.error}")
    assert q.error is not None, "Invalid ticker must have a non-null error field"
    assert q.price == 0.0, "Invalid ticker must have price=0"
    print("  ✅  Invalid ticker handled gracefully")


def test_bse_ticker():
    section("7. BSE ticker (.BO suffix)")
    q = get_quote("RELIANCE.BO", force_refresh=True)
    print(_fmt_quote(q))
    assert q.exchange == "BSE", f"Expected BSE, got {q.exchange}"
    assert q.currency == "INR", f"Expected INR, got {q.currency}"
    if not q.error:
        print("  ✅  BSE ticker resolved correctly")
    else:
        print(f"  ⚠  BSE fetch error (may be data gap): {q.error}")


def main():
    print("\n" + "═" * 65)
    print("  PaperTrade — Phase 1 Price Feed Smoke Test")
    print("═" * 65)

    tests = [
        test_indian_stocks,
        test_us_stocks,
        test_mixed_batch,
        test_cache,
        test_market_status,
        test_invalid_ticker,
        test_bse_ticker,
    ]

    failures = []
    for test_fn in tests:
        try:
            test_fn()
        except AssertionError as e:
            failures.append((test_fn.__name__, str(e)))
            print(f"  ❌  ASSERTION FAILED: {e}")
        except Exception as e:
            failures.append((test_fn.__name__, str(e)))
            print(f"  ❌  UNEXPECTED ERROR: {e}")

    print("\n" + "═" * 65)
    if failures:
        print(f"  RESULT: {len(failures)} test(s) FAILED")
        for name, msg in failures:
            print(f"    ✗ {name}: {msg}")
        sys.exit(1)
    else:
        print("  RESULT: All tests passed ✅")
    print("═" * 65 + "\n")


if __name__ == "__main__":
    main()
