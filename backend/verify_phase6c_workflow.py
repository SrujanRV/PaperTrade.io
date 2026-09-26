"""
verify_phase6c_workflow.py â€” Step-by-step verification of Phase 6c F&O Order Engine:

1. Open a Long Option (buy_to_open):
   - Premium paid upfront from cash.
   - 0 margin locked.
2. Open a Written Naked Option (sell_to_open):
   - 20% initial margin locked on notional.
   - Premium credited to cash.
   - Available buying power updated.
3. Open a Futures Position (buy_to_open):
   - 12% initial margin locked.
   - 0 cash debited upfront.
4. Run Daily MTM Settlement:
   - Cash credited directly for price movement.
   - Position remains open, margin stays locked.
5. Run Expiry Settlement:
   - Options intrinsic cash settlement (Call ITM payout, Put OTM worthless).
   - Indian futures settlement against underlying index price.
   - All locked margins released (margin_used returns to 0).
6. Verify API endpoints:
   - POST /api/derivatives/order
   - GET  /api/derivatives/positions/{market}
   - GET  /api/derivatives/contracts?underlying=NIFTY&type=option
"""

from __future__ import annotations

import os
import sys
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

# Ensure backend root on sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from database import Base, get_db
from models.orm import Wallet, DerivativeContract, DerivativePosition, DerivativeOrder, DerivativeTransaction
from services.derivatives_engine import (
    get_or_create_contract,
    place_derivative_order,
    evaluate_daily_futures_mtm,
    evaluate_derivatives_expiry_settlement,
    evaluate_derivative_margin_calls,
)
from main import app

