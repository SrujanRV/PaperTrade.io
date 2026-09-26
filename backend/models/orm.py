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
    margin_used: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
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
    derivative_positions: Mapped[list[DerivativePosition]] = relationship(
        "DerivativePosition", back_populates="wallet", cascade="all, delete-orphan"
    )
    derivative_orders: Mapped[list[DerivativeOrder]] = relationship(
        "DerivativeOrder", back_populates="wallet", cascade="all, delete-orphan"
    )
    derivative_transactions: Mapped[list[DerivativeTransaction]] = relationship(
        "DerivativeTransaction", back_populates="wallet", cascade="all, delete-orphan"
    )

    @property
    def available_buying_power(self) -> float:
        """Cash balance available for trading after locking margin collateral."""
        return max(0.0, round(self.current_cash_balance - (self.margin_used or 0.0), 2))

    def __repr__(self) -> str:
        return f"<Wallet market={self.market} cash={self.current_cash_balance:.2f} margin={self.margin_used:.2f} {self.currency}>"


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
    is_short: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    margin_locked: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc, onupdate=_now_utc
    )

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="holdings")
    lots: Mapped[list["HoldingLot"]] = relationship(
        "HoldingLot",
        back_populates="holding",
        cascade="all, delete-orphan",
        order_by="HoldingLot.created_at",
    )

    def __repr__(self) -> str:
        return f"<Holding {self.ticker} qty={self.quantity} avg={self.avg_buy_price} short={self.is_short} margin={self.margin_locked}>"


# ── HoldingLot (Tranche-based position tracking) ──────────────────────────────

class HoldingLot(Base):
    """
    Individual tranche or lot of shares within a Holding.
    Tracks distinct purchase quantities, buy prices, and optional square-off expiry dates.
    """
    __tablename__ = "holding_lots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    holding_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("holdings.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    buy_price: Mapped[float] = mapped_column(Float, nullable=False)
    square_off_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    is_intraday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_short: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    margin_locked: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )

    holding: Mapped[Holding] = relationship("Holding", back_populates="lots")

    def __repr__(self) -> str:
        return f"<HoldingLot {self.id} qty={self.quantity} @ {self.buy_price} short={self.is_short} margin={self.margin_locked}>"


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
    is_short:         True if order is a short sale or cover buy
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
    is_short: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
        return f"<Order {self.side.upper()} {self.quantity}x {self.ticker} [{self.status}] short={self.is_short} sq_off={self.square_off_date}>"


# ── Transaction ───────────────────────────────────────────────────────────────

