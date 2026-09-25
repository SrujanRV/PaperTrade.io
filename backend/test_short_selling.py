"""
test_short_selling.py — Unit and integration tests for Phase 5a Intraday Short Selling (NSE/BSE).

Tests:
1. Open short position in IN market (creates Holding with is_short=True, credits cash, creates HoldingLot with is_short=True).
2. Cash margin check (rejects if cash < 1x position value with 'insufficient_margin').
3. Intraday-only validation (rejects multi-day short duration with 'intraday_only_for_short').
4. US short rejection (short selling in US market rejected with 'us_short_not_supported').
5. Multi-lot FIFO cover buy (Clarification 1: covers short lots ordered strictly by created_at ASC with accurate realized P&L).
6. Long-to-short split sell (Clarification 2: selling more than held long closes long first, then opens short for excess).
7. Auto square-off cover buy (force-closes open short position near close with triggered_by="auto_square_off").
"""

import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add backend directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Base
from models.orm import Holding, HoldingLot, Order, Transaction, Wallet
from services.order_engine import (
    _execute_buy,
    _execute_cover_buy,
    _execute_sell,
    _execute_short_sell,
    evaluate_auto_square_off,
    place_order,
)
from services.portfolio import get_holdings_with_pnl, get_realized_pnl, get_wallet_summary
from services.price_feed import PriceQuote


def make_quote(symbol: str, price: float, market_open: bool = True, currency: str = "INR") -> PriceQuote:
    return PriceQuote(
        symbol=symbol,
        display_name=symbol,
        exchange="NSE" if symbol.endswith(".NS") else "NASDAQ",
        currency=currency,
        price=price,
        prev_close=price,
        change=0.0,
        change_pct=0.0,
        day_high=price,
        day_low=price,
        volume=1000,
        market_open=market_open,
        timestamp=datetime.now(timezone.utc).isoformat(),
        error=None,
    )


