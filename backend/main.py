"""
main.py — FastAPI application entry point.

Phase 1: price feed (prices router)
Phase 2: database models + wallet setup (wallet router)
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import CORS_ORIGINS
from database import Base, engine
from routers.prices import router as prices_router
from routers.wallet import router as wallet_router

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Create DB tables (idempotent — safe to call on every startup) ─────────────
# Import all ORM models so Base.metadata knows about them before create_all()
import models.orm  # noqa: F401  (side-effect import registers the mappers)

Base.metadata.create_all(bind=engine)
logger.info("Database tables verified / created at startup")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="PaperTrade API",
    description="Backend for the PaperTrade paper-trading web application.",
    version="0.2.0",
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
app.include_router(wallet_router)

# Phase 2b+ routers will be added here:
# app.include_router(orders_router)
# app.include_router(portfolio_router)


@app.get("/api/health")
async def health():
    """Simple liveness check."""
    return {"status": "ok", "version": app.version}
