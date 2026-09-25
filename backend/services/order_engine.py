"""
services/order_engine.py — Order execution and tick evaluation engine.

Supports:
- Market orders (BUY / SELL)
- Limit orders (BUY: current_price <= limit, SELL: current_price >= limit)
- Stop-Loss orders (SELL: current_price <= trigger, executed as market sell)
- Evaluation against incoming price ticks during market open hours
- Order cancellation for pending orders
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from models.orm import Holding, HoldingLot, Order, Transaction, Wallet
from services.price_feed import PriceQuote, get_quote
from services.trading_calendar import calculate_square_off_date, is_near_market_close
from config import MARKET_SESSIONS

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

_EXCHANGE_MARKET: dict[str, str] = {
    "NSE":    "IN",
    "BSE":    "IN",
    "NYSE":   "US",
    "NASDAQ": "US",
}

_SUFFIX_EXCHANGE: dict[str, str] = {
    ".NS": "NSE",
    ".BO": "BSE",
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ticker_exchange(ticker: str) -> str:
    upper = ticker.upper()
    for suffix, exchange in _SUFFIX_EXCHANGE.items():
        if upper.endswith(suffix):
            return exchange
    return "NASDAQ"


def _ticker_market(ticker: str) -> str:
    return _EXCHANGE_MARKET.get(_ticker_exchange(ticker), "US")


def _persist_rejected(
    db: Session,
    wallet_id: int,
    ticker: str,
    side: str,
    quantity: float,
    reject_reason: str,
    order_type: str = "market",
    requested_price: float | None = None,
    trigger_price: float | None = None,
    is_short: bool = False,
    existing_order: Order | None = None,
) -> Order:
    """Mark an existing order as rejected or create a new rejected Order row."""
    if existing_order:
        existing_order.status = "rejected"
        existing_order.reject_reason = reject_reason
        existing_order.is_short = is_short
        existing_order.executed_at = _now_utc()
        order = existing_order
    else:
        order = Order(
            wallet_id=wallet_id,
            ticker=ticker,
            order_type=order_type,
            side=side,
            quantity=quantity,
            requested_price=requested_price,
            trigger_price=trigger_price,
            is_short=is_short,
            status="rejected",
            reject_reason=reject_reason,
            created_at=_now_utc(),
            executed_at=_now_utc(),
        )
        db.add(order)

    db.commit()
    db.refresh(order)
    logger.info(
        "Order REJECTED: %s %s %s ×%s | reason=%s (is_short=%s)",
        order_type.upper(), side.upper(), ticker, quantity, reject_reason, is_short,
    )
    return order


# ── Buy execution ─────────────────────────────────────────────────────────────

def _execute_buy(
    db: Session,
    wallet: Wallet,
    ticker: str,
    quantity: float,
    price: float,
    order_type: str = "market",
    requested_price: float | None = None,
    trigger_price: float | None = None,
    square_off_date: date | None = None,
    is_intraday: bool = False,
    triggered_by: str | None = None,
    existing_order: Order | None = None,
) -> Order:
    total_cost = round(price * quantity, 2)

    # Cash check
    if wallet.current_cash_balance < total_cost:
        return _persist_rejected(
            db, wallet.id, ticker, "buy", quantity, "insufficient_funds",
            order_type=order_type, requested_price=requested_price,
            trigger_price=trigger_price, existing_order=existing_order,
        )

    # Deduct cash
    wallet.current_cash_balance = round(wallet.current_cash_balance - total_cost, 2)

    # Upsert holding — weighted average cost basis
    holding = (
        db.query(Holding)
        .filter(Holding.wallet_id == wallet.id, Holding.ticker == ticker)
        .first()
    )
    if holding:
        new_qty = holding.quantity + quantity
        holding.avg_buy_price = round(
            (holding.quantity * holding.avg_buy_price + quantity * price) / new_qty, 6
        )
        holding.quantity = round(new_qty, 8)
    else:
        holding = Holding(
            wallet_id=wallet.id,
            ticker=ticker,
            quantity=round(quantity, 8),
            avg_buy_price=round(price, 6),
            square_off_date=square_off_date,
            is_intraday=is_intraday,
        )
        db.add(holding)
        db.flush()

    # Create new lot tracking this specific purchase and duration
    lot = HoldingLot(
        holding_id=holding.id,
        quantity=round(quantity, 8),
        buy_price=round(price, 6),
        square_off_date=square_off_date,
        is_intraday=is_intraday,
        created_at=_now_utc(),
    )
    db.add(lot)
    db.flush()

    # Recompute earliest active square_off_date on the aggregated holding
    active_timed_lots = (
        db.query(HoldingLot)
        .filter(HoldingLot.holding_id == holding.id, HoldingLot.square_off_date.isnot(None))
        .order_by(HoldingLot.square_off_date.asc())
        .all()
    )
    if active_timed_lots:
        holding.square_off_date = active_timed_lots[0].square_off_date
        holding.is_intraday = active_timed_lots[0].is_intraday
    else:
        holding.square_off_date = None
        holding.is_intraday = False

    # Create or update order
    if existing_order:
        existing_order.executed_price = price
        existing_order.status = "filled"
        existing_order.executed_at = _now_utc()
        if square_off_date:
            existing_order.square_off_date = square_off_date
            existing_order.is_intraday = is_intraday
        if triggered_by:
            existing_order.triggered_by = triggered_by
        order = existing_order
    else:
        order = Order(
            wallet_id=wallet.id,
            ticker=ticker,
            order_type=order_type,
            side="buy",
            quantity=quantity,
            requested_price=requested_price,
            trigger_price=trigger_price,
            executed_price=price,
            status="filled",
            square_off_date=square_off_date,
            is_intraday=is_intraday,
            triggered_by=triggered_by,
            created_at=_now_utc(),
            executed_at=_now_utc(),
        )
        db.add(order)

    db.flush()

    # Ledger entry
    txn = Transaction(
        wallet_id=wallet.id,
        order_id=order.id,
        ticker=ticker,
        side="buy",
        quantity=quantity,
        price=price,
        total_value=total_cost,
        cash_balance_after=wallet.current_cash_balance,
        realized_pnl=None,
        timestamp=_now_utc(),
    )
    db.add(txn)
    db.commit()
    db.refresh(order)

    logger.info(
        "%s BUY filled: %s ×%s @ %.4f = %s %.2f | cash_after=%.2f",
        order_type.upper(), ticker, quantity, price, wallet.currency, total_cost, wallet.current_cash_balance,
    )
    return order


# ── Sell execution ────────────────────────────────────────────────────────────

def _execute_sell(
    db: Session,
    wallet: Wallet,
    ticker: str,
    quantity: float,
    price: float,
    order_type: str = "market",
    requested_price: float | None = None,
    trigger_price: float | None = None,
    triggered_by: str | None = None,
    existing_order: Order | None = None,
) -> Order:
    holding = (
        db.query(Holding)
        .filter(Holding.wallet_id == wallet.id, Holding.ticker == ticker)
        .first()
    )

    # Holdings check
    if not holding or holding.quantity < quantity - 1e-9:
        return _persist_rejected(
            db, wallet.id, ticker, "sell", quantity, "insufficient_holdings",
            order_type=order_type, requested_price=requested_price,
            trigger_price=trigger_price, existing_order=existing_order,
        )

    proceeds = round(price * quantity, 2)
    realized_pnl = round((price - holding.avg_buy_price) * quantity, 6)
    holding_avg_buy_price = holding.avg_buy_price

    # Add proceeds to cash
    wallet.current_cash_balance = round(wallet.current_cash_balance + proceeds, 2)

    # Reduce / close holding
    remaining = round(holding.quantity - quantity, 8)
    if remaining <= 1e-9:
        db.delete(holding)
    else:
        holding.quantity = remaining

        # Lot deduction
        qty_to_deduct = quantity
        if triggered_by == "auto_square_off":
            # Auto square-off specifically consumes the due expiring lots
            lots = (
                db.query(HoldingLot)
                .filter(HoldingLot.holding_id == holding.id, HoldingLot.square_off_date.isnot(None))
                .order_by(HoldingLot.square_off_date.asc(), HoldingLot.created_at.asc())
                .all()
            )
            fallback_lots = (
                db.query(HoldingLot)
                .filter(HoldingLot.holding_id == holding.id, HoldingLot.square_off_date.is_(None))
                .order_by(HoldingLot.created_at.asc())
                .all()
            )
            all_target_lots = lots + fallback_lots
        else:
            # Manual user sell: strictly FIFO ordered by created_at
            all_target_lots = (
                db.query(HoldingLot)
                .filter(HoldingLot.holding_id == holding.id)
                .order_by(HoldingLot.created_at.asc())
                .all()
            )

        for lot in all_target_lots:
            if qty_to_deduct <= 1e-9:
                break
            if lot.quantity <= qty_to_deduct + 1e-9:
                qty_to_deduct = round(qty_to_deduct - lot.quantity, 8)
                db.delete(lot)
            else:
                lot.quantity = round(lot.quantity - qty_to_deduct, 8)
                qty_to_deduct = 0.0

        db.flush()

        # Recompute earliest active square_off_date from remaining lots (if lots exist)
        has_any_lots = db.query(HoldingLot).filter(HoldingLot.holding_id == holding.id).count() > 0
        if has_any_lots:
            remaining_timed_lots = (
                db.query(HoldingLot)
                .filter(HoldingLot.holding_id == holding.id, HoldingLot.square_off_date.isnot(None))
                .order_by(HoldingLot.square_off_date.asc())
                .all()
            )
            if remaining_timed_lots:
                holding.square_off_date = remaining_timed_lots[0].square_off_date
                holding.is_intraday = remaining_timed_lots[0].is_intraday
            else:
                holding.square_off_date = None
                holding.is_intraday = False

    # Create or update order
    if existing_order:
        existing_order.executed_price = price
        existing_order.status = "filled"
        existing_order.executed_at = _now_utc()
        existing_order.is_short = False
        if triggered_by:
            existing_order.triggered_by = triggered_by
        order = existing_order
    else:
        order = Order(
            wallet_id=wallet.id,
            ticker=ticker,
            order_type=order_type,
            side="sell",
            quantity=quantity,
            requested_price=requested_price,
            trigger_price=trigger_price,
            executed_price=price,
            is_short=False,
            status="filled",
            triggered_by=triggered_by,
            created_at=_now_utc(),
            executed_at=_now_utc(),
        )
        db.add(order)

    db.flush()

    # Ledger entry (realized_pnl stored at fill time)
    txn = Transaction(
        wallet_id=wallet.id,
        order_id=order.id,
        ticker=ticker,
        side="sell",
        quantity=quantity,
        price=price,
        total_value=proceeds,
        cash_balance_after=wallet.current_cash_balance,
        realized_pnl=realized_pnl,
        avg_buy_price=round(holding_avg_buy_price, 6),
        triggered_by=triggered_by,
        is_short=False,
        timestamp=_now_utc(),
    )
    db.add(txn)
    db.commit()
    db.refresh(order)

    logger.info(
        "%s SELL filled: %s ×%s @ %.4f proceeds=%s %.2f realized_pnl=%.4f by=%s | cash_after=%.2f",
        order_type.upper(), ticker, quantity, price, wallet.currency, proceeds,
        realized_pnl, triggered_by, wallet.current_cash_balance,
    )
    return order


# ── Short Sell execution ──────────────────────────────────────────────────────

def _execute_short_sell(
    db: Session,
    wallet: Wallet,
    ticker: str,
    quantity: float,
    price: float,
    order_type: str = "market",
    requested_price: float | None = None,
    trigger_price: float | None = None,
    square_off_date: date | None = None,
    is_intraday: bool = False,
    triggered_by: str | None = None,
    existing_order: Order | None = None,
) -> Order:
    is_us = (wallet.market == "US")
    proceeds = round(price * quantity, 2)

    # 1. Margin requirement check
    if is_us:
        # Reg T initial margin requirement: 150% of position value, checked against available buying power
        required_margin = round(1.5 * price * quantity, 2)
        if wallet.available_buying_power < required_margin:
            return _persist_rejected(
                db, wallet.id, ticker, "sell", quantity, "insufficient_margin",
                order_type=order_type, requested_price=requested_price,
                trigger_price=trigger_price, is_short=True, existing_order=existing_order,
            )
        margin_to_lock = required_margin
    else:
        # IN market: 1x cash check (unchanged)
        required_margin = proceeds
        if wallet.current_cash_balance < required_margin:
            return _persist_rejected(
                db, wallet.id, ticker, "sell", quantity, "insufficient_margin",
                order_type=order_type, requested_price=requested_price,
                trigger_price=trigger_price, is_short=True, existing_order=existing_order,
            )
        margin_to_lock = 0.0

    # 2. Credit proceeds to cash balance
    wallet.current_cash_balance = round(wallet.current_cash_balance + proceeds, 2)

    # 3. Lock collateral into margin_used for US
    if margin_to_lock > 0:
        wallet.margin_used = round((wallet.margin_used or 0.0) + margin_to_lock, 2)

    # 4. Market date & duration
    if wallet.market == "IN":
        # IN shorts are strictly intraday
        exchange = "NSE"
        session_info = MARKET_SESSIONS.get(exchange)
        tz = session_info["tz"] if session_info else None
        market_today = datetime.now(tz=tz).date() if tz else date.today()
        effective_sq_date = market_today
        effective_intraday = True
    else:
        # US shorts can be held overnight / multi-day
        effective_sq_date = square_off_date
        effective_intraday = is_intraday

    # 5. Upsert short holding
    holding = (
        db.query(Holding)
        .filter(Holding.wallet_id == wallet.id, Holding.ticker == ticker, Holding.is_short == True)
        .first()
    )
    if holding:
        new_qty = holding.quantity + quantity
        holding.avg_buy_price = round(
            (holding.quantity * holding.avg_buy_price + quantity * price) / new_qty, 6
        )
        holding.quantity = round(new_qty, 8)
        holding.margin_locked = round((holding.margin_locked or 0.0) + margin_to_lock, 2)
        if effective_sq_date is not None:
            if holding.square_off_date is None or effective_sq_date < holding.square_off_date:
                holding.square_off_date = effective_sq_date
                holding.is_intraday = effective_intraday
    else:
        holding = Holding(
            wallet_id=wallet.id,
            ticker=ticker,
            quantity=round(quantity, 8),
            avg_buy_price=round(price, 6),
            square_off_date=effective_sq_date,
            is_intraday=effective_intraday,
            is_short=True,
            margin_locked=margin_to_lock,
        )
        db.add(holding)
        db.flush()

    # 6. Add short lot
    lot = HoldingLot(
        holding_id=holding.id,
        quantity=round(quantity, 8),
        buy_price=round(price, 6),
        square_off_date=effective_sq_date,
        is_intraday=effective_intraday,
        is_short=True,
        margin_locked=margin_to_lock,
        created_at=_now_utc(),
    )
    db.add(lot)
    db.flush()

    # 7. Create or update Order
    if existing_order:
        existing_order.executed_price = price
        existing_order.status = "filled"
        existing_order.executed_at = _now_utc()
        existing_order.is_short = True
        existing_order.is_intraday = effective_intraday
        existing_order.square_off_date = effective_sq_date
        if triggered_by:
            existing_order.triggered_by = triggered_by
        order = existing_order
    else:
        order = Order(
            wallet_id=wallet.id,
            ticker=ticker,
            order_type=order_type,
            side="sell",
            quantity=quantity,
            requested_price=requested_price,
            trigger_price=trigger_price,
            executed_price=price,
            status="filled",
            is_short=True,
            is_intraday=effective_intraday,
            square_off_date=effective_sq_date,
            triggered_by=triggered_by,
            created_at=_now_utc(),
            executed_at=_now_utc(),
        )
        db.add(order)

    db.flush()

    # 8. Ledger transaction
    txn = Transaction(
        wallet_id=wallet.id,
        order_id=order.id,
        ticker=ticker,
        side="sell",
        quantity=quantity,
        price=price,
        total_value=proceeds,
        cash_balance_after=wallet.current_cash_balance,
        realized_pnl=None,
        avg_buy_price=round(holding.avg_buy_price, 6),
        triggered_by=triggered_by,
        is_short=True,
        timestamp=_now_utc(),
    )
    db.add(txn)
    db.commit()
    db.refresh(order)

    logger.info(
        "%s SHORT SELL filled: %s ×%s @ %.4f proceeds=%s %.2f margin_locked=%.2f | cash_after=%.2f margin_used=%.2f bp=%.2f",
        order_type.upper(), ticker, quantity, price, wallet.currency, proceeds, margin_to_lock,
        wallet.current_cash_balance, wallet.margin_used, wallet.available_buying_power,
    )
    return order


# ── Cover Buy execution ───────────────────────────────────────────────────────

def _execute_cover_buy(
    db: Session,
    wallet: Wallet,
    ticker: str,
    quantity: float,
    price: float,
    order_type: str = "market",
    requested_price: float | None = None,
    trigger_price: float | None = None,
    triggered_by: str | None = None,
    existing_order: Order | None = None,
) -> Order:
    holding = (
        db.query(Holding)
        .filter(Holding.wallet_id == wallet.id, Holding.ticker == ticker, Holding.is_short == True)
        .first()
    )
    if not holding:
        return _persist_rejected(
            db, wallet.id, ticker, "buy", quantity, "no_short_position",
            order_type=order_type, requested_price=requested_price,
            trigger_price=trigger_price, is_short=True, existing_order=existing_order,
        )

    cover_qty = min(quantity, holding.quantity)
    total_cost = round(price * cover_qty, 2)

    # Cash check for buy-back cost (except margin-call liquidation where broker force-covers)
    if triggered_by != "margin_call_liquidation" and wallet.current_cash_balance < total_cost:
        return _persist_rejected(
            db, wallet.id, ticker, "buy", quantity, "insufficient_funds",
            order_type=order_type, requested_price=requested_price,
            trigger_price=trigger_price, is_short=True, existing_order=existing_order,
        )

    # Deduct buyback cash
    wallet.current_cash_balance = round(wallet.current_cash_balance - total_cost, 2)

    # FIFO deduction across short lots (strictly ordered by created_at ASC)
    lots = (
        db.query(HoldingLot)
        .filter(HoldingLot.holding_id == holding.id)
        .order_by(HoldingLot.created_at.asc())
        .all()
    )
    rem = cover_qty
    total_realized_pnl = 0.0
    weighted_entry_sum = 0.0
    total_margin_released = 0.0

    for lot in lots:
        if rem <= 1e-9:
            break
        deduct = min(lot.quantity, rem)
        # Short realized P&L: (short entry sell price - cover buy price) * deduct
        lot_pnl = (lot.buy_price - price) * deduct
        total_realized_pnl += lot_pnl
        weighted_entry_sum += lot.buy_price * deduct

        # Release locked margin proportionally from this lot
        lot_margin = lot.margin_locked or 0.0
        if lot_margin > 0 and lot.quantity > 0:
            if lot.quantity <= deduct + 1e-9:
                rel = lot_margin
            else:
                rel = round(lot_margin * (deduct / lot.quantity), 2)
            total_margin_released += rel
            lot.margin_locked = max(0.0, round(lot.margin_locked - rel, 2))

        rem = round(rem - deduct, 8)
        if lot.quantity <= deduct + 1e-9:
            db.delete(lot)
        else:
            lot.quantity = round(lot.quantity - deduct, 8)

    effective_entry_price = round(weighted_entry_sum / cover_qty, 6) if cover_qty > 0 else holding.avg_buy_price
    total_realized_pnl = round(total_realized_pnl, 6)

    # Release margin from wallet and holding
    if total_margin_released > 0:
        wallet.margin_used = max(0.0, round((wallet.margin_used or 0.0) - total_margin_released, 2))
        holding.margin_locked = max(0.0, round((holding.margin_locked or 0.0) - total_margin_released, 2))

    # Reduce / close short holding
    remaining_holding = round(holding.quantity - cover_qty, 8)
    if remaining_holding <= 1e-9:
        if (holding.margin_locked or 0.0) > 0:
            wallet.margin_used = max(0.0, round((wallet.margin_used or 0.0) - holding.margin_locked, 2))
            holding.margin_locked = 0.0
        db.delete(holding)
    else:
        holding.quantity = remaining_holding
        remaining_lots = (
            db.query(HoldingLot)
            .filter(HoldingLot.holding_id == holding.id)
            .all()
        )
        if remaining_lots:
            tot_qty = sum(l.quantity for l in remaining_lots)
            holding.avg_buy_price = round(
                sum(l.buy_price * l.quantity for l in remaining_lots) / tot_qty, 6
            )
            holding.margin_locked = round(sum(l.margin_locked or 0.0 for l in remaining_lots), 2)
    db.flush()

    # Create or update Order
    if existing_order:
        existing_order.executed_price = price
        existing_order.status = "filled"
        existing_order.executed_at = _now_utc()
        existing_order.is_short = True
        if triggered_by:
            existing_order.triggered_by = triggered_by
        order = existing_order
    else:
        order = Order(
            wallet_id=wallet.id,
            ticker=ticker,
            order_type=order_type,
            side="buy",
            quantity=cover_qty,
            requested_price=requested_price,
            trigger_price=trigger_price,
            executed_price=price,
            status="filled",
            is_short=True,
            triggered_by=triggered_by,
            created_at=_now_utc(),
            executed_at=_now_utc(),
        )
        db.add(order)

    db.flush()

    # Ledger entry (realized_pnl stored on cover buy transaction)
    txn = Transaction(
        wallet_id=wallet.id,
        order_id=order.id,
        ticker=ticker,
        side="buy",
        quantity=cover_qty,
        price=price,
        total_value=total_cost,
        cash_balance_after=wallet.current_cash_balance,
        realized_pnl=total_realized_pnl,
        avg_buy_price=effective_entry_price,
        triggered_by=triggered_by,
        is_short=True,
        timestamp=_now_utc(),
    )
    db.add(txn)
    db.commit()
    db.refresh(order)

    logger.info(
        "%s COVER BUY filled: %s ×%s @ %.4f cost=%s %.2f realized_pnl=%.4f margin_rel=%.2f by=%s | cash_after=%.2f margin_used=%.2f bp=%.2f",
        order_type.upper(), ticker, cover_qty, price, wallet.currency, total_cost,
        total_realized_pnl, total_margin_released, triggered_by, wallet.current_cash_balance,
        wallet.margin_used, wallet.available_buying_power,
    )

    # If user wanted to buy more than short quantity, the excess opens a regular long position!
    # (Only for manual user orders, not automated liquidations)
    if triggered_by != "margin_call_liquidation":
        excess_long = round(quantity - cover_qty, 8)
        if excess_long > 1e-9:
            _execute_buy(
                db=db,
                wallet=wallet,
                ticker=ticker,
                quantity=excess_long,
                price=price,
                order_type=order_type,
            )

    return order


# ── Public API: Place Order ───────────────────────────────────────────────────

def place_order(
    db: Session,
    market: str,
    ticker: str,
    side: str,
    quantity: float,
    order_type: str = "market",
    requested_price: float | None = None,
    trigger_price: float | None = None,
    holding_days: int | None = None,
    square_off_date: str | date | None = None,
    is_intraday: bool = False,
) -> Order:
    """
    Unified entry point for placing market, limit, and stop-loss orders.
    Supports optional holding duration (holding_days or explicit square_off_date) for BUY orders.
    """
    ticker = ticker.strip().upper()
    side = side.strip().lower()
    order_type = order_type.strip().lower()

    if side not in ("buy", "sell"):
        raise ValueError(f"Invalid side: {side!r} — must be 'buy' or 'sell'")
    if order_type not in ("market", "limit", "stop_loss"):
        raise ValueError(f"Invalid order_type: {order_type!r}")

    # ── Resolve square-off date ──────────────────────────────────────────────
    parsed_sq_date: date | None = None
    if square_off_date:
        if isinstance(square_off_date, date):
            parsed_sq_date = square_off_date
        elif isinstance(square_off_date, str) and square_off_date.strip():
            try:
                parsed_sq_date = date.fromisoformat(square_off_date.strip())
            except ValueError:
                parsed_sq_date = None
    elif holding_days is not None:
        calc = calculate_square_off_date(market, holding_days=holding_days)
        parsed_sq_date = date.fromisoformat(calc["square_off_date"])
        is_intraday = calc["is_intraday"]
    elif is_intraday:
        calc = calculate_square_off_date(market, holding_days=0)
        parsed_sq_date = date.fromisoformat(calc["square_off_date"])

    # ── Wallet lookup ──────────────────────────────────────────────────────────
    wallet = db.query(Wallet).filter(Wallet.market == market).first()
    if not wallet:
        raise ValueError(f"No wallet for market '{market}'. Call POST /api/wallet/setup first.")

    # ── Ticker ↔ wallet market check ──────────────────────────────────────────
    if _ticker_market(ticker) != market:
        exchange = _ticker_exchange(ticker)
        correct_market = _EXCHANGE_MARKET.get(exchange, "US")
        logger.warning(
            "Ticker %s (%s) sent to wrong wallet %s — should be %s",
            ticker, exchange, market, correct_market,
        )
        return _persist_rejected(
            db, wallet.id, ticker, side, quantity, "wrong_market",
            order_type=order_type, requested_price=requested_price, trigger_price=trigger_price,
        )

    # ── Fetch quote ───────────────────────────────────────────────────────────
    quote = get_quote(ticker, force_refresh=True)
    if quote.error:
        logger.warning("Invalid ticker %s: %s", ticker, quote.error)
        return _persist_rejected(
            db, wallet.id, ticker, side, quantity, "invalid_ticker",
            order_type=order_type, requested_price=requested_price, trigger_price=trigger_price,
        )

    # ── 1. MARKET ORDER ───────────────────────────────────────────────────────
    if order_type == "market":
        if not quote.market_open:
            return _persist_rejected(
                db, wallet.id, ticker, side, quantity, "market_closed",
                order_type="market",
            )
        holding = (
            db.query(Holding)
            .filter(Holding.wallet_id == wallet.id, Holding.ticker == ticker)
            .first()
        )

        if side == "buy":
            if holding and holding.is_short:
                return _execute_cover_buy(
                    db, wallet, ticker, quantity, quote.price, order_type="market",
                )
            else:
                return _execute_buy(
                    db, wallet, ticker, quantity, quote.price,
                    order_type="market",
                    square_off_date=parsed_sq_date,
                    is_intraday=is_intraday,
                )
        else:  # side == "sell"
            if holding and not holding.is_short:
                if quantity <= holding.quantity + 1e-9:
                    return _execute_sell(db, wallet, ticker, quantity, quote.price, order_type="market")
                else:
                    # Selling more than currently held long -> Split operation
                    if market == "IN" and ((holding_days is not None and holding_days > 0) or (square_off_date and not is_intraday)):
                        return _persist_rejected(
                            db, wallet.id, ticker, "sell", quantity, "intraday_only_for_short",
                            order_type="market",
                        )

                    # 1. Close existing long position normally
                    long_qty = holding.quantity
                    short_qty = round(quantity - long_qty, 8)
                    _execute_sell(db, wallet, ticker, long_qty, quote.price, order_type="market")

                    # 2. Check margin for the excess short portion
                    if market == "US":
                        required_margin = round(1.5 * quote.price * short_qty, 2)
                        if wallet.available_buying_power < required_margin:
                            return _persist_rejected(
                                db, wallet.id, ticker, "sell", short_qty, "insufficient_margin",
                                order_type="market", is_short=True,
                            )
                    else:
                        if wallet.current_cash_balance < round(quote.price * short_qty, 2):
                            return _persist_rejected(
                                db, wallet.id, ticker, "sell", short_qty, "insufficient_margin",
                                order_type="market", is_short=True,
                            )

                    # 3. Open new short position with the excess
                    return _execute_short_sell(
                        db, wallet, ticker, short_qty, quote.price, order_type="market",
                        square_off_date=parsed_sq_date, is_intraday=is_intraday,
                    )
            elif holding and holding.is_short:
                # Adding to existing short position
                if market == "IN" and ((holding_days is not None and holding_days > 0) or (square_off_date and not is_intraday)):
                    return _persist_rejected(
                        db, wallet.id, ticker, "sell", quantity, "intraday_only_for_short",
                        order_type="market", is_short=True,
                    )
                return _execute_short_sell(
                    db, wallet, ticker, quantity, quote.price, order_type="market",
                    square_off_date=parsed_sq_date, is_intraday=is_intraday,
                )
            else:
                # No holding at all -> Open short position
                if market == "IN" and ((holding_days is not None and holding_days > 0) or (square_off_date and not is_intraday)):
                    return _persist_rejected(
                        db, wallet.id, ticker, "sell", quantity, "intraday_only_for_short",
                        order_type="market", is_short=True,
                    )
                return _execute_short_sell(
                    db, wallet, ticker, quantity, quote.price, order_type="market",
                    square_off_date=parsed_sq_date, is_intraday=is_intraday,
                )

    # ── 2. LIMIT ORDER ────────────────────────────────────────────────────────
    if order_type == "limit":
        limit_price = requested_price
        if not limit_price or limit_price <= 0:
            return _persist_rejected(
                db, wallet.id, ticker, side, quantity, "invalid_limit_price",
                order_type="limit", requested_price=limit_price,
            )

        holding = (
            db.query(Holding)
            .filter(Holding.wallet_id == wallet.id, Holding.ticker == ticker)
            .first()
        )

        # Pre-execution sanity checks
        if side == "buy":
            cost = round(limit_price * quantity, 2)
            if wallet.current_cash_balance < cost:
                return _persist_rejected(
                    db, wallet.id, ticker, side, quantity, "insufficient_funds",
                    order_type="limit", requested_price=limit_price,
                )
            if holding and holding.is_short:
                # Cover limit buy: if favorable now (current <= limit), fill immediately!
                if quote.market_open and quote.price <= limit_price:
                    return _execute_cover_buy(
                        db, wallet, ticker, quantity, quote.price,
                        order_type="limit", requested_price=limit_price,
                    )
                # Pending cover buy
                pending_order = Order(
                    wallet_id=wallet.id,
                    ticker=ticker,
                    order_type="limit",
                    side="buy",
                    quantity=quantity,
                    requested_price=limit_price,
                    is_short=True,
                    status="pending",
                    created_at=_now_utc(),
                )
                db.add(pending_order)
                db.commit()
                db.refresh(pending_order)
                return pending_order
            else:
                # Regular limit buy
                if quote.market_open and quote.price <= limit_price:
                    return _execute_buy(
                        db, wallet, ticker, quantity, quote.price,
                        order_type="limit", requested_price=limit_price,
                        square_off_date=parsed_sq_date,
                        is_intraday=is_intraday,
                    )
                pending_order = Order(
                    wallet_id=wallet.id,
                    ticker=ticker,
                    order_type="limit",
                    side="buy",
                    quantity=quantity,
                    requested_price=limit_price,
                    square_off_date=parsed_sq_date,
                    is_intraday=is_intraday,
                    is_short=False,
                    status="pending",
                    created_at=_now_utc(),
                )
                db.add(pending_order)
                db.commit()
                db.refresh(pending_order)
                return pending_order
        else:  # side == "sell"
            if holding and not holding.is_short:
                if holding.quantity < quantity - 1e-9:
                    if market == "IN" and ((holding_days is not None and holding_days > 0) or (square_off_date and not is_intraday)):
                        return _persist_rejected(
                            db, wallet.id, ticker, side, quantity, "intraday_only_for_short",
                            order_type="limit", requested_price=limit_price,
                        )
                    if quote.market_open and quote.price >= limit_price:
                        long_qty = holding.quantity
                        short_qty = round(quantity - long_qty, 8)
                        _execute_sell(db, wallet, ticker, long_qty, quote.price, order_type="limit", requested_price=limit_price)
                        return _execute_short_sell(
                            db, wallet, ticker, short_qty, quote.price, order_type="limit", requested_price=limit_price,
                            square_off_date=parsed_sq_date, is_intraday=is_intraday,
                        )
                    return _persist_rejected(
                        db, wallet.id, ticker, side, quantity, "insufficient_holdings",
                        order_type="limit", requested_price=limit_price,
                    )
                else:
                    if quote.market_open and quote.price >= limit_price:
                        return _execute_sell(
                            db, wallet, ticker, quantity, quote.price,
                            order_type="limit", requested_price=limit_price,
                        )
                    pending_order = Order(
                        wallet_id=wallet.id,
                        ticker=ticker,
                        order_type="limit",
                        side="sell",
                        quantity=quantity,
                        requested_price=limit_price,
                        is_short=False,
                        status="pending",
                        created_at=_now_utc(),
                    )
                    db.add(pending_order)
                    db.commit()
                    db.refresh(pending_order)
                    return pending_order
            else:
                # Short limit sell (no holding or existing short holding)
                if market == "IN" and ((holding_days is not None and holding_days > 0) or (square_off_date and not is_intraday)):
                    return _persist_rejected(
                        db, wallet.id, ticker, side, quantity, "intraday_only_for_short",
                        order_type="limit", requested_price=limit_price, is_short=True,
                    )
                if market == "US":
                    req_margin = round(1.5 * limit_price * quantity, 2)
                    if wallet.available_buying_power < req_margin:
                        return _persist_rejected(
                            db, wallet.id, ticker, side, quantity, "insufficient_margin",
                            order_type="limit", requested_price=limit_price, is_short=True,
                        )
                else:
                    if wallet.current_cash_balance < round(limit_price * quantity, 2):
                        return _persist_rejected(
                            db, wallet.id, ticker, side, quantity, "insufficient_margin",
                            order_type="limit", requested_price=limit_price, is_short=True,
                        )
                if quote.market_open and quote.price >= limit_price:
                    return _execute_short_sell(
                        db, wallet, ticker, quantity, quote.price,
                        order_type="limit", requested_price=limit_price,
                        square_off_date=parsed_sq_date, is_intraday=is_intraday,
                    )
                pending_order = Order(
                    wallet_id=wallet.id,
                    ticker=ticker,
                    order_type="limit",
                    side="sell",
                    quantity=quantity,
                    requested_price=limit_price,
                    is_short=True,
                    is_intraday=is_intraday,
                    square_off_date=parsed_sq_date,
                    status="pending",
                    created_at=_now_utc(),
                )
                db.add(pending_order)
                db.commit()
                db.refresh(pending_order)
                logger.info(
                    "LIMIT SHORT SELL pending: %s ×%s limit=%.4f (current=%.4f)",
                    ticker, quantity, limit_price, quote.price,
                )
                return pending_order

    # ── 3. STOP-LOSS ORDER ────────────────────────────────────────────────────
    if order_type == "stop_loss":
        # Stop-loss is only available for sell side to protect downside
        if side != "sell":
            return _persist_rejected(
                db, wallet.id, ticker, side, quantity, "stop_loss_sell_only",
                order_type="stop_loss", trigger_price=trigger_price or requested_price,
            )

        stop_trigger = trigger_price if trigger_price is not None else requested_price
        if not stop_trigger or stop_trigger <= 0:
            return _persist_rejected(
                db, wallet.id, ticker, side, quantity, "invalid_trigger_price",
                order_type="stop_loss", trigger_price=stop_trigger,
            )

        holding = (
            db.query(Holding)
            .filter(Holding.wallet_id == wallet.id, Holding.ticker == ticker)
            .first()
        )
        if not holding or holding.quantity < quantity - 1e-9:
            return _persist_rejected(
                db, wallet.id, ticker, side, quantity, "insufficient_holdings",
                order_type="stop_loss", trigger_price=stop_trigger,
                requested_price=stop_trigger,
            )

        # If market is OPEN and price has already breached trigger (current <= trigger), execute market sell immediately!
        if quote.market_open and quote.price <= stop_trigger:
            return _execute_sell(
                db, wallet, ticker, quantity, quote.price,
                order_type="stop_loss", requested_price=stop_trigger,
                trigger_price=stop_trigger,
            )

        # Otherwise, save as pending stop-loss
        pending_order = Order(
            wallet_id=wallet.id,
            ticker=ticker,
            order_type="stop_loss",
            side="sell",
            quantity=quantity,
            requested_price=stop_trigger,
            trigger_price=stop_trigger,
            status="pending",
            created_at=_now_utc(),
        )
        db.add(pending_order)
        db.commit()
        db.refresh(pending_order)
        logger.info(
            "STOP-LOSS SELL pending: %s ×%s trigger=%.4f (current=%.4f, market_open=%s)",
            ticker, quantity, stop_trigger, quote.price, quote.market_open,
        )
        return pending_order

    raise ValueError(f"Unhandled order_type: {order_type}")


def place_market_order(
    db: Session,
    market: str,
    ticker: str,
    side: str,
    quantity: float,
) -> Order:
    """Backward-compatible helper for market orders."""
    return place_order(db=db, market=market, ticker=ticker, side=side, quantity=quantity, order_type="market")


# ── Tick Evaluation: Process Open Pending Orders ──────────────────────────────

def evaluate_pending_orders(
    db: Session,
    quotes: list[PriceQuote] | dict[str, PriceQuote] | None = None,
    market: str | None = None,
) -> list[Order]:
    """
    Evaluates open 'pending' orders against incoming market quotes.

    CRITICAL RULE (per user spec):
    When a stop-loss or limit order triggers based on price, it MUST still respect
    the market_open check before actually filling. If the market is closed, DO NOT
    fill it; leave it pending until the market is next open.
    """
    query = db.query(Order).filter(Order.status == "pending")
    if market:
        query = query.join(Wallet, Order.wallet_id == Wallet.id).filter(Wallet.market == market)

    pending_orders = query.all()
    if not pending_orders:
        return []

    # Map quotes for fast lookup
    quote_map: dict[str, PriceQuote] = {}
    if quotes:
        if isinstance(quotes, dict):
            quote_map = {k.upper(): v for k, v in quotes.items()}
        elif isinstance(quotes, list):
            quote_map = {q.symbol.upper(): q for q in quotes}

    filled_or_rejected: list[Order] = []

    for order in pending_orders:
        ticker = order.ticker.upper()
        quote = quote_map.get(ticker)
        if not quote:
            quote = get_quote(ticker)
            quote_map[ticker] = quote

        if not quote or quote.error:
            continue

        # ── 1. Market Hours Check (MUST BE OPEN TO FILL) ─────────────────────
        if not quote.market_open:
            # Leave pending!
            continue

        current_price = quote.price
        triggered = False

        # ── 2. Trigger Evaluation ────────────────────────────────────────────
        if order.order_type == "limit":
            limit_p = order.requested_price
            if limit_p is not None:
                if order.side == "buy" and current_price <= limit_p:
                    triggered = True
                elif order.side == "sell" and current_price >= limit_p:
                    triggered = True

        elif order.order_type == "stop_loss":
            trigger_p = order.trigger_price if order.trigger_price is not None else order.requested_price
            if trigger_p is not None:
                # Stop loss sell triggers when price drops to or below trigger price
                if order.side == "sell" and current_price <= trigger_p:
                    triggered = True

        # ── 3. Execution on Trigger ──────────────────────────────────────────
        if triggered:
            wallet = db.query(Wallet).filter(Wallet.id == order.wallet_id).first()
            if not wallet:
                continue

            logger.info(
                "Trigger condition met for pending order #%d (%s %s %s @ current %.4f)",
                order.id, order.order_type.upper(), order.side.upper(), order.ticker, current_price,
            )

            if order.side == "buy":
                if order.is_short:
                    result = _execute_cover_buy(
                        db=db,
                        wallet=wallet,
                        ticker=order.ticker,
                        quantity=order.quantity,
                        price=current_price,
                        order_type=order.order_type,
                        requested_price=order.requested_price,
                        trigger_price=order.trigger_price,
                        existing_order=order,
                    )
                else:
                    result = _execute_buy(
                        db=db,
                        wallet=wallet,
                        ticker=order.ticker,
                        quantity=order.quantity,
                        price=current_price,
                        order_type=order.order_type,
                        requested_price=order.requested_price,
                        trigger_price=order.trigger_price,
                        existing_order=order,
                    )
            else:
                if order.is_short:
                    result = _execute_short_sell(
                        db=db,
                        wallet=wallet,
                        ticker=order.ticker,
                        quantity=order.quantity,
                        price=current_price,
                        order_type=order.order_type,
                        requested_price=order.requested_price,
                        trigger_price=order.trigger_price,
                        existing_order=order,
                    )
                else:
                    result = _execute_sell(
                        db=db,
                        wallet=wallet,
                        ticker=order.ticker,
                        quantity=order.quantity,
                        price=current_price,
                        order_type=order.order_type,
                        requested_price=order.requested_price,
                        trigger_price=order.trigger_price,
                        existing_order=order,
                    )

            filled_or_rejected.append(result)

    return filled_or_rejected


# ── Order Cancellation ────────────────────────────────────────────────────────

def cancel_pending_order(db: Session, order_id: int) -> Order:
    """
    Cancels an open order. Only orders with status='pending' may be cancelled.
    Raises KeyError if not found, or ValueError if order is not pending.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise KeyError(f"Order #{order_id} not found.")

    if order.status != "pending":
        raise ValueError(
            f"Cannot cancel order #{order_id} — current status is '{order.status}' (only 'pending' orders can be cancelled)."
        )

    order.status = "cancelled"
    order.executed_at = _now_utc()
    db.commit()
    db.refresh(order)

    logger.info("Order #%d CANCELLED by user (%s %s %s)", order.id, order.order_type, order.side, order.ticker)
    return order


