"""
routers/orders.py — Order placement and order history endpoints.

Endpoints
---------
POST /api/orders
    Place a market buy or sell order.
    Returns the Order (status = "filled" or "rejected") with reject_reason if applicable.
    HTTP 201 in both cases — a new Order record is always created.

GET /api/orders/{market}
    Return full order history (filled + rejected) for the given wallet,
    newest first.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models.orm import Order, Wallet
from models.schemas import OrderOut, OrderRequest
from services.order_engine import place_market_order

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/orders", tags=["orders"])


# ── POST /api/orders ──────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Place a market order",
    description=(
        "Places a market buy or sell order. "
        "Returns the order with status='filled' on success or status='rejected' "
        "with a reject_reason on failure. A new order record is created in both cases."
    ),
)
def place_order(body: OrderRequest, db: Session = Depends(get_db)) -> OrderOut:
    try:
        order = place_market_order(
            db=db,
            market=body.market,
            ticker=body.ticker,
            side=body.side,
            quantity=body.quantity,
        )
    except ValueError as exc:
        # Raised only when the wallet doesn't exist yet
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return OrderOut.model_validate(order)


# ── GET /api/orders/{market} ──────────────────────────────────────────────────

@router.get(
    "/{market}",
    response_model=list[OrderOut],
    summary="Get order history",
    description="Returns all orders (filled and rejected) for the given market wallet, newest first.",
)
def get_order_history(
    market: Literal["IN", "US"],
    db: Session = Depends(get_db),
) -> list[OrderOut]:
    wallet = db.query(Wallet).filter(Wallet.market == market).first()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No wallet for market '{market}'. Call POST /api/wallet/setup first.",
        )

    orders = (
        db.query(Order)
        .filter(Order.wallet_id == wallet.id)
        .order_by(Order.created_at.desc())
        .all()
    )
    return [OrderOut.model_validate(o) for o in orders]