class Transaction(Base):
    """
    Immutable ledger entry — one row per filled order.

    total_value:         quantity × executed_price (always positive)
    cash_balance_after:  wallet.current_cash_balance after this transaction
    is_short:            True if transaction relates to a short position
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
    is_short: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    triggered_by: Mapped[str | None] = mapped_column(String(30), nullable=True, default=None)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="transactions")
    order: Mapped[Order] = relationship("Order", back_populates="transaction")

    def __repr__(self) -> str:
        return f"<Transaction {self.side.upper()} {self.quantity}x {self.ticker} @ {self.price} by={self.triggered_by}>"


# ── DerivativeContract ────────────────────────────────────────────────────────

class DerivativeContract(Base):
    """
    Represents a specific tradeable Options or Futures contract.

    underlying:      Index or stock symbol (e.g. "NIFTY", "BANKNIFTY", "AAPL", "ES")
    instrument_type: "option" | "future"
    option_type:     "call" | "put" | None (for futures)
    strike_price:    Strike price | None (for futures)
    expiry_date:     Settlement/expiry date | None (for perpetual US futures like ES=F)
    lot_size:        Number of units/shares per 1 contract lot (e.g. 65 for NIFTY, 100 for US equity options)
    market:          "IN" | "US"
    """
    __tablename__ = "derivative_contracts"
    __table_args__ = (
        UniqueConstraint(
            "market", "underlying", "instrument_type", "option_type", "strike_price", "expiry_date",
            name="uq_derivative_contract_spec"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    underlying: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    instrument_type: Mapped[str] = mapped_column(String(10), nullable=False)  # "option" | "future"
    option_type: Mapped[str | None] = mapped_column(String(4), nullable=True)  # "call" | "put" | None
    strike_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    lot_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    market: Mapped[str] = mapped_column(String(2), nullable=False)  # "IN" | "US"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )

    positions: Mapped[list[DerivativePosition]] = relationship(
        "DerivativePosition", back_populates="contract", cascade="all, delete-orphan"
    )
    orders: Mapped[list[DerivativeOrder]] = relationship(
        "DerivativeOrder", back_populates="contract"
    )

    def __repr__(self) -> str:
        return f"<DerivativeContract {self.symbol} {self.instrument_type} {self.market}>"


# ── DerivativePosition ────────────────────────────────────────────────────────

class DerivativePosition(Base):
    """
    Current open position in a derivative contract.

    quantity:        Expressed in LOTS (total units = quantity × contract.lot_size)
    side:            "long" | "short"
    entry_price:     Weighted average trade price / premium per unit
    is_covered:      True if written call/put is backed by underlying equity holding
    margin_locked:   Collateral locked for naked options write (20% init / 15% maint) or futures (12% init / 10% maint)
    last_mtm_price:  Tracks last daily MTM mark price for futures daily settlement
    last_mtm_date:   Date of last MTM settlement
    """
    __tablename__ = "derivative_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("derivative_contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    side: Mapped[str] = mapped_column(String(5), nullable=False)  # "long" | "short"
    quantity: Mapped[float] = mapped_column(Float, nullable=False)  # in lots
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    is_covered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    margin_locked: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_mtm_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_mtm_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="derivative_positions")
    contract: Mapped[DerivativeContract] = relationship("DerivativeContract", back_populates="positions")
    transactions: Mapped[list[DerivativeTransaction]] = relationship(
        "DerivativeTransaction", back_populates="position"
    )

    def __repr__(self) -> str:
        return f"<DerivativePosition {self.side.upper()} {self.quantity} lots of contract #{self.contract_id} @ {self.entry_price}>"


# ── DerivativeOrder ───────────────────────────────────────────────────────────

class DerivativeOrder(Base):
    """
    Derivative order record.

    action:          "buy_to_open" | "sell_to_open" (write/short) | "buy_to_close" (cover) | "sell_to_close" (exit long)
    quantity:        Number of contract lots
    margin_required: Initial margin requirement calculated at order evaluation
    status:          "pending" | "filled" | "rejected" | "cancelled"
    """
    __tablename__ = "derivative_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("derivative_contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # "buy" | "sell"
    action: Mapped[str] = mapped_column(String(15), nullable=False)  # "buy_to_open" | "sell_to_open" | "buy_to_close" | "sell_to_close"
    quantity: Mapped[float] = mapped_column(Float, nullable=False)  # in lots
    order_type: Mapped[str] = mapped_column(String(20), nullable=False, default="market")  # "market" | "limit"
    requested_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    executed_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # "pending" | "filled" | "rejected" | "cancelled"
    reject_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    margin_required: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="derivative_orders")
    contract: Mapped[DerivativeContract] = relationship("DerivativeContract", back_populates="orders")
    transaction: Mapped[DerivativeTransaction | None] = relationship(
        "DerivativeTransaction", back_populates="order", uselist=False
    )

    def __repr__(self) -> str:
        return f"<DerivativeOrder {self.action} {self.quantity}x contract #{self.contract_id} [{self.status}]>"


# ── DerivativeTransaction ─────────────────────────────────────────────────────

class DerivativeTransaction(Base):
    """
    Immutable ledger entry for derivative events:
    - "trade":              Order execution (premium debit/credit or futures open/close)
    - "mtm_settlement":     Daily mark-to-market futures cash settlement (not closing position)
    - "expiry_settlement":  Options cash settlement at expiry (intrinsic value) or futures expiry
    """
    __tablename__ = "derivative_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("derivative_positions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    order_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("derivative_orders.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    transaction_type: Mapped[str] = mapped_column(
        String(25), nullable=False
    )  # "trade" | "mtm_settlement" | "expiry_settlement"
    amount: Mapped[float] = mapped_column(Float, nullable=False)  # cash flow (+ credited, - debited)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    cash_balance_after: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )

    wallet: Mapped[Wallet] = relationship("Wallet", back_populates="derivative_transactions")
    position: Mapped[DerivativePosition | None] = relationship(
        "DerivativePosition", back_populates="transactions"
    )
    order: Mapped[DerivativeOrder | None] = relationship(
        "DerivativeOrder", back_populates="transaction"
    )

    def __repr__(self) -> str:
        return f"<DerivativeTransaction {self.transaction_type} amt={self.amount:.2f} pnl={self.realized_pnl}>"


