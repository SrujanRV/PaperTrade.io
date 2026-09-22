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

from models.orm import Holding, Order, Transaction, Wallet
from services.price_feed import PriceQuote, get_quote
from services.trading_calendar import calculate_square_off_date, is_near_market_close

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
    existing_order: Order | None = None,
) -> Order:
    """Mark an existing order as rejected or create a new rejected Order row."""
    if existing_order:
        existing_order.status = "rejected"
        existing_order.reject_reason = reject_reason
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
            status="rejected",
            reject_reason=reject_reason,
            created_at=_now_utc(),
            executed_at=_now_utc(),
        )
        db.add(order)

    db.commit()
    db.refresh(order)
    logger.info(
        "Order REJECTED: %s %s %s ×%s | reason=%s",
        order_type.upper(), side.upper(), ticker, quantity, reject_reason,
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
        if square_off_date:
            # Preserve earlier square-off date if already set, else set new
            if not holding.square_off_date or square_off_date < holding.square_off_date:
                holding.square_off_date = square_off_date
                holding.is_intraday = is_intraday
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

    # Add proceeds to cash
    wallet.current_cash_balance = round(wallet.current_cash_balance + proceeds, 2)

    # Reduce / close holding
    remaining = round(holding.quantity - quantity, 8)
    if remaining <= 1e-9:
        db.delete(holding)
    else:
        holding.quantity = remaining

    # Create or update order
    if existing_order:
        existing_order.executed_price = price
        existing_order.status = "filled"
        existing_order.executed_at = _now_utc()
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
        avg_buy_price=round(holding.avg_buy_price, 6),
        triggered_by=triggered_by,
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

    # ── Resolve square-off date for BUY orders ────────────────────────────────
    parsed_sq_date: date | None = None
    if side == "buy":
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
        if side == "buy":
            return _execute_buy(
                db, wallet, ticker, quantity, quote.price,
                order_type="market",
                square_off_date=parsed_sq_date,
                is_intraday=is_intraday,
            )
        else:
            return _execute_sell(db, wallet, ticker, quantity, quote.price, order_type="market")

    # ── 2. LIMIT ORDER ────────────────────────────────────────────────────────
    if order_type == "limit":
        limit_price = requested_price
        if not limit_price or limit_price <= 0:
            return _persist_rejected(
                db, wallet.id, ticker, side, quantity, "invalid_limit_price",
                order_type="limit", requested_price=limit_price,
            )

        # Pre-execution sanity checks
        if side == "buy":
            cost = round(limit_price * quantity, 2)
            if wallet.current_cash_balance < cost:
                return _persist_rejected(
                    db, wallet.id, ticker, side, quantity, "insufficient_funds",
                    order_type="limit", requested_price=limit_price,
                )
            # If market is OPEN and price is currently favorable (current <= limit), fill immediately!
            if quote.market_open and quote.price <= limit_price:
                return _execute_buy(
                    db, wallet, ticker, quantity, quote.price,
                    order_type="limit", requested_price=limit_price,
                    square_off_date=parsed_sq_date,
                    is_intraday=is_intraday,
                )
        else:
            holding = (
                db.query(Holding)
                .filter(Holding.wallet_id == wallet.id, Holding.ticker == ticker)
                .first()
            )
            if not holding or holding.quantity < quantity - 1e-9:
                return _persist_rejected(
                    db, wallet.id, ticker, side, quantity, "insufficient_holdings",
                    order_type="limit", requested_price=limit_price,
                )
            # If market is OPEN and price is currently favorable (current >= limit), fill immediately!
            if quote.market_open and quote.price >= limit_price:
                return _execute_sell(
                    db, wallet, ticker, quantity, quote.price,
                    order_type="limit", requested_price=limit_price,
                )

        # Otherwise, save as pending
        pending_order = Order(
            wallet_id=wallet.id,
            ticker=ticker,
            order_type="limit",
            side=side,
            quantity=quantity,
            requested_price=limit_price,
            square_off_date=parsed_sq_date,
            is_intraday=is_intraday,
            status="pending",
            created_at=_now_utc(),
        )
        db.add(pending_order)
        db.commit()
        db.refresh(pending_order)
        logger.info(
            "LIMIT %s pending: %s ×%s limit=%.4f (current=%.4f, market_open=%s, sq_off=%s)",
            side.upper(), ticker, quantity, limit_price, quote.price, quote.market_open, parsed_sq_date,
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
    Scans active holdings where square_off_date <= today.
    If market is near close (last 15 minutes of trading session) or force_time_check is True,
    executes an automatic market SELL for whatever remaining quantity is held.
    Marks orders and transactions with triggered_by="auto_square_off".
    """
    from config import MARKET_SESSIONS

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
            # Query holdings with a square_off_date that has arrived or passed
            holdings = (
                db.query(Holding)
                .filter(
                    Holding.wallet_id == wallet.id,
                    Holding.quantity > 0,
                    Holding.square_off_date.isnot(None),
                    Holding.square_off_date <= market_today,
                )
                .all()
            )

            for h in holdings:
                ticker = h.ticker.upper()
                quote = quote_map.get(ticker)
                if not quote:
                    quote = get_quote(ticker)
                    quote_map[ticker] = quote

                fill_price = quote.price if quote and quote.price > 0 else h.avg_buy_price
                qty_to_sell = h.quantity

                logger.info(
                    "Auto square-off triggered for %s (%s) qty=%.4f @ %.4f (sq_off_date=%s, today=%s)",
                    ticker, m, qty_to_sell, fill_price, h.square_off_date, market_today,
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

