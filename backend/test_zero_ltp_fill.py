"""
test_zero_ltp_fill.py — Explicit verification that orders on strikes where LTP = 0
do NOT execute at ₹0 / $0, and instead resolve via Bid/Ask book:
1. Buy orders lift the Ask price
2. Sell orders hit the Bid price
3. Orders where LTP=0 and no quotes exist are rejected with "unresolvable_price"
4. Concrete test on individual stock (RELIANCE 1020 CE and US MSFT 430 Call)
"""

import sys
import os
from datetime import date

# Ensure backend root is on python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from database import SessionLocal, Base, engine
from models.orm import Wallet, DerivativeContract, DerivativePosition, DerivativeOrder
from services.derivatives_engine import place_derivative_order, get_or_create_contract

def run_zero_ltp_verification():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        print("=" * 80)
        print("ZERO-LTP DERIVATIVE FILL-PRICE VERIFICATION SUITE")
        print("=" * 80)

        # Ensure Indian wallet with cash
        in_wallet = db.query(Wallet).filter(Wallet.market == "IN").first()
        if not in_wallet:
            in_wallet = Wallet(
                market="IN",
                initial_capital=500000.0,
                current_cash_balance=500000.0,
                margin_used=0.0
            )
            db.add(in_wallet)
            db.commit()
            db.refresh(in_wallet)
        else:
            in_wallet.current_cash_balance = 500000.0
            in_wallet.margin_used = 0.0
            db.commit()

        # ----------------------------------------------------------------------
        # TEST 1: Indian Stock (RELIANCE 1020 CE) with LTP = 0.0, Bid = 179.05, Ask = 238.20
        # ----------------------------------------------------------------------
        print("\n--- TEST 1: Buy order on RELIANCE 1020 CE where LTP = 0.0 ---")
        rel_contract = get_or_create_contract(
            db=db,
            market="IN",
            underlying="RELIANCE",
            instrument_type="option",
            option_type="call",
            strike_price=1020.0,
            expiry_date=date(2026, 9, 29),
            lot_size=250,
            symbol="RELIANCE-29SEP26-1020-CE",
        )

        cash_before = in_wallet.current_cash_balance
        print(f"Contract: {rel_contract.symbol} | Lot Size: {rel_contract.lot_size}")
        print(f"Market Book: LTP = ₹0.00 | Bid = ₹179.05 | Ask = ₹238.20")
        print(f"Cash Before: ₹{cash_before:,.2f}")

        # Buyer places Buy-To-Open market order with fill_price=0.0 / None, bid=179.05, ask=238.20
        buy_order = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=rel_contract,
            side="buy",
            action="buy_to_open",
            quantity=1, # 1 lot = 250 units
            order_type="market",
            fill_price=0.0, # simulates LTP = 0
            bid=179.05,
            ask=238.20,
            underlying_price=1380.0,
        )

        print(f"\nResulting Order:")
        print(f"  Status: {buy_order.status}")
        print(f"  Executed Price: ₹{buy_order.executed_price:,.2f}")
        print(f"  Total Cost Debited: ₹{(buy_order.executed_price * rel_contract.lot_size):,.2f}")
        print(f"  Cash After: ₹{in_wallet.current_cash_balance:,.2f}")

        # Assertions
        assert buy_order.status == "filled", f"Order failed: {buy_order.reject_reason}"
        assert buy_order.executed_price == 238.20, (
            f"Expected fill price to be Ask (₹238.20), got ₹{buy_order.executed_price}"
        )
        assert buy_order.executed_price > 0, "Executed price must be strictly positive!"
        expected_debit = round(238.20 * 250, 2) # ₹59,550.00
        actual_debit = round(cash_before - in_wallet.current_cash_balance, 2)
        assert actual_debit == expected_debit, f"Expected cash debit {expected_debit}, got {actual_debit}"
        print(f"✓ TEST 1 PASSED: Buy order lifted Ask at ₹238.20 (Debited ₹{expected_debit:,.2f}), NOT ₹0.00!")

        # ----------------------------------------------------------------------
        # TEST 2: Indian Stock (RELIANCE 1020 CE) Sell-To-Open with LTP = 0.0
        # ----------------------------------------------------------------------
        print("\n--- TEST 2: Sell order on RELIANCE 1020 CE where LTP = 0.0 ---")
        cash_before_sell = in_wallet.current_cash_balance
        margin_before = in_wallet.margin_used

        # Seller places Sell-To-Open order with fill_price=0.0, bid=179.05, ask=238.20
        sell_order = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=rel_contract,
            side="sell",
            action="sell_to_open",
            quantity=1, # 1 lot = 250 units
            order_type="market",
            fill_price=0.0, # simulates LTP = 0
            bid=179.05,
            ask=238.20,
            underlying_price=1380.0,
        )

        print(f"\nResulting Order:")
        print(f"  Status: {sell_order.status}")
        print(f"  Executed Price: ₹{sell_order.executed_price:,.2f}")
        print(f"  Premium Credited: ₹{(sell_order.executed_price * rel_contract.lot_size):,.2f}")
        print(f"  Margin Locked: ₹{sell_order.margin_required:,.2f}")

        # Assertions
        assert sell_order.status == "filled", f"Order failed: {sell_order.reject_reason}"
        assert sell_order.executed_price == 179.05, (
            f"Expected fill price to be Bid (₹179.05), got ₹{sell_order.executed_price}"
        )
        expected_credit = round(179.05 * 250, 2) # ₹44,762.50
        actual_credit = round(in_wallet.current_cash_balance - cash_before_sell, 2)
        assert actual_credit == expected_credit, f"Expected cash credit {expected_credit}, got {actual_credit}"
        # 20% of spot notional: 0.20 * 1380 * 250 = ₹69,000.00
        assert sell_order.margin_required == 69000.0, f"Expected margin ₹69,000, got ₹{sell_order.margin_required}"
        print(f"✓ TEST 2 PASSED: Sell order hit Bid at ₹179.05 (Credited ₹{expected_credit:,.2f}), NOT ₹0.00!")

        # ----------------------------------------------------------------------
        # TEST 3: US Stock (MSFT 430 Call) with LTP = 0.0, Bid = 4.20, Ask = 4.50
        # ----------------------------------------------------------------------
        print("\n--- TEST 3: US Stock (MSFT 430 Call) with LTP = 0.0 ---")
        us_wallet = db.query(Wallet).filter(Wallet.market == "US").first()
        if not us_wallet:
            us_wallet = Wallet(
                market="US",
                initial_capital=50000.0,
                current_cash_balance=50000.0,
                margin_used=0.0
            )
            db.add(us_wallet)
            db.commit()
            db.refresh(us_wallet)
        else:
            us_wallet.current_cash_balance = 50000.0
            us_wallet.margin_used = 0.0
            db.commit()

        msft_contract = get_or_create_contract(
            db=db,
            market="US",
            underlying="MSFT",
            instrument_type="option",
            option_type="call",
            strike_price=430.0,
            expiry_date=date(2026, 10, 16),
            lot_size=100,
            symbol="MSFT-20261016-430-C",
        )

        us_cash_before = us_wallet.current_cash_balance
        us_buy_order = place_derivative_order(
            db=db,
            wallet=us_wallet,
            contract=msft_contract,
            side="buy",
            action="buy_to_open",
            quantity=2, # 2 contracts = 200 shares
            order_type="market",
            fill_price=0.0,
            bid=4.20,
            ask=4.50,
            underlying_price=425.0,
        )

        print(f"Resulting US Order:")
        print(f"  Status: {us_buy_order.status}")
        print(f"  Executed Price: ${us_buy_order.executed_price:,.2f}")
        print(f"  Total Cost: ${us_buy_order.executed_price * 200:,.2f}")

        assert us_buy_order.status == "filled"
        assert us_buy_order.executed_price == 4.50, f"Expected Ask price $4.50, got ${us_buy_order.executed_price}"
        expected_us_debit = round(4.50 * 200, 2) # $900.00
        actual_us_debit = round(us_cash_before - us_wallet.current_cash_balance, 2)
        assert actual_us_debit == expected_us_debit, f"Expected debit {expected_us_debit}, got {actual_us_debit}"
        print(f"✓ TEST 3 PASSED: US Buy order lifted Ask at $4.50 (Debited ${expected_us_debit:,.2f}), NOT $0.00!")

        # ----------------------------------------------------------------------
        # TEST 4: Zero-LTP with Missing/Zero Bid & Ask (Unpriced phantom strike)
        # ----------------------------------------------------------------------
        print("\n--- TEST 4: Zero-LTP with NO valid Bid/Ask (Must strictly REJECT) ---")
        phantom_contract = get_or_create_contract(
            db=db,
            market="IN",
            underlying="RELIANCE",
            instrument_type="option",
            option_type="put",
            strike_price=700.0, # deep illiquid OTM put
            expiry_date=date(2026, 9, 29),
            lot_size=250,
            symbol="RELIANCE-29SEP26-700-PE",
        )

        rejected_order = place_derivative_order(
            db=db,
            wallet=in_wallet,
            contract=phantom_contract,
            side="buy",
            action="buy_to_open",
            quantity=1,
            order_type="market",
            fill_price=0.0, # LTP = 0
            bid=0.0,        # No bid
            ask=0.0,        # No ask
            underlying_price=1380.0,
        )

        print(f"Resulting Order:")
        print(f"  Status: {rejected_order.status}")
        print(f"  Reject Reason: {rejected_order.reject_reason}")
        print(f"  Executed Price: {rejected_order.executed_price}")

        assert rejected_order.status == "rejected", "Order on unresolvable price must be rejected!"
        assert rejected_order.reject_reason == "unresolvable_price", f"Expected 'unresolvable_price', got {rejected_order.reject_reason}"
        assert rejected_order.executed_price is None, "Executed price must be None for rejected orders!"
        print(f"✓ TEST 4 PASSED: Order on strike with no LTP and no Bid/Ask was strictly REJECTED (reason: unresolvable_price). Never executed at ₹0.00!")

        print("\n" + "=" * 80)
        print("ALL ZERO-LTP FILL-PRICE VERIFICATION TESTS PASSED SUCCESSFULLY!")
        print("=" * 80)

    finally:
        db.close()

if __name__ == "__main__":
    run_zero_ltp_verification()
