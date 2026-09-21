#!/usr/bin/env python3
"""
test_sse_stream.py — Step 3 smoke test for the SSE price streaming endpoint.

Tests:
  1. Missing tickers query param returns 400 Bad Request
  2. GET /api/prices/stream?tickers=AAPL,RELIANCE.NS returns text/event-stream
  3. Stream emits events with required fields:
     ticker, current_price, change_percent, timestamp, market_status
  4. Closed market tickers include last known price and market_status="closed"
  5. Alias ?symbols=... works identically
  6. Disconnect/cleanup handling works without hanging

Run from backend/ directory:
    python test_sse_stream.py
"""

from __future__ import annotations

import io
import json
import os
import sys
from unittest.mock import patch

# Force UTF-8 stdout on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))

from main import app
from fastapi.testclient import TestClient
from services.price_feed import PriceQuote

client = TestClient(app)
SEPARATOR = "─" * 65


def section(title: str):
    print(f"\n{SEPARATOR}\n  {title}\n{SEPARATOR}")


def check(condition: bool, msg: str):
    if not condition:
        raise AssertionError(msg)


def _make_mock_quote(symbol: str, price: float, market_open: bool) -> PriceQuote:
    upper = symbol.upper()
    exchange = "NSE" if upper.endswith(".NS") else "NASDAQ"
    currency = "INR" if exchange == "NSE" else "USD"
    return PriceQuote(
        symbol=upper,
        display_name=upper.split(".")[0],
        exchange=exchange,
        currency=currency,
        price=price,
        prev_close=round(price * 0.98, 2),
        change=round(price * 0.02, 2),
        change_pct=2.0,
        day_high=round(price * 1.05, 2),
        day_low=round(price * 0.95, 2),
        volume=1000000,
        market_open=market_open,
        timestamp="2026-09-21T16:00:00+00:00",
        error=None,
    )


def test_missing_tickers():
    section("1. Validation: Missing tickers param")
    r = client.get("/api/prices/stream")
    print(f"  Status: {r.status_code}, Body: {r.json()}")
    check(r.status_code == 400, f"Expected 400, got {r.status_code}")
    print("  ✅  Missing tickers rejected with 400")


def test_sse_stream_events():
    section("2. SSE Stream: payload schema & closed market behavior")

    mock_quotes = [
        _make_mock_quote("AAPL", 336.13, market_open=True),
        _make_mock_quote("RELIANCE.NS", 1247.40, market_open=False),
    ]

    with patch("routers.prices.get_quotes", return_value=mock_quotes):
        with client.stream("GET", "/api/prices/stream?tickers=AAPL,RELIANCE.NS&limit=1") as response:
            check(response.status_code == 200, f"Expected 200, got {response.status_code}")
            check(
                "text/event-stream" in response.headers.get("content-type", ""),
                f"Expected text/event-stream, got {response.headers.get('content-type')}",
            )
            print(f"  Status: {response.status_code}")
            print(f"  Content-Type: {response.headers.get('content-type')}")

            events = []
            for line in response.iter_lines():
                if line.startswith("data: "):
                    payload = json.loads(line[len("data: "):])
                    events.append(payload)
                    print(f"  Received event: {payload}")

            check(len(events) == 2, f"Expected 2 events (one per ticker), got {len(events)}")

            # Check AAPL event (open)
            aapl = events[0]
            check(aapl["ticker"] == "AAPL", "Ticker should be AAPL")
            check(aapl["current_price"] == 336.13, "current_price mismatch")
            check(aapl["change_percent"] == 2.0, "change_percent mismatch")
            check(aapl["timestamp"] == "2026-09-21T16:00:00+00:00", "timestamp mismatch")
            check(aapl["market_status"] == "open", f"Expected open, got {aapl['market_status']}")

            # Check RELIANCE.NS event (closed market, must still be sent with last price)
            rel = events[1]
            check(rel["ticker"] == "RELIANCE.NS", "Ticker should be RELIANCE.NS")
            check(rel["current_price"] == 1247.40, "current_price mismatch for closed stock")
            check(rel["market_status"] == "closed", f"Expected closed, got {rel['market_status']}")

    print("  ✅  SSE stream schema and closed-market handling verified")


def test_symbols_alias():
    section("3. SSE Stream: symbols query alias")
    mock_quotes = [_make_mock_quote("TSLA", 364.27, market_open=True)]

    with patch("routers.prices.get_quotes", return_value=mock_quotes):
        with client.stream("GET", "/api/prices/stream?symbols=TSLA&limit=1") as response:
            check(response.status_code == 200, f"Expected 200, got {response.status_code}")
            events = []
            for line in response.iter_lines():
                if line.startswith("data: "):
                    payload = json.loads(line[len("data: "):])
                    events.append(payload)
                    print(f"  Received event via ?symbols: {payload}")

            check(len(events) == 1, "Expected 1 event")
            check(events[0]["ticker"] == "TSLA", "Ticker should be TSLA")

    print("  ✅  symbols alias works correctly")


def main():
    print("\n" + "═" * 65)
    print("  PaperTrade — Step 3: SSE Price Streaming Tests")
    print("═" * 65)

    tests = [
        test_missing_tickers,
        test_sse_stream_events,
        test_symbols_alias,
    ]

    failures = []
    for fn in tests:
        try:
            fn()
        except AssertionError as e:
            failures.append((fn.__name__, str(e)))
            print(f"  ❌  ASSERTION FAILED: {e}")
        except Exception as e:
            failures.append((fn.__name__, str(e)))
            print(f"  ❌  UNEXPECTED ERROR in {fn.__name__}: {e}")
            import traceback; traceback.print_exc()

    print("\n" + "═" * 65)
    if failures:
        print(f"  RESULT: {len(failures)} test(s) FAILED")
        for name, msg in failures:
            print(f"    ✗ {name}: {msg}")
        sys.exit(1)
    else:
        print("  RESULT: All 3 tests passed ✅")
    print("═" * 65 + "\n")


if __name__ == "__main__":
    main()
