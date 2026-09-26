"""
services/derivatives_engine.py — Core execution engine for Options and Futures.

Handles:
1. Options Trading:
   - buy_to_open:  Pay premium upfront, 0 margin, cash deduction.
   - sell_to_close: Exit long option, credit premium proceeds, record realized P&L.
   - sell_to_open:  Write option. Covered if holding >= qty * lot_size (0 margin).
                    Naked write: 20% initial margin, 15% maintenance margin, credit premium.
   - buy_to_close:  Cover written option, debit buyback cost, record P&L, release margin.
2. Futures Trading:
   - Margin-based from 1st trade: 12% initial margin, 10% maintenance margin.
   - buy_to_open / sell_to_open: Locks margin, 0 cash debit.
   - sell_to_close / buy_to_close: Adjusts cash by P&L since last MTM, releases margin.
3. Daily Mark-to-Market (MTM) Settlement:
   - Futures positions: mark against settlement price, cash credit/debit directly,
     updates last_mtm_price and last_mtm_date without closing position.
   - US continuous futures (ES=F, CL=F, etc.): perpetual MTM, no forced expiry.
4. Expiry Cash Settlement:
   - Options: cash-settled using intrinsic value (call: max(0, S - K), put: max(0, K - S)).
   - Indian index futures: final MTM against underlying index price, full margin release.
5. Maintenance Margin & Liquidation:
   - Monitors naked written options (15% maint) and futures (10% maint).
   - Force-liquidates positions breaching maintenance threshold.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from sqlalchemy.orm import Session

from models.orm import (
    Wallet,
    Holding,
    DerivativeContract,
    DerivativePosition,
    DerivativeOrder,
    DerivativeTransaction,
)
from models.schemas import DerivativeOrderRequest
from services.price_feed import PriceQuote, get_quote

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _today_date() -> date:
    return datetime.now(timezone.utc).date()


# Default lot sizes (SEBI late 2025/2026 revisions)
DEFAULT_LOT_SIZES = {
    "NIFTY": 65,      # SEBI contract sizing mandate (65 x ~23,150 ≈ ₹15L)
    "BANKNIFTY": 30,  # SEBI mandate (30 x ~55,600 ≈ ₹16.7L)
    "FINNIFTY": 60,
    "MIDCPNIFTY": 120,
}


# ══════════════════════════════════════════════════════════════════════════════
# Contract Management Helper
# ══════════════════════════════════════════════════════════════════════════════

def get_or_create_contract(
    db: Session,
    market: str,
    underlying: str,
    instrument_type: str,
    option_type: str | None = None,
    strike_price: float | None = None,
    expiry_date: date | None = None,
    lot_size: int | None = None,
    symbol: str | None = None,
) -> DerivativeContract:
    """
    Finds existing contract matching the specification or creates a new one.
    """
    m = market.upper()
    und = underlying.upper()
    inst = instrument_type.lower()
    opt = option_type.lower() if option_type else None
    strike = round(strike_price, 2) if strike_price is not None else None

    # Determine default lot size if not supplied
    if lot_size is None or lot_size <= 0:
        if und in DEFAULT_LOT_SIZES:
            lot_size = DEFAULT_LOT_SIZES[und]
        elif m == "US" and inst == "option":
            lot_size = 100
        else:
            lot_size = 1

    query = (
        db.query(DerivativeContract)
        .filter(
            DerivativeContract.market == m,
            DerivativeContract.underlying == und,
            DerivativeContract.instrument_type == inst,
            DerivativeContract.option_type == opt,
            DerivativeContract.strike_price == strike,
            DerivativeContract.expiry_date == expiry_date,
        )
    )
    existing = query.first()
    if existing:
        return existing

    # Auto-generate symbol if not provided
    if not symbol:
        if inst == "future":
            if expiry_date:
                symbol = f"{und}-{expiry_date.strftime('%d%b%y').upper()}-FUT"
            else:
                symbol = f"{und}=F" if not und.endswith("=F") else und
        else:
            exp_str = expiry_date.strftime('%d%b%y').upper() if expiry_date else "PERP"
            symbol = f"{und}-{exp_str}-{int(strike) if strike.is_integer() else strike}-{opt.upper()}"

    contract = DerivativeContract(
        symbol=symbol,
        underlying=und,
        instrument_type=inst,
        option_type=opt,
        strike_price=strike,
        expiry_date=expiry_date,
        lot_size=lot_size,
        market=m,
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    logger.info("Created DerivativeContract #%d: %s (%s %s)", contract.id, contract.symbol, m, inst)
    return contract


# ══════════════════════════════════════════════════════════════════════════════
# Covered Options Verification
# ══════════════════════════════════════════════════════════════════════════════

def is_covered_option(
    db: Session,
    wallet_id: int,
    contract: DerivativeContract,
    quantity_lots: float,
) -> bool:
    """
    Checks if writing this option contract is fully covered by underlying equity holdings.
    - Call: User holds long shares >= quantity_lots * contract.lot_size.
    """
    if contract.instrument_type != "option":
        return False

    required_shares = quantity_lots * contract.lot_size
    holding = (
        db.query(Holding)
        .filter(
            Holding.wallet_id == wallet_id,
            Holding.ticker == contract.underlying,
            Holding.is_short == False,
        )
        .first()
    )
    if holding and holding.quantity >= required_shares:
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# Order Placement Engine
# ══════════════════════════════════════════════════════════════════════════════

def _persist_rejected_order(
    db: Session,
    wallet_id: int,
    contract_id: int,
    side: str,
    action: str,
    quantity: float,
    reason: str,
    order_type: str = "market",
    requested_price: float | None = None,
    margin_required: float = 0.0,
    triggered_by: str | None = None,
) -> DerivativeOrder:
    order = DerivativeOrder(
        wallet_id=wallet_id,
        contract_id=contract_id,
        side=side,
        action=action,
        quantity=quantity,
        order_type=order_type,
        requested_price=requested_price,
        executed_price=None,
        status="rejected",
        reject_reason=reason,
        margin_required=margin_required,
        triggered_by=triggered_by,
        executed_at=None,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    logger.warning("DerivativeOrder #%d REJECTED: %s %s lots of contract #%d | reason=%s", order.id, action, quantity, contract_id, reason)
    return order


def place_derivative_order(
    db: Session,
    wallet: Wallet,
    contract: DerivativeContract,
    side: Literal["buy", "sell"],
    action: Literal["buy_to_open", "sell_to_open", "buy_to_close", "sell_to_close"],
    quantity: float,
    order_type: Literal["market", "limit"] = "market",
    requested_price: float | None = None,
    fill_price: float | None = None,
    underlying_price: float | None = None,
    settlement_date: date | None = None,
    triggered_by: str | None = None,
) -> DerivativeOrder:
    """
    Executes an Options or Futures order with strict margin & premium validation.
    """
    if quantity <= 0:
        raise ValueError(f"Quantity must be greater than 0, got {quantity}")

    # Validate action vs side consistency
    if side == "buy" and action not in ("buy_to_open", "buy_to_close"):
        raise ValueError(f"Invalid action '{action}' for buy side order")
    if side == "sell" and action not in ("sell_to_open", "sell_to_close"):
        raise ValueError(f"Invalid action '{action}' for sell side order")

    # Resolve fill price
    if fill_price is None or fill_price <= 0:
        if order_type == "limit" and requested_price and requested_price > 0:
            fill_price = requested_price
        else:
            # Look up live price quote for the contract symbol or underlying
            quote = get_quote(contract.symbol)
            if quote and quote.price > 0:
                fill_price = quote.price
            else:
                # If option without direct quote, fallback to requested_price
                if requested_price and requested_price > 0:
                    fill_price = requested_price
                else:
                    return _persist_rejected_order(
                        db, wallet.id, contract.id, side, action, quantity,
                        "unresolvable_price", order_type, requested_price
                    )

    # Resolve underlying price (used for naked option notional calculation)
    if underlying_price is None or underlying_price <= 0:
        und_quote = get_quote(contract.underlying)
        if und_quote and und_quote.price > 0:
            underlying_price = und_quote.price
        else:
            underlying_price = contract.strike_price or fill_price

    total_units = quantity * contract.lot_size
    curr_date = settlement_date or _today_date()

    # ──────────────────────────────────────────────────────────────────────────
    # CASE 1: OPTIONS BUYING — buy_to_open
    # ──────────────────────────────────────────────────────────────────────────
    if contract.instrument_type == "option" and action == "buy_to_open":
        premium_cost = round(fill_price * total_units, 2)
        if wallet.current_cash_balance < premium_cost:
            return _persist_rejected_order(
                db, wallet.id, contract.id, side, action, quantity,
                "insufficient_funds", order_type, requested_price, margin_required=0.0
            )

        # Deduct upfront premium from cash
        wallet.current_cash_balance = round(wallet.current_cash_balance - premium_cost, 2)

        order = DerivativeOrder(
            wallet_id=wallet.id,
            contract_id=contract.id,
            side="buy",
            action="buy_to_open",
            quantity=quantity,
            order_type=order_type,
            requested_price=requested_price,
            executed_price=fill_price,
            status="filled",
            margin_required=0.0,
            triggered_by=triggered_by,
            executed_at=_now_utc(),
        )
        db.add(order)
        db.flush()

        # Update or create position
        pos = (
            db.query(DerivativePosition)
            .filter(
                DerivativePosition.wallet_id == wallet.id,
                DerivativePosition.contract_id == contract.id,
                DerivativePosition.side == "long",
            )
            .first()
        )
        if pos:
            new_qty = pos.quantity + quantity
            new_entry = ((pos.quantity * pos.entry_price) + (quantity * fill_price)) / new_qty
            pos.quantity = new_qty
            pos.entry_price = round(new_entry, 6)
        else:
            pos = DerivativePosition(
                wallet_id=wallet.id,
                contract_id=contract.id,
                side="long",
                quantity=quantity,
                entry_price=fill_price,
                is_covered=False,
                margin_locked=0.0,
            )
            db.add(pos)
        db.flush()

        txn = DerivativeTransaction(
            wallet_id=wallet.id,
            position_id=pos.id,
            order_id=order.id,
            transaction_type="trade",
            amount=-premium_cost,
            price=fill_price,
            realized_pnl=None,
            cash_balance_after=wallet.current_cash_balance,
            timestamp=_now_utc(),
        )
        db.add(txn)
        db.commit()
        db.refresh(order)
        logger.info("BUY TO OPEN Option filled: %s %s lots @ %.2f premium=%.2f | cash_after=%.2f", contract.symbol, quantity, fill_price, premium_cost, wallet.current_cash_balance)
        return order

    # ──────────────────────────────────────────────────────────────────────────
    # CASE 2: OPTIONS EXIT LONG — sell_to_close
    # ──────────────────────────────────────────────────────────────────────────
    elif contract.instrument_type == "option" and action == "sell_to_close":
        pos = (
            db.query(DerivativePosition)
            .filter(
                DerivativePosition.wallet_id == wallet.id,
                DerivativePosition.contract_id == contract.id,
                DerivativePosition.side == "long",
            )
            .first()
        )
        if not pos or pos.quantity <= 1e-9:
            return _persist_rejected_order(
                db, wallet.id, contract.id, side, action, quantity,
                "no_position_to_close", order_type, requested_price, triggered_by=triggered_by
            )

        closing_qty = min(quantity, pos.quantity)
        closing_units = closing_qty * contract.lot_size
        proceeds = round(fill_price * closing_units, 2)
        cost_basis = round(pos.entry_price * closing_units, 2)
        pnl = round(proceeds - cost_basis, 2)

        wallet.current_cash_balance = round(wallet.current_cash_balance + proceeds, 2)

        order = DerivativeOrder(
            wallet_id=wallet.id,
            contract_id=contract.id,
            side="sell",
            action="sell_to_close",
            quantity=closing_qty,
            order_type=order_type,
            requested_price=requested_price,
            executed_price=fill_price,
            status="filled",
            margin_required=0.0,
            triggered_by=triggered_by,
            executed_at=_now_utc(),
        )
        db.add(order)
        db.flush()

        pos_id = pos.id
        pos.quantity = round(pos.quantity - closing_qty, 8)
        if pos.quantity <= 1e-9:
            db.delete(pos)

        txn = DerivativeTransaction(
            wallet_id=wallet.id,
            position_id=pos_id if pos.quantity > 1e-9 else None,
            order_id=order.id,
            transaction_type="trade",
            amount=proceeds,
            price=fill_price,
            realized_pnl=pnl,
            cash_balance_after=wallet.current_cash_balance,
            timestamp=_now_utc(),
        )
        db.add(txn)
        db.commit()
        db.refresh(order)
        logger.info("SELL TO CLOSE Option filled: %s %s lots @ %.2f proceeds=%.2f pnl=%.2f", contract.symbol, closing_qty, fill_price, proceeds, pnl)
        return order

    # ──────────────────────────────────────────────────────────────────────────
    # CASE 3: OPTIONS WRITING / SHORT — sell_to_open
    # ──────────────────────────────────────────────────────────────────────────
    elif contract.instrument_type == "option" and action == "sell_to_open":
        is_cov = is_covered_option(db, wallet.id, contract, quantity)
        if is_cov:
            initial_margin = 0.0
            margin_to_lock = 0.0
        else:
            # Naked option write: 20% initial margin on notional value
            notional = round(underlying_price * total_units, 2)
            initial_margin = round(0.20 * notional, 2)
            margin_to_lock = initial_margin

            if wallet.available_buying_power < initial_margin:
                return _persist_rejected_order(
                    db, wallet.id, contract.id, side, action, quantity,
                    "insufficient_margin", order_type, requested_price, margin_required=initial_margin,
                    triggered_by=triggered_by,
                )

        premium_credit = round(fill_price * total_units, 2)
        # Credit premium cash and lock margin
        wallet.current_cash_balance = round(wallet.current_cash_balance + premium_credit, 2)
        wallet.margin_used = round(wallet.margin_used + margin_to_lock, 2)

        order = DerivativeOrder(
            wallet_id=wallet.id,
            contract_id=contract.id,
            side="sell",
            action="sell_to_open",
            quantity=quantity,
            order_type=order_type,
            requested_price=requested_price,
            executed_price=fill_price,
            status="filled",
            margin_required=initial_margin,
            triggered_by=triggered_by,
            executed_at=_now_utc(),
        )
        db.add(order)
        db.flush()

        pos = (
            db.query(DerivativePosition)
            .filter(
                DerivativePosition.wallet_id == wallet.id,
                DerivativePosition.contract_id == contract.id,
                DerivativePosition.side == "short",
            )
            .first()
        )
        if pos:
            new_qty = pos.quantity + quantity
            new_entry = ((pos.quantity * pos.entry_price) + (quantity * fill_price)) / new_qty
            pos.quantity = new_qty
            pos.entry_price = round(new_entry, 6)
            pos.margin_locked = round(pos.margin_locked + margin_to_lock, 2)
            pos.is_covered = pos.is_covered and is_cov
        else:
            pos = DerivativePosition(
                wallet_id=wallet.id,
                contract_id=contract.id,
                side="short",
                quantity=quantity,
                entry_price=fill_price,
                is_covered=is_cov,
                margin_locked=margin_to_lock,
            )
            db.add(pos)
        db.flush()

        txn = DerivativeTransaction(
            wallet_id=wallet.id,
            position_id=pos.id,
            order_id=order.id,
            transaction_type="trade",
            amount=premium_credit,
            price=fill_price,
            realized_pnl=None,
            cash_balance_after=wallet.current_cash_balance,
            timestamp=_now_utc(),
        )
        db.add(txn)
        db.commit()
        db.refresh(order)
        logger.info("SELL TO OPEN Option filled (covered=%s): %s %s lots @ %.2f premium=%.2f margin_locked=%.2f", is_cov, contract.symbol, quantity, fill_price, premium_credit, margin_to_lock)
        return order

    # ──────────────────────────────────────────────────────────────────────────
    # CASE 4: OPTIONS COVER SHORT — buy_to_close
    # ──────────────────────────────────────────────────────────────────────────
    elif contract.instrument_type == "option" and action == "buy_to_close":
        pos = (
            db.query(DerivativePosition)
            .filter(
                DerivativePosition.wallet_id == wallet.id,
                DerivativePosition.contract_id == contract.id,
                DerivativePosition.side == "short",
            )
            .first()
        )
        if not pos or pos.quantity <= 1e-9:
            return _persist_rejected_order(
                db, wallet.id, contract.id, side, action, quantity,
                "no_position_to_close", order_type, requested_price,
                triggered_by=triggered_by,
            )

        closing_qty = min(quantity, pos.quantity)
        closing_units = closing_qty * contract.lot_size
        buyback_cost = round(fill_price * closing_units, 2)

        # In forced liquidation, broker force-covers regardless of cash balance
        if triggered_by != "derivative_margin_call" and wallet.current_cash_balance < buyback_cost:
            return _persist_rejected_order(
                db, wallet.id, contract.id, side, action, quantity,
                "insufficient_funds", order_type, requested_price,
                triggered_by=triggered_by,
            )

        wallet.current_cash_balance = round(wallet.current_cash_balance - buyback_cost, 2)
        orig_premium = round(pos.entry_price * closing_units, 2)
        pnl = round(orig_premium - buyback_cost, 2)

        # Release proportional locked margin
        margin_release = round(pos.margin_locked * (closing_qty / pos.quantity), 2) if pos.quantity > 0 else 0.0
        pos.margin_locked = max(0.0, round(pos.margin_locked - margin_release, 2))
        wallet.margin_used = max(0.0, round(wallet.margin_used - margin_release, 2))

        order = DerivativeOrder(
            wallet_id=wallet.id,
            contract_id=contract.id,
            side="buy",
            action="buy_to_close",
            quantity=closing_qty,
            order_type=order_type,
            requested_price=requested_price,
            executed_price=fill_price,
            status="filled",
            margin_required=0.0,
            triggered_by=triggered_by,
            executed_at=_now_utc(),
        )
        db.add(order)
        db.flush()

        pos_id = pos.id
        pos.quantity = round(pos.quantity - closing_qty, 8)
        if pos.quantity <= 1e-9:
            db.delete(pos)

        txn = DerivativeTransaction(
            wallet_id=wallet.id,
            position_id=pos_id if pos.quantity > 1e-9 else None,
            order_id=order.id,
            transaction_type="trade",
            amount=-buyback_cost,
            price=fill_price,
            realized_pnl=pnl,
            cash_balance_after=wallet.current_cash_balance,
            timestamp=_now_utc(),
        )
        db.add(txn)
        db.commit()
        db.refresh(order)
        logger.info("BUY TO CLOSE Option filled: %s %s lots @ %.2f cost=%.2f pnl=%.2f margin_released=%.2f", contract.symbol, closing_qty, fill_price, buyback_cost, pnl, margin_release)
        return order

    # ──────────────────────────────────────────────────────────────────────────
    # CASE 5: FUTURES OPENING — buy_to_open / sell_to_open
    # ──────────────────────────────────────────────────────────────────────────
    elif contract.instrument_type == "future" and action in ("buy_to_open", "sell_to_open"):
        fut_side = "long" if action == "buy_to_open" else "short"
        notional = round(fill_price * total_units, 2)
        initial_margin = round(0.12 * notional, 2)  # 12% initial margin

        if wallet.available_buying_power < initial_margin:
            return _persist_rejected_order(
                db, wallet.id, contract.id, side, action, quantity,
                "insufficient_margin", order_type, requested_price, margin_required=initial_margin,
                triggered_by=triggered_by,
            )

        # Lock initial margin (no cash deduction for notional!)
        wallet.margin_used = round(wallet.margin_used + initial_margin, 2)

        order = DerivativeOrder(
            wallet_id=wallet.id,
            contract_id=contract.id,
            side=side,
            action=action,
            quantity=quantity,
            order_type=order_type,
            requested_price=requested_price,
            executed_price=fill_price,
            status="filled",
            margin_required=initial_margin,
            triggered_by=triggered_by,
            executed_at=_now_utc(),
        )
        db.add(order)
        db.flush()

        pos = (
            db.query(DerivativePosition)
            .filter(
                DerivativePosition.wallet_id == wallet.id,
                DerivativePosition.contract_id == contract.id,
                DerivativePosition.side == fut_side,
            )
            .first()
        )
        if pos:
            new_qty = pos.quantity + quantity
            new_entry = ((pos.quantity * pos.entry_price) + (quantity * fill_price)) / new_qty
            pos.quantity = new_qty
            pos.entry_price = round(new_entry, 6)
            pos.last_mtm_price = round(new_entry, 6)
            pos.last_mtm_date = curr_date
            pos.margin_locked = round(pos.margin_locked + initial_margin, 2)
        else:
            pos = DerivativePosition(
                wallet_id=wallet.id,
                contract_id=contract.id,
                side=fut_side,
                quantity=quantity,
                entry_price=fill_price,
                is_covered=False,
                margin_locked=initial_margin,
                last_mtm_price=fill_price,
                last_mtm_date=curr_date,
            )
            db.add(pos)
        db.flush()

        txn = DerivativeTransaction(
            wallet_id=wallet.id,
            position_id=pos.id,
            order_id=order.id,
            transaction_type="trade",
            amount=0.0,
            price=fill_price,
            realized_pnl=None,
            cash_balance_after=wallet.current_cash_balance,
            timestamp=_now_utc(),
        )
        db.add(txn)
        db.commit()
        db.refresh(order)
        logger.info("OPEN FUTURES %s filled: %s %s lots @ %.2f margin_locked=%.2f", fut_side.upper(), contract.symbol, quantity, fill_price, initial_margin)
        return order

    # ──────────────────────────────────────────────────────────────────────────
    # CASE 6: FUTURES CLOSING — sell_to_close / buy_to_close
    # ──────────────────────────────────────────────────────────────────────────
    elif contract.instrument_type == "future" and action in ("sell_to_close", "buy_to_close"):
        target_side = "long" if action == "sell_to_close" else "short"
        pos = (
            db.query(DerivativePosition)
            .filter(
                DerivativePosition.wallet_id == wallet.id,
                DerivativePosition.contract_id == contract.id,
                DerivativePosition.side == target_side,
            )
            .first()
        )
        if not pos or pos.quantity <= 1e-9:
            return _persist_rejected_order(
                db, wallet.id, contract.id, side, action, quantity,
                "no_position_to_close", order_type, requested_price,
                triggered_by=triggered_by,
            )

        closing_qty = min(quantity, pos.quantity)
        closing_units = closing_qty * contract.lot_size

        # P&L is calculated against last_mtm_price (or entry_price if no prior MTM)
        ref_price = pos.last_mtm_price if pos.last_mtm_price is not None else pos.entry_price
        if target_side == "long":
            pnl = round((fill_price - ref_price) * closing_units, 2)
        else:
            pnl = round((ref_price - fill_price) * closing_units, 2)

        # Cash balance is adjusted by the realized P&L since last MTM
        wallet.current_cash_balance = round(wallet.current_cash_balance + pnl, 2)

        # Release proportional locked margin
        margin_release = round(pos.margin_locked * (closing_qty / pos.quantity), 2) if pos.quantity > 0 else 0.0
        pos.margin_locked = max(0.0, round(pos.margin_locked - margin_release, 2))
        wallet.margin_used = max(0.0, round(wallet.margin_used - margin_release, 2))

        order = DerivativeOrder(
            wallet_id=wallet.id,
            contract_id=contract.id,
            side=side,
            action=action,
            quantity=closing_qty,
            order_type=order_type,
            requested_price=requested_price,
            executed_price=fill_price,
            status="filled",
            margin_required=0.0,
            triggered_by=triggered_by,
            executed_at=_now_utc(),
        )
        db.add(order)
        db.flush()

        pos_id = pos.id
        pos.quantity = round(pos.quantity - closing_qty, 8)
        if pos.quantity <= 1e-9:
            db.delete(pos)

        txn = DerivativeTransaction(
            wallet_id=wallet.id,
            position_id=pos_id if pos.quantity > 1e-9 else None,
            order_id=order.id,
            transaction_type="trade",
            amount=pnl,
            price=fill_price,
            realized_pnl=pnl,
            cash_balance_after=wallet.current_cash_balance,
            timestamp=_now_utc(),
        )
        db.add(txn)
        db.commit()
        db.refresh(order)
        logger.info("CLOSE FUTURES %s filled: %s %s lots @ %.2f pnl=%.2f margin_released=%.2f", target_side.upper(), contract.symbol, closing_qty, fill_price, pnl, margin_release)
        return order

    else:
        raise ValueError(f"Unsupported combination: instrument_type='{contract.instrument_type}' action='{action}'")


# ══════════════════════════════════════════════════════════════════════════════
# Daily Mark-to-Market (MTM) Settlement for Futures
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_daily_futures_mtm(
    db: Session,
    mark_prices: Dict[str, float] | None = None,
    settlement_date: date | None = None,
) -> List[DerivativeTransaction]:
    """
    Executes daily cash mark-to-market settlement for all open futures positions.
    Positions where last_mtm_date < current_date are adjusted:
    - Long:  mtm_gain = (mark_price - last_mtm_price) * qty * lot_size
    - Short: mtm_gain = (last_mtm_price - mark_price) * qty * lot_size
    Cash is credited or debited directly to wallet.current_cash_balance.
    Position remains open; margin remains locked.
    """
    curr_date = settlement_date or _today_date()
    prices = mark_prices or {}

    open_futures = (
        db.query(DerivativePosition)
        .join(DerivativeContract)
        .filter(
            DerivativeContract.instrument_type == "future",
            DerivativePosition.quantity > 0,
        )
        .all()
    )

    settlement_txns: List[DerivativeTransaction] = []

    for pos in open_futures:
        contract = pos.contract
        wallet = pos.wallet

        # Only settle if not already marked today
        if pos.last_mtm_date is not None and pos.last_mtm_date >= curr_date:
            continue

        mark_p = prices.get(contract.symbol)
        if mark_p is None or mark_p <= 0:
            q = get_quote(contract.symbol)
            if q and q.price > 0:
                mark_p = q.price
            else:
                # If no mark price available, skip MTM for this position
                continue

        ref_p = pos.last_mtm_price if pos.last_mtm_price is not None else pos.entry_price
        units = pos.quantity * contract.lot_size

        if pos.side == "long":
            mtm_cash = round((mark_p - ref_p) * units, 2)
        else:
            mtm_cash = round((ref_p - mark_p) * units, 2)

        # Settle directly into wallet cash balance
        wallet.current_cash_balance = round(wallet.current_cash_balance + mtm_cash, 2)
        pos.last_mtm_price = mark_p
        pos.last_mtm_date = curr_date

        txn = DerivativeTransaction(
            wallet_id=wallet.id,
            position_id=pos.id,
            order_id=None,
            transaction_type="mtm_settlement",
            amount=mtm_cash,
            price=mark_p,
            realized_pnl=mtm_cash,
            cash_balance_after=wallet.current_cash_balance,
            timestamp=_now_utc(),
        )
        db.add(txn)
        settlement_txns.append(txn)
        logger.info("MTM SETTLEMENT for %s %s lots of %s: mark=%.2f cash_adj=%+.2f | cash_after=%.2f", pos.side.upper(), pos.quantity, contract.symbol, mark_p, mtm_cash, wallet.current_cash_balance)

    if settlement_txns:
        db.commit()

    return settlement_txns


# ══════════════════════════════════════════════════════════════════════════════
# Expiry Cash Settlement (Options Intrinsic Value & Indian Futures)
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_derivatives_expiry_settlement(
    db: Session,
    underlying_prices: Dict[str, float] | None = None,
    settlement_date: date | None = None,
) -> List[DerivativeTransaction]:
    """
    Cash settles expired options and futures positions:
    - Options: Settled against underlying price using intrinsic value:
      * Call Intrinsic: max(0.0, underlying_price - strike_price)
      * Put Intrinsic:  max(0.0, strike_price - underlying_price)
      Long options receive intrinsic payout (or expire worthless with full premium lost).
      Written options pay intrinsic payout (or keep full premium if OTM) and release locked margin.
    - Indian Index Futures: final MTM against cash index settlement price, releases margin.
    """
    curr_date = settlement_date or _today_date()
    prices = underlying_prices or {}

    due_positions = (
        db.query(DerivativePosition)
        .join(DerivativeContract)
        .filter(
            DerivativeContract.expiry_date.isnot(None),
            DerivativeContract.expiry_date <= curr_date,
            DerivativePosition.quantity > 0,
        )
        .all()
    )

    settlement_txns: List[DerivativeTransaction] = []

    for pos in due_positions:
        contract = pos.contract
        wallet = pos.wallet
        units = pos.quantity * contract.lot_size

        und_price = prices.get(contract.underlying)
        if und_price is None or und_price <= 0:
            q = get_quote(contract.underlying)
            if q and q.price > 0:
                und_price = q.price
            else:
                und_price = contract.strike_price or pos.entry_price

        # ── OPTIONS EXPIRY SETTLEMENT ──────────────────────────────────────────
        if contract.instrument_type == "option":
            strike = contract.strike_price or 0.0
            if contract.option_type == "call":
                intrinsic = max(0.0, round(und_price - strike, 2))
            else:
                intrinsic = max(0.0, round(strike - und_price, 2))

            total_payout = round(intrinsic * units, 2)
            orig_premium = round(pos.entry_price * units, 2)

            if pos.side == "long":
                # Long option holder receives intrinsic cash payout
                wallet.current_cash_balance = round(wallet.current_cash_balance + total_payout, 2)
                pnl = round(total_payout - orig_premium, 2)
                cash_flow = total_payout
            else:
                # Written short option writer pays intrinsic cash payout
                wallet.current_cash_balance = round(wallet.current_cash_balance - total_payout, 2)
                pnl = round(orig_premium - total_payout, 2)
                cash_flow = -total_payout
                # Release locked margin
                wallet.margin_used = max(0.0, round(wallet.margin_used - pos.margin_locked, 2))

            txn = DerivativeTransaction(
                wallet_id=wallet.id,
                position_id=pos.id,
                order_id=None,
                transaction_type="expiry_settlement",
                amount=cash_flow,
                price=und_price,
                realized_pnl=pnl,
                cash_balance_after=wallet.current_cash_balance,
                timestamp=_now_utc(),
            )
            db.add(txn)
            settlement_txns.append(txn)
            logger.info("EXPIRY SETTLEMENT Option %s %s: strike=%.2f und=%.2f IV=%.2f payout=%.2f pnl=%.2f", contract.symbol, pos.side.upper(), strike, und_price, intrinsic, total_payout, pnl)
            db.delete(pos)

        # ── FUTURES EXPIRY SETTLEMENT ─────────────────────────────────────────
        elif contract.instrument_type == "future":
            ref_p = pos.last_mtm_price if pos.last_mtm_price is not None else pos.entry_price
            if pos.side == "long":
                final_mtm = round((und_price - ref_p) * units, 2)
            else:
                final_mtm = round((ref_p - und_price) * units, 2)

            wallet.current_cash_balance = round(wallet.current_cash_balance + final_mtm, 2)
            wallet.margin_used = max(0.0, round(wallet.margin_used - pos.margin_locked, 2))

            txn = DerivativeTransaction(
                wallet_id=wallet.id,
                position_id=pos.id,
                order_id=None,
                transaction_type="expiry_settlement",
                amount=final_mtm,
                price=und_price,
                realized_pnl=final_mtm,
                cash_balance_after=wallet.current_cash_balance,
                timestamp=_now_utc(),
            )
            db.add(txn)
            settlement_txns.append(txn)
            logger.info("EXPIRY SETTLEMENT Futures %s %s: final_p=%.2f final_mtm=%+.2f", contract.symbol, pos.side.upper(), und_price, final_mtm)
            db.delete(pos)

    if settlement_txns:
        db.commit()

    return settlement_txns


# ══════════════════════════════════════════════════════════════════════════════
# Maintenance Margin & Liquidation
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_derivative_margin_calls(
    db: Session,
    current_quotes: Dict[str, PriceQuote] | Dict[str, float] | None = None,
) -> List[DerivativeOrder]:
    """
    Evaluates open derivative positions requiring margin (naked option writes & futures):
    - Naked option writes: Maintenance requirement = 15% of notional value.
    - Futures (long & short): Maintenance requirement = 10% of notional value.
    Breach occurs when: pos.margin_locked < maintenance_required.
    When breached, force-liquidates the entire position with triggered_by="derivative_margin_call".
    """
    quotes = current_quotes or {}
    margin_positions = (
        db.query(DerivativePosition)
        .join(DerivativeContract)
        .filter(
            DerivativePosition.quantity > 0,
            DerivativePosition.margin_locked > 0,
        )
        .all()
    )

    liquidated_orders: List[DerivativeOrder] = []

    for pos in margin_positions:
        contract = pos.contract
        wallet = pos.wallet
        units = pos.quantity * contract.lot_size

        # Resolve live mark price and underlying price
        mark_p = None
        if contract.symbol in quotes:
            val = quotes[contract.symbol]
            mark_p = val.price if isinstance(val, PriceQuote) else float(val)

        und_p = None
        if contract.underlying in quotes:
            val = quotes[contract.underlying]
            und_p = val.price if isinstance(val, PriceQuote) else float(val)

        if mark_p is None:
            q = get_quote(contract.symbol)
            mark_p = q.price if q and q.price > 0 else pos.entry_price

        if und_p is None:
            q_und = get_quote(contract.underlying)
            und_p = q_und.price if q_und and q_und.price > 0 else (contract.strike_price or mark_p)

        # ── Maintenance Requirement Calculation ────────────────────────────────
        if contract.instrument_type == "option":
            # Naked short option: 15% of underlying notional value
            notional = und_p * units
            maint_req = round(0.15 * notional, 2)
            # Unrealized P&L for short option
            opt_pnl = round((pos.entry_price - mark_p) * units, 2)
            effective_margin = round(pos.margin_locked + opt_pnl, 2)
        else:
            # Futures: 10% of current mark notional value
            notional = mark_p * units
            maint_req = round(0.10 * notional, 2)
            ref_p = pos.last_mtm_price if pos.last_mtm_price is not None else pos.entry_price
            if pos.side == "long":
                fut_pnl = round((mark_p - ref_p) * units, 2)
            else:
                fut_pnl = round((ref_p - mark_p) * units, 2)
            effective_margin = round(pos.margin_locked + fut_pnl, 2)

        # Ratio: effective margin vs maintenance required
        if maint_req > 0:
            ratio = min(pos.margin_locked, effective_margin) / maint_req
        else:
            ratio = 1.0

        if ratio < 1.0 - 1e-6:
            logger.warning(
                "DERIVATIVE MARGIN CALL LIQUIDATION triggered for %s: margin_locked=%.2f, eff_margin=%.2f, maint_req=%.2f, ratio=%.4f (< 1.0)",
                contract.symbol, pos.margin_locked, effective_margin, maint_req, ratio
            )

            # Close position: buy_to_close if short, sell_to_close if long
            close_action = "buy_to_close" if pos.side == "short" else "sell_to_close"
            close_side = "buy" if pos.side == "short" else "sell"

            liq_order = place_derivative_order(
                db=db,
                wallet=wallet,
                contract=contract,
                side=close_side,
                action=close_action,
                quantity=pos.quantity,
                order_type="market",
                fill_price=mark_p,
                underlying_price=und_p,
                triggered_by="derivative_margin_call",
            )
            liquidated_orders.append(liq_order)

    return liquidated_orders


# ══════════════════════════════════════════════════════════════════════════════
# Portfolio Position Summary with Live Metrics
# ══════════════════════════════════════════════════════════════════════════════

def get_derivative_positions_summary(
    db: Session,
    wallet_id: int,
    live_quotes: Dict[str, PriceQuote] | None = None,
) -> List[Dict[str, Any]]:
    """
    Enriches open derivative positions with live market prices, P&L, and margin health.
    """
    positions = (
        db.query(DerivativePosition)
        .join(DerivativeContract)
        .filter(
            DerivativePosition.wallet_id == wallet_id,
            DerivativePosition.quantity > 0,
        )
        .all()
    )

    quotes = live_quotes or {}
    results = []

    for pos in positions:
        c = pos.contract
        units = pos.quantity * c.lot_size

        q = quotes.get(c.symbol)
        curr_p = q.price if q and q.price > 0 else pos.entry_price

        # Current market value
        if c.instrument_type == "option":
            notional = (contract_und_p := (quotes.get(c.underlying).price if quotes.get(c.underlying) else c.strike_price or curr_p)) * units
            market_val = curr_p * units
            if pos.side == "long":
                unrealized_pnl = round((curr_p - pos.entry_price) * units, 2)
            else:
                unrealized_pnl = round((pos.entry_price - curr_p) * units, 2)

            maint_req = round(0.15 * notional, 2) if (pos.side == "short" and not pos.is_covered) else 0.0
        else:
            notional = curr_p * units
            market_val = notional
            ref_p = pos.last_mtm_price if pos.last_mtm_price is not None else pos.entry_price
            if pos.side == "long":
                unrealized_pnl = round((curr_p - ref_p) * units, 2)
            else:
                unrealized_pnl = round((ref_p - curr_p) * units, 2)

            maint_req = round(0.10 * notional, 2)

        entry_val = pos.entry_price * units
        unrealized_pct = round((unrealized_pnl / entry_val) * 100, 2) if entry_val > 0 else 0.0
        eff_margin = min(pos.margin_locked, pos.margin_locked + unrealized_pnl)
        margin_level = round((eff_margin / maint_req) * 100, 1) if maint_req > 0 else None

        results.append({
            "position": pos,
            "contract": c,
            "current_price": curr_p,
            "notional_value": notional,
            "market_value": market_val,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pct,
            "maintenance_margin_required": maint_req,
            "margin_level_pct": margin_level,
        })

    return results
