"""
test_derivatives_api.py — Integration test suite for FastAPI Derivatives Endpoints.

Verifies:
1. POST /api/derivatives/order — placing options and futures orders via HTTP.
2. GET  /api/derivatives/{market}/positions — retrieving positions with live market metrics.
3. GET  /api/derivatives/{market}/orders — order history.
4. GET  /api/derivatives/{market}/transactions — transaction ledger.
5. GET  /api/derivatives/{market}/contracts — listing available contracts.
6. POST /api/derivatives/settle-mtm — daily futures MTM trigger.
7. POST /api/derivatives/settle-expiry — expiry settlement trigger.
8. POST /api/derivatives/evaluate-margin-calls — liquidation evaluation trigger.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure backend root on sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from database import Base, get_db
from main import app
from models.orm import Wallet, Holding
from services.price_feed import PriceQuote

from sqlalchemy.pool import StaticPool

# In-memory SQLite for API test with StaticPool so all connections share the same memory DB
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)
TestingSessionLocal = sessionmaker(bind=test_engine)
Base.metadata.create_all(bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def init_wallets():
    db = TestingSessionLocal()
    db.query(Wallet).delete()
    db.commit()

    in_wallet = Wallet(
        market="IN",
        currency="INR",
        starting_balance=1000000.0,
        current_cash_balance=1000000.0,
        margin_used=0.0,
    )
    us_wallet = Wallet(
        market="US",
        currency="USD",
        starting_balance=50000.0,
        current_cash_balance=50000.0,
        margin_used=0.0,
    )
    db.add(in_wallet)
    db.add(us_wallet)
    db.commit()
    db.close()


def test_derivatives_api_full_workflow():
    init_wallets()

    # 1. Place Option Buy Order (NIFTY 23,150 Call)
    # 1 lot @ limit price ₹150 (lot size = 65 -> cost = ₹9,750)
    order_req = {
        "market": "IN",
        "underlying": "NIFTY",
        "instrument_type": "option",
        "option_type": "call",
        "strike_price": 23150.0,
        "expiry_date": "2026-09-29",
        "lot_size": 65,
        "side": "buy",
        "action": "buy_to_open",
        "quantity": 1.0,
        "order_type": "limit",
        "price": 150.0,
    }
    resp = client.post("/api/derivatives/order", json=order_req)
    assert resp.status_code == 201, resp.text
    order_data = resp.json()
    assert order_data["status"] == "filled"
    assert order_data["executed_price"] == 150.0
    contract_id = order_data["contract_id"]

    # 2. Query Open Positions
    mock_quote = PriceQuote(
        symbol="NIFTY-29SEP26-23150-CALL",
        display_name="NIFTY Call",
        exchange="NSE",
        currency="INR",
        price=180.0,
        prev_close=150.0,
        change=30.0,
        change_pct=20.0,
        day_high=190.0,
        day_low=140.0,
        volume=10000,
        market_open=True,
        timestamp="2026-09-26T10:00:00Z",
    )
    with patch("routers.derivatives.get_quotes", return_value=[mock_quote]):
        pos_resp = client.get("/api/derivatives/IN/positions")
        assert pos_resp.status_code == 200
        positions = pos_resp.json()
        assert len(positions) == 1
        p = positions[0]
        assert p["side"] == "long"
        assert p["quantity"] == 1.0
        assert p["entry_price"] == 150.0
        assert p["current_price"] == 180.0
        assert p["unrealized_pnl"] == (180.0 - 150.0) * 65  # +₹1,950

    # 3. Query Orders
    orders_resp = client.get("/api/derivatives/IN/orders")
    assert orders_resp.status_code == 200
    orders = orders_resp.json()
    assert len(orders) >= 1
    assert orders[0]["action"] == "buy_to_open"

    # 4. Query Transactions
    txns_resp = client.get("/api/derivatives/IN/transactions")
    assert txns_resp.status_code == 200
    txns = txns_resp.json()
    assert len(txns) >= 1
    assert txns[0]["transaction_type"] == "trade"
    assert txns[0]["amount"] == -9750.0

    # 5. Query Contracts
    contracts_resp = client.get("/api/derivatives/IN/contracts?underlying=NIFTY")
    assert contracts_resp.status_code == 200
    contracts = contracts_resp.json()
    assert len(contracts) >= 1
    assert contracts[0]["id"] == contract_id

    # 6. US Futures Order (ES=F)
    fut_order_req = {
        "market": "US",
        "symbol": "ES=F",
        "underlying": "ES",
        "instrument_type": "future",
        "side": "buy",
        "action": "buy_to_open",
        "quantity": 1.0,
        "order_type": "limit",
        "price": 5000.0,
        "lot_size": 1,
    }
    fut_resp = client.post("/api/derivatives/order", json=fut_order_req)
    assert fut_resp.status_code == 201
    assert fut_resp.json()["status"] == "filled"
    assert fut_resp.json()["margin_required"] == 600.0  # 12% of 5,000

    # 7. Settle MTM
    mtm_resp = client.post("/api/derivatives/settle-mtm")
    assert mtm_resp.status_code == 200

    # 8. Settle Expiry
    exp_resp = client.post("/api/derivatives/settle-expiry")
    assert exp_resp.status_code == 200

    # 9. Evaluate Margin Calls
    mc_resp = client.post("/api/derivatives/evaluate-margin-calls")
    assert mc_resp.status_code == 200

    print("[PASS] test_derivatives_api_full_workflow passed")


if __name__ == "__main__":
    test_derivatives_api_full_workflow()
