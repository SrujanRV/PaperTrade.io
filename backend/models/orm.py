"""
models/orm.py — SQLAlchemy ORM table definitions.

Four tables for Phase 2:
    Wallet      — one row per market (IN or US), tracks cash balance
    Holding     — one row per ticker per wallet, tracks position
    Order       — every order attempt (filled or rejected)
    Transaction — immutable ledger entry created for every filled order
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey,
    Integer, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── Wallet ────────────────────────────────────────────────────────────────────

class Wallet(Base):
    """
    One row per market. market is the natural primary key but we use
    an integer PK for FK references from other tables.

    market:                "IN" | "US"
    currency:              "INR" | "USD"
    starting_balance:      the amount the user chose at setup — never changes
    current_cash_balance:  decreases on buy, increases on sell
    """
    __tablename__ = "wallets"
    __table_args__ = (
        UniqueConstraint("market", name="uq_wallet_market"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(2), nullable=False)          # "IN" | "US"
    currency: Mapped[str] = mapped_column(String(3), nullable=False)        # "INR" | "USD"
    starting_balance: Mapped[float] = mapped_column(Float, nullable=False)
    current_cash_balance: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )

    # Relationships
    holdings: Mapped[list[Holding]] = relationship(
        "Holding", back_populates="wallet", cascade="all, delete-orphan"
    )
    orders: Mapped[list[Order]] = relationship(
        "Order", back_populates="wallet", cascade="all, delete-orphan"
    )
    transactions: Mapped[list[Transaction]] = relationship(
        "Transaction", back_populates="wallet", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Wallet market={self.market} cash={self.current_cash_balance:.2f} {self.currency}>"


# ── Holding ───────────────────────────────────────────────────────────────────

class Holding(Base):
    """
    Current open position for one ticker in one wallet.

    avg_buy_price is the volume-weighted average of all buy fills.
    When a position is fully closed (quantity reaches 0), the row is deleted
    rather than kept at 0 — keeps the table clean.
    """
    __tablename__ = "holdings"
    __table_args__ = (
        UniqueConstraint("wallet_id", "ticker", name="uq_holding_wallet_ticker"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_buy_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    square_off_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    is_intraday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc, onupdate=_now_utc
    )

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="holdings")

    def __repr__(self) -> str:
        return f"<Holding {self.ticker} qty={self.quantity} avg={self.avg_buy_price} sq_off={self.square_off_date}>"


# ── Order ─────────────────────────────────────────────────────────────────────

class Order(Base):
    """
    Every order attempt — both filled and rejected.

    order_type:       "market" | "limit" | "stop_loss"
    side:             "buy" | "sell"
    requested_price:  None for market orders; set for limit/stop
    executed_price:   actual fill price (= live market price for market orders)
    status:           "pending" | "filled" | "rejected" | "cancelled"
    square_off_date:  target date for time-based auto square-off
    is_intraday:      True if order is an intraday position
    triggered_by:     "user" | "auto_square_off" | "stop_loss"
    """
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False, default="market")
    side: Mapped[str] = mapped_column(String(4), nullable=False)            # "buy" | "sell"
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    requested_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trigger_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    executed_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)         # "pending" | "filled" | "rejected" | "cancelled"
    reject_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    square_off_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    is_intraday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    triggered_by: Mapped[str | None] = mapped_column(String(30), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="orders")
    transaction: Mapped[Transaction | None] = relationship(
        "Transaction", back_populates="order", uselist=False
    )

    def __repr__(self) -> str:
        return f"<Order {self.side.upper()} {self.quantity}x {self.ticker} [{self.status}] sq_off={self.square_off_date}>"


# ── Transaction ───────────────────────────────────────────────────────────────

class Transaction(Base):
    """
    Immutable ledger entry — one row per filled order.

    total_value:         quantity × executed_price (always positive)
    cash_balance_after:  wallet.current_cash_balance after this transaction
    triggered_by:        "auto_square_off" | None
    """
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    total_value: Mapped[float] = mapped_column(Float, nullable=False)
    cash_balance_after: Mapped[float] = mapped_column(Float, nullable=False)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    avg_buy_price: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    triggered_by: Mapped[str | None] = mapped_column(String(30), nullable=True, default=None)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="transactions")
    order: Mapped[Order] = relationship("Order", back_populates="transaction")

    def __repr__(self) -> str:
        return f"<Transaction {self.side.upper()} {self.quantity}x {self.ticker} @ {self.price} by={self.triggered_by}>"

