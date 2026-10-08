"""
test_derivatives_live_price_sync.py — Verification Suite for Derivatives Live Price Resolution.

Verifies:
1. Long NIFTY Futures position (User Bug Reproduction):
   - Entry: 22,492.10, lot=65.
   - Live LTP: 22,529.80 via nse_client.get_futures.
   - Verified: current_price=22,529.80, unrealized_pnl=+2,450.50 (NOT 0.00).
   - Verified: MTM settlement credits +2,450.50 to wallet cash.
2. Short Futures Position (US ES=F continuous futures):
   - Price movement reflects in unrealized P&L, margin level, and margin call liquidation.
3. Long Options (both Indian NSE and US yfinance):
   - Price movement in Option Chain reflects directly in position LTP & P&L.
4. Price Unavailable / Stale Price Safeguards:
   - NEVER falls back silently to entry_price.
   - Returns price_available=False, current_price=None.
   - Daily MTM settlement and liquidation evaluation cleanly skip without corrupting cash or triggering false liquidations.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from database import Base
from models.orm import (
    Wallet,
    DerivativeContract,
    DerivativePosition,
    DerivativeOrder,
    DerivativeTransaction,
)
from services.derivatives_engine import (
    get_or_create_contract,
    place_derivative_order,
    get_derivative_positions_summary,
    evaluate_daily_futures_mtm,
    evaluate_derivative_margin_calls,
)
from services.derivatives_feed import (
    resolve_derivative_contract_quote,
    DerivativeQuoteResult,
)
from services.price_feed import PriceQuote


def setup_test_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    in_wallet = Wallet(
        market="IN",
        currency="INR",
        starting_balance=500000.0,
        current_cash_balance=500000.0,
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
    db.refresh(in_wallet)
    db.refresh(us_wallet)
    return db, in_wallet, us_wallet


# ── TEST 1: User Reported Bug - NIFTY Future Entry 22,492.10 vs Live 22,529.80 ──

def test_nifty_future_live_price_and_pnl_sync():
    print("\n--- TEST 1: NIFTY Future Entry 22,492.10 vs Live 22,529.80 (User Bug Fix) ---")
    db, in_wallet, _ = setup_test_db()

    # 1. Create NIFTY Future contract expiring 27-Oct-2026, lot size = 65
    contract = get_or_create_contract(
        db=db,
        market="IN",
        underlying="NIFTY",
        instrument_type="future",
        expiry_date=date(2026, 10, 27),
        lot_size=65,
        symbol="NIFTY-27OCT26-FUT",
    )

    # 2. Buy 1 lot @ 22,492.10 (Margin locked = 12% of 22492.10 * 65 = 175,438.38)
    order = place_derivative_order(
        db=db,
        wallet=in_wallet,
        contract=contract,
        side="buy",
        action="buy_to_open",
        quantity=1,
        fill_price=22492.10,
        settlement_date=date(2026, 10, 26),
        check_market_hours=False,
    )
    assert order.status == "filled"
    db.refresh(in_wallet)
    assert in_wallet.margin_used > 0

    # 3. Mock live Futures Market feed returning 22,529.80 for the 27-Oct-2026 contract
    mock_futures_feed = {
        "symbol": "NIFTY",
        "market": "IN",
        "currency": "INR",
        "underlying_value": 22500.0,
        "contracts": [
            {
                "contract": "NIFTY-27OCT26-FUT",
                "expiry": "27-Oct-2026",
                "ltp": 22529.80,
                "open": 22480.0,
                "high": 22550.0,
                "low": 22450.0,
                "underlying_value": 22500.0,
            }
        ],
    }

    with patch("services.derivatives_feed.nse_client.get_futures", return_value=mock_futures_feed):
        # A. Verify shared price resolution function directly
        quote_res = resolve_derivative_contract_quote(contract)
        assert quote_res.price_available is True
        assert quote_res.price == 22529.80

        # B. Verify positions summary (used by GET /api/derivatives/IN/positions)
        summaries = get_derivative_positions_summary(db=db, wallet_id=in_wallet.id)
        assert len(summaries) == 1
        summary = summaries[0]

        print(f"Position: entry={summary['position'].entry_price}, current_price={summary['current_price']}")
        print(f"Unrealized P&L: {summary['unrealized_pnl']} (expected +2,450.50)")

        # Exact user expected check:
        # Expected unrealized P&L = (22,529.80 - 22,492.10) * 65 = 37.70 * 65 = +2,450.50
        assert summary["price_available"] is True
        assert summary["current_price"] == 22529.80
        assert summary["unrealized_pnl"] == 2450.50
        assert summary["unrealized_pnl_pct"] == round((2450.50 / (22492.10 * 65)) * 100, 2)

        # C. Verify daily MTM settlement uses the SAME live price
        initial_cash = in_wallet.current_cash_balance
        txns = evaluate_daily_futures_mtm(db=db, settlement_date=date(2026, 10, 27))
        assert len(txns) == 1
        txn = txns[0]

        assert txn.amount == 2450.50
        assert txn.price == 22529.80
        db.refresh(in_wallet)
        assert in_wallet.current_cash_balance == round(initial_cash + 2450.50, 2)
        print(f"MTM Settlement: cash credited={txn.amount}, new wallet cash={in_wallet.current_cash_balance}")

    print("[PASS] TEST 1 PASSED: NIFTY Future correctly resolves live price 22,529.80 and +2,450.50 P&L.")


# ── TEST 2: US Continuous Futures (ES=F) Short, Margin Level & Liquidation ─────

def test_us_continuous_futures_short_and_liquidation():
    print("\n--- TEST 2: US Continuous Futures (ES=F) Short, Margin Level & Liquidation ---")
    db, _, us_wallet = setup_test_db()

    contract = get_or_create_contract(
        db=db,
        market="US",
        underlying="ES",
        instrument_type="future",
        lot_size=50,
        symbol="ES=F",
    )

    # Short 1 lot of ES=F @ $5,000 (Lot size = 50 -> Notional = $250,000, 12% margin = $30,000)
    order = place_derivative_order(
        db=db,
        wallet=us_wallet,
        contract=contract,
        side="sell",
        action="sell_to_open",
        quantity=1,
        fill_price=5000.0,
        check_market_hours=False,
    )
    assert order.status == "filled"
    db.refresh(us_wallet)
    assert us_wallet.margin_used == 30000.0

    # 1. Price drops to $4,950.00 (favorable for short: gain of $50 * 50 = +$2,500)
    mock_quote_gain = PriceQuote(
        symbol="ES=F", display_name="ES=F", exchange="CME", currency="USD",
        price=4950.0, prev_close=5000.0, change=-50.0, change_pct=-1.0,
        day_high=5000.0, day_low=4950.0, volume=50000, market_open=True,
        timestamp=datetime.now(timezone.utc).isoformat(), error=None,
    )

    with patch("services.derivatives_feed.get_quote", return_value=mock_quote_gain):
        summaries = get_derivative_positions_summary(db=db, wallet_id=us_wallet.id)
        assert len(summaries) == 1
        assert summaries[0]["current_price"] == 4950.0
        assert summaries[0]["unrealized_pnl"] == 2500.0
        print(f"Short ES=F Gain: current_price={summaries[0]['current_price']}, PnL=+${summaries[0]['unrealized_pnl']}")

    # 2. Price surges against short to $5,800.00 (loss of ($5,800 - $5,000) * 50 = -$40,000)
    # Locked margin was $30,000. Effective margin = $30,000 - $40,000 = -$10,000
    # Maintenance requirement = 10% of $5,800 * 50 = $29,000
    # Ratio = -10,000 / 29,000 < 1.0 -> Liquidation MUST trigger at $5,800!
    mock_quote_loss = PriceQuote(
        symbol="ES=F", display_name="ES=F", exchange="CME", currency="USD",
        price=5800.0, prev_close=5000.0, change=800.0, change_pct=16.0,
        day_high=5800.0, day_low=5000.0, volume=50000, market_open=True,
        timestamp=datetime.now(timezone.utc).isoformat(), error=None,
    )

    with patch("services.derivatives_feed.get_quote", return_value=mock_quote_loss), \
         patch("services.derivatives_engine.get_quote", return_value=mock_quote_loss):
        liq_orders = evaluate_derivative_margin_calls(db=db)
        assert len(liq_orders) == 1
        liq = liq_orders[0]
        assert liq.status == "filled"
        assert liq.action == "buy_to_close"
        assert liq.executed_price == 5800.0
        print(f"Liquidation executed: action={liq.action}, price=${liq.executed_price}, status={liq.status}")

        # Position should now be closed
        rem_positions = get_derivative_positions_summary(db=db, wallet_id=us_wallet.id)
        assert len(rem_positions) == 0

    print("[PASS] TEST 2 PASSED: US Continuous Futures short handles live P&L and liquidation trigger.")


# ── TEST 3: Indian & US Options Live Price Sync ───────────────────────────────

def test_options_live_price_sync():
    print("\n--- TEST 3: Indian (NSE) & US (yfinance) Options Live Price Sync ---")
    db, in_wallet, us_wallet = setup_test_db()

    # A. Indian Option: RELIANCE 1400 CE, lot=250, bought @ 20.0
    in_contract = get_or_create_contract(
        db=db,
        market="IN",
        underlying="RELIANCE",
        instrument_type="option",
        option_type="call",
        strike_price=1400.0,
        expiry_date=date(2026, 10, 29),
        lot_size=250,
        symbol="RELIANCE-29OCT26-1400-CALL",
    )
    in_order = place_derivative_order(
        db=db,
        wallet=in_wallet,
        contract=in_contract,
        side="buy",
        action="buy_to_open",
        quantity=1,
        fill_price=20.0,
        check_market_hours=False,
    )
    assert in_order.status == "filled"

    # Mock NSE Option Chain with RELIANCE 1400 CE moving from 20.0 to 35.50
    mock_in_chain = {
        "symbol": "RELIANCE",
        "market": "IN",
        "underlying_value": 1420.0,
        "strikes": [
            {
                "strike": 1400.0,
                "call": {"ltp": 35.50, "bid": 35.0, "ask": 36.0},
                "put": {"ltp": 12.0, "bid": 11.5, "ask": 12.5},
            }
        ],
    }

    with patch("services.derivatives_feed.nse_client.get_option_chain", return_value=mock_in_chain):
        in_summaries = get_derivative_positions_summary(db=db, wallet_id=in_wallet.id)
        assert len(in_summaries) == 1
        pos_summary = in_summaries[0]
        assert pos_summary["price_available"] is True
        assert pos_summary["current_price"] == 35.50
        # Expected PnL = (35.50 - 20.0) * 250 = 15.50 * 250 = +3,875.00
        assert pos_summary["unrealized_pnl"] == 3875.00
        print(f"Indian Option Live Sync: LTP=35.50, PnL=+INR {pos_summary['unrealized_pnl']}")

    # B. US Option: AAPL 220 CE, lot=100, bought @ 5.0
    us_contract = get_or_create_contract(
        db=db,
        market="US",
        underlying="AAPL",
        instrument_type="option",
        option_type="call",
        strike_price=220.0,
        expiry_date=date(2026, 10, 16),
        lot_size=100,
        symbol="AAPL-16OCT26-220-CALL",
    )
    us_order = place_derivative_order(
        db=db,
        wallet=us_wallet,
        contract=us_contract,
        side="buy",
        action="buy_to_open",
        quantity=1,
        fill_price=5.0,
        check_market_hours=False,
    )
    assert us_order.status == "filled"

    # Mock US Option Chain with AAPL 220 CE moving from 5.0 to 8.20
    mock_us_chain = {
        "symbol": "AAPL",
        "market": "US",
        "underlying_value": 225.0,
        "strikes": [
            {
                "strike": 220.0,
                "call": {"ltp": 8.20, "bid": 8.15, "ask": 8.25},
                "put": {"ltp": 2.10, "bid": 2.05, "ask": 2.15},
            }
        ],
    }

    with patch("services.derivatives_feed.fetch_us_option_chain", return_value=mock_us_chain):
        us_summaries = get_derivative_positions_summary(db=db, wallet_id=us_wallet.id)
        assert len(us_summaries) == 1
        us_pos_summary = us_summaries[0]
        assert us_pos_summary["price_available"] is True
        assert us_pos_summary["current_price"] == 8.20
        # Expected PnL = (8.20 - 5.0) * 100 = 3.20 * 100 = +$320.00
        assert us_pos_summary["unrealized_pnl"] == 320.00
        print(f"US Option Live Sync: LTP=8.20, PnL=+${us_pos_summary['unrealized_pnl']}")

    print("[PASS] TEST 3 PASSED: Both Indian and US options sync live prices and calculate accurate P&L.")


# ── TEST 4: Price Unavailable / Stale Price Safeguard ─────────────────────────

def test_stale_price_safeguards():
    print("\n--- TEST 4: Price Unavailable Safeguards (No Silent Fallback to Entry Price) ---")
    db, in_wallet, _ = setup_test_db()

    contract = get_or_create_contract(
        db=db,
        market="IN",
        underlying="NIFTY",
        instrument_type="future",
        expiry_date=date(2026, 10, 27),
        lot_size=65,
        symbol="NIFTY-27OCT26-FUT",
    )

    place_derivative_order(
        db=db,
        wallet=in_wallet,
        contract=contract,
        side="buy",
        action="buy_to_open",
        quantity=1,
        fill_price=22492.10,
        check_market_hours=False,
    )

    # Feed returns empty/broken response (unresolvable live quote)
    mock_broken_feed = {"symbol": "NIFTY", "contracts": []}

    with patch("services.derivatives_feed.nse_client.get_futures", return_value=mock_broken_feed), \
         patch("services.derivatives_feed.get_quote", return_value=None), \
         patch("services.derivatives_engine.get_quote", return_value=None):

        # 1. Position summary MUST report price_available=False and current_price=None (NOT entry price!)
        summaries = get_derivative_positions_summary(db=db, wallet_id=in_wallet.id)
        assert len(summaries) == 1
        s = summaries[0]
        assert s["price_available"] is False
        assert s["current_price"] is None
        assert s["unrealized_pnl"] == 0.0
        print(f"Stale Position Summary: price_available={s['price_available']}, current_price={s['current_price']}")

        # 2. Daily MTM settlement MUST cleanly skip without adjusting cash or recording transaction
        cash_before = in_wallet.current_cash_balance
        txns = evaluate_daily_futures_mtm(db=db)
        assert len(txns) == 0
        db.refresh(in_wallet)
        assert in_wallet.current_cash_balance == cash_before
        print(f"MTM with Stale Price: skipped cleanly, cash unchanged at INR {in_wallet.current_cash_balance}")

        # 3. Liquidation evaluation MUST cleanly skip without falsely liquidating
        liq_orders = evaluate_derivative_margin_calls(db=db)
        assert len(liq_orders) == 0
        print("Liquidation with Stale Price: skipped cleanly, 0 false liquidations")

    print("[PASS] TEST 4 PASSED: Unresolvable prices safely report price_available=False and skip MTM/liquidation.")


if __name__ == "__main__":
    print("=" * 70)
    print("RUNNING DERIVATIVES LIVE PRICE SYNC VERIFICATION SUITE")
    print("=" * 70)

    test_nifty_future_live_price_and_pnl_sync()
    test_us_continuous_futures_short_and_liquidation()
    test_options_live_price_sync()
    test_stale_price_safeguards()

    print("\n" + "=" * 70)
    print("ALL 4 DERIVATIVES LIVE PRICE SYNC TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)
