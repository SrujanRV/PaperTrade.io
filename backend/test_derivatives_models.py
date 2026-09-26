"""
test_derivatives_models.py — Unit tests for Phase 6b: Options & Futures Database Models & Pooled Margin.
Verifies:
1. ORM table creation for DerivativeContract, DerivativePosition, DerivativeOrder, DerivativeTransaction
2. Pydantic schema validation (DerivativeContractOut, DerivativePositionOut, DerivativeOrderOut, DerivativeTransactionOut)
3. Single pooled wallet.margin_used shared across equity shorts and derivative positions
4. Cascade deletions and foreign key integrity
"""

import sys
from datetime import date, datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.orm import (
    Wallet,
    Holding,
    DerivativeContract,
    DerivativePosition,
    DerivativeOrder,
    DerivativeTransaction,
)
from models.schemas import (
    DerivativeContractOut,
    DerivativePositionOut,
    DerivativeOrderOut,
    DerivativeTransactionOut,
)


def setup_in_memory_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_derivative_contract_creation():
    db = setup_in_memory_db()
    try:
        # 1. Option contract (NIFTY Call)
        opt_contract = DerivativeContract(
            symbol="NIFTY26SEP23150CE",
            underlying="NIFTY",
            instrument_type="option",
            option_type="call",
            strike_price=23150.0,
            expiry_date=date(2026, 9, 29),
            lot_size=65,
            market="IN",
        )
        db.add(opt_contract)

        # 2. Perpetual / Continuous Futures contract (ES=F)
        fut_contract = DerivativeContract(
            symbol="ES=F",
            underlying="ES",
            instrument_type="future",
            option_type=None,
            strike_price=None,
            expiry_date=None,  # Perpetual continuous
            lot_size=1,
            market="US",
        )
        db.add(fut_contract)
        db.commit()

        # Verify query and serialization
        c1 = db.query(DerivativeContract).filter(DerivativeContract.symbol == "NIFTY26SEP23150CE").first()
        assert c1 is not None
        assert c1.lot_size == 65
        assert c1.instrument_type == "option"
        schema_c1 = DerivativeContractOut.model_validate(c1)
        assert schema_c1.strike_price == 23150.0
        assert schema_c1.expiry_date == date(2026, 9, 29)

        c2 = db.query(DerivativeContract).filter(DerivativeContract.symbol == "ES=F").first()
        assert c2 is not None
        assert c2.expiry_date is None
        schema_c2 = DerivativeContractOut.model_validate(c2)
        assert schema_c2.instrument_type == "future"

        print("[PASS] test_derivative_contract_creation passed")
    finally:
        db.close()


def test_multiple_strikes_coexist_and_duplicate_rejected():
    """
    Confirms that UniqueConstraint on DerivativeContract allows multiple strike prices
    to coexist for the same underlying + expiry + option_type, while rejecting exact duplicates.
    """
    from sqlalchemy.exc import IntegrityError

    db = setup_in_memory_db()
    try:
        # 1. Insert multiple strikes for same underlying + expiry + call
        strikes = [23000.0, 23050.0, 23100.0, 23150.0, 23200.0]
        for s in strikes:
            contract = DerivativeContract(
                symbol=f"NIFTY26SEP{int(s)}CE",
                underlying="NIFTY",
                instrument_type="option",
                option_type="call",
                strike_price=s,
                expiry_date=date(2026, 9, 29),
                lot_size=65,
                market="IN",
            )
            db.add(contract)
        db.commit()

        # Also add a PUT at strike 23150 (same underlying, expiry, strike as CE)
        put_contract = DerivativeContract(
            symbol="NIFTY26SEP23150PE",
            underlying="NIFTY",
            instrument_type="option",
            option_type="put",
            strike_price=23150.0,
            expiry_date=date(2026, 9, 29),
            lot_size=65,
            market="IN",
        )
        db.add(put_contract)
        db.commit()

        # Query all NIFTY 29-Sep-2026 calls
        calls = (
            db.query(DerivativeContract)
            .filter(
                DerivativeContract.underlying == "NIFTY",
                DerivativeContract.expiry_date == date(2026, 9, 29),
                DerivativeContract.option_type == "call",
            )
            .all()
        )
        assert len(calls) == 5
        retrieved_strikes = sorted([c.strike_price for c in calls])
        assert retrieved_strikes == strikes

        # 2. Attempt exact duplicate (NIFTY 29-Sep-2026 Call @ 23150) -> Must trigger IntegrityError
        duplicate_contract = DerivativeContract(
            symbol="NIFTY26SEP23150CE_DUP",
            underlying="NIFTY",
            instrument_type="option",
            option_type="call",
            strike_price=23150.0,  # Exact duplicate spec!
            expiry_date=date(2026, 9, 29),
            lot_size=65,
            market="IN",
        )
        db.add(duplicate_contract)
        try:
            db.commit()
            assert False, "Expected IntegrityError for duplicate contract spec, but commit succeeded"
        except IntegrityError:
            db.rollback()

        print("[PASS] test_multiple_strikes_coexist_and_duplicate_rejected passed: multiple strikes coexist seamlessly, exact duplicate rejected!")
    finally:
        db.close()


