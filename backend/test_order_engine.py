#!/usr/bin/env python3
"""
test_order_engine.py — Step 2b smoke tests: order engine + portfolio P&L.

Uses:
  - FastAPI TestClient with StaticPool in-memory SQLite (never touches db.sqlite)
  - unittest.mock.patch to mock get_quote so tests run offline and are
    independent of market hours

Tests:
  1. Successful market BUY — cash deducted, holding created
  2. Successful market SELL — proceeds added, holding reduced, realized P&L stored
  3. Insufficient funds rejection
  4. Insufficient holdings rejection
  5. Market-closed rejection
  6. Invalid ticker rejection
  7. avg_buy_price recalculation when adding to existing position
  8. Full position close — Holding row deleted
  9. GET /api/orders/{market} — order history contains all orders
 10. GET /api/wallet/{market}/summary — correct P&L totals (mocked prices)

Run from backend/ directory:
    python test_order_engine.py
"""

from __future__ import annotations

import io
import os
import sys
from unittest.mock import patch

# ── UTF-8 stdout on Windows ───────────────────────────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))

# ── In-memory test DB with StaticPool ────────────────────────────────────────
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)

from database import Base
import models.orm  # register mappers
Base.metadata.create_all(bind=_test_engine)

from main import app
from database import get_db
from fastapi.testclient import TestClient
from services.price_feed import PriceQuote


def _override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app)

SEPARATOR = "─" * 65


# ── Mock quote factory ────────────────────────────────────────────────────────

def _make_quote(
    symbol: str,
    price: float,
    market_open: bool = True,
    error: str | None = None,
) -> PriceQuote:
    """Build a fake PriceQuote to inject via mock."""
    upper = symbol.upper()
    if upper.endswith(".NS"):
        exchange, currency = "NSE", "INR"
    elif upper.endswith(".BO"):
        exchange, currency = "BSE", "INR"
    else:
        exchange, currency = "NASDAQ", "USD"

    return PriceQuote(
        symbol=upper,
        display_name=upper.split(".")[0],
        exchange=exchange,
        currency=currency,
        price=price,
        prev_close=round(price * 0.99, 4),
        change=round(price * 0.01, 4),
        change_pct=1.0,
        day_high=round(price * 1.02, 4),
        day_low=round(price * 0.98, 4),
        volume=500000,
        market_open=market_open,
        timestamp="2026-09-21T14:00:00+00:00",
        error=error,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def section(title: str):
    print(f"\n{SEPARATOR}\n  {title}\n{SEPARATOR}")


def check(condition: bool, msg: str):
    if not condition:
        raise AssertionError(msg)


def setup_us_wallet(balance: float = 10_000.0):
    """Reset the US wallet to a clean state with the given balance."""
    r = client.post("/api/wallet/setup", json={"market": "US", "starting_balance": balance})
    assert r.status_code == 201, f"Wallet setup failed: {r.text}"
    return r.json()


def setup_in_wallet(balance: float = 500_000.0):
    """Reset the IN wallet to a clean state with the given balance."""
    r = client.post("/api/wallet/setup", json={"market": "IN", "starting_balance": balance})
    assert r.status_code == 201, f"Wallet setup failed: {r.text}"
    return r.json()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_buy_success():
    section("1. Successful BUY — AAPL 10 shares @ $150")
    setup_us_wallet(10_000)

    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 150.0, True)):
        r = client.post("/api/orders", json={
            "market": "US", "ticker": "AAPL", "side": "buy", "quantity": 10
        })

    check(r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}")
    order = r.json()
    print(f"  Order: status={order['status']} executed_price={order['executed_price']}")
    check(order["status"] == "filled",       "status should be filled")
    check(order["executed_price"] == 150.0,  "executed_price mismatch")
    check(order["side"] == "buy",            "side should be buy")
    check(order["reject_reason"] is None,    "reject_reason should be None")

    wallet = client.get("/api/wallet/US").json()
    expected_cash = round(10_000 - 150 * 10, 2)
    print(f"  Cash after: {wallet['current_cash_balance']} (expected {expected_cash})")
    check(wallet["current_cash_balance"] == expected_cash, "cash_balance mismatch after buy")

    check(len(wallet["holdings"]) == 1,              "should have 1 holding")
    h = wallet["holdings"][0]
    check(h["ticker"] == "AAPL",                     "holding ticker mismatch")
    check(h["quantity"] == 10.0,                     "holding quantity mismatch")
    check(h["avg_buy_price"] == 150.0,               "avg_buy_price mismatch")
    print("  ✅  Buy executed: cash deducted, holding created")


