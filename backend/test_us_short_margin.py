"""
test_us_short_margin.py — Test suite for US Short Selling, Reg T Margin, and Liquidation.
"""

import os
import sys
from datetime import date
from unittest.mock import MagicMock, patch

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from database import Base, SessionLocal, engine
from models.orm import Holding, HoldingLot, Order, Transaction, Wallet
from services.order_engine import (
    _execute_cover_buy,
    _execute_short_sell,
    evaluate_auto_square_off,
    evaluate_margin_calls,
    place_order,
)
from services.portfolio import get_holdings_with_pnl, get_wallet_summary
from services.price_feed import PriceQuote


def setup_clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    # Create US wallet
    wallet = Wallet(
        market="US",
        currency="USD",
        starting_balance=10000.0,
        current_cash_balance=10000.0,
        margin_used=0.0,
    )
    db.add(wallet)
    db.commit()
    db.refresh(wallet)
    return db, wallet


def make_quote(symbol: str, price: float, market_open: bool = True) -> PriceQuote:
    return PriceQuote(
        symbol=symbol,
        display_name=symbol,
        exchange="NASDAQ",
        currency="USD",
        price=price,
        prev_close=price,
        change=0.0,
        change_pct=0.0,
        day_high=price,
        day_low=price,
        volume=100000,
        market_open=market_open,
        timestamp=1234567890,
    )


def test_us_short_initial_margin_and_buying_power():
    db, wallet = setup_clean_db()
    try:
        mock_quote = make_quote("AAPL", 200.0)

        with patch("services.order_engine.get_quote", return_value=mock_quote):
            # Short 10 AAPL @ $200 = $2,000 value.
            # 150% margin requirement = $3,000.
            # Available buying power is $10,000 >= $3,000 -> succeeds!
            order = place_order(
                db=db,
                market="US",
                ticker="AAPL",
                side="sell",
                quantity=10.0,
                order_type="market",
            )

        assert order.status == "filled"
        assert order.is_short is True

        db.refresh(wallet)
        # Proceeds +$2,000 added to cash: cash = $12,000
        assert wallet.current_cash_balance == 12000.0
        # Collateral locked: $3,000
        assert wallet.margin_used == 3000.0
        # Available buying power = $12,000 - $3,000 = $9,000
        assert wallet.available_buying_power == 9000.0

        # Holding checks
        holding = db.query(Holding).filter(Holding.wallet_id == wallet.id, Holding.ticker == "AAPL").first()
        assert holding is not None
        assert holding.quantity == 10.0
        assert holding.avg_buy_price == 200.0
        assert holding.is_short is True
        assert holding.margin_locked == 3000.0

        # Portfolio metrics
        with patch("services.portfolio.get_quotes", return_value=[mock_quote]):
            summary = get_wallet_summary(db, wallet)
        assert summary.margin_used == 3000.0
        assert summary.available_buying_power == 9000.0

        h_pnl = summary.holdings[0]
        assert h_pnl.margin_locked == 3000.0
        # At $200, current position val = $2,000.
        # Maintenance req (125%) = $2,500.
        assert h_pnl.maintenance_margin_required == 2500.0
        # Margin level ratio = 3000 / 2000 = 150%
        assert h_pnl.margin_level_pct == 150.0
        # Liquidation price = 3000 / (1.25 * 10) = $240.0
        assert h_pnl.liquidation_price == 240.0
        # Distance to call = (240 - 200) / 200 = 20%
        assert h_pnl.distance_to_margin_call_pct == 20.0

        print("[PASS] test_us_short_initial_margin_and_buying_power passed")
    finally:
        db.close()


def test_us_short_insufficient_margin_rejected():
    db, wallet = setup_clean_db()
    try:
        mock_quote = make_quote("TSLA", 1000.0)

        with patch("services.order_engine.get_quote", return_value=mock_quote):
            # Short 10 TSLA @ $1000 = $10,000 position value.
            # 150% margin requirement = $15,000 > available BP $10,000 -> Rejected!
            order = place_order(
                db=db,
                market="US",
                ticker="TSLA",
                side="sell",
                quantity=10.0,
                order_type="market",
            )

        assert order.status == "rejected"
        assert order.reject_reason == "insufficient_margin"
        assert wallet.margin_used == 0.0
        assert wallet.current_cash_balance == 10000.0
        print("[PASS] test_us_short_insufficient_margin_rejected passed")
    finally:
        db.close()


