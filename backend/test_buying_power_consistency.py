"""
test_buying_power_consistency.py — Verification Suite for Buying Power Enforcement.

Verifies:
1. Futures position locks margin -> equity buy exceeding available buying power (even if cash is sufficient) is rejected.
2. Equity buy within available buying power fills cleanly.
3. Closing futures position releases margin -> larger equity buy now fills.
4. Naked option write locks margin -> equity buy exceeding available buying power rejected, within fills, close releases.
5. US equity short locks Reg T margin -> equity buy exceeding available buying power rejected, within fills, cover releases.
6. Pending limit buy placed when buying power was sufficient, then margin locked, then price triggers -> rejected at trigger time.
7. Edge case: margin_used > current_cash_balance -> available buying power is strictly 0.0 and rejects new buys.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure backend root on sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from database import Base
from models.orm import (
    Wallet,
    Holding,
    Order,
    DerivativeContract,
    DerivativePosition,
    DerivativeOrder,
    DerivativeTransaction,
)
from services.order_engine import (
    place_order,
    evaluate_pending_orders,
)
from services.derivatives_engine import (
    get_or_create_contract,
    place_derivative_order,
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
        starting_balance=10000.0,
        current_cash_balance=10000.0,
        margin_used=0.0,
    )
    db.add(in_wallet)
    db.add(us_wallet)
    db.commit()
    db.refresh(in_wallet)
    db.refresh(us_wallet)
    return db, in_wallet, us_wallet


def make_quote(
    symbol: str,
    price: float,
    market_open: bool = True,
    exchange: str = "NSE",
    currency: str = "INR",
) -> PriceQuote:
    return PriceQuote(
        symbol=symbol,
        display_name=symbol,
        exchange=exchange,
        currency=currency,
        price=price,
        prev_close=price,
        change=0.0,
        change_pct=0.0,
        day_high=price,
        day_low=price,
        volume=100000,
        market_open=market_open,
        timestamp=datetime.now(timezone.utc).isoformat(),
        error=None,
    )


# ── TEST 1: Futures Margin Blocks Equity Buy ──────────────────────────────────

def test_futures_margin_blocks_equity_buy():
    print("\n--- TEST 1: Futures Position Locks Margin & Blocks Excessive Equity Buy ---")
    db, in_wallet, _ = setup_test_db()

    # Create NIFTY Future: Underlying price = 24,000, lot_size = 50
    # Notional = 24,000 * 50 = 1,200,000
    # Initial margin 12% = 144,000
    fut_contract = get_or_create_contract(
        db=db,
        underlying="NIFTY",
        instrument_type="future",
        expiry_date=date(2026, 10, 29),
        market="IN",
        lot_size=50,
    )

    with patch("services.derivatives_engine.is_derivative_market_open", return_value=True), \
         patch("services.derivatives_engine.get_quote", return_value=make_quote("NIFTY", 24000.0)):
        fut_order = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=fut_contract,
            side="buy",
            action="buy_to_open",
            quantity=1,
            fill_price=24000.0,
            check_market_hours=False,
        )

    assert fut_order.status == "filled"
    db.refresh(in_wallet)
    assert in_wallet.current_cash_balance == 500000.0
    assert in_wallet.margin_used == 144000.0
    assert in_wallet.available_buying_power == 356000.0
    print(f"Futures opened: cash={in_wallet.current_cash_balance}, margin_used={in_wallet.margin_used}, BP={in_wallet.available_buying_power}")

    # Now attempt equity BUY of RELIANCE.NS for ₹400,000 (400 shares @ ₹1,000)
    # Total cash is ₹500,000 (so raw cash would have passed!), but available BP is ₹356,000
    with patch("services.order_engine.get_quote", return_value=make_quote("RELIANCE.NS", 1000.0)):
        rej_equity = place_order(
            db=db,
            market="IN",
            ticker="RELIANCE.NS",
            side="buy",
            quantity=400,
            order_type="market",
        )

    assert rej_equity.status == "rejected"
    assert rej_equity.reject_reason in ("insufficient_funds", "insufficient_buying_power")
    print(f"Excess equity BUY correctly REJECTED: status={rej_equity.status}, reason={rej_equity.reject_reason}")

    # Same buy within available buying power (300 shares @ ₹1,000 = ₹300,000 <= ₹356,000) -> FILLS!
    with patch("services.order_engine.get_quote", return_value=make_quote("RELIANCE.NS", 1000.0)):
        fill_equity = place_order(
            db=db,
            market="IN",
            ticker="RELIANCE.NS",
            side="buy",
            quantity=300,
            order_type="market",
        )

    assert fill_equity.status == "filled"
    db.refresh(in_wallet)
    assert in_wallet.current_cash_balance == 200000.0
    assert in_wallet.margin_used == 144000.0
    assert in_wallet.available_buying_power == 56000.0
    print(f"Equity BUY within BP FILLED: cash={in_wallet.current_cash_balance}, BP={in_wallet.available_buying_power}")

    # Close futures position -> margin releases
    with patch("services.derivatives_engine.is_derivative_market_open", return_value=True), \
         patch("services.derivatives_engine.get_quote", return_value=make_quote("NIFTY", 24000.0)):
        close_fut = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=fut_contract,
            side="sell",
            action="sell_to_close",
            quantity=1,
            fill_price=24000.0,
            check_market_hours=False,
        )

    assert close_fut.status == "filled"
    db.refresh(in_wallet)
    assert in_wallet.margin_used == 0.0
    assert in_wallet.available_buying_power == 200000.0
    print(f"Futures closed: margin released, BP={in_wallet.available_buying_power}")

    # Now an equity buy of ₹150,000 (150 shares @ ₹1,000) that previously exceeded BP (₹56,000) now FILLS!
    with patch("services.order_engine.get_quote", return_value=make_quote("RELIANCE.NS", 1000.0)):
        post_close_buy = place_order(
            db=db,
            market="IN",
            ticker="RELIANCE.NS",
            side="buy",
            quantity=150,
            order_type="market",
        )

    assert post_close_buy.status == "filled"
    print("[PASS] TEST 1 PASSED: Futures margin correctly blocks and releases equity buying power.")


# ── TEST 2: Naked Option Write Locks Margin & Blocks Equity Buy ───────────────

def test_naked_option_margin_blocks_equity_buy():
    print("\n--- TEST 2: Naked Option Write Locks Margin & Blocks Excessive Equity Buy ---")
    db, in_wallet, _ = setup_test_db()

    # NIFTY 24500 CE, spot = 24,000, lot = 50
    # Spot notional = 24,000 * 50 = 1,200,000
    # 20% spot notional margin = 240,000
    opt_contract = get_or_create_contract(
        db=db,
        underlying="NIFTY",
        instrument_type="option",
        strike_price=24500.0,
        option_type="call",
        expiry_date=date(2026, 10, 29),
        market="IN",
        lot_size=50,
    )

    with patch("services.derivatives_engine.is_derivative_market_open", return_value=True), \
         patch("services.derivatives_engine.get_quote", return_value=make_quote("NIFTY", 24000.0)):
        opt_order = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=opt_contract,
            side="sell",
            action="sell_to_open",
            quantity=1,
            fill_price=200.0,  # Premium = 200 * 50 = 10,000
            underlying_price=24000.0,
            check_market_hours=False,
        )

    assert opt_order.status == "filled"
    db.refresh(in_wallet)
    assert in_wallet.current_cash_balance == 510000.0
    assert in_wallet.margin_used == 240000.0
    assert in_wallet.available_buying_power == 270000.0
    print(f"Naked call written: cash={in_wallet.current_cash_balance}, margin_used={in_wallet.margin_used}, BP={in_wallet.available_buying_power}")

    # Attempt equity BUY of ₹300,000 (300 shares of TCS.NS @ ₹1,000)
    # Total cash is ₹510,000, but BP is ₹270,000 -> REJECTED!
    with patch("services.order_engine.get_quote", return_value=make_quote("TCS.NS", 1000.0)):
        rej_buy = place_order(
            db=db,
            market="IN",
            ticker="TCS.NS",
            side="buy",
            quantity=300,
            order_type="market",
        )

    assert rej_buy.status == "rejected"
    assert rej_buy.reject_reason in ("insufficient_funds", "insufficient_buying_power")
    print(f"Excess equity BUY correctly REJECTED: reason={rej_buy.reject_reason}")

    # Buy of ₹200,000 (within ₹270,000 BP) -> FILLS!
    with patch("services.order_engine.get_quote", return_value=make_quote("TCS.NS", 1000.0)):
        fill_buy = place_order(
            db=db,
            market="IN",
            ticker="TCS.NS",
            side="buy",
            quantity=200,
            order_type="market",
        )

    assert fill_buy.status == "filled"
    print("[PASS] TEST 2 PASSED: Naked option margin correctly blocks equity buying power.")


# ── TEST 3: US Short Position Locks Margin & Blocks Equity Buy ────────────────

def test_us_short_margin_blocks_equity_buy():
    print("\n--- TEST 3: US Short Position Locks Margin & Blocks Excessive Equity Buy ---")
    db, _, us_wallet = setup_test_db()

    # US short 50 shares of TSLA @ $100
    # Proceeds = $5,000 credited to cash (cash becomes $15,000)
    # Reg T initial margin (150%) = 1.5 * 100 * 50 = $7,500 locked
    # Available BP = $15,000 - $7,500 = $7,500
    with patch("services.order_engine.get_quote", return_value=make_quote("TSLA", 100.0, exchange="NASDAQ", currency="USD")):
        short_order = place_order(
            db=db,
            market="US",
            ticker="TSLA",
            side="sell",
            quantity=50,
            order_type="market",
        )

    assert short_order.status == "filled"
    assert short_order.is_short is True
    db.refresh(us_wallet)
    assert us_wallet.current_cash_balance == 15000.0
    assert us_wallet.margin_used == 7500.0
    assert us_wallet.available_buying_power == 7500.0
    print(f"US short opened: cash={us_wallet.current_cash_balance}, margin_used={us_wallet.margin_used}, BP={us_wallet.available_buying_power}")

    # Attempt equity BUY of 100 shares of AAPL @ $100 = $10,000
    # Smaller than total cash ($15,000), but exceeds BP ($7,500) -> REJECTED!
    with patch("services.order_engine.get_quote", return_value=make_quote("AAPL", 100.0, exchange="NASDAQ", currency="USD")):
        rej_us_buy = place_order(
            db=db,
            market="US",
            ticker="AAPL",
            side="buy",
            quantity=100,
            order_type="market",
        )

    assert rej_us_buy.status == "rejected"
    assert rej_us_buy.reject_reason in ("insufficient_funds", "insufficient_buying_power")
    print(f"Excess US equity BUY correctly REJECTED: reason={rej_us_buy.reject_reason}")

    # Buy within available BP (50 shares @ $100 = $5,000 <= $7,500) -> FILLS!
    with patch("services.order_engine.get_quote", return_value=make_quote("AAPL", 100.0, exchange="NASDAQ", currency="USD")):
        fill_us_buy = place_order(
            db=db,
            market="US",
            ticker="AAPL",
            side="buy",
            quantity=50,
            order_type="market",
        )

    assert fill_us_buy.status == "filled"
    db.refresh(us_wallet)
    assert us_wallet.current_cash_balance == 10000.0
    assert us_wallet.margin_used == 7500.0
    assert us_wallet.available_buying_power == 2500.0
    print(f"US equity BUY within BP FILLED: cash={us_wallet.current_cash_balance}, BP={us_wallet.available_buying_power}")

    # Cover the short position -> margin released!
    with patch("services.order_engine.get_quote", return_value=make_quote("TSLA", 100.0, exchange="NASDAQ", currency="USD")):
        cover_order = place_order(
            db=db,
            market="US",
            ticker="TSLA",
            side="buy",
            quantity=50,
            order_type="market",
        )

    assert cover_order.status == "filled"
    db.refresh(us_wallet)
    assert us_wallet.margin_used == 0.0
    assert us_wallet.current_cash_balance == 5000.0
    assert us_wallet.available_buying_power == 5000.0
    print(f"Short covered: margin released, BP={us_wallet.available_buying_power}")
    print("[PASS] TEST 3 PASSED: US short margin correctly blocks equity buying power and releases on cover.")


# ── TEST 4: Pending Limit Buy Rejected at Trigger Time if Margin Locked ───────

def test_pending_limit_buy_rejected_on_trigger_if_margin_locked():
    print("\n--- TEST 4: Pending Limit Buy Rejected at Trigger Time After Margin Lock ---")
    db, in_wallet, _ = setup_test_db()

    # Initial cash ₹500,000, BP ₹500,000
    # Place limit buy for 400 shares of RELIANCE.NS @ limit price ₹1,000 (total ₹400,000)
    # Market quote is ₹1,050 (above limit), so order stays pending
    with patch("services.order_engine.get_quote", return_value=make_quote("RELIANCE.NS", 1050.0)):
        pending_order = place_order(
            db=db,
            market="IN",
            ticker="RELIANCE.NS",
            side="buy",
            quantity=400,
            order_type="limit",
            requested_price=1000.0,
        )

    assert pending_order.status == "pending"
    print(f"Limit order placed: status={pending_order.status}, limit={pending_order.requested_price}")

    # Now lock margin in futures (e.g. 2 lots of NIFTY futures, locking 2 * 144,000 = ₹288,000 margin)
    fut_contract = get_or_create_contract(
        db=db,
        underlying="NIFTY",
        instrument_type="future",
        expiry_date=date(2026, 10, 29),
        market="IN",
        lot_size=50,
    )

    with patch("services.derivatives_engine.is_derivative_market_open", return_value=True), \
         patch("services.derivatives_engine.get_quote", return_value=make_quote("NIFTY", 24000.0)):
        fut_order = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=fut_contract,
            side="buy",
            action="buy_to_open",
            quantity=2,
            fill_price=24000.0,
            check_market_hours=False,
        )

    assert fut_order.status == "filled"
    db.refresh(in_wallet)
    assert in_wallet.margin_used == 288000.0
    assert in_wallet.available_buying_power == 212000.0
    print(f"Margin locked in futures: margin_used={in_wallet.margin_used}, BP={in_wallet.available_buying_power}")

    # Price of RELIANCE drops to ₹990 (triggering the limit condition!)
    # At trigger time, order requires ₹400,000, but BP is only ₹212,000 -> must REJECT!
    trigger_quote = make_quote("RELIANCE.NS", 990.0)
    evaluated = evaluate_pending_orders(db, quotes={"RELIANCE.NS": trigger_quote}, market="IN")

    assert len(evaluated) == 1
    triggered_order = evaluated[0]
    assert triggered_order.id == pending_order.id
    assert triggered_order.status == "rejected"
    assert triggered_order.reject_reason in ("insufficient_funds", "insufficient_buying_power")

    # Confirm wallet cash was NOT deducted and no holding was created
    db.refresh(in_wallet)
    assert in_wallet.current_cash_balance == 500000.0
    rel_holding = db.query(Holding).filter(Holding.wallet_id == in_wallet.id, Holding.ticker == "RELIANCE.NS").first()
    assert rel_holding is None
    print(f"Pending limit order on trigger was correctly REJECTED: status={triggered_order.status}, reason={triggered_order.reject_reason}")
    print("[PASS] TEST 4 PASSED: Pending limit buy safely rejected at trigger time when BP is insufficient.")


# ── TEST 5: Edge Case - Floored Buying Power Never Negative ────────────────────

def test_buying_power_floors_at_zero():
    print("\n--- TEST 5: Edge Case - Buying Power Floors at Zero When Margin Exceeds Cash ---")
    db, in_wallet, _ = setup_test_db()

    # Simulate MTM loss where margin_used > current_cash_balance
    in_wallet.current_cash_balance = 50000.0
    in_wallet.margin_used = 120000.0
    db.commit()
    db.refresh(in_wallet)

    assert in_wallet.available_buying_power == 0.0
    print(f"Wallet with cash={in_wallet.current_cash_balance}, margin={in_wallet.margin_used} -> BP={in_wallet.available_buying_power}")

    # Attempt any buy (even for 1 share of ₹10) -> Rejected
    with patch("services.order_engine.get_quote", return_value=make_quote("RELIANCE.NS", 10.0)):
        order = place_order(
            db=db,
            market="IN",
            ticker="RELIANCE.NS",
            side="buy",
            quantity=1,
            order_type="market",
        )

    assert order.status == "rejected"
    assert order.reject_reason in ("insufficient_funds", "insufficient_buying_power")
    print(f"Order correctly REJECTED when BP is 0: status={order.status}, reason={order.reject_reason}")
    print("[PASS] TEST 5 PASSED: Available buying power strictly floored at 0 and rejects new buys.")


if __name__ == "__main__":
    print("=" * 70)
    print("RUNNING BUYING POWER CONSISTENCY VERIFICATION SUITE")
    print("=" * 70)

    test_futures_margin_blocks_equity_buy()
    test_naked_option_margin_blocks_equity_buy()
    test_us_short_margin_blocks_equity_buy()
    test_pending_limit_buy_rejected_on_trigger_if_margin_locked()
    test_buying_power_floors_at_zero()

    print("\n" + "=" * 70)
    print("ALL 5 BUYING POWER CONSISTENCY TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)