def test_sell_success():
    section("2. Successful SELL — AAPL 5 shares @ $170 (realized P&L = $100)")
    setup_us_wallet(10_000)

    # Buy first
    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 150.0, True)):
        client.post("/api/orders", json={"market": "US", "ticker": "AAPL", "side": "buy", "quantity": 10})

    # Sell 5 at higher price
    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 170.0, True)):
        r = client.post("/api/orders", json={
            "market": "US", "ticker": "AAPL", "side": "sell", "quantity": 5
        })

    check(r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}")
    order = r.json()
    print(f"  Order: status={order['status']} executed_price={order['executed_price']}")
    check(order["status"] == "filled",       "status should be filled")
    check(order["executed_price"] == 170.0,  "executed_price should be 170")

    wallet = client.get("/api/wallet/US").json()
    # Cash: 10000 - 1500 (buy) + 850 (sell 5@170) = 9350
    expected_cash = round(10_000 - 150 * 10 + 170 * 5, 2)
    print(f"  Cash after: {wallet['current_cash_balance']} (expected {expected_cash})")
    check(wallet["current_cash_balance"] == expected_cash, "cash_balance mismatch after sell")
    check(len(wallet["holdings"]) == 1,              "should still have 1 holding (5 left)")
    check(wallet["holdings"][0]["quantity"] == 5.0,  "remaining quantity should be 5")
    print("  ✅  Sell executed: proceeds added, holding reduced")


def test_insufficient_funds():
    section("3. Rejection — insufficient funds")
    setup_us_wallet(100.0)   # only $100

    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 150.0, True)):
        r = client.post("/api/orders", json={
            "market": "US", "ticker": "AAPL", "side": "buy", "quantity": 10  # costs $1500
        })

    check(r.status_code == 201, f"Expected 201 (rejected order saved), got {r.status_code}")
    order = r.json()
    print(f"  Order: status={order['status']} reason={order['reject_reason']}")
    check(order["status"] == "rejected",              "status should be rejected")
    check(order["reject_reason"] == "insufficient_funds", "wrong reject_reason")

    # Wallet unchanged
    wallet = client.get("/api/wallet/US").json()
    check(wallet["current_cash_balance"] == 100.0, "cash should be unchanged on rejection")
    check(wallet["holdings"] == [],                "no holdings on rejection")
    print("  ✅  Rejected correctly, wallet unchanged")


def test_insufficient_holdings():
    section("4. Rejection — insufficient holdings (sell more than owned on pending limit)")
    setup_us_wallet(10_000)

    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 150.0, True)):
        client.post("/api/orders", json={"market": "US", "ticker": "AAPL", "side": "buy", "quantity": 5})

    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 150.0, True)):
        r = client.post("/api/orders", json={
            "market": "US", "ticker": "AAPL", "side": "sell", "quantity": 10,  # only have 5
            "order_type": "limit", "requested_price": 200.0,
        })

    order = r.json()
    print(f"  Order: status={order['status']} reason={order['reject_reason']}")
    check(order["status"] == "rejected",                   "status should be rejected")
    check(order["reject_reason"] == "insufficient_holdings", "wrong reject_reason")
    print("  ✅  Rejected correctly (tried to limit sell 10, only have 5)")


def test_market_closed():
    section("5. Rejection — market closed")
    setup_us_wallet(10_000)

    with patch("services.order_engine.get_quote",
               return_value=_make_quote("AAPL", 150.0, market_open=False)):
        r = client.post("/api/orders", json={
            "market": "US", "ticker": "AAPL", "side": "buy", "quantity": 1
        })

    order = r.json()
    print(f"  Order: status={order['status']} reason={order['reject_reason']}")
    check(order["status"] == "rejected",            "status should be rejected")
    check(order["reject_reason"] == "market_closed", "wrong reject_reason")
    print("  ✅  Rejected correctly when market is closed")


