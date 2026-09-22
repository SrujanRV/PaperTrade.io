#!/usr/bin/env python3
"""
test_order_types.py — Phase 4j tests: Limit & Stop-Loss order placement,
market-hours enforcement, tick evaluation, pending listing, and cancellation.
"""

from __future__ import annotations

import io
import os
import sys
from unittest.mock import patch

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)

from database import Base, get_db
import models.orm  # register mappers
Base.metadata.create_all(bind=_test_engine)

from main import app
from fastapi.testclient import TestClient
from services.price_feed import PriceQuote
from services.order_engine import evaluate_pending_orders

def _override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app)

def _make_quote(
    symbol: str,
    price: float,
    market_open: bool = True,
    error: str | None = None,
) -> PriceQuote:
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
        day_high=price * 1.02,
        day_low=price * 0.98,
        volume=1_000_000,
        market_open=market_open,
        timestamp="2026-09-21T14:00:00+00:00",
        error=error,
    )


def run_tests():
    print("=" * 70)
    print("PHASE 4j: LIMIT & STOP-LOSS ORDERS TEST SUITE")
    print("=" * 70)

    # 1. Setup wallets
    res = client.post("/api/wallet/setup", json={"market": "US", "starting_balance": 10000.0})
    assert res.status_code == 201, f"Setup US wallet failed: {res.text}"
    res = client.post("/api/wallet/setup", json={"market": "IN", "starting_balance": 500000.0})
    assert res.status_code == 201, f"Setup IN wallet failed: {res.text}"
    print("[PASS] Wallets initialized")

    # 2. Limit BUY immediately marketable (current <= limit) when market is OPEN -> executes
    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 150.0, market_open=True)):
        res = client.post("/api/orders", json={
            "market": "US",
            "ticker": "AAPL",
            "side": "buy",
            "quantity": 10,
            "order_type": "limit",
            "requested_price": 155.0,  # limit is 155, current is 150 -> fills immediately
        })
        assert res.status_code == 201, res.text
        data = res.json()
        assert data["status"] == "filled"
        assert data["executed_price"] == 150.0
        print("[PASS] Limit BUY immediately marketable fills at market price")

    # 3. Limit BUY below current price -> stays pending
    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 150.0, market_open=True)):
        res = client.post("/api/orders", json={
            "market": "US",
            "ticker": "AAPL",
            "side": "buy",
            "quantity": 5,
            "order_type": "limit",
            "requested_price": 140.0,  # limit is 140, current is 150 -> pending
        })
        assert res.status_code == 201, res.text
        pending_buy = res.json()
        assert pending_buy["status"] == "pending"
        assert pending_buy["requested_price"] == 140.0
        print(f"[PASS] Limit BUY below current price created as pending (id={pending_buy['id']})")

    # 4. Tick evaluation when market is CLOSED -> price is <= limit (138 <= 140) BUT market is closed -> MUST REMAIN PENDING
    db = _TestSession()
    try:
        closed_quote = _make_quote("AAPL", 138.0, market_open=False)
        filled = evaluate_pending_orders(db, quotes=[closed_quote], market="US")
        assert len(filled) == 0, "Orders should NOT fill when market is closed!"
        with patch("services.order_engine.get_quote", return_value=closed_quote):
            res = client.get("/api/orders/US/pending")
        pending_list = res.json()
        assert any(o["id"] == pending_buy["id"] for o in pending_list)
        print("[PASS] Pending Limit BUY does NOT execute when market is closed, even if price breached")
    finally:
        db.close()

    # 5. Tick evaluation when market is OPEN -> price is <= limit (138 <= 140) -> fills!
    db = _TestSession()
    try:
        open_quote = _make_quote("AAPL", 138.0, market_open=True)
        filled = evaluate_pending_orders(db, quotes=[open_quote], market="US")
        assert len(filled) == 1
        assert filled[0].id == pending_buy["id"]
        assert filled[0].status == "filled"
        assert filled[0].executed_price == 138.0
        print("[PASS] Pending Limit BUY executes when price triggers AND market is open")
    finally:
        db.close()

    # Verify wallet now has 10 + 5 = 15 AAPL shares
    res = client.get("/api/wallet/US")
    holdings = res.json()["holdings"]
    aapl = next(h for h in holdings if h["ticker"] == "AAPL")
    assert aapl["quantity"] == 15.0

    # 6. Stop-loss BUY should be rejected (stop-loss is sell-only)
    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 138.0, market_open=True)):
        res = client.post("/api/orders", json={
            "market": "US",
            "ticker": "AAPL",
            "side": "buy",
            "quantity": 5,
            "order_type": "stop_loss",
            "trigger_price": 130.0,
        })
        assert res.status_code == 201
        assert res.json()["status"] == "rejected"
        assert "stop_loss_sell_only" in res.json()["reject_reason"]
        print("[PASS] Stop-loss BUY is rejected (sell-only enforcement)")

    # 7. Stop-loss SELL with no holding should be rejected
    with patch("services.order_engine.get_quote", return_value=_make_quote("TSLA", 200.0, market_open=True)):
        res = client.post("/api/orders", json={
            "market": "US",
            "ticker": "TSLA",
            "side": "sell",
            "quantity": 1,
            "order_type": "stop_loss",
            "trigger_price": 180.0,
        })
        assert res.status_code == 201
        assert res.json()["status"] == "rejected"
        assert "insufficient_holdings" in res.json()["reject_reason"]
        print("[PASS] Stop-loss SELL on unowned ticker is rejected")

    # 8. Stop-loss SELL on owned AAPL: current=138, trigger=130 -> pending
    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 138.0, market_open=True)):
        res = client.post("/api/orders", json={
            "market": "US",
            "ticker": "AAPL",
            "side": "sell",
            "quantity": 5,
            "order_type": "stop_loss",
            "trigger_price": 130.0,
        })
        assert res.status_code == 201
        stop_order = res.json()
        assert stop_order["status"] == "pending"
        assert stop_order["trigger_price"] == 130.0
        print(f"[PASS] Stop-loss SELL created as pending (id={stop_order['id']})")

    # 9. Stop-loss tick evaluation with market closed -> price drops to 125 <= 130 -> MUST REMAIN PENDING
    db = _TestSession()
    try:
        closed_drop = _make_quote("AAPL", 125.0, market_open=False)
        filled = evaluate_pending_orders(db, quotes=[closed_drop], market="US")
        assert len(filled) == 0, "Stop loss must not execute when market is closed"
        print("[PASS] Stop-loss does NOT trigger when market is closed")
    finally:
        db.close()

    # 10. Stop-loss tick evaluation with market open -> price drops to 125 <= 130 -> fills!
    db = _TestSession()
    try:
        open_drop = _make_quote("AAPL", 125.0, market_open=True)
        filled = evaluate_pending_orders(db, quotes=[open_drop], market="US")
        assert len(filled) == 1
        assert filled[0].id == stop_order["id"]
        assert filled[0].status == "filled"
        assert filled[0].executed_price == 125.0
        print("[PASS] Stop-loss triggers & fills when market is open and price breaches trigger")
    finally:
        db.close()

    # 11. Test Cancel Pending Order
    # Create another pending limit order
    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 125.0, market_open=True)):
        res = client.post("/api/orders", json={
            "market": "US",
            "ticker": "AAPL",
            "side": "buy",
            "quantity": 2,
            "order_type": "limit",
            "requested_price": 100.0,
        })
        assert res.status_code == 201
        cancel_target = res.json()
        assert cancel_target["status"] == "pending"

    # Verify it appears in GET /api/orders/{market}/pending
    with patch("services.order_engine.get_quote", return_value=_make_quote("AAPL", 125.0, market_open=True)):
        res = client.get("/api/orders/US/pending")
        assert res.status_code == 200
        pending_list = res.json()
        assert any(o["id"] == cancel_target["id"] for o in pending_list)
        print(f"[PASS] GET /api/orders/US/pending returns pending order #{cancel_target['id']}")

    # Cancel via DELETE /api/order/{order_id}
    res = client.delete(f"/api/order/{cancel_target['id']}")
    assert res.status_code == 200
    cancelled_data = res.json()
    assert cancelled_data["status"] == "cancelled"
    print(f"[PASS] DELETE /api/order/{cancel_target['id']} cancelled order")

    # Trying to cancel again should fail with 400
    res = client.delete(f"/api/order/{cancel_target['id']}")
    assert res.status_code == 400
    print("[PASS] Cancelling non-pending order returns 400")

    # Trying to cancel non-existent order should return 404
    res = client.delete("/api/order/999999")
    assert res.status_code == 404
    print("[PASS] Cancelling non-existent order returns 404")

    print("\nALL 11 CHECKS PASSED!")


if __name__ == "__main__":
    run_tests()
