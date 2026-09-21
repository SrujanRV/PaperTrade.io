"""
routers/wallet.py — Wallet setup and retrieval endpoints.

Phase 2a scope:
    POST /api/wallet/setup   — create or re-initialise a wallet
    GET  /api/wallet/{market} — return wallet state + holdings

Phase 2b will add:
    GET  /api/wallet/{market}/orders
    GET  /api/wallet/{market}/transactions
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models.orm import Wallet
from models.schemas import HoldingWithPnLOut, WalletOut, WalletSetupRequest, WalletSummaryOut
from services.portfolio import get_wallet_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wallet", tags=["wallet"])

# Maps market code → currency
_CURRENCY: dict[str, str] = {"IN": "INR", "US": "USD"}


# ── POST /api/wallet/setup ─────────────────────────────────────────────────────

@router.post(
    "/setup",
    response_model=WalletOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create or reset a wallet",
    description=(
        "Creates a new wallet for the given market, or resets an existing one "
        "to a fresh starting balance (clears holdings and order history too). "
        "Call once for 'IN' and once for 'US' to set up both portfolios."
    ),
)
def setup_wallet(body: WalletSetupRequest, db: Session = Depends(get_db)) -> WalletOut:
    currency = _CURRENCY[body.market]

    existing = db.query(Wallet).filter(Wallet.market == body.market).first()

    if existing:
        # Re-initialise — wipe balance back to fresh start.
        # Cascade delete on holdings/orders/transactions is handled by the ORM
        # relationship (cascade="all, delete-orphan") when we delete and recreate.
        logger.info(
            "Re-initialising %s wallet (old balance: %.2f %s → new: %.2f %s)",
            body.market, existing.current_cash_balance, currency,
            body.starting_balance, currency,
        )
        db.delete(existing)
        db.flush()   # ensure the old row + cascades are gone before inserting

    wallet = Wallet(
        market=body.market,
        currency=currency,
        starting_balance=body.starting_balance,
        current_cash_balance=body.starting_balance,
    )
    db.add(wallet)
    db.commit()
    db.refresh(wallet)

    logger.info("Wallet created: %s", wallet)
    return WalletOut.model_validate(wallet)


# ── GET /api/wallet/{market} ───────────────────────────────────────────────────

@router.get(
    "/{market}",
    response_model=WalletOut,
    summary="Get wallet state",
    description="Returns the wallet's current cash balance and open holdings.",
)
def get_wallet(
    market: Literal["IN", "US"],
    db: Session = Depends(get_db),
) -> WalletOut:
    wallet = db.query(Wallet).filter(Wallet.market == market).first()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No wallet found for market '{market}'. "
                   f"Call POST /api/wallet/setup first.",
        )
    return WalletOut.model_validate(wallet)


# ── GET /api/wallet/{market}/summary ─────────────────────────────────────────

@router.get(
    "/{market}/summary",
    response_model=WalletSummaryOut,
    summary="Full portfolio snapshot",
    description=(
        "Returns cash balance, all open holdings with live prices and unrealized P&L, "
        "total portfolio value, total unrealized P&L, and total realized P&L from all sells."
    ),
)
def wallet_summary(
    market: Literal["IN", "US"],
    db: Session = Depends(get_db),
) -> WalletSummaryOut:
    wallet = db.query(Wallet).filter(Wallet.market == market).first()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No wallet found for market '{market}'. "
                   f"Call POST /api/wallet/setup first.",
        )

    summary = get_wallet_summary(db, wallet)

    return WalletSummaryOut(
        wallet_id=summary.wallet_id,
        market=summary.market,
        currency=summary.currency,
        cash_balance=summary.cash_balance,
        starting_balance=summary.starting_balance,
        holdings=[
            HoldingWithPnLOut(**dataclasses.asdict(h))
            for h in summary.holdings
        ],
        total_holdings_value=summary.total_holdings_value,
        total_wallet_value=summary.total_wallet_value,
        total_unrealized_pnl=summary.total_unrealized_pnl,
        total_realized_pnl=summary.total_realized_pnl,
    )