def test_invalid_ticker():
    section("6. Rejection — invalid ticker")
    setup_us_wallet(10_000)

    bad_quote = _make_quote("FAKEXYZ", 0.0, True, error="No data found — ticker may be delisted")
    with patch("services.order_engine.get_quote", return_value=bad_quote):
        r = client.post("/api/orders", json={
            "market": "US", "ticker": "FAKEXYZ", "side": "buy", "quantity": 1
        })

    order = r.json()
    print(f"  Order: status={order['status']} reason={order['reject_reason']}")
    check(order["status"] == "rejected",            "status should be rejected")
    check(order["reject_reason"] == "invalid_ticker", "wrong reject_reason")
    print("  ✅  Rejected correctly for invalid ticker")


def test_avg_buy_price_recalculation():
    section("7. Avg buy price recalculation (buy more of existing position)")
    setup_us_wallet(50_000)

    # Buy 10 @ $100 → avg = $100
    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 100.0, True)):
        client.post("/api/orders", json={"market": "US", "ticker": "AAPL", "side": "buy", "quantity": 10})

    wallet_after_first = client.get("/api/wallet/US").json()
    avg1 = wallet_after_first["holdings"][0]["avg_buy_price"]
    print(f"  After 1st buy (10 @ $100): avg_buy_price = {avg1}")
    check(abs(avg1 - 100.0) < 0.001, f"avg should be 100, got {avg1}")

    # Buy 10 more @ $120 → new avg = (10*100 + 10*120) / 20 = $110
    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 120.0, True)):
        client.post("/api/orders", json={"market": "US", "ticker": "AAPL", "side": "buy", "quantity": 10})

    wallet_after_second = client.get("/api/wallet/US").json()
    avg2 = wallet_after_second["holdings"][0]["avg_buy_price"]
    qty  = wallet_after_second["holdings"][0]["quantity"]
    print(f"  After 2nd buy (10 @ $120): avg_buy_price = {avg2}, total qty = {qty}")
    check(abs(avg2 - 110.0) < 0.001, f"avg should be 110, got {avg2}")
    check(qty == 20.0,               f"qty should be 20, got {qty}")
    print("  ✅  Weighted avg correctly recalculated: (10×100 + 10×120) / 20 = $110")


def test_full_position_close():
    section("8. Full position close — Holding row deleted when qty hits 0")
    setup_us_wallet(10_000)

    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 150.0, True)):
        client.post("/api/orders", json={"market": "US", "ticker": "AAPL", "side": "buy", "quantity": 5})

    # Sell ALL 5
    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 160.0, True)):
        r = client.post("/api/orders", json={"market": "US", "ticker": "AAPL", "side": "sell", "quantity": 5})

    check(r.json()["status"] == "filled", "sell should be filled")

    wallet = client.get("/api/wallet/US").json()
    print(f"  Holdings after full close: {wallet['holdings']}")
    check(wallet["holdings"] == [], "holdings list should be empty after full close")
    # Cash: 10000 - 750 + 800 = 10050
    check(wallet["current_cash_balance"] == 10_050.0, f"cash mismatch: {wallet['current_cash_balance']}")
    print("  ✅  Holding row deleted on full close, cash correct")


def test_order_history():
    section("9. GET /api/orders/US — order history (filled + rejected)")
    setup_us_wallet(500.0)  # small balance forces 1 rejection

    # Valid buy
    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 100.0, True)):
        client.post("/api/orders", json={"market": "US", "ticker": "AAPL", "side": "buy", "quantity": 4})

    # Rejected (not enough cash for 10 @ $100)
    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 100.0, True)):
        client.post("/api/orders", json={"market": "US", "ticker": "AAPL", "side": "buy", "quantity": 10})

    r = client.get("/api/orders/US")
    check(r.status_code == 200, f"Expected 200, got {r.status_code}")
    orders = r.json()
    print(f"  Orders returned: {len(orders)}")
    statuses = [o["status"] for o in orders]
    print(f"  Statuses: {statuses}")
    check(len(orders) == 2,            "should have 2 orders in history")
    check("filled"   in statuses,      "should have at least one filled")
    check("rejected" in statuses,      "should have at least one rejected")
    # Newest first
    check(orders[0]["created_at"] >= orders[1]["created_at"], "should be newest-first")
    print("  ✅  Order history contains both filled and rejected orders")