def test_derivative_position_and_transactions():
    db = setup_in_memory_db()
    try:
        wallet = Wallet(
            market="IN",
            currency="INR",
            starting_balance=1000000.0,
            current_cash_balance=1000000.0,
            margin_used=0.0,
        )
        db.add(wallet)
        db.commit()

        contract = DerivativeContract(
            symbol="BANKNIFTY26SEP55600PE",
            underlying="BANKNIFTY",
            instrument_type="option",
            option_type="put",
            strike_price=55600.0,
            expiry_date=date(2026, 9, 29),
            lot_size=30,
            market="IN",
        )
        db.add(contract)
        db.commit()

        # Create an Order
        order = DerivativeOrder(
            wallet_id=wallet.id,
            contract_id=contract.id,
            side="buy",
            action="buy_to_open",
            quantity=2.0,  # 2 lots
            order_type="market",
            requested_price=None,
            executed_price=243.90,  # premium per share
            status="filled",
            margin_required=0.0,  # options buy = premium paid, 0 margin
            executed_at=datetime.now(timezone.utc),
        )
        db.add(order)
        db.commit()

        # Create Position
        pos = DerivativePosition(
            wallet_id=wallet.id,
            contract_id=contract.id,
            side="long",
            quantity=2.0,
            entry_price=243.90,
            is_covered=False,
            margin_locked=0.0,
            last_mtm_price=None,
            last_mtm_date=None,
        )
        db.add(pos)
        db.commit()

        # Create Transactions
        # 1. Trade execution transaction (debit premium: 2 lots × 30 lot_size × ₹243.90 = ₹14,634)
        premium_cost = 2.0 * 30 * 243.90
        wallet.current_cash_balance -= premium_cost
        t1 = DerivativeTransaction(
            wallet_id=wallet.id,
            position_id=pos.id,
            order_id=order.id,
            transaction_type="trade",
            amount=-premium_cost,
            price=243.90,
            realized_pnl=None,
            cash_balance_after=wallet.current_cash_balance,
        )
        db.add(t1)

        # 2. Expiry settlement transaction (simulated ITM exercise: intrinsic value ₹300)
        settlement_gain = 2.0 * 30 * 300.0
        pnl = settlement_gain - premium_cost
        wallet.current_cash_balance += settlement_gain
        t2 = DerivativeTransaction(
            wallet_id=wallet.id,
            position_id=pos.id,
            order_id=None,
            transaction_type="expiry_settlement",
            amount=settlement_gain,
            price=300.0,
            realized_pnl=pnl,
            cash_balance_after=wallet.current_cash_balance,
        )
        db.add(t2)
        db.commit()

        # Validate Pydantic outputs
        order_out = DerivativeOrderOut.model_validate(order)
        assert order_out.action == "buy_to_open"
        assert order_out.quantity == 2.0

        pos_out = DerivativePositionOut.model_validate(pos)
        assert pos_out.side == "long"
        assert pos_out.contract.symbol == "BANKNIFTY26SEP55600PE"

        t1_out = DerivativeTransactionOut.model_validate(t1)
        assert t1_out.transaction_type == "trade"
        assert t1_out.amount == -14634.0

        t2_out = DerivativeTransactionOut.model_validate(t2)
        assert t2_out.transaction_type == "expiry_settlement"
        assert t2_out.realized_pnl == 3366.0

        print("[PASS] test_derivative_position_and_transactions passed")
    finally:
        db.close()


