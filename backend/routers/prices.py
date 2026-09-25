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

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from config import SSE_PUSH_INTERVAL_SECONDS, SSE_PING_INTERVAL_SECONDS
from services.price_feed import (
    get_quotes,
    get_quote,
    is_market_open,
    search_symbols,
    get_previous_close,
    get_historical_candles,
)

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

async def _price_event_generator(
    request: Request,
    symbols: list[str],
    limit: int | None = None,
) -> AsyncGenerator[str, None]:
    """
    Async generator that pushes SSE events with fresh price data for each ticker.
    Gracefully stops fetching as soon as client disconnects or limit is reached.
    """
    disconnected = False

    async def watch_disconnect():
        nonlocal disconnected
        try:
            while True:
                msg = await request.receive()
                if msg.get("type") == "http.disconnect":
                    disconnected = True
                    break
        except Exception:
            disconnected = True

    watcher = asyncio.create_task(watch_disconnect())
    logger.info("SSE client connected for tickers: %s", symbols)

    try:
        ticks = 0
        while not disconnected:
            quotes = get_quotes(symbols)

            # Evaluate open pending orders against fresh incoming quotes
            try:
                from database import SessionLocal
                from services.order_engine import evaluate_pending_orders, evaluate_auto_square_off, evaluate_margin_calls
                with SessionLocal() as db_session:
                    triggered = evaluate_pending_orders(db_session, quotes=quotes)
                    if triggered:
                        logger.info("SSE tick cycle triggered %d pending order(s)", len(triggered))
                    auto_sq_orders = evaluate_auto_square_off(db_session, quotes=quotes)
                    if auto_sq_orders:
                        logger.info("SSE tick cycle auto squared off %d holding(s)", len(auto_sq_orders))
                    margin_call_orders = evaluate_margin_calls(db_session, quotes=quotes)
                    if margin_call_orders:
                        logger.info("SSE tick cycle liquidated %d short holding(s) due to margin call", len(margin_call_orders))
            except Exception as eval_exc:
                logger.warning("Error evaluating pending orders / auto square-off / margin calls in SSE cycle: %s", eval_exc)

            for q in quotes:
                payload = {
                    "ticker": q.symbol,
                    "current_price": q.price,
                    "change_percent": q.change_pct,
                    "timestamp": q.timestamp,
                    "market_status": "open" if q.market_open else "closed",
                }
                yield f"data: {json.dumps(payload)}\n\n"

            ticks += 1
            if limit is not None and ticks >= limit:
                logger.info("SSE limit reached (%d ticks) for tickers: %s", limit, symbols)
                break

            # Sleep in 0.5s increments while monitoring disconnect state
            sleep_chunk = 0.5
            elapsed = 0.0
            while elapsed < SSE_PUSH_INTERVAL_SECONDS:
                if disconnected:
                    logger.info("SSE client disconnected during sleep: %s", symbols)
                    return
                await asyncio.sleep(sleep_chunk)
                elapsed += sleep_chunk

    except (asyncio.CancelledError, GeneratorExit):
        logger.info("SSE stream cancelled for tickers: %s", symbols)
        raise
    except Exception as exc:
        logger.error("SSE stream error for %s: %s", symbols, exc)
    finally:
        watcher.cancel()
        logger.info("SSE stream cleaned up for tickers: %s", symbols)


@router.get("/stream")
async def stream_prices(
    request: Request,
    tickers: str | None = Query(None, description="Comma-separated ticker symbols, e.g. AAPL,TSLA,RELIANCE.NS"),
    symbols: str | None = Query(None, description="Alternative alias for tickers"),
    limit: int | None = Query(None, description="Optional maximum updates to stream before closing (useful for tests)"),
):
    """
    SSE endpoint — stream live price updates for requested tickers.

    Example: GET /api/prices/stream?tickers=AAPL,TSLA,RELIANCE.NS
    """
    raw_tickers = tickers or symbols
    if not raw_tickers:
        raise HTTPException(
            status_code=400,
            detail="No tickers provided. Usage: /api/prices/stream?tickers=AAPL,TSLA,RELIANCE.NS",
        )

    ticker_list = [s.strip().upper() for s in raw_tickers.split(",") if s.strip()]
    if not ticker_list:
        raise HTTPException(status_code=400, detail="No valid tickers provided")
    if len(ticker_list) > 50:
        raise HTTPException(status_code=400, detail="Max 50 tickers per request")

    return StreamingResponse(
        _price_event_generator(request, ticker_list, limit=limit),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
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


# ── /api/prices/search ───────────────────────────────────────────────────────

@router.get("/search")
async def search_tickers(
    q: str = Query(..., min_length=1, description="Company name or ticker query"),
    market: str = Query("US", description="Market to scope results ('IN' or 'US')"),
):
    """
    Search symbols by company name or ticker, scoped strictly to IN or US market.

    Example: GET /api/prices/search?q=Tata&market=IN
    """
    return search_symbols(query=q, market=market)


# ── /api/prices/{ticker}/previous-close ───────────────────────────────────────

@router.get("/{ticker}/previous-close")
async def previous_close(
    ticker: str,
):
    """
    Return yesterday's closing price for the specified ticker.

    Example: GET /api/prices/AAPL/previous-close
    """
    sym = ticker.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="Ticker symbol required")
    data = get_previous_close(sym)
    return data


# ── /api/prices/{ticker}/history ──────────────────────────────────────────────

@router.get("/{ticker}/history")
async def price_history(
    ticker: str,
    range: str = Query("1d", description="Time range: '1d', '1w', '1m'"),
    interval: str | None = Query(None, description="Candle interval, e.g. '5m', '15m', '1d'"),
):
    """
    Return OHLC historical candles for the specified ticker and time range.

    Example: GET /api/prices/AAPL/history?range=1w&interval=15m
    """
    sym = ticker.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="Ticker symbol required")
    candles = get_historical_candles(sym, range_str=range, interval_str=interval)
    return candles

