"""
services/portfolio.py — Live portfolio calculations.

All functions take an open SQLAlchemy Session and a Wallet ORM object.
They return plain dataclasses (not ORM or Pydantic) so they're testable
without FastAPI context.

The router layer converts these into Pydantic response schemas.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field

from datetime import date
from sqlalchemy.orm import Session

from models.orm import Transaction, Wallet
from services.price_feed import get_quotes

logger = logging.getLogger(__name__)


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class HoldingPnL:
    """A single holding enriched with its current market value and P&L."""
    id: int
    ticker: str
    quantity: float
    avg_buy_price: float
    current_price: float
    current_value: float
    cost_basis: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    currency: str
    market_open: bool
    square_off_date: date | None = None
    is_intraday: bool = False
    price_error: str | None = None


@dataclass
class WalletSummary:
    """Full snapshot of a wallet: cash + live holdings + P&L totals."""
    wallet_id: int
    market: str
    currency: str
    cash_balance: float
    starting_balance: float
    holdings: list[HoldingPnL] = field(default_factory=list)
    total_holdings_value: float = 0.0
    total_wallet_value: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_realized_pnl: float = 0.0


# ── Core functions ────────────────────────────────────────────────────────────

def get_holdings_with_pnl(db: Session, wallet: Wallet) -> list[HoldingPnL]:
    """
    Return each open holding enriched with a live price and unrealized P&L.

    Fetches all tickers in a single batched yfinance call.
    Holdings whose price fetch fails get price_error set and zero P&L.
    """
    holdings = wallet.holdings   # loaded via SQLAlchemy relationship
    if not holdings:
        return []

    symbols = [h.ticker for h in holdings]
    quotes_list = get_quotes(symbols)
    quotes = {q.symbol: q for q in quotes_list}

    result: list[HoldingPnL] = []
    for h in holdings:
        q = quotes.get(h.ticker)

        if q is None or q.error:
            error_msg = (q.error if q else f"No quote returned for {h.ticker}")
            logger.warning("Could not price holding %s: %s", h.ticker, error_msg)
            result.append(
                HoldingPnL(
                    id=h.id,
                    ticker=h.ticker,
                    quantity=h.quantity,
                    avg_buy_price=h.avg_buy_price,
                    current_price=0.0,
                    current_value=0.0,
                    cost_basis=round(h.avg_buy_price * h.quantity, 2),
                    unrealized_pnl=0.0,
                    unrealized_pnl_pct=0.0,
                    currency=wallet.currency,
                    market_open=False,
                    square_off_date=h.square_off_date,
                    is_intraday=bool(h.is_intraday),
                    price_error=error_msg,
                )
            )
        else:
            cost_basis     = round(h.avg_buy_price * h.quantity, 2)
            current_value  = round(q.price * h.quantity, 2)
            unrealized_pnl = round(current_value - cost_basis, 2)
            unrealized_pnl_pct = (
                round((unrealized_pnl / cost_basis) * 100, 4)
                if cost_basis != 0 else 0.0
            )
            result.append(
                HoldingPnL(
                    id=h.id,
                    ticker=h.ticker,
                    quantity=h.quantity,
                    avg_buy_price=h.avg_buy_price,
                    current_price=q.price,
                    current_value=current_value,
                    cost_basis=cost_basis,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_pct=unrealized_pnl_pct,
                    currency=wallet.currency,
                    market_open=q.market_open,
                    square_off_date=h.square_off_date,
                    is_intraday=bool(h.is_intraday),
                    price_error=None,
                )
            )

    return result


def get_realized_pnl(db: Session, wallet: Wallet) -> float:
    """
    Sum of realized_pnl from all sell Transactions for this wallet.

    realized_pnl per sell = (sell_price - avg_buy_price_at_sale) × quantity
    It is stored on the Transaction at fill time, so it's always accurate
    even after a position is fully closed and the Holding row is deleted.
    """
    sell_txns = (
        db.query(Transaction)
        .filter(Transaction.wallet_id == wallet.id, Transaction.side == "sell")
        .all()
    )
    total = sum(t.realized_pnl or 0.0 for t in sell_txns)
    return round(total, 6)


def get_wallet_summary(db: Session, wallet: Wallet) -> WalletSummary:
    """
    Full portfolio snapshot: cash balance + live holdings P&L + totals.

    This makes one batched price-feed call for all open holdings.
    """
    holdings_pnl   = get_holdings_with_pnl(db, wallet)
    realized_pnl   = get_realized_pnl(db, wallet)

    total_holdings_value = round(sum(h.current_value  for h in holdings_pnl), 2)
    total_wallet_value   = round(wallet.current_cash_balance + total_holdings_value, 2)
    total_unrealized_pnl = round(sum(h.unrealized_pnl for h in holdings_pnl), 2)

    return WalletSummary(
        wallet_id=wallet.id,
        market=wallet.market,
        currency=wallet.currency,
        cash_balance=wallet.current_cash_balance,
        starting_balance=wallet.starting_balance,
        holdings=holdings_pnl,
        total_holdings_value=total_holdings_value,
        total_wallet_value=total_wallet_value,
        total_unrealized_pnl=total_unrealized_pnl,
        total_realized_pnl=realized_pnl,
    )
