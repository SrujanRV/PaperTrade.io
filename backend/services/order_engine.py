"""
services/order_engine.py — Market order execution logic.

Responsibilities
----------------
1. Look up the wallet for the requested market.
2. Validate the ticker's exchange matches the wallet's market.
3. Fetch a live quote via price_feed and check market hours.
4. Execute BUY or SELL atomically:
   BUY:  deduct cash, upsert Holding with weighted-avg price, persist Order + Transaction
   SELL: add proceeds, reduce Holding (delete if fully closed), persist Order + Transaction
5. For any rejection: persist a rejected Order and return it (no other DB changes).

All DB writes happen inside a single commit, so a mid-operation crash leaves no
partial state — the order row is the last thing committed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.orm import Holding, Order, Transaction, Wallet
from services.price_feed import get_quote

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

# Which wallet market a ticker's exchange belongs to
_EXCHANGE_MARKET: dict[str, str] = {
    "NSE":    "IN",
    "BSE":    "IN",
    "NYSE":   "US",
    "NASDAQ": "US",
}

# Suffix → exchange (mirrors config.py — kept local to avoid circular imports)
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
    return "NASDAQ"  # default for US tickers


def _ticker_market(ticker: str) -> str:
    return _EXCHANGE_MARKET.get(_ticker_exchange(ticker), "US")


def _persist_rejected(
    db: Session,
    wallet_id: int,
    ticker: str,
    side: str,
    quantity: float,
    reject_reason: str,
) -> Order:
    """Create and commit a rejected Order record, returning it."""
    order = Order(
        wallet_id=wallet_id,
        ticker=ticker,
        order_type="market",
        side=side,
        quantity=quantity,
        status="rejected",
        reject_reason=reject_reason,
        created_at=_now_utc(),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    logger.info("Order REJECTED: %s %s ×%s | reason=%s", side.upper(), ticker, quantity, reject_reason)
    return order


# ── Buy execution ─────────────────────────────────────────────────────────────

def _execute_buy(
    db: Session,
    wallet: Wallet,
    ticker: str,
    quantity: float,
    price: float,
) -> Order:
    total_cost = round(price * quantity, 2)

    # Cash check
    if wallet.current_cash_balance < total_cost:
        return _persist_rejected(
            db, wallet.id, ticker, "buy", quantity, "insufficient_funds"
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
        )
        db.add(holding)

    # Create filled order
    order = Order(
        wallet_id=wallet.id,
        ticker=ticker,
        order_type="market",
        side="buy",
        quantity=quantity,
        executed_price=price,
        status="filled",
        created_at=_now_utc(),
        executed_at=_now_utc(),
    )
    db.add(order)
    db.flush()  # get order.id before creating Transaction

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
        "BUY filled: %s ×%s @ %.4f = %s %.2f | cash_after=%.2f",
        ticker, quantity, price, wallet.currency, total_cost, wallet.current_cash_balance,
    )
    return order


# ── Sell execution ────────────────────────────────────────────────────────────

def _execute_sell(
    db: Session,
    wallet: Wallet,
    ticker: str,
    quantity: float,
    price: float,
) -> Order:
    holding = (
        db.query(Holding)
        .filter(Holding.wallet_id == wallet.id, Holding.ticker == ticker)
        .first()
    )

    # Holdings check (use small epsilon for float comparison)
    if not holding or holding.quantity < quantity - 1e-9:
        return _persist_rejected(
            db, wallet.id, ticker, "sell", quantity, "insufficient_holdings"
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

    # Create filled order
    order = Order(
        wallet_id=wallet.id,
        ticker=ticker,
        order_type="market",
        side="sell",
        quantity=quantity,
        executed_price=price,
        status="filled",
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
        timestamp=_now_utc(),
    )
    db.add(txn)
    db.commit()
    db.refresh(order)

    logger.info(
        "SELL filled: %s ×%s @ %.4f proceeds=%s %.2f realized_pnl=%.4f | cash_after=%.2f",
        ticker, quantity, price, wallet.currency, proceeds,
        realized_pnl, wallet.current_cash_balance,
    )
    return order


# ── Public API ────────────────────────────────────────────────────────────────

def place_market_order(
    db: Session,
    market: str,
    ticker: str,
    side: str,
    quantity: float,
) -> Order:
    """
    Place a market buy or sell order against the given wallet.

    Validates (in order):
      1. Wallet exists for the given market
      2. Ticker's exchange matches the wallet's market
      3. Quote is fetchable (valid ticker)
      4. Exchange is currently open
      5. Sufficient cash (buy) or holdings (sell)

    Returns the Order ORM object (status = "filled" or "rejected").
    Raises ValueError if the wallet doesn't exist (caller should handle as 404).
    """
    ticker = ticker.strip().upper()

    # ── Wallet lookup ──────────────────────────────────────────────────────────
    wallet = db.query(Wallet).filter(Wallet.market == market).first()
    if not wallet:
        raise ValueError(
            f"No wallet for market '{market}'. Call POST /api/wallet/setup first."
        )

    # ── Ticker ↔ wallet market check ──────────────────────────────────────────
    if _ticker_market(ticker) != market:
        exchange = _ticker_exchange(ticker)
        correct_market = _EXCHANGE_MARKET.get(exchange, "US")
        logger.warning(
            "Ticker %s (%s) sent to wrong wallet %s — should be %s",
            ticker, exchange, market, correct_market,
        )
        return _persist_rejected(db, wallet.id, ticker, side, quantity, "wrong_market")

    # ── Fetch live quote ───────────────────────────────────────────────────────
    quote = get_quote(ticker, force_refresh=True)
    if quote.error:
        logger.warning("Invalid ticker %s: %s", ticker, quote.error)
        return _persist_rejected(db, wallet.id, ticker, side, quantity, "invalid_ticker")

    # ── Market-hours check ─────────────────────────────────────────────────────
    if not quote.market_open:
        return _persist_rejected(db, wallet.id, ticker, side, quantity, "market_closed")

    price = quote.price

    # ── Route to buy / sell ────────────────────────────────────────────────────
    if side == "buy":
        return _execute_buy(db, wallet, ticker, quantity, price)
    elif side == "sell":
        return _execute_sell(db, wallet, ticker, quantity, price)
    else:
        raise ValueError(f"Invalid side: {side!r} — must be 'buy' or 'sell'")
