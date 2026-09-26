"""
routers/derivatives.py — FastAPI endpoints for Futures & Options (F&O).

Endpoints:
- POST /api/derivatives/order                  — Place option or futures order
- GET  /api/derivatives/{market}/positions     — Active positions with live P&L and margin health
- GET  /api/derivatives/{market}/orders        — Derivative order history
- GET  /api/derivatives/{market}/transactions  — Derivative transaction ledger (trades, MTM, expiry)
- GET  /api/derivatives/{market}/contracts     — List available or active derivative contracts
- POST /api/derivatives/settle-mtm             — Trigger daily futures cash MTM settlement
- POST /api/derivatives/settle-expiry          — Trigger expiry cash settlement (options & index futures)
- POST /api/derivatives/evaluate-margin-calls  — Evaluate maintenance margin & force-liquidate breaches
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from models.orm import (
    Wallet,
    DerivativeContract,
    DerivativePosition,
    DerivativeOrder,
    DerivativeTransaction,
)
from models.schemas import (
    DerivativeContractOut,
    DerivativeOrderOut,
    DerivativeOrderRequest,
    DerivativePositionOut,
    DerivativePositionWithPnLOut,
    DerivativeTransactionOut,
)
from services.derivatives_engine import (
    DEFAULT_LOT_SIZES,
    evaluate_daily_futures_mtm,
    evaluate_derivative_margin_calls,
    evaluate_derivatives_expiry_settlement,
    get_derivative_positions_summary,
    get_or_create_contract,
    place_derivative_order,
)
from services.price_feed import get_quote, get_quotes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/derivatives", tags=["derivatives"])


# ── POST /api/derivatives/order ───────────────────────────────────────────────

@router.post(
    "/order",
    response_model=DerivativeOrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Place a derivative order (Options or Futures)",
    description=(
        "Executes an options or futures order. Supports buy_to_open, sell_to_open, "
        "buy_to_close, and sell_to_close. Automatically manages unified margin and cash balance."
    ),
)
def create_derivative_order(
    body: DerivativeOrderRequest,
    db: Session = Depends(get_db),
) -> DerivativeOrderOut:
    m = body.market.upper()
    wallet = db.query(Wallet).filter(Wallet.market == m).first()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No wallet found for market '{m}'",
        )

    # 1. Resolve contract
    contract: DerivativeContract | None = None
    if body.contract_id:
        contract = db.query(DerivativeContract).filter(DerivativeContract.id == body.contract_id).first()
        if not contract:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"DerivativeContract with id {body.contract_id} not found",
            )
    else:
        # Resolve via contract parameters
        if not body.underlying or not body.instrument_type:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Must specify either contract_id or (underlying and instrument_type)",
            )
        contract = get_or_create_contract(
            db=db,
            market=m,
            underlying=body.underlying,
            instrument_type=body.instrument_type,
            option_type=body.option_type,
            strike_price=body.strike_price,
            expiry_date=body.expiry_date,
            lot_size=body.lot_size,
            symbol=body.symbol,
        )

    # 2. Place order
    try:
        order = place_derivative_order(
            db=db,
            wallet=wallet,
            contract=contract,
            side=body.side,
            action=body.action,
            quantity=body.quantity,
            order_type=body.order_type,
            requested_price=body.price,
            fill_price=body.price if body.order_type == "limit" else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return DerivativeOrderOut.model_validate(order)


# ── GET /api/derivatives/{market}/positions ───────────────────────────────────

@router.get(
    "/{market}/positions",
    response_model=List[DerivativePositionWithPnLOut],
    summary="Get open derivative positions with live metrics",
    description="Returns all active options and futures positions enriched with live market prices, P&L, and margin health.",
)
def get_derivative_positions(
    market: Literal["IN", "US"],
    db: Session = Depends(get_db),
) -> List[DerivativePositionWithPnLOut]:
    m = market.upper()
    wallet = db.query(Wallet).filter(Wallet.market == m).first()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No wallet found for market '{m}'",
        )

    # Fetch positions from DB to determine symbols needed for quote fetching
    open_positions = (
        db.query(DerivativePosition)
        .join(DerivativeContract)
        .filter(
            DerivativePosition.wallet_id == wallet.id,
            DerivativePosition.quantity > 0,
        )
        .all()
    )
    if not open_positions:
        return []

    symbols = set()
    for pos in open_positions:
        symbols.add(pos.contract.symbol)
        symbols.add(pos.contract.underlying)

    # Fetch live quotes in batch
    quotes_list = get_quotes(list(symbols))
    live_quotes = {q.symbol.upper(): q for q in quotes_list}

    summaries = get_derivative_positions_summary(
        db=db,
        wallet_id=wallet.id,
        live_quotes=live_quotes,
    )

    results: List[DerivativePositionWithPnLOut] = []
    for item in summaries:
        pos: DerivativePosition = item["position"]
        c: DerivativeContract = item["contract"]
        results.append(
            DerivativePositionWithPnLOut(
                id=pos.id,
                wallet_id=pos.wallet_id,
                contract_id=pos.contract_id,
                contract=DerivativeContractOut.model_validate(c),
                side=pos.side,
                quantity=pos.quantity,
                entry_price=pos.entry_price,
                current_price=item["current_price"],
                notional_value=item["notional_value"],
                market_value=item["market_value"],
                unrealized_pnl=item["unrealized_pnl"],
                unrealized_pnl_pct=item["unrealized_pnl_pct"],
                is_covered=pos.is_covered,
                margin_locked=pos.margin_locked,
                maintenance_margin_required=item["maintenance_margin_required"],
                margin_level_pct=item["margin_level_pct"],
                last_mtm_price=pos.last_mtm_price,
                last_mtm_date=pos.last_mtm_date,
                created_at=pos.created_at,
            )
        )

    return results


# ── GET /api/derivatives/{market}/orders ──────────────────────────────────────

@router.get(
    "/{market}/orders",
    response_model=List[DerivativeOrderOut],
    summary="Get derivative order history",
    description="Returns order history for options and futures in newest-first order.",
)
def get_derivative_orders(
    market: Literal["IN", "US"],
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[DerivativeOrderOut]:
    m = market.upper()
    wallet = db.query(Wallet).filter(Wallet.market == m).first()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No wallet found for market '{m}'",
        )

    orders = (
        db.query(DerivativeOrder)
        .filter(DerivativeOrder.wallet_id == wallet.id)
        .order_by(DerivativeOrder.created_at.desc())
        .limit(limit)
        .all()
    )
    return [DerivativeOrderOut.model_validate(o) for o in orders]


# ── GET /api/derivatives/{market}/transactions ────────────────────────────────

@router.get(
    "/{market}/transactions",
    response_model=List[DerivativeTransactionOut],
    summary="Get derivative transactions ledger",
    description="Returns immutable ledger entries for trades, daily futures MTM, and expiry settlements.",
)
def get_derivative_transactions(
    market: Literal["IN", "US"],
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[DerivativeTransactionOut]:
    m = market.upper()
    wallet = db.query(Wallet).filter(Wallet.market == m).first()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No wallet found for market '{m}'",
        )

    txns = (
        db.query(DerivativeTransaction)
        .filter(DerivativeTransaction.wallet_id == wallet.id)
        .order_by(DerivativeTransaction.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [DerivativeTransactionOut.model_validate(t) for t in txns]


# ── GET /api/derivatives/{market}/contracts ───────────────────────────────────

@router.get(
    "/{market}/contracts",
    response_model=List[DerivativeContractOut],
    summary="List derivative contracts",
    description="List available contracts filtered by underlying and instrument type.",
)
def get_derivative_contracts(
    market: Literal["IN", "US"],
    underlying: Optional[str] = Query(None, description="Underlying ticker (e.g. NIFTY, ES)"),
    instrument_type: Optional[Literal["option", "future"]] = Query(None),
    db: Session = Depends(get_db),
) -> List[DerivativeContractOut]:
    m = market.upper()
    query = db.query(DerivativeContract).filter(DerivativeContract.market == m)
    if underlying:
        query = query.filter(DerivativeContract.underlying == underlying.upper())
    if instrument_type:
        query = query.filter(DerivativeContract.instrument_type == instrument_type.lower())

    contracts = query.order_by(DerivativeContract.expiry_date.asc().nulls_last()).all()
    return [DerivativeContractOut.model_validate(c) for c in contracts]


# ── POST /api/derivatives/settle-mtm ──────────────────────────────────────────

@router.post(
    "/settle-mtm",
    response_model=List[DerivativeTransactionOut],
    summary="Trigger daily futures Mark-to-Market settlement",
    description="Marks open futures positions against settlement prices, adjusting cash balances directly.",
)
def trigger_futures_mtm(
    db: Session = Depends(get_db),
) -> List[DerivativeTransactionOut]:
    txns = evaluate_daily_futures_mtm(db=db)
    return [DerivativeTransactionOut.model_validate(t) for t in txns]


# ── POST /api/derivatives/settle-expiry ───────────────────────────────────────

@router.post(
    "/settle-expiry",
    response_model=List[DerivativeTransactionOut],
    summary="Trigger expiry cash settlement",
    description="Settles expired options using intrinsic value and Indian index futures against closing index prices.",
)
def trigger_expiry_settlement(
    db: Session = Depends(get_db),
) -> List[DerivativeTransactionOut]:
    txns = evaluate_derivatives_expiry_settlement(db=db)
    return [DerivativeTransactionOut.model_validate(t) for t in txns]


# ── POST /api/derivatives/evaluate-margin-calls ───────────────────────────────

@router.post(
    "/evaluate-margin-calls",
    response_model=List[DerivativeOrderOut],
    summary="Evaluate maintenance margin and execute liquidations",
    description="Checks naked options (15% maint) and futures (10% maint) for threshold breaches and liquidates breached positions.",
)
def trigger_margin_call_evaluation(
    db: Session = Depends(get_db),
) -> List[DerivativeOrderOut]:
    orders = evaluate_derivative_margin_calls(db=db)
    return [DerivativeOrderOut.model_validate(o) for o in orders]