def test_us_short_overnight_not_auto_squared_off():
    db, wallet = setup_clean_db()
    try:
        mock_quote = make_quote("MSFT", 300.0)

        with patch("services.order_engine.get_quote", return_value=mock_quote):
            # Short 5 MSFT without duration (overnight by default)
            order = place_order(
                db=db,
                market="US",
                ticker="MSFT",
                side="sell",
                quantity=5.0,
                order_type="market",
            )
            assert order.status == "filled"

            # Run auto square off evaluation (force_time_check=True)
            sq_orders = evaluate_auto_square_off(db, quotes=[mock_quote], force_time_check=True, market_filter="US")

        # Overnight US shorts must NOT be squared off!
        assert len(sq_orders) == 0

        holding = db.query(Holding).filter(Holding.ticker == "MSFT").first()
        assert holding is not None
        assert holding.quantity == 5.0
        print("[PASS] test_us_short_overnight_not_auto_squared_off passed")
    finally:
        db.close()


def test_long_to_short_split_sell_us():
    db, wallet = setup_clean_db()
    try:
        mock_quote = make_quote("NVDA", 100.0)

        with patch("services.order_engine.get_quote", return_value=mock_quote):
            # 1. Buy 5 NVDA long @ $100 (cost = $500, cash = $9,500)
            buy_order = place_order(
                db=db,
                market="US",
                ticker="NVDA",
                side="buy",
                quantity=5.0,
                order_type="market",
            )
            assert buy_order.status == "filled"

            # 2. Sell 15 NVDA: 5 long should close, 10 should open as short!
            split_order = place_order(
                db=db,
                market="US",
                ticker="NVDA",
                side="sell",
                quantity=15.0,
                order_type="market",
            )

        assert split_order.status == "filled"
        assert split_order.is_short is True
        assert split_order.quantity == 10.0

        db.refresh(wallet)
        # Long sold: proceeds +$500 (cash = $10,000)
        # Short opened: 10 * 100 = proceeds +$1,000 (cash = $11,000)
        # Margin locked: 1.5 * $1,000 = $1,500
        assert wallet.current_cash_balance == 11000.0
        assert wallet.margin_used == 1500.0
        assert wallet.available_buying_power == 9500.0

        # Holding should now be short 10 NVDA
        holding = db.query(Holding).filter(Holding.ticker == "NVDA").first()
        assert holding is not None
        assert holding.is_short is True
        assert holding.quantity == 10.0

        print("[PASS] test_long_to_short_split_sell_us passed")
    finally:
        db.close()


def test_fifo_cover_buy_and_margin_release():
    db, wallet = setup_clean_db()
    try:
        # Create 2 short lots at different entry prices:
        # Lot 1: 10 shares @ $100 -> margin = $1,500
        # Lot 2: 10 shares @ $120 -> margin = $1,800
        # Total margin = $3,300
        _execute_short_sell(
            db=db, wallet=wallet, ticker="AMZN", quantity=10.0, price=100.0, order_type="market"
        )
        _execute_short_sell(
            db=db, wallet=wallet, ticker="AMZN", quantity=10.0, price=120.0, order_type="market"
        )

        db.refresh(wallet)
        assert wallet.margin_used == 3300.0
        holding = db.query(Holding).filter(Holding.ticker == "AMZN").first()
        assert holding.quantity == 20.0
        assert holding.margin_locked == 3300.0

        # Cover-buy 5 shares @ $90 (FIFO: consumed from Lot 1)
        cover_order = _execute_cover_buy(
            db=db, wallet=wallet, ticker="AMZN", quantity=5.0, price=90.0, order_type="market"
        )
        assert cover_order.status == "filled"

        db.refresh(wallet)
        # Released margin from Lot 1 (5/10 * 1500 = $750)
        assert wallet.margin_used == 2550.0
        assert holding.margin_locked == 2550.0
        assert holding.quantity == 15.0

        # Check realized P&L on cover transaction:
        # Entry price was $100 (Lot 1), cover price $90 -> P&L = ($100 - $90) * 5 = +$50
        txn = db.query(Transaction).filter(Transaction.order_id == cover_order.id).first()
        assert txn.realized_pnl == 50.0

        print("[PASS] test_fifo_cover_buy_and_margin_release passed")
    finally:
        db.close()


