"""
models/schemas.py — Pydantic v2 request/response schemas.

Separate from ORM models so the API surface is decoupled from
the database shape (we can rename/add DB columns without breaking clients).
"""

from __future__ import annotations

from datetime import datetime
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


class HoldingOut(BaseModel):
    """Holding row — plain, no live price (used by GET /api/wallet/{market})"""
    id: int
    ticker: str
    quantity: float
    avg_buy_price: float
    last_updated: datetime

    model_config = {"from_attributes": True}


class WalletOut(BaseModel):
    """Full wallet state returned by GET /api/wallet/{market}"""
    id: int
    market: str
    currency: str
    starting_balance: float
    current_cash_balance: float
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
    price_error: str | None = None


class WalletSummaryOut(BaseModel):
    """Full portfolio snapshot: cash + live holdings + P&L totals"""
    wallet_id: int
    market: str
    currency: str
    cash_balance: float
    starting_balance: float
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

    @field_validator("ticker")
    @classmethod
    def upper_ticker(cls, v: str) -> str:
        return v.strip().upper()


class OrderOut(BaseModel):
    """Order record — returned for both filled and rejected orders"""
    id: int
    wallet_id: int
    ticker: str
    order_type: str
    side: str
    quantity: float
    requested_price: float | None
    executed_price: float | None
    status: str
    reject_reason: str | None
    created_at: datetime
    executed_at: datetime | None

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
    timestamp: datetime

    model_config = {"from_attributes": True}

