"""
backend/test_auto_square_off.py — Comprehensive tests for Phase 4l:
Time-Based Auto Square-Off for Holdings.
"""

from datetime import date
from fastapi.testclient import TestClient

from database import SessionLocal
from main import app
from models.orm import Holding, HoldingLot, Order, Transaction, Wallet
from services.order_engine import evaluate_auto_square_off, place_order
from services.trading_calendar import (
    calculate_square_off_date,
    is_near_market_close,
    is_trading_day,
    resolve_to_valid_trading_day,
)

client = TestClient(app)


def test_trading_calendar_logic():
    print("--- Testing Trading Calendar & Holiday Shift ---")
    # 1. Weekends are not trading days
    saturday = date(2026, 9, 26)
    sunday = date(2026, 9, 27)
    assert not is_trading_day("US", saturday)
    assert not is_trading_day("IN", sunday)

    # 2. NSE Holiday (Gandhi Jayanti 2026-10-02)
    gandhi_jayanti = date(2026, 10, 2)
    assert not is_trading_day("IN", gandhi_jayanti)

    # 3. US Holiday (Christmas 2026-12-25)
    xmas = date(2026, 12, 25)
    assert not is_trading_day("US", xmas)

    # 4. Thursday + 2 trading days = Monday (skipping Sat/Sun)
    thursday = date(2026, 9, 24)
    calc = calculate_square_off_date("US", start_date=thursday, holding_days=2)
    assert calc["square_off_date"] == "2026-09-28", f"Expected Monday 2026-09-28, got {calc['square_off_date']}"
    assert calc["is_intraday"] is False
    assert calc["holding_days"] == 2
    print("PASS: Thursday + 2 trading days correctly resolves to Monday:", calc)

    # 5. Shift to previous trading day if target lands on closed day
    # Suppose a naive date lands on Sunday 2026-09-27 -> must shift to Friday 2026-09-25
    resolved, shifted, reason = resolve_to_valid_trading_day("US", sunday)
    assert resolved == date(2026, 9, 25), f"Expected Friday 2026-09-25, got {resolved}"
    assert shifted is True
    assert "earlier" in reason.lower()
    print("PASS: Shift to previous trading day verified:", reason)


def test_api_calculate_square_off():
    print("--- Testing /api/orders/calculate-square-off endpoint ---")
    resp = client.get("/api/orders/calculate-square-off?market=US&days=1&start_date=2026-09-25")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Friday 2026-09-25 + 1 trading day = Monday 2026-09-28
    assert data["square_off_date"] == "2026-09-28"
    assert data["holding_days"] == 1
    assert "Mon, 28 Sep" in data["formatted_date"]
    print("PASS: /api/orders/calculate-square-off returned:", data)


def test_place_buy_order_with_duration():
    print("--- Testing Order placement with duration ---")
    # Setup test wallet for US
    client.post("/api/wallet/setup", json={"market": "US", "starting_balance": 50000.0})

    resp = client.post(
        "/api/orders",
        json={
            "market": "US",
            "ticker": "AAPL",
            "side": "buy",
            "quantity": 5,
            "order_type": "limit",
            "requested_price": 500.0,  # high limit to fill immediately if open, or test pending
            "holding_days": 2,
        },
    )
    assert resp.status_code == 201, resp.text
    order_data = resp.json()
    assert order_data["square_off_date"] is not None
    print(f"PASS: Placed BUY order with square_off_date: {order_data['square_off_date']}")

    # Verify Holding in DB
    with SessionLocal() as db:
        wallet = db.query(Wallet).filter(Wallet.market == "US").first()
        holding = db.query(Holding).filter(Holding.wallet_id == wallet.id, Holding.ticker == "AAPL").first()
        if holding:
            assert holding.square_off_date is not None
            print(f"PASS: Holding has square_off_date: {holding.square_off_date}")


def test_auto_square_off_execution_and_partial_sell():
    print("--- Testing Auto Square-Off Execution & Partial Sell Logic ---")
    with SessionLocal() as db:
        wallet = db.query(Wallet).filter(Wallet.market == "US").first()
        if not wallet:
            wallet = Wallet(market="US", currency="USD", starting_balance=50000.0, current_cash_balance=50000.0)
            db.add(wallet)
            db.commit()
            db.refresh(wallet)

        # Clear existing holdings and lots for clean test
        db.query(HoldingLot).delete()
        db.query(Holding).filter(Holding.wallet_id == wallet.id).delete()
        db.commit()

        # Create a test holding of 10 MSFT shares with square_off_date set to today or earlier
        past_date = date(2026, 9, 20)
        test_holding = Holding(
            wallet_id=wallet.id,
            ticker="MSFT",
            quantity=10.0,
            avg_buy_price=300.0,
            square_off_date=past_date,
            is_intraday=False,
        )
        db.add(test_holding)
        db.commit()
        db.refresh(test_holding)

        lot = HoldingLot(
            holding_id=test_holding.id,
            quantity=10.0,
            buy_price=300.0,
            square_off_date=past_date,
            is_intraday=False,
            is_short=False,
        )
        db.add(lot)
        db.commit()

        initial_cash = wallet.current_cash_balance

        # 1. Partial manual sell of 4 shares before square-off executes
        from services.order_engine import _execute_sell
        _execute_sell(db, wallet, "MSFT", 4.0, 310.0, order_type="market")
        db.refresh(wallet)
        holding_after_manual = db.query(Holding).filter(Holding.wallet_id == wallet.id, Holding.ticker == "MSFT").first()
        assert holding_after_manual is not None
        assert abs(holding_after_manual.quantity - 6.0) < 1e-6
        assert holding_after_manual.square_off_date == past_date
        print("PASS: Partial manual sell reduced holding to 6 shares while preserving square_off_date.")

        # 2. Trigger auto square-off (force_time_check=True)
        executed = evaluate_auto_square_off(db, force_time_check=True, market_filter="US")
        assert len(executed) >= 1
        auto_order = next((o for o in executed if o.ticker == "MSFT"), None)
        assert auto_order is not None
        assert auto_order.side == "sell"
        assert abs(auto_order.quantity - 6.0) < 1e-6
        assert auto_order.triggered_by == "auto_square_off"
        assert auto_order.status == "filled"

        # Verify transaction
        txn = db.query(Transaction).filter(Transaction.order_id == auto_order.id).first()
        assert txn is not None
        assert txn.triggered_by == "auto_square_off"

        # Verify holding is now completely closed (deleted)
        final_holding = db.query(Holding).filter(Holding.wallet_id == wallet.id, Holding.ticker == "MSFT").first()
        assert final_holding is None

        db.refresh(wallet)
        assert wallet.current_cash_balance > initial_cash
        print(f"PASS: Auto square-off executed cleanly for remaining 6 shares with triggered_by='auto_square_off'!")


if __name__ == "__main__":
    test_trading_calendar_logic()
    test_api_calculate_square_off()
    test_place_buy_order_with_duration()
    test_auto_square_off_execution_and_partial_sell()
    print("\nALL PHASE 4L BACKEND TESTS PASSED SUCCESSFULLY!")
