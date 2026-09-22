import sys
import os
from datetime import date, datetime

# Add backend directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models.orm import Wallet, Holding, HoldingLot, Order, Transaction
from services.order_engine import _execute_buy, _execute_sell, evaluate_auto_square_off
from services.trading_calendar import calculate_square_off_date

def run_tests():
    db = SessionLocal()
    try:
        print("--- Testing Quantity-Specific Auto Square-Off & Lot Management ---")

        # 1. Setup isolated test wallet
        w = db.query(Wallet).filter(Wallet.market == "US").first()
        if not w:
            w = Wallet(market="US", currency="USD", starting_balance=100000.0, current_cash_balance=100000.0)
            db.add(w)
            db.commit()

        # Clean existing test holding for AAPL
        existing_h = db.query(Holding).filter(Holding.wallet_id == w.id, Holding.ticker == "AAPL").first()
        if existing_h:
            db.delete(existing_h)
            db.commit()

        today = date.today()
        two_days_date = date.fromisoformat(calculate_square_off_date("US", holding_days=2)["square_off_date"])

        # 2. Buy Lot 1: 10 shares @ $150 with NO duration
        print("Executing BUY 1: 10 shares AAPL (no timer)...")
        _execute_buy(db, wallet=w, ticker="AAPL", quantity=10.0, price=150.0, square_off_date=None, is_intraday=False)

        h = db.query(Holding).filter(Holding.wallet_id == w.id, Holding.ticker == "AAPL").first()
        assert h is not None, "Holding should exist"
        assert abs(h.quantity - 10.0) < 1e-6, f"Expected 10 shares, got {h.quantity}"
        assert h.square_off_date is None, "Holding square_off_date should be None"
        assert len(h.lots) == 1, f"Expected 1 lot, got {len(h.lots)}"
        print("PASS: Lot 1 created (10 shares, no timer)")

        # 3. Buy Lot 2: 5 shares @ $160 with 2-day duration
        print("Executing BUY 2: 5 shares AAPL (2-day timer)...")
        _execute_buy(db, wallet=w, ticker="AAPL", quantity=5.0, price=160.0, square_off_date=two_days_date, is_intraday=False)

        db.refresh(h)
        assert abs(h.quantity - 15.0) < 1e-6, f"Expected 15 shares, got {h.quantity}"
        assert h.square_off_date == two_days_date, f"Holding square_off_date should be {two_days_date}"
        assert len(h.lots) == 2, f"Expected 2 lots, got {len(h.lots)}"
        print(f"PASS: Lot 2 added (5 shares, square-off: {two_days_date})")

        # 4. Buy Lot 3: 3 shares @ $170 with intraday duration (today)
        print("Executing BUY 3: 3 shares AAPL (intraday timer)...")
        _execute_buy(db, wallet=w, ticker="AAPL", quantity=3.0, price=170.0, square_off_date=today, is_intraday=True)

        db.refresh(h)
        assert abs(h.quantity - 18.0) < 1e-6, f"Expected 18 shares, got {h.quantity}"
        assert h.square_off_date == today, f"Holding square_off_date should be {today}"
        assert len(h.lots) == 3, f"Expected 3 lots, got {len(h.lots)}"
        print("PASS: Lot 3 added (3 shares, square-off: today)")

        # 5. Trigger auto square-off for today (should ONLY sell the 3 intraday shares!)
        print("\nTriggering auto square-off for today...")
        executed = evaluate_auto_square_off(db, force_time_check=True, market_filter="US")
        auto_orders = [o for o in executed if o.ticker == "AAPL"]
        assert len(auto_orders) == 1, f"Expected 1 auto square-off order for AAPL, got {len(auto_orders)}"
        assert abs(auto_orders[0].quantity - 3.0) < 1e-6, f"Expected auto sell of EXACTLY 3 shares, got {auto_orders[0].quantity}"
        assert auto_orders[0].triggered_by == "auto_square_off", "Order triggered_by must be auto_square_off"

        # Check holding after auto sell
        db.refresh(h)
        assert abs(h.quantity - 15.0) < 1e-6, f"Expected 15 shares remaining, got {h.quantity}"
        assert h.square_off_date == two_days_date, f"Holding square_off_date should now be {two_days_date}"
        assert len(h.lots) == 2, f"Expected 2 remaining lots, got {len(h.lots)}"
        print("PASS: Exactly 3 shares sold! Remaining 15 shares stay intact with 2-day timer.")

        # 6. Test manual sell FIFO deduction: user sells 2 shares
        print("\nExecuting manual SELL of 2 shares...")
        _execute_sell(db, wallet=w, ticker="AAPL", quantity=2.0, price=175.0, order_type="market")

        db.refresh(h)
        assert abs(h.quantity - 13.0) < 1e-6, f"Expected 13 shares remaining, got {h.quantity}"
        # Check FIFO: Lot 1 (originally 10 shares) should now be 8 shares. Lot 2 (5 shares) untouched!
        lots = sorted(h.lots, key=lambda l: l.created_at)
        assert len(lots) == 2, f"Expected 2 lots, got {len(lots)}"
        assert abs(lots[0].quantity - 8.0) < 1e-6, f"Oldest lot should be reduced to 8 shares, got {lots[0].quantity}"
        assert abs(lots[1].quantity - 5.0) < 1e-6, f"Timed lot should still have 5 shares, got {lots[1].quantity}"
        assert lots[1].square_off_date == two_days_date, "Timed lot date must be preserved"
        print("PASS: FIFO manual sell correctly deducted 2 shares from the oldest untimed lot, leaving timed lot intact.")

        # 7. Simulate arrival of 2-day expiry date
        print("\nSimulating 2-day square-off expiry...")
        lots[1].square_off_date = today
        db.commit()

        executed_2 = evaluate_auto_square_off(db, force_time_check=True, market_filter="US")
        auto_orders_2 = [o for o in executed_2 if o.ticker == "AAPL"]
        assert len(auto_orders_2) == 1, f"Expected 1 auto sell order, got {len(auto_orders_2)}"
        assert abs(auto_orders_2[0].quantity - 5.0) < 1e-6, f"Expected auto sell of EXACTLY 5 shares, got {auto_orders_2[0].quantity}"

        db.refresh(h)
        assert abs(h.quantity - 8.0) < 1e-6, f"Expected 8 shares remaining, got {h.quantity}"
        assert h.square_off_date is None, f"Holding square_off_date should be None, got {h.square_off_date}"
        assert len(h.lots) == 1, f"Expected 1 remaining lot, got {len(h.lots)}"
        assert abs(h.lots[0].quantity - 8.0) < 1e-6, f"Remaining lot should have 8 shares, got {h.lots[0].quantity}"
        print("PASS: Exactly 5 shares sold! 8 untimed shares remain safely in portfolio with no active timers.")

        print("\nALL QUANTITY-SPECIFIC AUTO SQUARE-OFF UNIT TESTS PASSED SUCCESSFULLY!")

    finally:
        db.close()

if __name__ == "__main__":
    run_tests()
