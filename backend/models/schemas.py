"""
models/schemas.py — Pydantic v2 request/response schemas.

Separate from ORM models so the API surface is decoupled from
the database shape (we can rename/add DB columns without breaking clients).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ── Wallet ────────────────────────────────────────────────────────────────────

class WalletSetupRequest(BaseModel):
    """Body for POST /api/wallet/setup"""
    market: Literal["IN", "US"] = Field(
        ..., description="'IN' for Indian (NSE/BSE), 'US' for US (NYSE/NASDAQ)"
    )
    starting_balance: float = Field(
        ..., gt=0, description="Starting virtual cash — must be > 0"
    )

    @field_validator("starting_balance")
    @classmethod
    def round_balance(cls, v: float) -> float:
        return round(v, 2)


class BalanceResetRequest(BaseModel):
    """Body for PATCH /api/wallet/{market}/balance"""
    cash_balance: float = Field(..., gt=0, description="New cash balance")

    @field_validator("cash_balance")
    @classmethod
    def round_balance(cls, v: float) -> float:
        return round(v, 2)


class HoldingLotOut(BaseModel):
    id: int
    quantity: float
    buy_price: float
    square_off_date: date | None = None
    is_intraday: bool = False
    is_short: bool = False
    margin_locked: float = 0.0
    created_at: datetime

    model_config = {"from_attributes": True}


class HoldingOut(BaseModel):
    """Holding row — plain, no live price (used by GET /api/wallet/{market})"""
    id: int
    ticker: str
    quantity: float
    avg_buy_price: float
    square_off_date: date | None = None
    is_intraday: bool = False
    is_short: bool = False
    margin_locked: float = 0.0
    square_off_quantity: float | None = None
    lots: list[HoldingLotOut] = []
    last_updated: datetime

    model_config = {"from_attributes": True}


class WalletOut(BaseModel):
    """Full wallet state returned by GET /api/wallet/{market}"""
    id: int
    market: str
    currency: str
    starting_balance: float
    current_cash_balance: float
    margin_used: float = 0.0
    available_buying_power: float = 0.0
    created_at: datetime
    holdings: list[HoldingOut] = []

    model_config = {"from_attributes": True}


# ── Holdings with live P&L (used by /summary) ─────────────────────────────────

class HoldingWithPnLOut(BaseModel):
    """Holding enriched with live price and unrealized P&L"""
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
    is_short: bool = False
    margin_locked: float | None = None
    maintenance_margin_required: float | None = None
    margin_level_pct: float | None = None
    liquidation_price: float | None = None
    distance_to_margin_call_pct: float | None = None
    square_off_quantity: float | None = None
    lots: list[HoldingLotOut] = []
    price_error: str | None = None


class WalletSummaryOut(BaseModel):
    """Full portfolio snapshot: cash + live holdings + P&L totals"""
    wallet_id: int
    market: str
    currency: str
    cash_balance: float
    starting_balance: float
    margin_used: float = 0.0
    available_buying_power: float = 0.0
    holdings: list[HoldingWithPnLOut] = []
    total_holdings_value: float
    total_wallet_value: float      # cash + holdings value
    total_unrealized_pnl: float
    total_realized_pnl: float


# ── Orders ────────────────────────────────────────────────────────────────────

class OrderRequest(BaseModel):
    """Body for POST /api/orders"""
    market: Literal["IN", "US"] = Field(
        ..., description="Which wallet to trade from"
    )
    ticker: str = Field(
        ..., min_length=1, max_length=20,
        description="Ticker symbol — use .NS suffix for NSE (e.g. RELIANCE.NS) or plain for US (e.g. AAPL)"
    )
    side: Literal["buy", "sell"]
    quantity: float = Field(..., gt=0, description="Number of shares/units — must be > 0")
    order_type: Literal["market", "limit", "stop_loss"] = Field(
        default="market", description="Execution type: market, limit, or stop_loss"
    )
    requested_price: float | None = Field(
        default=None, gt=0, description="Limit price for limit order, or trigger price for stop-loss"
    )
    trigger_price: float | None = Field(
        default=None, gt=0, description="Trigger price for stop-loss order"
    )
    holding_days: int | None = Field(
        default=None, ge=0, description="Optional holding duration in trading days (0 = intraday)"
    )
    square_off_date: str | None = Field(
        default=None, description="Target date for auto square-off ('YYYY-MM-DD')"
    )
    is_intraday: bool = Field(
        default=False, description="Whether this is an intraday position"
    )

    @field_validator("ticker")
    @classmethod
    def upper_ticker(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("requested_price", "trigger_price")
    @classmethod
    def round_prices(cls, v: float | None) -> float | None:
        if v is not None:
            return round(v, 4)
        return v


class OrderOut(BaseModel):
    """Order record — returned for pending, filled, rejected, and cancelled orders"""
    id: int
    wallet_id: int
    ticker: str
    order_type: str
    side: str
    quantity: float
    requested_price: float | None = None
    trigger_price: float | None = None
    executed_price: float | None = None
    status: str
    reject_reason: str | None = None
    square_off_date: date | None = None
    is_intraday: bool = False
    is_short: bool = False
    triggered_by: str | None = None
    created_at: datetime
    executed_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── Transactions ───────────────────────────────────────────────────────────────

class TransactionOut(BaseModel):
    """Immutable ledger entry for every filled order"""
    id: int
    wallet_id: int
    order_id: int
    ticker: str
    side: str
    quantity: float
    price: float
    total_value: float
    cash_balance_after: float
    realized_pnl: float | None   # non-null for sell transactions
    avg_buy_price: float | None = None
    triggered_by: str | None = None
    is_short: bool = False
    timestamp: datetime

    model_config = {"from_attributes": True}


# ── Trades (Closed Round-Trips) ───────────────────────────────────────────────

class TradeOut(BaseModel):
    """Closed round-trip trade resulting from a sell execution"""
    id: int
    wallet_id: int
    order_id: int
    ticker: str
    quantity: float
    avg_buy_price: float
    sell_price: float
    total_value: float
    realized_pnl: float
    realized_pnl_percent: float
    triggered_by: str | None = None
    is_short: bool = False
    timestamp: datetime

    model_config = {"from_attributes": True}


# ── Derivatives (F&O) Schemas ─────────────────────────────────────────────────

class DerivativeContractOut(BaseModel):
    """Tradeable Options or Futures contract specification"""
    id: int
    symbol: str
    underlying: str
    instrument_type: Literal["option", "future"]
    option_type: Literal["call", "put"] | None = None
    strike_price: float | None = None
    expiry_date: date | None = None
    lot_size: int
    market: Literal["IN", "US"]
    created_at: datetime

    model_config = {"from_attributes": True}


class DerivativePositionOut(BaseModel):
    """Open Options or Futures position"""
    id: int
    wallet_id: int
    contract_id: int
    contract: DerivativeContractOut
    side: Literal["long", "short"]
    quantity: float  # in lots
    entry_price: float
    is_covered: bool = False
    margin_locked: float = 0.0
    last_mtm_price: float | None = None
    last_mtm_date: date | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DerivativeOrderOut(BaseModel):
    """Derivative order attempt and execution status"""
    id: int
    wallet_id: int
    contract_id: int
    contract: DerivativeContractOut | None = None
    side: Literal["buy", "sell"]
    action: Literal["buy_to_open", "sell_to_open", "buy_to_close", "sell_to_close"]
    quantity: float  # in lots
    order_type: Literal["market", "limit"] = "market"
    requested_price: float | None = None
    executed_price: float | None = None
    status: Literal["pending", "filled", "rejected", "cancelled"]
    reject_reason: str | None = None
    margin_required: float = 0.0
    triggered_by: str | None = None
    created_at: datetime
    executed_at: datetime | None = None

    model_config = {"from_attributes": True}


class DerivativeTransactionOut(BaseModel):
    """Immutable ledger entry for derivative events (trades, daily MTM, expiry)"""
    id: int
    wallet_id: int
    position_id: int | None = None
    order_id: int | None = None
    transaction_type: Literal["trade", "mtm_settlement", "expiry_settlement"]
    amount: float  # cash flow (+ credited, - debited)
    price: float | None = None
    realized_pnl: float | None = None
    cash_balance_after: float
    timestamp: datetime

    model_config = {"from_attributes": True}


class DerivativeOrderRequest(BaseModel):
    """Body for placing an Options or Futures order"""
    market: Literal["IN", "US"]
    contract_id: int | None = None
    # Alternatively specify contract specification:
    symbol: str | None = None
    underlying: str | None = None
    instrument_type: Literal["option", "future"] | None = None
    option_type: Literal["call", "put"] | None = None
    strike_price: float | None = None
    expiry_date: date | None = None
    lot_size: int | None = None

    side: Literal["buy", "sell"]
    action: Literal["buy_to_open", "sell_to_open", "buy_to_close", "sell_to_close"]
    quantity: float = Field(..., gt=0, description="Order quantity in lots (e.g. 1, 2)")
    order_type: Literal["market", "limit"] = "market"
    price: float | None = Field(None, gt=0, description="Limit price (or fill price override for testing)")


class DerivativePositionWithPnLOut(BaseModel):
    """Open Options or Futures position with live market metrics"""
    id: int
    wallet_id: int
    contract_id: int
    contract: DerivativeContractOut
    side: Literal["long", "short"]
    quantity: float  # in lots
    entry_price: float
    current_price: float
    notional_value: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    is_covered: bool = False
    margin_locked: float = 0.0
    maintenance_margin_required: float = 0.0
    margin_level_pct: float | None = None
    last_mtm_price: float | None = None
    last_mtm_date: date | None = None
    created_at: datetime