# In-memory shared test database
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)
TestingSession = sessionmaker(bind=test_engine)
Base.metadata.create_all(bind=test_engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def print_step_header(title: str):
    print("\n" + "=" * 75)
    print(f"  {title}")
    print("=" * 75)


def run_full_verification():
    db = TestingSession()

    # Setup INR Wallet with â‚¹10,00,000 starting balance
    wallet = Wallet(
        market="IN",
        currency="INR",
        starting_balance=1000000.0,
        current_cash_balance=1000000.0,
        margin_used=0.0,
    )
    db.add(wallet)
    db.commit()
    db.refresh(wallet)

    print_step_header("INITIAL STATE")
    print(f"Wallet Cash Balance:      â‚¹{wallet.current_cash_balance:,.2f}")
    print(f"Margin Used:              â‚¹{wallet.margin_used:,.2f}")
    print(f"Available Buying Power:   â‚¹{wallet.available_buying_power:,.2f}")
    assert wallet.current_cash_balance == 1000000.0
    assert wallet.margin_used == 0.0

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # STEP 1: OPEN A LONG OPTION (buy_to_open)
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print_step_header("STEP 1: BUY TO OPEN LONG CALL OPTION")
    # NIFTY 23,150 Call, Lot size = 65, Expiry = 2026-09-29
    call_contract = get_or_create_contract(
        db=db,
        market="IN",
        underlying="NIFTY",
        instrument_type="option",
        option_type="call",
        strike_price=23150.0,
        expiry_date=date(2026, 9, 29),
        lot_size=65,
    )
    # Buy 1 lot @ â‚¹150 premium -> Total premium = 1 * 65 * 150 = â‚¹9,750
    order_buy_call = place_derivative_order(
        db=db,
        wallet=wallet,
        contract=call_contract,
        side="buy",
        action="buy_to_open",
        quantity=1.0,
        fill_price=150.0,
    )
    db.refresh(wallet)
    print(f"Order:                     #{order_buy_call.id} {order_buy_call.action} {order_buy_call.quantity} lot(s) @ â‚¹{order_buy_call.executed_price} [{order_buy_call.status}]")
    print(f"Premium Paid:              â‚¹{9750.0:,.2f}")
    print(f"Wallet Cash Balance:      â‚¹{wallet.current_cash_balance:,.2f} (Expected â‚¹9,90,250.00)")
    print(f"Margin Used:              â‚¹{wallet.margin_used:,.2f} (Expected â‚¹0.00)")
    print(f"Available Buying Power:   â‚¹{wallet.available_buying_power:,.2f}")

    assert order_buy_call.status == "filled"
    assert wallet.current_cash_balance == 990250.0
    assert wallet.margin_used == 0.0
    assert wallet.available_buying_power == 990250.0

    pos_call = db.query(DerivativePosition).filter(DerivativePosition.contract_id == call_contract.id).first()
    assert pos_call is not None
    assert pos_call.side == "long"
    assert pos_call.quantity == 1.0
    assert pos_call.entry_price == 150.0
    assert pos_call.margin_locked == 0.0
    print("[CONFIRMED] Long Option: Upfront premium debited, 0 margin locked.")

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # STEP 2: OPEN A WRITTEN (NAKED) OPTION (sell_to_open)
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print_step_header("STEP 2: SELL TO OPEN NAKED PUT OPTION (20% MARGIN)")
    # NIFTY 23,000 Put, Lot size = 65, Expiry = 2026-09-29
    put_contract = get_or_create_contract(
        db=db,
        market="IN",
        underlying="NIFTY",
        instrument_type="option",
        option_type="put",
        strike_price=23000.0,
        expiry_date=date(2026, 9, 29),
        lot_size=65,
    )
    # Sell 1 lot naked @ â‚¹100 premium, NIFTY spot = â‚¹23,000
    # Notional = 23,000 * 65 = â‚¹14,95,000
    # 20% Initial Margin = 0.20 * 14,95,000 = â‚¹2,99,000
    # Premium Credit = 100 * 65 = +â‚¹6,500
    order_sell_put = place_derivative_order(
        db=db,
        wallet=wallet,
        contract=put_contract,
        side="sell",
        action="sell_to_open",
        quantity=1.0,
        fill_price=100.0,
        underlying_price=23000.0,
    )
    db.refresh(wallet)
    print(f"Order:                     #{order_sell_put.id} {order_sell_put.action} {order_sell_put.quantity} lot(s) @ â‚¹{order_sell_put.executed_price} [{order_sell_put.status}]")
    print(f"Premium Credited:          +â‚¹{6500.0:,.2f}")
    print(f"Margin Locked (20%):       â‚¹{order_sell_put.margin_required:,.2f}")
    print(f"Wallet Cash Balance:      â‚¹{wallet.current_cash_balance:,.2f} (Expected â‚¹9,96,750.00)")
    print(f"Margin Used:              â‚¹{wallet.margin_used:,.2f} (Expected â‚¹2,99,000.00)")
    print(f"Available Buying Power:   â‚¹{wallet.available_buying_power:,.2f} (Expected â‚¹6,97,750.00)")

    assert order_sell_put.status == "filled"
    assert wallet.current_cash_balance == 996750.0
    assert wallet.margin_used == 299000.0
    assert wallet.available_buying_power == 697750.0

    pos_put = db.query(DerivativePosition).filter(DerivativePosition.contract_id == put_contract.id).first()
    assert pos_put is not None
    assert pos_put.side == "short"
    assert pos_put.is_covered is False
    assert pos_put.margin_locked == 299000.0
    print("[CONFIRMED] Naked Option: Premium credited, 20% notional initial margin locked.")

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # STEP 3: OPEN A FUTURES POSITION (buy_to_open)
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print_step_header("STEP 3: BUY TO OPEN FUTURES POSITION (12% MARGIN, 0 CASH DEBIT)")
    # NIFTY Index Futures, Lot size = 65, Expiry = 2026-09-29
    fut_contract = get_or_create_contract(
        db=db,
        market="IN",
        underlying="NIFTY",
        instrument_type="future",
        expiry_date=date(2026, 9, 29),
        lot_size=65,
    )
    # Buy 1 lot futures @ â‚¹23,200
    # Notional = 23,200 * 65 = â‚¹15,08,000
    # 12% Initial Margin = 0.12 * 15,08,000 = â‚¹1,80,960
    order_buy_fut = place_derivative_order(
        db=db,
        wallet=wallet,
        contract=fut_contract,
        side="buy",
        action="buy_to_open",
        quantity=1.0,
        fill_price=23200.0,
        settlement_date=date(2026, 9, 20),
    )
    db.refresh(wallet)
    print(f"Order:                     #{order_buy_fut.id} {order_buy_fut.action} {order_buy_fut.quantity} lot(s) @ â‚¹{order_buy_fut.executed_price} [{order_buy_fut.status}]")
    print(f"Futures Notional Value:    â‚¹{1508000.0:,.2f}")
    print(f"Margin Locked (12%):       â‚¹{order_buy_fut.margin_required:,.2f}")
    print(f"Wallet Cash Balance:      â‚¹{wallet.current_cash_balance:,.2f} (UNCHANGED, Expected â‚¹9,96,750.00)")
    print(f"Margin Used:              â‚¹{wallet.margin_used:,.2f} (Expected â‚¹4,79,960.00)")
    print(f"Available Buying Power:   â‚¹{wallet.available_buying_power:,.2f} (Expected â‚¹5,16,790.00)")

    assert order_buy_fut.status == "filled"
    assert wallet.current_cash_balance == 996750.0  # 0 cash debited for notional!
    assert wallet.margin_used == 299000.0 + 180960.0  # â‚¹4,79,960.00
    assert wallet.available_buying_power == 996750.0 - 479960.0  # â‚¹5,16,790.00

    pos_fut = db.query(DerivativePosition).filter(DerivativePosition.contract_id == fut_contract.id).first()
    assert pos_fut is not None
    assert pos_fut.side == "long"
    assert pos_fut.quantity == 1.0
    assert pos_fut.entry_price == 23200.0
    assert pos_fut.last_mtm_price == 23200.0
    assert pos_fut.margin_locked == 180960.0
    print("[CONFIRMED] Futures: 0 cash debit, 12% margin locked into single pooled wallet.margin_used.")

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # STEP 4: RUN DAILY MARK-TO-MARKET (MTM) SETTLEMENT
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print_step_header("STEP 4: RUN DAILY FUTURES MTM SETTLEMENT")
    # Next day (2026-09-21): NIFTY Futures mark price rises from 23,200 to 23,300 (+100 points)
    # Cash MTM gain = (23,300 - 23,200) * 65 = +â‚¹6,500
    mtm_txns = evaluate_daily_futures_mtm(
        db=db,
        mark_prices={fut_contract.symbol: 23300.0},
        settlement_date=date(2026, 9, 21),
    )
    db.refresh(wallet)
    db.refresh(pos_fut)
    print(f"MTM Settlement Transactions: {len(mtm_txns)}")
    txn_mtm = mtm_txns[0]
    print(f"Transaction Type:          {txn_mtm.transaction_type}")
    print(f"MTM Cash Adjustment:       +â‚¹{txn_mtm.amount:,.2f}")
    print(f"Wallet Cash Balance After: â‚¹{wallet.current_cash_balance:,.2f} (Expected â‚¹10,03,250.00)")
    print(f"Margin Used:              â‚¹{wallet.margin_used:,.2f} (STAYS LOCKED at â‚¹4,79,960.00)")
    print(f"Position Status:           Open (quantity={pos_fut.quantity}, last_mtm_price=â‚¹{pos_fut.last_mtm_price})")

    assert len(mtm_txns) == 1
    assert txn_mtm.transaction_type == "mtm_settlement"
    assert txn_mtm.amount == 6500.0
    assert wallet.current_cash_balance == 996750.0 + 6500.0  # â‚¹10,03,250.00
    assert wallet.margin_used == 479960.0  # Margin stays locked!
    assert pos_fut.quantity == 1.0         # Position stays open!
    assert pos_fut.last_mtm_price == 23300.0
    assert pos_fut.last_mtm_date == date(2026, 9, 21)
    print("[CONFIRMED] Daily MTM: Cash credited directly, position stays open, margin stays locked.")

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # STEP 5: RUN EXPIRY CASH SETTLEMENT
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print_step_header("STEP 5: RUN EXPIRY CASH SETTLEMENT ON 2026-09-29")
    # On 2026-09-29, NIFTY underlying closes @ 23,250:
    # 1. Call 23,150: Intrinsic = 23,250 - 23,150 = 100 points -> Payout = 100 * 65 = +â‚¹6,500.
    #    Realized P&L = 6,500 - 9,750 = -â‚¹3,250.
    # 2. Put 23,000 (Written): 23,250 > 23,000 -> OTM, expires worthless!
    #    Payout = â‚¹0. Writer keeps entire â‚¹6,500 premium. Realized P&L = +â‚¹6,500.
    #    Locked margin of â‚¹2,99,000 is released!
    # 3. Futures: Final MTM against 23,250 vs last MTM 23,300 = -50 points.
    #    Cash adjustment = -50 * 65 = -â‚¹3,250.
    #    Locked margin of â‚¹1,80,960 is released!
    exp_txns = evaluate_derivatives_expiry_settlement(
        db=db,
        underlying_prices={"NIFTY": 23250.0},
        settlement_date=date(2026, 9, 29),
    )
    db.refresh(wallet)
    print(f"Expiry Settlement Transactions: {len(exp_txns)}")
    for t in exp_txns:
        print(f" - {t.transaction_type}: cash_flow={t.amount:+,.2f}, realized_pnl={t.realized_pnl:+,.2f}")

    print(f"\nFinal Wallet Cash Balance: â‚¹{wallet.current_cash_balance:,.2f}")
    print(f"Final Margin Used:         â‚¹{wallet.margin_used:,.2f} (ALL RELEASED, Expected â‚¹0.00)")
    print(f"Final Buying Power:        â‚¹{wallet.available_buying_power:,.2f}")

    assert len(exp_txns) == 3
    # Net cash flow: +6,500 (call payout) + 0 (put OTM) - 3,250 (futures final MTM) = +â‚¹3,250
    assert wallet.current_cash_balance == 1003250.0 + 6500.0 - 3250.0  # â‚¹10,06,500.00
    assert wallet.margin_used == 0.0  # All locked margins released!
    assert wallet.available_buying_power == 1006500.0

    remaining_positions = db.query(DerivativePosition).filter(DerivativePosition.wallet_id == wallet.id).count()
    assert remaining_positions == 0
    print("[CONFIRMED] Expiry Settlement: Intrinsic cash payouts completed, 100% margin released, positions closed.")

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # STEP 6: VERIFY FASTAPI ENDPOINTS
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print_step_header("STEP 6: VERIFY FASTAPI HTTP ENDPOINTS")

    # 1. Browse contracts endpoint: GET /api/derivatives/contracts?underlying=NIFTY&type=option
    r_contracts = client.get("/api/derivatives/contracts?underlying=NIFTY&type=option")
    assert r_contracts.status_code == 200
    contracts_list = r_contracts.json()
    print(f"GET /api/derivatives/contracts?underlying=NIFTY&type=option -> {len(contracts_list)} contract(s)")
    assert len(contracts_list) >= 2
    for c in contracts_list:
        print(f" - Contract #{c['id']}: {c['symbol']} (strike={c['strike_price']}, expiry={c['expiry_date']})")

    # 2. Place an order via HTTP: POST /api/derivatives/order
    r_order = client.post(
        "/api/derivatives/order",
        json={
            "market": "IN",
            "contract_id": call_contract.id,
            "side": "buy",
            "action": "buy_to_open",
            "quantity": 1.0,
            "order_type": "limit",
            "price": 120.0,
        },
    )
    assert r_order.status_code == 201
    order_res = r_order.json()
    print(f"\nPOST /api/derivatives/order -> #{order_res['id']} {order_res['action']} status={order_res['status']} price={order_res['executed_price']}")
    assert order_res["status"] == "filled"

    # 3. Check open positions endpoint: GET /api/derivatives/positions/IN
    r_positions = client.get("/api/derivatives/positions/IN")
    assert r_positions.status_code == 200
    pos_list = r_positions.json()
    print(f"\nGET /api/derivatives/positions/IN -> {len(pos_list)} active position(s)")
    assert len(pos_list) == 1
    p = pos_list[0]
    print(f" - Position: {p['contract']['symbol']} qty={p['quantity']} entry={p['entry_price']} current={p['current_price']} pnl={p['unrealized_pnl']}")
    assert p["side"] == "long"
    assert p["quantity"] == 1.0

    print("\n" + "=" * 75)
    print("  ALL PHASE 6c WORKFLOW CHECKS & HTTP ENDPOINTS VERIFIED SUCCESSFULLY!")
    print("=" * 75)


if __name__ == "__main__":
    run_full_verification()