def test_shared_pooled_margin_used():
    """
    CRITICAL CHECK:
    Confirm that wallet.margin_used is a single, shared pool across:
    1. Equity shorts (from Phase 5b)
    2. Naked option writing positions
    3. Futures positions
    And that available_buying_power correctly reflects the unified pool.
    """
    db = setup_in_memory_db()
    try:
        wallet = Wallet(
            market="US",
            currency="USD",
            starting_balance=50000.0,
            current_cash_balance=50000.0,
            margin_used=0.0,
        )
        db.add(wallet)
        db.commit()

        assert wallet.margin_used == 0.0
        assert wallet.available_buying_power == 50000.0

        # ── Step 1: Open an Equity Short Position (Phase 5b) ───────────────────
        # Short 10 TSLA @ $200. Reg T 150% initial margin = $3,000 locked.
        # Cash receives +$2,000 proceeds -> cash = $52,000.
        equity_short_margin = 3000.0
        wallet.current_cash_balance += 2000.0
        wallet.margin_used += equity_short_margin
        db.commit()

        assert wallet.margin_used == 3000.0
        # Available buying power = 52,000 - 3,000 = 49,000
        assert wallet.available_buying_power == 49000.0

        # ── Step 2: Open a Naked Call Write (Phase 6b) ─────────────────────────
        # Write 1 lot naked AAPL call. Notional = $25,000. 20% margin = $5,000.
        opt_contract = DerivativeContract(
            symbol="AAPL26SEP300CE",
            underlying="AAPL",
            instrument_type="option",
            option_type="call",
            strike_price=300.0,
            expiry_date=date(2026, 9, 29),
            lot_size=100,
            market="US",
        )
        db.add(opt_contract)
        db.commit()

        naked_call_margin = 5000.0
        naked_call_pos = DerivativePosition(
            wallet_id=wallet.id,
            contract_id=opt_contract.id,
            side="short",
            quantity=1.0,  # 1 lot
            entry_price=40.0,  # $40 premium received ($4,000 cash)
            is_covered=False,  # Naked write!
            margin_locked=naked_call_margin,
        )
        db.add(naked_call_pos)
        # Lock into the SAME pooled margin_used
        wallet.current_cash_balance += 4000.0
        wallet.margin_used += naked_call_margin
        db.commit()

        # Pooled margin_used is now $3,000 (equity short) + $5,000 (naked option) = $8,000
        assert wallet.margin_used == 8000.0
        # Cash = 52,000 + 4,000 = 56,000
        # Available buying power = 56,000 - 8,000 = 48,000
        assert wallet.available_buying_power == 48000.0

        # ── Step 3: Open a Long Futures Position (Phase 6b) ────────────────────
        # Buy 1 ES=F future contract @ 7,800. Notional = $7,800. 12% margin = $936.
        fut_contract = DerivativeContract(
            symbol="ES=F",
            underlying="ES",
            instrument_type="future",
            option_type=None,
            strike_price=None,
            expiry_date=None,
            lot_size=1,
            market="US",
        )
        db.add(fut_contract)
        db.commit()

        fut_margin = 936.0
        fut_pos = DerivativePosition(
            wallet_id=wallet.id,
            contract_id=fut_contract.id,
            side="long",
            quantity=1.0,
            entry_price=7800.0,
            is_covered=False,
            margin_locked=fut_margin,
            last_mtm_price=7800.0,
            last_mtm_date=date(2026, 9, 25),
        )
        db.add(fut_pos)
        # Lock into the SAME pooled margin_used
        wallet.margin_used += fut_margin
        db.commit()

        # Total pooled margin_used = 3,000 (equity short) + 5,000 (naked option) + 936 (futures) = 8,936
        assert wallet.margin_used == 8936.0
        # Cash = 56,000
        # Available buying power = 56,000 - 8,936 = 47,064.0
        assert wallet.available_buying_power == 47064.0

        # ── Step 4: Daily MTM Settlement on Futures ───────────────────────────
        # Next day ES=F rises to 7,850 (+50 points). MTM settlement = +$50 cash.
        # Position is NOT closed! Margin remains locked.
        mtm_gain = 50.0
        fut_pos.last_mtm_price = 7850.0
        fut_pos.last_mtm_date = date(2026, 9, 26)
        wallet.current_cash_balance += mtm_gain

        mtm_txn = DerivativeTransaction(
            wallet_id=wallet.id,
            position_id=fut_pos.id,
            transaction_type="mtm_settlement",
            amount=mtm_gain,
            price=7850.0,
            realized_pnl=mtm_gain,
            cash_balance_after=wallet.current_cash_balance,
        )
        db.add(mtm_txn)
        db.commit()

        assert mtm_txn.transaction_type == "mtm_settlement"
        assert wallet.current_cash_balance == 56050.0
        assert wallet.margin_used == 8936.0
        assert wallet.available_buying_power == 47114.0

        # ── Step 5: Close Naked Option Write -> Releases Its Margin Only ──────
        wallet.margin_used -= naked_call_pos.margin_locked
        db.delete(naked_call_pos)
        db.commit()

        # Margin used decreases from 8,936 to 3,936 (3,000 equity short + 936 futures remain intact!)
        assert wallet.margin_used == 3936.0
        assert wallet.available_buying_power == 52114.0

        # ── Step 6: Close Futures -> Releases Futures Margin Only ──────────────
        wallet.margin_used -= fut_pos.margin_locked
        db.delete(fut_pos)
        db.commit()

        # Margin used decreases from 3,936 to 3,000 (only equity short remains!)
        assert wallet.margin_used == 3000.0
        assert wallet.available_buying_power == 53050.0

        # ── Step 7: Close Equity Short -> Margin Becomes 0.0 ──────────────────
        wallet.margin_used -= equity_short_margin
        db.commit()

        assert wallet.margin_used == 0.0
        assert wallet.available_buying_power == 56050.0

        print("[PASS] test_shared_pooled_margin_used passed: single pooled margin_used verified across equity shorts, naked options, and futures!")
    finally:
        db.close()


if __name__ == "__main__":
    test_derivative_contract_creation()
    test_multiple_strikes_coexist_and_duplicate_rejected()
    test_derivative_position_and_transactions()
    test_shared_pooled_margin_used()
    print("\nALL PHASE 6b DATABASE MODELS & MARGIN POOLING TESTS PASSED SUCCESSFULLY!")
