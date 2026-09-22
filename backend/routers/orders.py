"""
routers/orders.py — Order placement, pending tracking, history, and cancellation.

Endpoints:
- POST   /api/orders               — Place market, limit, or stop-loss order
- GET    /api/orders/{market}/pending — List open untriggered pending orders
- GET    /api/orders/{market}         — Full order history (newest first)
- DELETE /api/order/{order_id}        — Cancel an open pending order
- DELETE /api/orders/{order_id}       — Alias for cancel endpoint
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from models.orm import Order, Wallet
from models.schemas import OrderOut, OrderRequest
from services.order_engine import (
    cancel_pending_order,
    evaluate_pending_orders,
    evaluate_auto_square_off,
    place_order,
)
from services.trading_calendar import calculate_square_off_date

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orders", tags=["orders"])
single_order_router = APIRouter(prefix="/api/order", tags=["orders"])


# ── POST /api/orders ──────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Place an order",
    description=(
        "Places a market, limit, or stop-loss order. "
        "Market orders execute immediately. "
        "Limit and stop-loss orders are evaluated against live price ticks and market hours, "
        "returning status='pending' until trigger conditions are met."
    ),
)
@single_order_router.post(
    "",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_order(body: OrderRequest, db: Session = Depends(get_db)) -> OrderOut:
    try:
        order = place_order(
            db=db,
            market=body.market,
            ticker=body.ticker,
            side=body.side,
            quantity=body.quantity,
            order_type=body.order_type,
            requested_price=body.requested_price,
            trigger_price=body.trigger_price,
            holding_days=body.holding_days,
            square_off_date=body.square_off_date,
            is_intraday=body.is_intraday,
        )
    except ValueError as exc:
        # Wallet not found or invalid side/type
        if "No wallet" in str(exc):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return OrderOut.model_validate(order)


# ── GET /api/orders/calculate-square-off ───────────────────────────────────────

@router.get(
    "/calculate-square-off",
    summary="Calculate square-off date based on market trading days",
    description="Resolves N trading days to a calendar date, accounting for market weekends and holidays.",
)
def get_calculated_square_off(
    market: Literal["IN", "US"] = Query("US", description="Market identifier: IN or US"),
    days: int = Query(0, ge=0, description="Holding duration in trading days (0 = intraday)"),
    start_date: str | None = Query(None, description="Optional ISO start date 'YYYY-MM-DD'"),
) -> dict:
    parsed_start: date | None = None
    if start_date:
        try:
            parsed_start = date.fromisoformat(start_date.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format — expected YYYY-MM-DD")

    return calculate_square_off_date(market=market, start_date=parsed_start, holding_days=days)


# ── POST /api/orders/trigger-square-off ───────────────────────────────────────

@router.post(
    "/trigger-square-off",
    response_model=list[OrderOut],
    summary="Trigger auto square-off evaluation",
    description="Scans holdings where square_off_date <= today and executes market sells (force_time_check=True for test/manual execution).",
)
def trigger_square_off_evaluation(
    market: Literal["IN", "US"] | None = Query(None, description="Optional market filter"),
    db: Session = Depends(get_db),
) -> list[OrderOut]:
    executed = evaluate_auto_square_off(db=db, force_time_check=True, market_filter=market)
    return [OrderOut.model_validate(o) for o in executed]



# ── GET /api/orders/{market}/pending ──────────────────────────────────────────

@router.get(
    "/{market}/pending",
    response_model=list[OrderOut],
    summary="Get open pending orders",
    description="Returns all untriggered limit and stop-loss orders (status='pending') for the given market wallet.",
)
def get_pending_orders(
    market: Literal["IN", "US"],
    db: Session = Depends(get_db),
) -> list[OrderOut]:
    wallet = db.query(Wallet).filter(Wallet.market == market).first()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No wallet for market '{market}'. Call POST /api/wallet/setup first.",
        )

    # Evaluate against latest cached price ticks before returning
    evaluate_pending_orders(db, market=market)

    orders = (
        db.query(Order)
        .filter(Order.wallet_id == wallet.id, Order.status == "pending")
        .order_by(Order.created_at.desc())
        .all()
    )
    return [OrderOut.model_validate(o) for o in orders]


# ── GET /api/orders/{market} ──────────────────────────────────────────────────

@router.get(
    "/{market}",
    response_model=list[OrderOut],
    summary="Get full order history",
    description="Returns all orders (filled, pending, rejected, cancelled) for the given market wallet, newest first.",
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


# ── DELETE /api/order/{order_id} & DELETE /api/orders/{order_id} ──────────────

def _handle_cancel_order(order_id: int, db: Session) -> OrderOut:
    try:
        order = cancel_pending_order(db=db, order_id=order_id)
        return OrderOut.model_validate(order)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@single_order_router.delete(
    "/{order_id}",
    response_model=OrderOut,
    summary="Cancel a pending order",
    description="Cancels an open order before it triggers. Only allowed while status is 'pending'.",
)
def cancel_order_single(order_id: int, db: Session = Depends(get_db)) -> OrderOut:
    return _handle_cancel_order(order_id, db)


@router.delete(
    "/{order_id}",
    response_model=OrderOut,
    summary="Cancel a pending order (plural route alias)",
    description="Cancels an open order before it triggers. Only allowed while status is 'pending'.",
)
def cancel_order_plural(order_id: int, db: Session = Depends(get_db)) -> OrderOut:
    return _handle_cancel_order(order_id, db)
