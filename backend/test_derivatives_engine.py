"""
test_derivatives_engine.py — Comprehensive Unit Test Suite for Phase 6c:
Options & Futures Order Engine Logic.

Verifies:
1. Option Buying (buy_to_open): upfront premium deduction, 0 margin locked, position creation, weighted average entry, insufficient cash rejection.
2. Covered Call Writing (sell_to_open): 0 margin locked when holding underlying shares, premium credited to cash.
3. Naked Option Writing (sell_to_open): 20% initial margin locked, premium credited to cash, insufficient buying power rejection.
4. Option Exits (sell_to_close & buy_to_close): premium proceeds, realized P&L, proportional margin release.
5. Futures Trading (buy_to_open & sell_to_open): 12% initial margin locked, 0 cash debit, margin rejection, closing with P&L and margin release.
6. Futures Daily Mark-to-Market (MTM): cash settlement into wallet, last_mtm_price update, position stays open, margin stays locked.
7. Expiry Cash Settlement: ITM intrinsic cash payout, OTM worthless expiry, written option margin release, Indian index futures final MTM.
8. Derivative Margin Call Liquidation: auto-liquidation of naked options (15% maint) and futures (10% maint) on threshold breach.
9. Portfolio Derivatives Summary: live mark-to-market metrics, unrealized P&L, margin health level.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure backend root on sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from database import Base
from models.orm import (
    Wallet,
    Holding,
    DerivativeContract,
    DerivativePosition,
    DerivativeOrder,
    DerivativeTransaction,
)
from services.derivatives_engine import (
    DEFAULT_LOT_SIZES,
    get_or_create_contract,
    is_covered_option,
    place_derivative_order,
    evaluate_daily_futures_mtm,
    evaluate_derivatives_expiry_settlement,
    evaluate_derivative_margin_calls,
    get_derivative_positions_summary,
)
from services.price_feed import PriceQuote


def setup_test_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # Create IN and US wallets
    in_wallet = Wallet(
        market="IN",
        currency="INR",
        starting_balance=1000000.0,  # ₹10,00,000
        current_cash_balance=1000000.0,
        margin_used=0.0,
    )
    us_wallet = Wallet(
        market="US",
        currency="USD",
        starting_balance=50000.0,     # $50,000
        current_cash_balance=50000.0,
        margin_used=0.0,
    )
    db.add(in_wallet)
    db.add(us_wallet)
    db.commit()
    db.refresh(in_wallet)
    db.refresh(us_wallet)
    return db, in_wallet, us_wallet


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1: Option Buying (buy_to_open)
# ══════════════════════════════════════════════════════════════════════════════

def test_option_buying_upfront_premium_and_no_margin():
    """
    Test buying options:
    - Premium is paid upfront from cash balance.
    - 0 margin is locked.
    - Position is created with side='long' and quantity in lots.
    - Multiple buys calculate weighted average entry price.
    - Order is rejected if cash is insufficient.
    """
    db, in_wallet, _ = setup_test_db()
    try:
        # NIFTY 23,150 Call (lot size = 65)
        contract = get_or_create_contract(
            db=db,
            market="IN",
            underlying="NIFTY",
            instrument_type="option",
            option_type="call",
            strike_price=23150.0,
            expiry_date=date(2026, 9, 29),
            lot_size=65,
        )
        assert contract.lot_size == 65

        # 1. Buy 2 lots @ ₹150 premium
        # Premium cost = 2 lots * 65 shares/lot * ₹150 = ₹19,500
        order1 = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=contract,
            side="buy",
            action="buy_to_open",
            quantity=2.0,
            fill_price=150.0,
        )
        assert order1.status == "filled"
        assert order1.executed_price == 150.0

        db.refresh(in_wallet)
        # Cash should be ₹10,00,000 - ₹19,500 = ₹9,80,500
        assert in_wallet.current_cash_balance == 980500.0
        # Margin used must be 0
        assert in_wallet.margin_used == 0.0
        assert in_wallet.available_buying_power == 980500.0

        pos = db.query(DerivativePosition).filter(DerivativePosition.contract_id == contract.id).first()
        assert pos is not None
        assert pos.side == "long"
        assert pos.quantity == 2.0
        assert pos.entry_price == 150.0
        assert pos.margin_locked == 0.0

        # Verify transaction ledger
        txn = db.query(DerivativeTransaction).filter(DerivativeTransaction.order_id == order1.id).first()
        assert txn is not None
        assert txn.transaction_type == "trade"
        assert txn.amount == -19500.0
        assert txn.cash_balance_after == 980500.0

        # 2. Buy another 1 lot @ ₹180 premium
        # Additional premium = 1 * 65 * 180 = ₹11,700
        # Weighted average entry = ((2 * 150) + (1 * 180)) / 3 = 480 / 3 = 160.0
        order2 = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=contract,
            side="buy",
            action="buy_to_open",
            quantity=1.0,
            fill_price=180.0,
        )
        assert order2.status == "filled"

        db.refresh(in_wallet)
        assert in_wallet.current_cash_balance == 980500.0 - 11700.0  # ₹9,68,800
        assert in_wallet.margin_used == 0.0

        db.refresh(pos)
        assert pos.quantity == 3.0
        assert pos.entry_price == 160.0

        # 3. Insufficient funds test
        # Try buying 1,000 lots @ ₹150 = 1000 * 65 * 150 = ₹97,50,000 (exceeds cash)
        rej_order = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=contract,
            side="buy",
            action="buy_to_open",
            quantity=1000.0,
            fill_price=150.0,
        )
        assert rej_order.status == "rejected"
        assert rej_order.reject_reason == "insufficient_funds"

        print("[PASS] test_option_buying_upfront_premium_and_no_margin")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2: Covered Call Writing (sell_to_open)
# ══════════════════════════════════════════════════════════════════════════════

def test_covered_call_writing_zero_margin():
    """
    Test covered call writing:
    - User holds >= quantity * lot_size shares of underlying equity.
    - Writing call option requires ZERO extra margin.
    - Premium is credited directly to cash balance.
    """
    db, in_wallet, _ = setup_test_db()
    try:
        # User owns 130 shares of RELIANCE (long equity holding)
        holding = Holding(
            wallet_id=in_wallet.id,
            ticker="RELIANCE",
            quantity=130.0,
            avg_buy_price=2900.0,
            is_short=False,
            margin_locked=0.0,
        )
        db.add(holding)
        db.commit()

        contract = get_or_create_contract(
            db=db,
            market="IN",
            underlying="RELIANCE",
            instrument_type="option",
            option_type="call",
            strike_price=3000.0,
            expiry_date=date(2026, 9, 29),
            lot_size=65,
        )

        # Check coverage helper
        assert is_covered_option(db, in_wallet.id, contract, 2.0) is True  # 2 * 65 = 130 shares held
        assert is_covered_option(db, in_wallet.id, contract, 3.0) is False # 3 * 65 = 195 > 130 held

        # Sell to open 2 lots covered call @ ₹40 premium
        # Total premium credited = 2 * 65 * 40 = ₹5,200
        order = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=contract,
            side="sell",
            action="sell_to_open",
            quantity=2.0,
            fill_price=40.0,
        )
        assert order.status == "filled"
        assert order.margin_required == 0.0

        db.refresh(in_wallet)
        # Cash balance credited with premium: ₹10,00,000 + ₹5,200 = ₹10,05,200
        assert in_wallet.current_cash_balance == 1005200.0
        # Margin used remains 0!
        assert in_wallet.margin_used == 0.0

        pos = db.query(DerivativePosition).filter(DerivativePosition.contract_id == contract.id).first()
        assert pos is not None
        assert pos.side == "short"
        assert pos.is_covered is True
        assert pos.margin_locked == 0.0
        assert pos.quantity == 2.0
        assert pos.entry_price == 40.0

        print("[PASS] test_covered_call_writing_zero_margin")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3: Naked Option Writing (sell_to_open)
# ══════════════════════════════════════════════════════════════════════════════

def test_naked_option_writing_requires_20_pct_initial_margin():
    """
    Test naked option writing:
    - User has no underlying long shares.
    - Requires 20% initial margin on notional value (underlying_price * qty * lot_size).
    - Premium is credited to cash.
    - Available buying power is checked and locked margin increments wallet.margin_used.
    - Rejected if buying power is insufficient.
    """
    db, in_wallet, _ = setup_test_db()
    try:
        # NIFTY 23,000 Put (lot size = 65)
        contract = get_or_create_contract(
            db=db,
            market="IN",
            underlying="NIFTY",
            instrument_type="option",
            option_type="put",
            strike_price=23000.0,
            expiry_date=date(2026, 9, 29),
            lot_size=65,
        )

        # Sell to open 1 lot naked put @ ₹100 premium, underlying NIFTY @ 23,100
        # Total units = 1 * 65 = 65
        # Notional value = 23,100 * 65 = ₹15,01,500
        # 20% initial margin = 0.20 * 15,01,500 = ₹3,00,300
        # Premium credit = 100 * 65 = ₹6,500
        order = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=contract,
            side="sell",
            action="sell_to_open",
            quantity=1.0,
            fill_price=100.0,
            underlying_price=23100.0,
        )
        assert order.status == "filled"
        assert order.margin_required == 300300.0

        db.refresh(in_wallet)
        # Cash credited: 1,000,000 + 6,500 = 1,006,500
        assert in_wallet.current_cash_balance == 1006500.0
        # Margin used locked: 300,300
        assert in_wallet.margin_used == 300300.0
        # Available buying power = 1,006,500 - 300,300 = 706,200
        assert in_wallet.available_buying_power == 706200.0

        pos = db.query(DerivativePosition).filter(DerivativePosition.contract_id == contract.id).first()
        assert pos is not None
        assert pos.side == "short"
        assert pos.is_covered is False
        assert pos.margin_locked == 300300.0

        # Try opening 5 more lots:
        # 5 * 300,300 = 1,501,500 margin required > 706,200 available -> REJECTED
        rej_order = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=contract,
            side="sell",
            action="sell_to_open",
            quantity=5.0,
            fill_price=100.0,
            underlying_price=23100.0,
        )
        assert rej_order.status == "rejected"
        assert rej_order.reject_reason == "insufficient_margin"

        print("[PASS] test_naked_option_writing_requires_20_pct_initial_margin")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4: Option Exits (sell_to_close & buy_to_close)
# ══════════════════════════════════════════════════════════════════════════════

def test_option_exits_and_margin_release():
    """
    Test exiting options:
    - sell_to_close for long options: credits proceeds, records realized P&L.
    - buy_to_close for written short options: debits buyback cost, releases proportional locked margin, records realized P&L.
    """
    db, in_wallet, _ = setup_test_db()
    try:
        contract_long = get_or_create_contract(
            db=db,
            market="IN",
            underlying="NIFTY",
            instrument_type="option",
            option_type="call",
            strike_price=23150.0,
            expiry_date=date(2026, 9, 29),
            lot_size=65,
        )
        # Buy 2 lots @ ₹100 = ₹13,000 cost
        place_derivative_order(
            db=db, wallet=in_wallet, contract=contract_long, side="buy", action="buy_to_open",
            quantity=2.0, fill_price=100.0,
        )

        # 1. sell_to_close 1 lot @ ₹140
        # Proceeds = 1 * 65 * 140 = ₹9,100
        # Cost basis = 1 * 65 * 100 = ₹6,500
        # Realized P&L = +₹2,600
        order_stc = place_derivative_order(
            db=db, wallet=in_wallet, contract=contract_long, side="sell", action="sell_to_close",
            quantity=1.0, fill_price=140.0,
        )
        assert order_stc.status == "filled"

        txn_stc = db.query(DerivativeTransaction).filter(DerivativeTransaction.order_id == order_stc.id).first()
        assert txn_stc.realized_pnl == 2600.0
        assert txn_stc.amount == 9100.0

        pos_long = db.query(DerivativePosition).filter(DerivativePosition.contract_id == contract_long.id).first()
        assert pos_long.quantity == 1.0

        # Close remaining 1 lot @ ₹80 (loss)
        order_stc2 = place_derivative_order(
            db=db, wallet=in_wallet, contract=contract_long, side="sell", action="sell_to_close",
            quantity=1.0, fill_price=80.0,
        )
        txn_stc2 = db.query(DerivativeTransaction).filter(DerivativeTransaction.order_id == order_stc2.id).first()
        assert txn_stc2.realized_pnl == round((80.0 - 100.0) * 65, 2)  # -₹1,300

        # Position should now be deleted
        pos_long_after = db.query(DerivativePosition).filter(DerivativePosition.contract_id == contract_long.id).first()
        assert pos_long_after is None

        # 2. Short option buy_to_close with margin release
        contract_short = get_or_create_contract(
            db=db,
            market="IN",
            underlying="NIFTY",
            instrument_type="option",
            option_type="put",
            strike_price=23000.0,
            expiry_date=date(2026, 9, 29),
            lot_size=65,
        )
        # Sell to open 2 lots naked @ ₹120 premium, NIFTY @ 23,000
        # Total units = 2 * 65 = 130
        # Notional = 23,000 * 130 = ₹29,90,000
        # 20% margin = ₹5,98,000
        # Premium credit = 120 * 130 = ₹15,600
        place_derivative_order(
            db=db, wallet=in_wallet, contract=contract_short, side="sell", action="sell_to_open",
            quantity=2.0, fill_price=120.0, underlying_price=23000.0,
        )

        db.refresh(in_wallet)
        assert in_wallet.margin_used == 598000.0

        # Cover 1 lot (buy_to_close) @ ₹50 (profit)
        # Buyback cost = 1 * 65 * 50 = ₹3,250
        # Original premium for 1 lot = 1 * 65 * 120 = ₹7,800
        # Realized P&L = 7,800 - 3,250 = +₹4,550
        # Margin released = 598,000 * (1/2) = ₹2,99,000
        order_btc = place_derivative_order(
            db=db, wallet=in_wallet, contract=contract_short, side="buy", action="buy_to_close",
            quantity=1.0, fill_price=50.0,
        )
        assert order_btc.status == "filled"

        db.refresh(in_wallet)
        assert in_wallet.margin_used == 299000.0  # exactly 50% margin released

        txn_btc = db.query(DerivativeTransaction).filter(DerivativeTransaction.order_id == order_btc.id).first()
        assert txn_btc.realized_pnl == 4550.0
        assert txn_btc.amount == -3250.0

        pos_short = db.query(DerivativePosition).filter(DerivativePosition.contract_id == contract_short.id).first()
        assert pos_short.quantity == 1.0
        assert pos_short.margin_locked == 299000.0

        # Cover final 1 lot @ ₹150 (loss)
        # Buyback cost = 1 * 65 * 150 = ₹9,750
        # Realized P&L = 7,800 - 9,750 = -₹1,950
        # Remaining margin released = ₹2,99,000
        order_btc2 = place_derivative_order(
            db=db, wallet=in_wallet, contract=contract_short, side="buy", action="buy_to_close",
            quantity=1.0, fill_price=150.0,
        )
        assert order_btc2.status == "filled"

        db.refresh(in_wallet)
        assert in_wallet.margin_used == 0.0  # 100% margin released

        pos_short_after = db.query(DerivativePosition).filter(DerivativePosition.contract_id == contract_short.id).first()
        assert pos_short_after is None

        print("[PASS] test_option_exits_and_margin_release")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# TEST 5: Futures Trading (buy_to_open & sell_to_open)
# ══════════════════════════════════════════════════════════════════════════════

def test_futures_trading_margin_and_closure():
    """
    Test Futures trading:
    - 12% initial margin locked from first trade (both long and short).
    - 0 cash deducted upfront on order entry (notional is financed via margin).
    - Rejection if wallet buying power < 12% initial margin.
    - sell_to_close and buy_to_close releases locked margin and credits/debits realized P&L.
    """
    db, _, us_wallet = setup_test_db()
    try:
        # Continuous US S&P 500 E-mini futures (ES=F, lot size = 1)
        contract = get_or_create_contract(
            db=db,
            market="US",
            underlying="ES",
            instrument_type="future",
            symbol="ES=F",
            lot_size=1,
        )

        initial_cash = us_wallet.current_cash_balance  # $50,000

        # 1. Long 2 contracts of ES=F @ $5,000
        # Notional = 2 * 1 * $5,000 = $10,000
        # 12% initial margin = 0.12 * 10,000 = $1,200
        order_long = place_derivative_order(
            db=db,
            wallet=us_wallet,
            contract=contract,
            side="buy",
            action="buy_to_open",
            quantity=2.0,
            fill_price=5000.0,
        )
        assert order_long.status == "filled"
        assert order_long.margin_required == 1200.0

        db.refresh(us_wallet)
        # Cash balance MUST NOT BE DEBITED for the $10,000 notional!
        assert us_wallet.current_cash_balance == initial_cash
        # Margin used must be $1,200
        assert us_wallet.margin_used == 1200.0
        # Available buying power = $50,000 - $1,200 = $48,800
        assert us_wallet.available_buying_power == 48800.0

        pos = db.query(DerivativePosition).filter(DerivativePosition.contract_id == contract.id).first()
        assert pos is not None
        assert pos.side == "long"
        assert pos.quantity == 2.0
        assert pos.entry_price == 5000.0
        assert pos.last_mtm_price == 5000.0
        assert pos.margin_locked == 1200.0

        # 2. Close 1 contract (sell_to_close) @ $5,100 (+100 gain)
        # Realized P&L = (5,100 - 5,000) * 1 * 1 = +$100
        # Margin release = 1,200 * (1/2) = $600
        order_close = place_derivative_order(
            db=db,
            wallet=us_wallet,
            contract=contract,
            side="sell",
            action="sell_to_close",
            quantity=1.0,
            fill_price=5100.0,
        )
        assert order_close.status == "filled"

        db.refresh(us_wallet)
        # Cash balance adjusted by +$100: $50,100
        assert us_wallet.current_cash_balance == 50100.0
        # Margin used reduced to $600
        assert us_wallet.margin_used == 600.0

        txn_close = db.query(DerivativeTransaction).filter(DerivativeTransaction.order_id == order_close.id).first()
        assert txn_close.realized_pnl == 100.0
        assert txn_close.amount == 100.0

        # Close remaining 1 contract @ $4,950 (-$50 loss from entry)
        order_close2 = place_derivative_order(
            db=db,
            wallet=us_wallet,
            contract=contract,
            side="sell",
            action="sell_to_close",
            quantity=1.0,
            fill_price=4950.0,
        )
        assert order_close2.status == "filled"

        db.refresh(us_wallet)
        # Cash balance: 50,100 - 50 = $50,050
        assert us_wallet.current_cash_balance == 50050.0
        # Margin used back to 0
        assert us_wallet.margin_used == 0.0

        pos_after = db.query(DerivativePosition).filter(DerivativePosition.contract_id == contract.id).first()
        assert pos_after is None

        # 3. Short futures test (sell_to_open)
        # Short 1 contract of ES=F @ $5,000
        # Margin required: 12% of 5,000 = $600
        order_short = place_derivative_order(
            db=db,
            wallet=us_wallet,
            contract=contract,
            side="sell",
            action="sell_to_open",
            quantity=1.0,
            fill_price=5000.0,
        )
        assert order_short.status == "filled"

        db.refresh(us_wallet)
        assert us_wallet.margin_used == 600.0

        pos_short = db.query(DerivativePosition).filter(DerivativePosition.contract_id == contract.id).first()
        assert pos_short.side == "short"

        # Buy to close @ $4,900 (gain of $100 for short)
        order_btc = place_derivative_order(
            db=db,
            wallet=us_wallet,
            contract=contract,
            side="buy",
            action="buy_to_close",
            quantity=1.0,
            fill_price=4900.0,
        )
        assert order_btc.status == "filled"

        db.refresh(us_wallet)
        assert us_wallet.current_cash_balance == 50050.0 + 100.0  # $50,150
        assert us_wallet.margin_used == 0.0

        print("[PASS] test_futures_trading_margin_and_closure")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# TEST 6: Futures Daily Mark-to-Market (MTM) Settlement
# ══════════════════════════════════════════════════════════════════════════════

def test_futures_daily_mark_to_market_settlement():
    """
    Test daily cash MTM settlement:
    - Positions marked on previous days are adjusted against today's mark price.
    - Cash balance is directly credited/debited.
    - transaction_type='mtm_settlement'.
    - Position remains open and locked margin remains intact.
    - last_mtm_price and last_mtm_date update to today.
    """
    db, _, us_wallet = setup_test_db()
    try:
        contract = get_or_create_contract(
            db=db,
            market="US",
            underlying="ES",
            instrument_type="future",
            symbol="ES=F",
            lot_size=1,
        )

        day1 = date(2026, 9, 20)
        day2 = date(2026, 9, 21)

        # Open Long 2 contracts @ $5,000 on Day 1
        place_derivative_order(
            db=db,
            wallet=us_wallet,
            contract=contract,
            side="buy",
            action="buy_to_open",
            quantity=2.0,
            fill_price=5000.0,
            settlement_date=day1,
        )

        pos = db.query(DerivativePosition).filter(DerivativePosition.contract_id == contract.id).first()
        assert pos.last_mtm_price == 5000.0
        assert pos.last_mtm_date == day1
        assert pos.margin_locked == 1200.0

        # Day 2: Mark price rises to $5,050 (+$50 gain per contract * 2 contracts = +$100)
        mtm_txns = evaluate_daily_futures_mtm(
            db=db,
            mark_prices={"ES=F": 5050.0},
            settlement_date=day2,
        )
        assert len(mtm_txns) == 1
        txn = mtm_txns[0]
        assert txn.transaction_type == "mtm_settlement"
        assert txn.amount == 100.0
        assert txn.realized_pnl == 100.0

        db.refresh(us_wallet)
        # Cash credited by $100: $50,000 + $100 = $50,100
        assert us_wallet.current_cash_balance == 50100.0
        # Margin used still locked!
        assert us_wallet.margin_used == 1200.0

        db.refresh(pos)
        # Position is still open!
        assert pos.quantity == 2.0
        assert pos.last_mtm_price == 5050.0
        assert pos.last_mtm_date == day2

        # Subsequent call on same day should skip (no duplicate settlement)
        mtm_txns_dupe = evaluate_daily_futures_mtm(
            db=db,
            mark_prices={"ES=F": 5050.0},
            settlement_date=day2,
        )
        assert len(mtm_txns_dupe) == 0

        # Day 3: Mark price falls to $4,980 (-$70 loss per contract * 2 contracts = -$140)
        day3 = date(2026, 9, 22)
        mtm_txns_day3 = evaluate_daily_futures_mtm(
            db=db,
            mark_prices={"ES=F": 4980.0},
            settlement_date=day3,
        )
        assert len(mtm_txns_day3) == 1
        assert mtm_txns_day3[0].amount == -140.0

        db.refresh(us_wallet)
        assert us_wallet.current_cash_balance == 50100.0 - 140.0  # $49,960
        assert us_wallet.margin_used == 1200.0

        db.refresh(pos)
        assert pos.last_mtm_price == 4980.0
        assert pos.last_mtm_date == day3

        print("[PASS] test_futures_daily_mark_to_market_settlement")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# TEST 7: Expiry Cash Settlement
# ══════════════════════════════════════════════════════════════════════════════

def test_derivatives_expiry_cash_settlement():
    """
    Test expiry settlement:
    - ITM Call: S > K -> pays intrinsic cash S - K.
    - OTM Call: S <= K -> expires worthless (0 payout, full premium lost).
    - ITM Put: K > S -> pays intrinsic cash K - S.
    - Short written options: debits payout, releases full locked margin.
    - Indian index futures: final MTM against underlying index price, releases locked margin.
    """
    db, in_wallet, _ = setup_test_db()
    try:
        exp_date = date(2026, 9, 29)

        # 1. Long ITM Call: Strike 23,000, bought @ ₹150 premium (65 shares)
        # Cost = 150 * 65 = ₹9,750
        call_itm = get_or_create_contract(
            db=db, market="IN", underlying="NIFTY", instrument_type="option",
            option_type="call", strike_price=23000.0, expiry_date=exp_date, lot_size=65,
        )
        place_derivative_order(
            db=db, wallet=in_wallet, contract=call_itm, side="buy", action="buy_to_open",
            quantity=1.0, fill_price=150.0,
        )

        # 2. Long OTM Call: Strike 23,500, bought @ ₹50 premium (65 shares)
        # Cost = 50 * 65 = ₹3,250
        call_otm = get_or_create_contract(
            db=db, market="IN", underlying="NIFTY", instrument_type="option",
            option_type="call", strike_price=23500.0, expiry_date=exp_date, lot_size=65,
        )
        place_derivative_order(
            db=db, wallet=in_wallet, contract=call_otm, side="buy", action="buy_to_open",
            quantity=1.0, fill_price=50.0,
        )

        # 3. Short ITM Put: Strike 23,300, written @ ₹80 premium (65 shares)
        # Received ₹5,200. Margin locked = 20% of 23,300 * 65 = ₹3,02,900
        put_itm_short = get_or_create_contract(
            db=db, market="IN", underlying="NIFTY", instrument_type="option",
            option_type="put", strike_price=23300.0, expiry_date=exp_date, lot_size=65,
        )
        place_derivative_order(
            db=db, wallet=in_wallet, contract=put_itm_short, side="sell", action="sell_to_open",
            quantity=1.0, fill_price=80.0, underlying_price=23300.0,
        )

        # 4. Long Indian Index Futures: NIFTY 29-Sep FUT, bought @ 23,100
        # Margin locked = 12% of 23,100 * 65 = ₹1,80,180
        fut_contract = get_or_create_contract(
            db=db, market="IN", underlying="NIFTY", instrument_type="future",
            expiry_date=exp_date, lot_size=65,
        )
        place_derivative_order(
            db=db, wallet=in_wallet, contract=fut_contract, side="buy", action="buy_to_open",
            quantity=1.0, fill_price=23100.0,
        )

        db.refresh(in_wallet)
        cash_before_settle = in_wallet.current_cash_balance
        margin_before_settle = in_wallet.margin_used

        # Settle expiry on 2026-09-29 when NIFTY underlying closes @ 23,200
        settle_txns = evaluate_derivatives_expiry_settlement(
            db=db,
            underlying_prices={"NIFTY": 23200.0},
            settlement_date=exp_date,
        )
        assert len(settle_txns) == 4

        # Verify Call ITM: Intrinsic = 23,200 - 23,000 = 200. Payout = 200 * 65 = ₹13,000
        # P&L = 13,000 - 9,750 = +₹3,250
        txn_call_itm = next(t for t in settle_txns if t.transaction_type == "expiry_settlement" and t.amount == 13000.0)
        assert txn_call_itm.amount == 13000.0
        assert txn_call_itm.realized_pnl == 3250.0

        # Verify Call OTM: Intrinsic = max(0, 23,200 - 23,500) = 0. Payout = 0
        # P&L = 0 - 3,250 = -₹3,250
        txn_call_otm = next(t for t in settle_txns if t.amount == 0.0 and t.realized_pnl == -3250.0)
        assert txn_call_otm.amount == 0.0

        # Verify Short Put ITM: Intrinsic = 23,300 - 23,200 = 100. Writer pays 100 * 65 = -₹6,500
        # P&L = 5,200 - 6,500 = -₹1,300
        txn_put_short = next(t for t in settle_txns if t.amount == -6500.0)
        assert txn_put_short.realized_pnl == -1300.0

        # Verify Futures Settlement: Final MTM = (23,200 - 23,100) * 65 = +₹6,500
        txn_fut = next(t for t in settle_txns if t.amount == 6500.0 and t.realized_pnl == 6500.0)
        assert txn_fut.realized_pnl == 6500.0

        db.refresh(in_wallet)
        # All positions expired -> margin_used must be 0!
        assert in_wallet.margin_used == 0.0

        # All positions should be deleted from active derivative positions
        open_pos_count = db.query(DerivativePosition).filter(DerivativePosition.wallet_id == in_wallet.id).count()
        assert open_pos_count == 0

        print("[PASS] test_derivatives_expiry_cash_settlement")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# TEST 8: Derivative Margin Call Liquidation
# ══════════════════════════════════════════════════════════════════════════════

def test_derivative_margin_call_liquidation():
    """
    Test margin call liquidation:
    - Naked written option: underlying moves sharply against writer, breaching 15% maintenance requirement.
      Auto-liquidates via buy_to_close (triggered_by="derivative_margin_call") and releases locked margin.
    - Futures position: mark price moves sharply against position, breaching 10% maintenance requirement.
      Auto-liquidates via close order and releases locked margin.
    """
    db, in_wallet, us_wallet = setup_test_db()
    try:
        # 1. Naked Call Option on NIFTY:
        # Strike 23,000, written @ ₹100 premium when NIFTY was 23,000
        # Total units = 65
        # Initial margin = 20% of 23,000 * 65 = ₹2,99,000
        call_contract = get_or_create_contract(
            db=db, market="IN", underlying="NIFTY", instrument_type="option",
            option_type="call", strike_price=23000.0, expiry_date=date(2026, 9, 29), lot_size=65,
        )
        place_derivative_order(
            db=db, wallet=in_wallet, contract=call_contract, side="sell", action="sell_to_open",
            quantity=1.0, fill_price=100.0, underlying_price=23000.0,
        )

        pos_call = db.query(DerivativePosition).filter(DerivativePosition.contract_id == call_contract.id).first()
        assert pos_call.margin_locked == 299000.0

        # Now NIFTY explodes to 24,000 and Call premium jumps to ₹1,100
        # Unrealized P&L = (100 - 1,100) * 65 = -₹65,000
        # Effective margin = 299,000 - 65,000 = ₹2,34,000
        # Maintenance requirement = 15% of 24,000 * 65 = ₹2,34,000
        # If NIFTY jumps to 24,500 and Call premium to ₹1,600:
        # Unrealized P&L = (100 - 1,600) * 65 = -₹97,500
        # Effective margin = 299,000 - 97,500 = ₹2,01,500
        # Maintenance requirement = 15% of 24,500 * 65 = ₹2,38,875
        # Ratio = 201,500 / 238,875 = 0.843 < 1.0 -> BREACH!
        quotes_in = {
            call_contract.symbol: 1600.0,
            "NIFTY": 24500.0,
        }
        liq_orders = evaluate_derivative_margin_calls(db=db, current_quotes=quotes_in)
        assert len(liq_orders) == 1
        liq_order = liq_orders[0]
        assert liq_order.status == "filled"
        assert liq_order.action == "buy_to_close"
        assert liq_order.triggered_by == "derivative_margin_call"

        db.refresh(in_wallet)
        # Locked margin released!
        assert in_wallet.margin_used == 0.0

        pos_call_after = db.query(DerivativePosition).filter(DerivativePosition.contract_id == call_contract.id).first()
        assert pos_call_after is None

        # 2. Long Futures on ES=F:
        # Entered Long @ $5,000. 12% initial margin = $600.
        fut_contract = get_or_create_contract(
            db=db, market="US", underlying="ES", instrument_type="future",
            symbol="ES=F", lot_size=1,
        )
        place_derivative_order(
            db=db, wallet=us_wallet, contract=fut_contract, side="buy", action="buy_to_open",
            quantity=1.0, fill_price=5000.0,
        )

        db.refresh(us_wallet)
        assert us_wallet.margin_used == 600.0

        # Now ES=F plunges to $4,800
        # Unrealized P&L = 4,800 - 5,000 = -$200
        # Effective margin = $600 - $200 = $400
        # Maintenance requirement = 10% of $4,800 = $480
        # Ratio = $400 / $480 = 0.833 < 1.0 -> BREACH!
        quotes_us = {
            "ES=F": 4800.0,
        }
        fut_liq_orders = evaluate_derivative_margin_calls(db=db, current_quotes=quotes_us)
        assert len(fut_liq_orders) == 1
        fut_liq = fut_liq_orders[0]
        assert fut_liq.status == "filled"
        assert fut_liq.action == "sell_to_close"
        assert fut_liq.triggered_by == "derivative_margin_call"

        db.refresh(us_wallet)
        assert us_wallet.margin_used == 0.0

        pos_fut_after = db.query(DerivativePosition).filter(DerivativePosition.contract_id == fut_contract.id).first()
        assert pos_fut_after is None

        print("[PASS] test_derivative_margin_call_liquidation")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# TEST 9: Portfolio Derivatives Summary
# ══════════════════════════════════════════════════════════════════════════════

def test_get_derivative_positions_summary():
    """
    Test portfolio summary calculation:
    - Verifies current mark price, notional value, market value, unrealized P&L,
      maintenance margin requirement, and margin level %.
    """
    db, in_wallet, _ = setup_test_db()
    try:
        contract = get_or_create_contract(
            db=db, market="IN", underlying="NIFTY", instrument_type="option",
            option_type="call", strike_price=23150.0, expiry_date=date(2026, 9, 29), lot_size=65,
        )
        # Buy 1 lot @ ₹100
        place_derivative_order(
            db=db, wallet=in_wallet, contract=contract, side="buy", action="buy_to_open",
            quantity=1.0, fill_price=100.0,
        )

        mock_quote = PriceQuote(
            symbol=contract.symbol,
            display_name=contract.symbol,
            exchange="NSE",
            currency="INR",
            price=125.0,  # +₹25 gain
            prev_close=100.0,
            change=25.0,
            change_pct=25.0,
            day_high=130.0,
            day_low=95.0,
            volume=50000,
            market_open=True,
            timestamp=1234567890,
        )

        summary = get_derivative_positions_summary(
            db=db,
            wallet_id=in_wallet.id,
            live_quotes={contract.symbol: mock_quote},
        )
        assert len(summary) == 1
        item = summary[0]
        assert item["current_price"] == 125.0
        assert item["market_value"] == 125.0 * 65  # ₹8,125
        assert item["unrealized_pnl"] == 25.0 * 65  # +₹1,625
        assert item["unrealized_pnl_pct"] == 25.0

        print("[PASS] test_get_derivative_positions_summary")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# TEST 10: Naked Option Margin Calculation Strictly Uses SPOT, Not Strike
# ══════════════════════════════════════════════════════════════════════════════

def test_naked_option_margin_uses_spot_price_not_strike():
    """
    Confirms explicitly that naked option margin_locked (sell_to_open) uses the
    CURRENT UNDERLYING SPOT PRICE, NEVER the strike price:
    - Deep OTM Call (strike ₹26,000 >> spot ₹23,000):
      Margin = 20% of (23,000 * 65) = ₹2,99,000 (NOT 20% of 26,000 * 65 = ₹3,38,000)
    - Deep OTM Put (strike ₹19,000 << spot ₹23,000):
      Margin = 20% of (23,000 * 65) = ₹2,99,000 (NOT 20% of 19,000 * 65 = ₹2,47,000)
    - Auto-resolution via resolve_underlying_spot_price when underlying_price is omitted.
    """
    db, in_wallet, _ = setup_test_db()
    try:
        spot_price = 23000.0

        # 1. Deep OTM Call: Strike 26,000 (+3,000 above spot)
        contract_otm_call = get_or_create_contract(
            db=db,
            market="IN",
            underlying="NIFTY",
            instrument_type="option",
            option_type="call",
            strike_price=26000.0,
            expiry_date=date(2026, 9, 29),
            lot_size=65,
        )

        order_call = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=contract_otm_call,
            side="sell",
            action="sell_to_open",
            quantity=1.0,
            fill_price=15.0,
            underlying_price=spot_price,
        )
        assert order_call.status == "filled"
        # 20% of (23,000 * 65) = ₹2,99,000.00
        # If strike (26,000) had been used, it would be ₹3,38,000.00
        assert order_call.margin_required == 299000.0
        assert order_call.margin_required != 338000.0

        db.refresh(in_wallet)
        assert in_wallet.margin_used == 299000.0

        pos_call = db.query(DerivativePosition).filter(DerivativePosition.contract_id == contract_otm_call.id).first()
        assert pos_call.margin_locked == 299000.0

        # 2. Deep OTM Put: Strike 19,000 (-4,000 below spot)
        contract_otm_put = get_or_create_contract(
            db=db,
            market="IN",
            underlying="NIFTY",
            instrument_type="option",
            option_type="put",
            strike_price=19000.0,
            expiry_date=date(2026, 9, 29),
            lot_size=65,
        )

        order_put = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=contract_otm_put,
            side="sell",
            action="sell_to_open",
            quantity=1.0,
            fill_price=10.0,
            underlying_price=spot_price,
        )
        assert order_put.status == "filled"
        # 20% of (23,000 * 65) = ₹2,99,000.00
        # If strike (19,000) had been used, it would be ₹2,47,000.00
        assert order_put.margin_required == 299000.0
        assert order_put.margin_required != 247000.0

        db.refresh(in_wallet)
        # Total pooled margin = 299,000 + 299,000 = 598,000.00
        assert in_wallet.margin_used == 598000.0

        pos_put = db.query(DerivativePosition).filter(DerivativePosition.contract_id == contract_otm_put.id).first()
        assert pos_put.margin_locked == 299000.0

        # 3. Test auto-resolution via resolve_underlying_spot_price when underlying_price is omitted
        contract_otm_call2 = get_or_create_contract(
            db=db,
            market="IN",
            underlying="NIFTY",
            instrument_type="option",
            option_type="call",
            strike_price=27000.0,  # +4,000 above spot
            expiry_date=date(2026, 9, 29),
            lot_size=65,
        )
        mock_spot_quote = PriceQuote(
            symbol="^NSEI",
            display_name="NIFTY 50",
            exchange="NSE",
            currency="INR",
            price=23000.0,
            prev_close=22950.0,
            change=50.0,
            change_pct=0.22,
            day_high=23050.0,
            day_low=22900.0,
            volume=1000000,
            market_open=True,
            timestamp="2026-09-26T10:00:00Z",
        )
        with patch("services.derivatives_engine.get_quote", return_value=mock_spot_quote):
            order_auto = place_derivative_order(
                db=db,
                wallet=in_wallet,
                contract=contract_otm_call2,
                side="sell",
                action="sell_to_open",
                quantity=1.0,
                fill_price=8.0,
                # underlying_price omitted! Engine must auto-resolve spot price
            )
            assert order_auto.status == "filled"
            assert order_auto.margin_required == 299000.0  # based on 23,000 spot, NOT 27,000 strike!
            assert order_auto.margin_required != round(0.20 * 27000.0 * 65, 2)  # NOT 351,000

        print("[PASS] test_naked_option_margin_uses_spot_price_not_strike")
    finally:
        db.close()


def test_derivative_market_hours_enforcement():
    """
    Verifies market-hours blocking across all derivative instrument types:
    1. Indian F&O (NSE):
       - Wednesday 10:30 IST -> open -> order fills.
       - Wednesday 16:00 IST -> closed -> order rejected with "market_closed".
       - Saturday 12:00 IST  -> closed -> order rejected with "market_closed".
    2. US Options (NASDAQ/NYSE):
       - Wednesday 11:00 ET  -> open -> order fills.
       - Wednesday 18:00 ET  -> closed -> order rejected with "market_closed".
       - Sunday 12:00 ET     -> closed -> order rejected with "market_closed".
    3. US Continuous Futures (CME Globex):
       - Wednesday 02:00 CT  -> open -> order fills.
       - Wednesday 16:30 CT (daily halt) -> closed -> order rejected with "market_closed".
       - Saturday 12:00 CT (weekend)     -> closed -> order rejected with "market_closed".
       - Sunday 18:00 CT (reopens)       -> open -> order fills.
    """
    from zoneinfo import ZoneInfo
    db, in_wallet, us_wallet = setup_test_db()
    try:
        # 1. Indian F&O Contract
        in_contract = get_or_create_contract(
            db=db,
            market="IN",
            underlying="NIFTY",
            instrument_type="option",
            option_type="call",
            strike_price=23000.0,
            expiry_date=date(2026, 9, 29),
            lot_size=65,
        )

        # 1a. Wednesday 10:30 IST (during session)
        dt_in_open = datetime(2026, 9, 23, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
        order_in_open = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=in_contract,
            side="buy",
            action="buy_to_open",
            quantity=1.0,
            fill_price=100.0,
            execution_time=dt_in_open,
        )
        assert order_in_open.status == "filled", f"Expected filled, got {order_in_open.reject_reason}"

        # 1b. Wednesday 16:00 IST (after NSE close at 15:30)
        dt_in_afterhours = datetime(2026, 9, 23, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        order_in_closed = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=in_contract,
            side="buy",
            action="buy_to_open",
            quantity=1.0,
            fill_price=100.0,
            execution_time=dt_in_afterhours,
        )
        assert order_in_closed.status == "rejected"
        assert order_in_closed.reject_reason == "market_closed"

        # 1c. Saturday 12:00 IST (weekend)
        dt_in_weekend = datetime(2026, 9, 26, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        order_in_sat = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=in_contract,
            side="buy",
            action="buy_to_open",
            quantity=1.0,
            fill_price=100.0,
            execution_time=dt_in_weekend,
        )
        assert order_in_sat.status == "rejected"
        assert order_in_sat.reject_reason == "market_closed"

        # 2. US Options Contract
        us_opt = get_or_create_contract(
            db=db,
            market="US",
            underlying="AAPL",
            instrument_type="option",
            option_type="call",
            strike_price=220.0,
            expiry_date=date(2026, 10, 16),
            lot_size=100,
        )

        # 2a. Wednesday 11:00 ET (during regular session)
        dt_us_open = datetime(2026, 9, 23, 11, 0, tzinfo=ZoneInfo("America/New_York"))
        order_us_open = place_derivative_order(
            db=db,
            wallet=us_wallet,
            contract=us_opt,
            side="buy",
            action="buy_to_open",
            quantity=1.0,
            fill_price=5.0,
            execution_time=dt_us_open,
        )
        assert order_us_open.status == "filled"

        # 2b. Wednesday 18:00 ET (after regular close at 16:00 ET)
        dt_us_afterhours = datetime(2026, 9, 23, 18, 0, tzinfo=ZoneInfo("America/New_York"))
        order_us_closed = place_derivative_order(
            db=db,
            wallet=us_wallet,
            contract=us_opt,
            side="buy",
            action="buy_to_open",
            quantity=1.0,
            fill_price=5.0,
            execution_time=dt_us_afterhours,
        )
        assert order_us_closed.status == "rejected"
        assert order_us_closed.reject_reason == "market_closed"

        # 2c. Sunday 12:00 ET (weekend)
        dt_us_weekend = datetime(2026, 9, 27, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        order_us_sun = place_derivative_order(
            db=db,
            wallet=us_wallet,
            contract=us_opt,
            side="buy",
            action="buy_to_open",
            quantity=1.0,
            fill_price=5.0,
            execution_time=dt_us_weekend,
        )
        assert order_us_sun.status == "rejected"
        assert order_us_sun.reject_reason == "market_closed"

        # 3. US Continuous Futures (CME Globex: ES=F)
        us_fut = get_or_create_contract(
            db=db,
            market="US",
            underlying="ES",
            instrument_type="future",
            symbol="ES=F",
            lot_size=50,
        )

        # 3a. Wednesday 02:00 CT (overnight Globex trading)
        dt_cme_overnight = datetime(2026, 9, 23, 2, 0, tzinfo=ZoneInfo("America/Chicago"))
        order_cme_open = place_derivative_order(
            db=db,
            wallet=us_wallet,
            contract=us_fut,
            side="buy",
            action="buy_to_open",
            quantity=1.0,
            fill_price=5500.0,
            execution_time=dt_cme_overnight,
        )
        assert order_cme_open.status == "filled"

        # 3b. Wednesday 16:30 CT (daily maintenance halt: 16:00-17:00 CT)
        dt_cme_halt = datetime(2026, 9, 23, 16, 30, tzinfo=ZoneInfo("America/Chicago"))
        order_cme_halt = place_derivative_order(
            db=db,
            wallet=us_wallet,
            contract=us_fut,
            side="buy",
            action="buy_to_open",
            quantity=1.0,
            fill_price=5500.0,
            execution_time=dt_cme_halt,
        )
        assert order_cme_halt.status == "rejected"
        assert order_cme_halt.reject_reason == "market_closed"

        # 3c. Saturday 12:00 CT (weekend shutdown)
        dt_cme_sat = datetime(2026, 9, 26, 12, 0, tzinfo=ZoneInfo("America/Chicago"))
        order_cme_sat = place_derivative_order(
            db=db,
            wallet=us_wallet,
            contract=us_fut,
            side="buy",
            action="buy_to_open",
            quantity=1.0,
            fill_price=5500.0,
            execution_time=dt_cme_sat,
        )
        assert order_cme_sat.status == "rejected"
        assert order_cme_sat.reject_reason == "market_closed"

        # 3d. Sunday 18:00 CT (Globex Sunday reopen at 17:00 CT)
        us_wallet.margin_used = 0.0
        db.commit()
        dt_cme_sun_open = datetime(2026, 9, 27, 18, 0, tzinfo=ZoneInfo("America/Chicago"))
        order_cme_sun = place_derivative_order(
            db=db,
            wallet=us_wallet,
            contract=us_fut,
            side="buy",
            action="buy_to_open",
            quantity=1.0,
            fill_price=5500.0,
            execution_time=dt_cme_sun_open,
        )
        assert order_cme_sun.status == "filled"

        print("[PASS] test_derivative_market_hours_enforcement")
    finally:
        db.close()


if __name__ == "__main__":
    print("Running test_derivatives_engine.py unit test suite...")
    with patch("services.derivatives_engine.is_derivative_market_open", return_value=True):
        test_option_buying_upfront_premium_and_no_margin()
        test_covered_call_writing_zero_margin()
        test_naked_option_writing_requires_20_pct_initial_margin()
        test_option_exits_and_margin_release()
        test_futures_trading_margin_and_closure()
        test_futures_daily_mark_to_market_settlement()
        test_derivatives_expiry_cash_settlement()
        test_derivative_margin_call_liquidation()
        test_get_derivative_positions_summary()
        test_naked_option_margin_uses_spot_price_not_strike()
    test_derivative_market_hours_enforcement()
    print("\nALL 11 DERIVATIVES ENGINE TESTS PASSED!")