# ── Auto Square-Off Evaluation ────────────────────────────────────────────────

def evaluate_auto_square_off(
    db: Session,
    quotes: list[PriceQuote] | None = None,
    force_time_check: bool = False,
    market_filter: str | None = None,
) -> list[Order]:
    """
    Scans active holdings where square_off_date <= today or open short holdings in IN market.
    If market is near close (last 15 minutes of trading session) or force_time_check is True:
    - Automatically executes market COVER BUY for all open short positions.
    - Executes an automatic market SELL for long holdings due today.
    Marks orders and transactions with triggered_by="auto_square_off".
    """
    quote_map = {q.symbol.upper(): q for q in quotes} if quotes else {}
    executed_orders: list[Order] = []

    markets = [market_filter.upper()] if market_filter else ["IN", "US"]

    for m in markets:
        # Check if near close (or forced for tests)
        near_close = is_near_market_close(m)
        if not near_close and not force_time_check:
            continue

        # Determine current date in that market's timezone
        exchange = "NSE" if m == "IN" else "NASDAQ"
        session_info = MARKET_SESSIONS.get(exchange)
        tz = session_info["tz"] if session_info else None
        now_local = datetime.now(tz=tz) if tz else datetime.now()
        market_today = now_local.date()

        wallets = db.query(Wallet).filter(Wallet.market == m).all()
        for wallet in wallets:
            # 1. Force-close (cover buy) any open short positions
            short_holdings = (
                db.query(Holding)
                .filter(
                    Holding.wallet_id == wallet.id,
                    Holding.quantity > 0,
                    Holding.is_short == True,
                )
                .all()
            )
            for sh in short_holdings:
                # For US market: only square off if intraday or timed lot due today
                if m == "US":
                    is_due = bool(sh.is_intraday) or (sh.square_off_date is not None and sh.square_off_date <= market_today)
                    if not is_due:
                        continue

                ticker = sh.ticker.upper()
                quote = quote_map.get(ticker)
                if not quote:
                    quote = get_quote(ticker)
                    quote_map[ticker] = quote
                fill_price = quote.price if quote and quote.price > 0 else sh.avg_buy_price
                logger.info(
                    "Auto square-off COVER triggered for short %s (%s) qty=%.4f @ %.4f",
                    ticker, m, sh.quantity, fill_price,
                )
                cover_order = _execute_cover_buy(
                    db=db,
                    wallet=wallet,
                    ticker=ticker,
                    quantity=sh.quantity,
                    price=fill_price,
                    order_type="market",
                    triggered_by="auto_square_off",
                )
                executed_orders.append(cover_order)

            # 2. Query long holdings that have active lots due on or before today
            holdings_with_lots = (
                db.query(Holding)
                .join(HoldingLot, Holding.id == HoldingLot.holding_id)
                .filter(
                    Holding.wallet_id == wallet.id,
                    Holding.quantity > 0,
                    Holding.is_short == False,
                    HoldingLot.square_off_date.isnot(None),
                    HoldingLot.square_off_date <= market_today,
                )
                .all()
            )
            legacy_holdings = (
                db.query(Holding)
                .filter(
                    Holding.wallet_id == wallet.id,
                    Holding.quantity > 0,
                    Holding.is_short == False,
                    Holding.square_off_date.isnot(None),
                    Holding.square_off_date <= market_today,
                    ~Holding.lots.any(),
                )
                .all()
            )
            holdings = list({h.id: h for h in (holdings_with_lots + legacy_holdings)}.values())

            for h in holdings:
                ticker = h.ticker.upper()

                # Calculate quantity specifically belonging to due lots for this holding
                due_lots = (
                    db.query(HoldingLot)
                    .filter(
                        HoldingLot.holding_id == h.id,
                        HoldingLot.square_off_date.isnot(None),
                        HoldingLot.square_off_date <= market_today,
                    )
                    .all()
                )
                if due_lots:
                    due_qty = round(sum(lot.quantity for lot in due_lots), 8)
                elif not h.lots:
                    # Legacy holding without lots
                    due_qty = h.quantity
                else:
                    due_qty = 0.0
                if due_qty <= 1e-9:
                    # No lots due (or already sold); clear holding square_off_date if needed
                    active_timed = (
                        db.query(HoldingLot)
                        .filter(HoldingLot.holding_id == h.id, HoldingLot.square_off_date.isnot(None))
                        .order_by(HoldingLot.square_off_date.asc())
                        .all()
                    )
                    if active_timed:
                        h.square_off_date = active_timed[0].square_off_date
                        h.is_intraday = active_timed[0].is_intraday
                    else:
                        h.square_off_date = None
                        h.is_intraday = False
                    db.commit()
                    continue

                qty_to_sell = min(due_qty, h.quantity)

                quote = quote_map.get(ticker)
                if not quote:
                    quote = get_quote(ticker)
                    quote_map[ticker] = quote

                fill_price = quote.price if quote and quote.price > 0 else h.avg_buy_price

                logger.info(
                    "Auto square-off triggered for %s (%s) qty=%.4f (due_lots_qty=%.4f, total_holding=%.4f) @ %.4f (sq_off_date=%s, today=%s)",
                    ticker, m, qty_to_sell, due_qty, h.quantity, fill_price, h.square_off_date, market_today,
                )

                sell_order = _execute_sell(
                    db=db,
                    wallet=wallet,
                    ticker=ticker,
                    quantity=qty_to_sell,
                    price=fill_price,
                    order_type="market",
                    triggered_by="auto_square_off",
                )
                executed_orders.append(sell_order)

    return executed_orders


