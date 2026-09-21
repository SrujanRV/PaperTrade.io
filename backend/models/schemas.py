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
    """Holding row as returned by GET /api/wallet/{market}"""
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


# ── Order (stub — body not used until Phase 2b) ───────────────────────────────

class OrderRequest(BaseModel):
    """Body for POST /api/orders (Phase 2b)"""
    market: Literal["IN", "US"]
    ticker: str = Field(..., min_length=1, max_length=20)
    side: Literal["buy", "sell"]
    quantity: float = Field(..., gt=0)

    @field_validator("ticker")
    @classmethod
    def upper_ticker(cls, v: str) -> str:
        return v.strip().upper()


class OrderOut(BaseModel):
    """Order row as returned from the API"""
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


class TransactionOut(BaseModel):
    """Transaction ledger entry"""
    id: int
    wallet_id: int
    order_id: int
    ticker: str
    side: str
    quantity: float
    price: float
    total_value: float
    cash_balance_after: float
    timestamp: datetime

    model_config = {"from_attributes": True}