def test_margin_call_liquidation_entire_position_multi_lot():
    """
    User clarification:
    When evaluate_margin_calls triggers on a holding with multiple lots at different entry prices,
    liquidate the ENTIRE short position for that ticker (not a partial amount),
    processing lot-by-lot in FIFO order with correct per-lot realized P&L and full margin release.
    """
    db, wallet = setup_clean_db()
    try:
        # Lot 1: 10 MSFT @ $100. Margin locked = $1,500
        _execute_short_sell(
            db=db, wallet=wallet, ticker="MSFT", quantity=10.0, price=100.0, order_type="market"
        )
        # Lot 2: 10 MSFT @ $110. Margin locked = $1,650
        _execute_short_sell(
            db=db, wallet=wallet, ticker="MSFT", quantity=10.0, price=110.0, order_type="market"
        )

        db.refresh(wallet)
        # Cash starting: 10,000 + 1,000 + 1,100 = 12,100
        assert wallet.current_cash_balance == 12100.0
        assert wallet.margin_used == 3150.0

        holding = db.query(Holding).filter(Holding.ticker == "MSFT").first()
        assert holding.quantity == 20.0
        assert holding.margin_locked == 3150.0

        # Liquidation price = 3150 / (1.25 * 20) = $126.00
        # Price spikes to $130 (breaches maintenance margin: ratio = 3150 / (20 * 130) = 1.2115 < 1.25)
        spike_quote = make_quote("MSFT", 130.0)

        # Trigger margin calls
        liquidated_orders = evaluate_margin_calls(db, quotes=[spike_quote])

        assert len(liquidated_orders) == 1
        liq_order = liquidated_orders[0]
        assert liq_order.status == "filled"
        assert liq_order.triggered_by == "margin_call_liquidation"
        # Entire 20 shares covered!
        assert liq_order.quantity == 20.0
        assert liq_order.executed_price == 130.0

        # Holding should be completely closed & deleted
        closed_holding = db.query(Holding).filter(Holding.ticker == "MSFT").first()
        assert closed_holding is None

        # All lots deleted
        lots = db.query(HoldingLot).all()
        assert len(lots) == 0

        db.refresh(wallet)
        # All margin released
        assert wallet.margin_used == 0.0

        # Buyback cost: 20 * 130 = $2,600
        # Cash before was $12,100 -> after: $12,100 - $2,600 = $9,500
        assert wallet.current_cash_balance == 9500.0

        # Check transaction and P&L
        txn = db.query(Transaction).filter(Transaction.order_id == liq_order.id).first()
        assert txn.triggered_by == "margin_call_liquidation"
        assert txn.is_short is True
        # Realized P&L:
        # Lot 1: (100 - 130) * 10 = -$300
        # Lot 2: (110 - 130) * 10 = -$200
        # Total realized P&L = -$500!
        assert txn.realized_pnl == -500.0

        print("[PASS] test_margin_call_liquidation_entire_position_multi_lot passed")
    finally:
        db.close()


if __name__ == "__main__":
    test_us_short_initial_margin_and_buying_power()
    test_us_short_insufficient_margin_rejected()
    test_us_short_overnight_not_auto_squared_off()
    test_long_to_short_split_sell_us()
    test_fifo_cover_buy_and_margin_release()
    test_margin_call_liquidation_entire_position_multi_lot()
    print("\nALL US SHORT SELLING & MARGIN TESTS PASSED SUCCESSFULLY!")