# ── Margin Call Evaluation & Liquidation ──────────────────────────────────────

def evaluate_margin_calls(
    db: Session,
    quotes: list[PriceQuote] | dict[str, PriceQuote] | None = None,
) -> list[Order]:
    """
    Evaluates open US short positions against current market prices for maintenance margin breaches.

    Rules:
    - US market only.
    - Initial margin is 150%, maintenance margin threshold is 125% of current market value.
    - Ratio: margin_locked / (current_price * holding.quantity) < 1.25
      (equivalently: current_price > (holding.margin_locked / (1.25 * holding.quantity)))
    - When triggered on a holding (even with multiple lots at different entry prices),
      liquidates the ENTIRE short position for that ticker in strict FIFO order,
      releasing all locked margin and recording realized P&L per lot against its specific entry price.
    - Cover-buy order and transaction are marked with triggered_by="margin_call_liquidation".
    """
    quote_map: dict[str, PriceQuote] = {}
    if quotes:
        if isinstance(quotes, dict):
            quote_map = {k.upper(): v for k, v in quotes.items()}
        elif isinstance(quotes, list):
            quote_map = {q.symbol.upper(): q for q in quotes}

    us_wallet = db.query(Wallet).filter(Wallet.market == "US").first()
    if not us_wallet:
        return []

    short_holdings = (
        db.query(Holding)
        .filter(Holding.wallet_id == us_wallet.id, Holding.is_short == True, Holding.quantity > 0)
        .all()
    )
    if not short_holdings:
        return []

    liquidated_orders: list[Order] = []

    for holding in short_holdings:
        ticker = holding.ticker.upper()
        quote = quote_map.get(ticker)
        if not quote:
            quote = get_quote(ticker)
            quote_map[ticker] = quote

        if not quote or quote.error or quote.price <= 0:
            continue

        curr_price = quote.price
        current_value = curr_price * holding.quantity
        if current_value <= 0:
            continue

        margin_locked = holding.margin_locked or 0.0
        margin_ratio = margin_locked / current_value

        # Breach when margin_ratio < 1.25 (i.e. < 125% maintenance margin)
        if margin_ratio < 1.25 - 1e-9:
            logger.warning(
                "MARGIN CALL LIQUIDATION triggered for %s: margin_locked=%.2f, curr_val=%.2f, ratio=%.4f (< 1.25) @ price=%.4f",
                ticker, margin_locked, current_value, margin_ratio, curr_price,
            )
            # Liquidate the ENTIRE short position for that ticker
            cover_order = _execute_cover_buy(
                db=db,
                wallet=us_wallet,
                ticker=ticker,
                quantity=holding.quantity,
                price=curr_price,
                order_type="market",
                triggered_by="margin_call_liquidation",
            )
            liquidated_orders.append(cover_order)

    return liquidated_orders

