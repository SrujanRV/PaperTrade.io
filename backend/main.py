"""
main.py — FastAPI application entry point.

Phase 1 scope: price feed only.
Subsequent phases will register additional routers (orders, portfolio, settings).
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import CORS_ORIGINS
from routers.prices import router as prices_router

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="PaperTrade API",
    description="Backend for the PaperTrade paper-trading web application.",
    version="0.1.0",
)

# ── CORS (development: allow Vite + CRA dev servers) ─────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(prices_router)

# Phase 2+ routers will be added here:
# app.include_router(settings_router)
# app.include_router(orders_router)
# app.include_router(portfolio_router)


@app.get("/api/health")
async def health():
    """Simple liveness check."""
    return {"status": "ok", "version": app.version}
