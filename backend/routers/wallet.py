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
from models.orm import Transaction, Wallet
from models.schemas import (
    BalanceResetRequest,
    HoldingWithPnLOut,
    TradeOut,
    WalletOut,
    WalletSetupRequest,
    WalletSummaryOut,
)
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
        margin_used=summary.margin_used,
        available_buying_power=summary.available_buying_power,
        holdings=[
            HoldingWithPnLOut(**dataclasses.asdict(h))
            for h in summary.holdings
        ],
        total_holdings_value=summary.total_holdings_value,
        total_wallet_value=summary.total_wallet_value,
        total_unrealized_pnl=summary.total_unrealized_pnl,
        total_realized_pnl=summary.total_realized_pnl,
    )


# ── GET /api/wallet/{market}/trades ──────────────────────────────────────────

@router.get(
    "/{market}/trades",
    response_model=list[TradeOut],
    summary="Closed trades log",
    description=(
        "Returns all closed trades (sell transactions) with realized P&L, "
        "avg buy price, sell price, and return %, newest first."
    ),
)
def get_trades(
    market: Literal["IN", "US"],
    db: Session = Depends(get_db),
) -> list[TradeOut]:
    wallet = db.query(Wallet).filter(Wallet.market == market).first()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No wallet found for market '{market}'. Call POST /api/wallet/setup first.",
        )

    txns = (
        db.query(Transaction)
        .filter(Transaction.wallet_id == wallet.id, Transaction.realized_pnl.isnot(None))
        .order_by(Transaction.timestamp.desc())
        .all()
    )

    trades: list[TradeOut] = []
    for t in txns:
        pnl = t.realized_pnl or 0.0
        qty = t.quantity or 1.0
        is_short = bool(t.is_short)

        if is_short:
            # Short cover: closing transaction is side="buy"
            buy_p = t.price  # cover purchase price
            sell_p = (
                t.avg_buy_price
                if t.avg_buy_price is not None
                else round(buy_p + (pnl / qty), 4)
            )  # entry short sale price
            basis = sell_p * qty
            pnl_pct = round((pnl / basis) * 100, 2) if basis > 0 else 0.0
        else:
            sell_p = t.price
            buy_p = (
                t.avg_buy_price
                if t.avg_buy_price is not None
                else round(sell_p - (pnl / qty), 4)
            )
            cost = buy_p * qty
            pnl_pct = round((pnl / cost) * 100, 2) if cost > 0 else 0.0

        trades.append(
            TradeOut(
                id=t.id,
                wallet_id=t.wallet_id,
                order_id=t.order_id,
                ticker=t.ticker,
                quantity=qty,
                avg_buy_price=buy_p,
                sell_price=sell_p,
                total_value=t.total_value,
                realized_pnl=pnl,
                realized_pnl_percent=pnl_pct,
                triggered_by=t.triggered_by,
                is_short=is_short,
                timestamp=t.timestamp,
            )
        )

    return trades


# ── PATCH /api/wallet/{market}/balance ─────────────────────────────────────────

@router.patch(
    "/{market}/balance",
    response_model=WalletOut,
    summary="Update wallet cash balance",
    description="Adjusts current_cash_balance without wiping transaction or order history.",
)
def update_wallet_balance(
    market: Literal["IN", "US"],
    body: BalanceResetRequest,
    db: Session = Depends(get_db),
) -> WalletOut:
    wallet = db.query(Wallet).filter(Wallet.market == market).first()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No wallet found for market '{market}'. Call POST /api/wallet/setup first.",
        )

    logger.info(
        "Updating %s wallet cash balance from %.2f to %.2f",
        market, wallet.current_cash_balance, body.cash_balance,
    )
    wallet.current_cash_balance = body.cash_balance
    db.commit()
    db.refresh(wallet)
    return WalletOut.model_validate(wallet)


# ── DELETE /api/wallet/{market} ───────────────────────────────────────────────

@router.delete(
    "/{market}",
    status_code=status.HTTP_200_OK,
    summary="Delete portfolio and reset wallet",
    description="Permanently deletes the wallet and all associated holdings, orders, and transactions.",
)
def delete_wallet(
    market: Literal["IN", "US"],
    db: Session = Depends(get_db),
) -> dict[str, str]:
    wallet = db.query(Wallet).filter(Wallet.market == market).first()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No wallet found for market '{market}'.",
        )

    logger.info("Deleting %s wallet and all associated records", market)
    db.delete(wallet)
    db.commit()
    return {"status": "deleted", "market": market}