class TestShortSelling(unittest.TestCase):
    def setUp(self):
        # Use an isolated in-memory SQLite database
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # Set up an Indian wallet (INR) with 100,000 starting balance
        self.in_wallet = Wallet(
            market="IN",
            currency="INR",
            starting_balance=100000.0,
            current_cash_balance=100000.0,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(self.in_wallet)

        # Set up a US wallet (USD) with 10,000 starting balance
        self.us_wallet = Wallet(
            market="US",
            currency="USD",
            starting_balance=10000.0,
            current_cash_balance=100000.0,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(self.us_wallet)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    @patch("services.order_engine.get_quote")
    def test_1_open_short_position_in_market(self, mock_get_quote):
        """Test opening an intraday short position in IN market."""
        mock_get_quote.return_value = make_quote("RELIANCE.NS", 2500.0)

        initial_cash = self.in_wallet.current_cash_balance
        order = place_order(
            db=self.db,
            market="IN",
            ticker="RELIANCE.NS",
            side="sell",
            quantity=10,
            order_type="market",
        )

        self.assertEqual(order.status, "filled")
        self.assertTrue(order.is_short)
        self.assertTrue(order.is_intraday)
        self.assertEqual(order.executed_price, 2500.0)

        # Cash balance should be credited with proceeds: 10 * 2500 = 25,000
        self.assertAlmostEqual(self.in_wallet.current_cash_balance, initial_cash + 25000.0, places=2)

        # Holding check
        holding = (
            self.db.query(Holding)
            .filter(Holding.wallet_id == self.in_wallet.id, Holding.ticker == "RELIANCE.NS")
            .first()
        )
        self.assertIsNotNone(holding)
        self.assertTrue(holding.is_short)
        self.assertEqual(holding.quantity, 10)
        self.assertEqual(holding.avg_buy_price, 2500.0)

        # HoldingLot check
        lots = self.db.query(HoldingLot).filter(HoldingLot.holding_id == holding.id).all()
        self.assertEqual(len(lots), 1)
        self.assertTrue(lots[0].is_short)
        self.assertEqual(lots[0].quantity, 10)
        self.assertEqual(lots[0].buy_price, 2500.0)

        # Transaction check
        txn = self.db.query(Transaction).filter(Transaction.order_id == order.id).first()
        self.assertIsNotNone(txn)
        self.assertTrue(txn.is_short)
        self.assertEqual(txn.side, "sell")
        self.assertIsNone(txn.realized_pnl)

    @patch("services.order_engine.get_quote")
    def test_2_margin_check_rejection(self, mock_get_quote):
        """Test rejection when cash balance is below 1x margin requirement."""
        mock_get_quote.return_value = make_quote("TCS.NS", 4000.0)

        # Set wallet cash to only 5,000
        self.in_wallet.current_cash_balance = 5000.0
        self.db.commit()

        # Attempt to short 2 shares of TCS (value = 8,000 > cash 5,000)
        order = place_order(
            db=self.db,
            market="IN",
            ticker="TCS.NS",
            side="sell",
            quantity=2,
            order_type="market",
        )

        self.assertEqual(order.status, "rejected")
        self.assertEqual(order.reject_reason, "insufficient_margin")
        self.assertTrue(order.is_short)

    @patch("services.order_engine.get_quote")
    def test_3_intraday_only_rejection(self, mock_get_quote):
        """Test rejection if trying to open a multi-day short in Indian equities."""
        mock_get_quote.return_value = make_quote("INFY.NS", 1500.0)

        order = place_order(
            db=self.db,
            market="IN",
            ticker="INFY.NS",
            side="sell",
            quantity=5,
            order_type="market",
            holding_days=3,  # Multi-day requested!
        )

        self.assertEqual(order.status, "rejected")
        self.assertEqual(order.reject_reason, "intraday_only_for_short")

    @patch("services.order_engine.get_quote")
    def test_4_us_market_short_rejection(self, mock_get_quote):
        """Test US short selling is now supported with 150% initial margin."""
        mock_get_quote.return_value = make_quote("AAPL", 220.0, currency="USD")

        order = place_order(
            db=self.db,
            market="US",
            ticker="AAPL",
            side="sell",
            quantity=10,
            order_type="market",
        )

        self.assertEqual(order.status, "filled")
        self.assertTrue(order.is_short)
        self.db.refresh(self.us_wallet)
        # 10 * 220 = $2,200 proceeds; 1.5 * 2,200 = $3,300 margin locked
        self.assertEqual(self.us_wallet.margin_used, 3300.0)

    @patch("services.order_engine.get_quote")
    def test_5_multi_lot_fifo_cover_buy(self, mock_get_quote):
        """
        Clarification 1 Test: Multiple short lots at different entry prices
        covered in strict FIFO order (created_at ASC) with accurate realized P&L.
        """
        # Create Short Lot 1: 10 shares @ 3000 at T0
        # Create Short Lot 2: 10 shares @ 3200 at T1
        holding = Holding(
            wallet_id=self.in_wallet.id,
            ticker="LT.NS",
            quantity=20.0,
            avg_buy_price=3100.0,
            is_intraday=True,
            is_short=True,
        )
        self.db.add(holding)
        self.db.flush()

        t0 = datetime(2026, 9, 23, 10, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 9, 23, 11, 0, 0, tzinfo=timezone.utc)

        lot1 = HoldingLot(
            holding_id=holding.id,
            quantity=10.0,
            buy_price=3000.0,
            is_intraday=True,
            is_short=True,
            created_at=t0,
        )
        lot2 = HoldingLot(
            holding_id=holding.id,
            quantity=10.0,
            buy_price=3200.0,
            is_intraday=True,
            is_short=True,
            created_at=t1,
        )
        self.db.add_all([lot1, lot2])
        self.db.commit()

        # Cover 15 shares at 2800.
        # FIFO expects:
        # - Consume all 10 shares of Lot 1 (@ 3000): P&L = (3000 - 2800) * 10 = +2000
        # - Consume 5 shares of Lot 2 (@ 3200): P&L = (3200 - 2800) * 5 = +2000
        # Total Realized P&L = 4000.
        # Remaining in Lot 2: 5 shares @ 3200.
        mock_get_quote.return_value = make_quote("LT.NS", 2800.0)

        cover_order = place_order(
            db=self.db,
            market="IN",
            ticker="LT.NS",
            side="buy",
            quantity=15,
            order_type="market",
        )

        self.assertEqual(cover_order.status, "filled")
        self.assertTrue(cover_order.is_short)
        self.assertEqual(cover_order.executed_price, 2800.0)

        # Check transaction realized P&L
        txn = self.db.query(Transaction).filter(Transaction.order_id == cover_order.id).first()
        self.assertIsNotNone(txn)
        self.assertTrue(txn.is_short)
        self.assertEqual(txn.realized_pnl, 4000.0)

        # Check holding remaining
        self.db.refresh(holding)
        self.assertEqual(holding.quantity, 5.0)
        self.assertEqual(holding.avg_buy_price, 3200.0)

        # Check lots remaining: only Lot 2 with 5 shares
        remaining_lots = self.db.query(HoldingLot).filter(HoldingLot.holding_id == holding.id).all()
        self.assertEqual(len(remaining_lots), 1)
        self.assertEqual(remaining_lots[0].quantity, 5.0)
        self.assertEqual(remaining_lots[0].buy_price, 3200.0)

        # Verify portfolio realized P&L matches exactly
        realized_total = get_realized_pnl(self.db, self.in_wallet)
        self.assertEqual(realized_total, 4000.0)

    @patch("services.order_engine.get_quote")
    def test_6_long_to_short_split_sell(self, mock_get_quote):
        """
        Clarification 2 Test: User holds 5 shares long of HDFCBANK.NS.
        Submits SELL order for 8 shares.
        Must split into:
        1. Close 5 long shares normally (standard sell, standard long P&L).
        2. Open 3 shares short (short holding, proceeds credited, is_short=True).
        """
        # User owns 5 shares @ 1500 long
        holding = Holding(
            wallet_id=self.in_wallet.id,
            ticker="HDFCBANK.NS",
            quantity=5.0,
            avg_buy_price=1500.0,
            is_intraday=False,
            is_short=False,
        )
        self.db.add(holding)
        self.db.flush()
        lot = HoldingLot(
            holding_id=holding.id,
            quantity=5.0,
            buy_price=1500.0,
            is_intraday=False,
            is_short=False,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(lot)
        self.db.commit()

        # Current price = 1600
        mock_get_quote.return_value = make_quote("HDFCBANK.NS", 1600.0)

        initial_cash = self.in_wallet.current_cash_balance

        # Sell 8 shares (5 long + 3 short)
        short_order = place_order(
            db=self.db,
            market="IN",
            ticker="HDFCBANK.NS",
            side="sell",
            quantity=8,
            order_type="market",
        )

        self.assertEqual(short_order.status, "filled")
        self.assertTrue(short_order.is_short)
        self.assertEqual(short_order.quantity, 3.0)

        # Check transactions:
        # Txn 1: Long sell of 5 shares @ 1600 -> Realized P&L = (1600 - 1500) * 5 = +500
        # Txn 2: Short sell of 3 shares @ 1600 -> Realized P&L = None
        txns = (
            self.db.query(Transaction)
            .filter(Transaction.ticker == "HDFCBANK.NS")
            .order_by(Transaction.id.asc())
            .all()
        )
        self.assertEqual(len(txns), 2)

        long_txn = txns[0]
        self.assertFalse(long_txn.is_short)
        self.assertEqual(long_txn.quantity, 5.0)
        self.assertEqual(long_txn.realized_pnl, 500.0)

        short_txn = txns[1]
        self.assertTrue(short_txn.is_short)
        self.assertEqual(short_txn.quantity, 3.0)
        self.assertIsNone(short_txn.realized_pnl)

        # Verify new holding is short with 3 shares
        new_holding = (
            self.db.query(Holding)
            .filter(Holding.wallet_id == self.in_wallet.id, Holding.ticker == "HDFCBANK.NS")
            .first()
        )
        self.assertIsNotNone(new_holding)
        self.assertTrue(new_holding.is_short)
        self.assertEqual(new_holding.quantity, 3.0)
        self.assertEqual(new_holding.avg_buy_price, 1600.0)

        # Cash check: proceeds from long (5 * 1600 = 8000) + proceeds from short (3 * 1600 = 4800) = 12800
        self.assertAlmostEqual(self.in_wallet.current_cash_balance, initial_cash + 12800.0, places=2)

    @patch("services.order_engine.get_quote")
    def test_7_auto_square_off_cover_buy(self, mock_get_quote):
        """Test auto square-off force-closing an open short position at session close."""
        holding = Holding(
            wallet_id=self.in_wallet.id,
            ticker="WIPRO.NS",
            quantity=10.0,
            avg_buy_price=500.0,
            is_intraday=True,
            is_short=True,
            square_off_date=date.today(),
        )
        self.db.add(holding)
        self.db.flush()
        lot = HoldingLot(
            holding_id=holding.id,
            quantity=10.0,
            buy_price=500.0,
            is_intraday=True,
            is_short=True,
            square_off_date=date.today(),
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(lot)
        self.db.commit()

        # Quote at close: price drops to 480
        mock_get_quote.return_value = make_quote("WIPRO.NS", 480.0)

        executed = evaluate_auto_square_off(
            db=self.db,
            force_time_check=True,
            market_filter="IN",
        )

        self.assertEqual(len(executed), 1)
        cover_order = executed[0]
        self.assertEqual(cover_order.status, "filled")
        self.assertTrue(cover_order.is_short)
        self.assertEqual(cover_order.side, "buy")
        self.assertEqual(cover_order.triggered_by, "auto_square_off")

        # Holding should now be deleted
        remaining_holding = (
            self.db.query(Holding)
            .filter(Holding.wallet_id == self.in_wallet.id, Holding.ticker == "WIPRO.NS")
            .first()
        )
        self.assertIsNone(remaining_holding)

        # Realized P&L check: (500 - 480) * 10 = +200
        txn = self.db.query(Transaction).filter(Transaction.order_id == cover_order.id).first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.realized_pnl, 200.0)
        self.assertEqual(txn.triggered_by, "auto_square_off")


if __name__ == "__main__":
    unittest.main()