def test_wallet_summary_pnl():
    section("10. GET /api/wallet/US/summary — P&L totals (mocked prices)")
    setup_us_wallet(10_000)

    # Buy 10 AAPL @ $100
    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 100.0, True)):
        client.post("/api/orders", json={"market": "US", "ticker": "AAPL", "side": "buy", "quantity": 10})

    # Sell 5 @ $120 → realized_pnl = (120-100)*5 = $100
    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 120.0, True)):
        client.post("/api/orders", json={"market": "US", "ticker": "AAPL", "side": "sell", "quantity": 5})

    # Now mock current price at $130 for portfolio summary (remaining 5 shares)
    summary_quote = _make_quote("AAPL", 130.0, True)
    with patch("services.portfolio.get_quotes", return_value=[summary_quote]):
        r = client.get("/api/wallet/US/summary")

    check(r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}")
    s = r.json()
    print(f"  cash_balance       = {s['cash_balance']}")
    print(f"  total_holdings_val = {s['total_holdings_value']}")
    print(f"  total_wallet_value = {s['total_wallet_value']}")
    print(f"  unrealized_pnl     = {s['total_unrealized_pnl']}")
    print(f"  realized_pnl       = {s['total_realized_pnl']}")

    # Cash: 10000 - 1000 (buy 10@100) + 600 (sell 5@120) = 9600
    check(abs(s["cash_balance"] - 9_600.0) < 0.01,        f"cash mismatch: {s['cash_balance']}")
    # Holdings: 5 shares @ $130 = $650
    check(abs(s["total_holdings_value"] - 650.0) < 0.01,  f"holdings value mismatch: {s['total_holdings_value']}")
    # Total: 9600 + 650 = 10250
    check(abs(s["total_wallet_value"] - 10_250.0) < 0.01, f"wallet value mismatch: {s['total_wallet_value']}")
    # Unrealized: (130-100)*5 = $150
    check(abs(s["total_unrealized_pnl"] - 150.0) < 0.01,  f"unrealized mismatch: {s['total_unrealized_pnl']}")
    # Realized: (120-100)*5 = $100
    check(abs(s["total_realized_pnl"] - 100.0) < 0.01,    f"realized mismatch: {s['total_realized_pnl']}")

    h = s["holdings"][0]
    print(f"  Holding: {h['ticker']} qty={h['quantity']} avg={h['avg_buy_price']} "
          f"cur={h['current_price']} pnl={h['unrealized_pnl']} ({h['unrealized_pnl_pct']}%)")
    check(h["ticker"]           == "AAPL",  "holding ticker mismatch")
    check(h["quantity"]         == 5.0,     "remaining quantity should be 5")
    check(h["avg_buy_price"]    == 100.0,   "avg_buy_price should be $100")
    check(h["current_price"]    == 130.0,   "current_price should be mocked $130")
    check(h["unrealized_pnl"]   == 150.0,   "unrealized P&L should be $150")
    check(abs(h["unrealized_pnl_pct"] - 30.0) < 0.01, "unrealized pct should be 30%")
    print("  ✅  Summary P&L calculations all correct")


# ── Runner ────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "═" * 65)
    print("  PaperTrade — Step 2b: Order Engine + Portfolio P&L Tests")
    print("═" * 65)

    tests = [
        test_buy_success,
        test_sell_success,
        test_insufficient_funds,
        test_insufficient_holdings,
        test_market_closed,
        test_invalid_ticker,
        test_avg_buy_price_recalculation,
        test_full_position_close,
        test_order_history,
        test_wallet_summary_pnl,
    ]

    failures: list[tuple[str, str]] = []
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
        print("  RESULT: All 10 tests passed ✅")
    print("═" * 65 + "\n")


if __name__ == "__main__":
    main()
