"""
main.py — FastAPI application entry point.

Phase 1: price feed (prices router)
Phase 2a: database models + wallet setup (wallet router)
Phase 2b: order engine + portfolio P&L (orders router, wallet summary)
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect as sa_inspect, text

from config import CORS_ORIGINS
from database import Base, engine
from routers.prices import router as prices_router
from routers.wallet import router as wallet_router
from routers.orders import router as orders_router

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Register ORM mappers then create/verify tables ────────────────────────────
import models.orm  # noqa: F401  — side-effect: registers all ORM models with Base

Base.metadata.create_all(bind=engine)
logger.info("Database tables verified / created at startup")

# ── Schema migrations (safe to run on every startup) ─────────────────────────
# Add any columns introduced after the initial schema creation.
_inspector = sa_inspect(engine)
if "transactions" in _inspector.get_table_names():
    _existing_cols = {c["name"] for c in _inspector.get_columns("transactions")}
    if "realized_pnl" not in _existing_cols:
        with engine.connect() as _conn:
            _conn.execute(text("ALTER TABLE transactions ADD COLUMN realized_pnl FLOAT DEFAULT NULL"))
            _conn.commit()
        logger.info("Migration applied: added 'realized_pnl' column to transactions")

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
app.include_router(orders_router)

from routers.orders import place_order
from models.schemas import OrderOut
app.add_api_route(
    "/api/order",
    place_order,
    methods=["POST"],
    response_model=OrderOut,
    status_code=201,
    tags=["orders"],
    summary="Place order (alias for /api/orders)",
)

from fastapi.responses import RedirectResponse

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")


@app.get("/api/health")
async def health():
    """Simple liveness check."""
    return {"status": "ok", "version": app.version}
