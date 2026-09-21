"""
routers/prices.py — FastAPI router for price endpoints and SSE stream.

Endpoints
---------
GET /api/prices?symbols=RELIANCE.NS,AAPL,TCS.NS
    Returns JSON array of PriceQuote objects (uses cache).

GET /api/prices/stream?symbols=RELIANCE.NS,AAPL
    Server-Sent Events stream — pushes fresh quotes every SSE_PUSH_INTERVAL_SECONDS.

GET /api/prices/market-status?exchange=NSE
    Returns whether a specific exchange is currently open.

GET /api/prices/validate?symbol=RELIANCE.NS
    Quick check: is the symbol recognised by yfinance?
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from config import SSE_PUSH_INTERVAL_SECONDS, SSE_PING_INTERVAL_SECONDS
from services.price_feed import get_quotes, get_quote, is_market_open

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/prices", tags=["prices"])


# ── /api/prices ───────────────────────────────────────────────────────────────

@router.get("")
async def fetch_prices(
    symbols: str = Query(..., description="Comma-separated list of ticker symbols"),
    refresh: bool = Query(False, description="Force bypass cache"),
):
    """
    Return current quotes for one or more symbols.

    Example: GET /api/prices?symbols=RELIANCE.NS,TCS.NS,AAPL,TSLA
    """
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="No symbols provided")
    if len(symbol_list) > 50:
        raise HTTPException(status_code=400, detail="Max 50 symbols per request")

    quotes = get_quotes(symbol_list, force_refresh=refresh)
    return [q.to_dict() for q in quotes]


# ── /api/prices/stream ────────────────────────────────────────────────────────

async def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def _price_event_generator(symbols: list[str]) -> AsyncGenerator[str, None]:
    """Async generator that pushes SSE events with fresh price data."""
    tick = 0
    while True:
        try:
            quotes = get_quotes(symbols)
            payload = [q.to_dict() for q in quotes]
            yield await _sse_event({"type": "quotes", "data": payload})
        except Exception as exc:
            logger.error("SSE fetch error: %s", exc)
            yield await _sse_event({"type": "error", "message": str(exc)})

        # Send keepalive pings between price pushes
        for _ in range(SSE_PUSH_INTERVAL_SECONDS // SSE_PING_INTERVAL_SECONDS):
            await asyncio.sleep(SSE_PING_INTERVAL_SECONDS)
            yield ": ping\n\n"

        tick += 1


@router.get("/stream")
async def stream_prices(
    symbols: str = Query(..., description="Comma-separated ticker symbols"),
):
    """
    SSE endpoint — connect once, receive periodic price pushes.

    Example: GET /api/prices/stream?symbols=RELIANCE.NS,AAPL
    """
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="No symbols provided")

    return StreamingResponse(
        _price_event_generator(symbol_list),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if behind proxy
        },
    )


# ── /api/prices/market-status ─────────────────────────────────────────────────

@router.get("/market-status")
async def market_status(
    exchange: str = Query(..., description="Exchange name: NSE, BSE, NYSE, NASDAQ"),
):
    """
    Return whether the given exchange is currently in its trading session.

    Example: GET /api/prices/market-status?exchange=NSE
    """
    exchange = exchange.upper()
    open_now = is_market_open(exchange)
    return {"exchange": exchange, "is_open": open_now}


# ── /api/prices/validate ─────────────────────────────────────────────────────

@router.get("/validate")
async def validate_symbol(
    symbol: str = Query(..., description="Ticker symbol to validate"),
):
    """
    Quick symbol validation — fetches the quote and returns success/error.

    Example: GET /api/prices/validate?symbol=RELIANCE.NS
    """
    symbol = symbol.strip()
    quote = get_quote(symbol, force_refresh=True)
    if quote.error:
        return {"valid": False, "symbol": symbol, "reason": quote.error}
    return {"valid": True, "symbol": symbol, "price": quote.price, "exchange": quote.exchange}
