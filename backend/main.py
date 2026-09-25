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
    if "avg_buy_price" not in _existing_cols:
        with engine.connect() as _conn:
            _conn.execute(text("ALTER TABLE transactions ADD COLUMN avg_buy_price FLOAT DEFAULT NULL"))
            _conn.commit()
        logger.info("Migration applied: added 'avg_buy_price' column to transactions")
    if "triggered_by" not in _existing_cols:
        with engine.connect() as _conn:
            _conn.execute(text("ALTER TABLE transactions ADD COLUMN triggered_by VARCHAR(30) DEFAULT NULL"))
            _conn.commit()
        logger.info("Migration applied: added 'triggered_by' column to transactions")
    if "is_short" not in _existing_cols:
        with engine.connect() as _conn:
            _conn.execute(text("ALTER TABLE transactions ADD COLUMN is_short BOOLEAN DEFAULT 0"))
            _conn.commit()
        logger.info("Migration applied: added 'is_short' column to transactions")

if "orders" in _inspector.get_table_names():
    _order_cols = {c["name"] for c in _inspector.get_columns("orders")}
    if "trigger_price" not in _order_cols:
        with engine.connect() as _conn:
            _conn.execute(text("ALTER TABLE orders ADD COLUMN trigger_price FLOAT DEFAULT NULL"))
            _conn.commit()
        logger.info("Migration applied: added 'trigger_price' column to orders")
    if "square_off_date" not in _order_cols:
        with engine.connect() as _conn:
            _conn.execute(text("ALTER TABLE orders ADD COLUMN square_off_date DATE DEFAULT NULL"))
            _conn.commit()
        logger.info("Migration applied: added 'square_off_date' column to orders")
    if "is_intraday" not in _order_cols:
        with engine.connect() as _conn:
            _conn.execute(text("ALTER TABLE orders ADD COLUMN is_intraday BOOLEAN DEFAULT 0"))
            _conn.commit()
        logger.info("Migration applied: added 'is_intraday' column to orders")
    if "triggered_by" not in _order_cols:
        with engine.connect() as _conn:
            _conn.execute(text("ALTER TABLE orders ADD COLUMN triggered_by VARCHAR(30) DEFAULT NULL"))
            _conn.commit()
        logger.info("Migration applied: added 'triggered_by' column to orders")
    if "is_short" not in _order_cols:
        with engine.connect() as _conn:
            _conn.execute(text("ALTER TABLE orders ADD COLUMN is_short BOOLEAN DEFAULT 0"))
            _conn.commit()
        logger.info("Migration applied: added 'is_short' column to orders")

if "holdings" in _inspector.get_table_names():
    _holding_cols = {c["name"] for c in _inspector.get_columns("holdings")}
    if "square_off_date" not in _holding_cols:
        with engine.connect() as _conn:
            _conn.execute(text("ALTER TABLE holdings ADD COLUMN square_off_date DATE DEFAULT NULL"))
            _conn.commit()
        logger.info("Migration applied: added 'square_off_date' column to holdings")
    if "is_intraday" not in _holding_cols:
        with engine.connect() as _conn:
            _conn.execute(text("ALTER TABLE holdings ADD COLUMN is_intraday BOOLEAN DEFAULT 0"))
            _conn.commit()
        logger.info("Migration applied: added 'is_intraday' column to holdings")
    if "is_short" not in _holding_cols:
        with engine.connect() as _conn:
            _conn.execute(text("ALTER TABLE holdings ADD COLUMN is_short BOOLEAN DEFAULT 0"))
            _conn.commit()
        logger.info("Migration applied: added 'is_short' column to holdings")

if "holding_lots" in _inspector.get_table_names():
    _lot_cols = {c["name"] for c in _inspector.get_columns("holding_lots")}
    if "is_short" not in _lot_cols:
        with engine.connect() as _conn:
            _conn.execute(text("ALTER TABLE holding_lots ADD COLUMN is_short BOOLEAN DEFAULT 0"))
            _conn.commit()
        logger.info("Migration applied: added 'is_short' column to holding_lots")

if "holding_lots" in _inspector.get_table_names() and "holdings" in _inspector.get_table_names():
    with engine.connect() as _conn:
        _conn.execute(text("""
            INSERT INTO holding_lots (holding_id, quantity, buy_price, square_off_date, is_intraday, created_at)
            SELECT h.id, h.quantity, h.avg_buy_price, h.square_off_date, h.is_intraday, h.last_updated
            FROM holdings h
            WHERE h.quantity > 0 AND NOT EXISTS (SELECT 1 FROM holding_lots l WHERE l.holding_id = h.id)
        """))
        _conn.commit()


from contextlib import asynccontextmanager
import asyncio
from services.heartbeat import HeartbeatManager

@asynccontextmanager
async def lifespan(app: FastAPI):
    manager = HeartbeatManager.get_instance()
    watchdog_task = asyncio.create_task(manager.start_watchdog())
    yield
    watchdog_task.cancel()
    try:
        await watchdog_task
    except asyncio.CancelledError:
        pass

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="PaperTrade API",
    description="Backend for the PaperTrade paper-trading web application.",
    version="0.2.0",
    lifespan=lifespan,
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
from routers.orders import single_order_router

app.include_router(prices_router)
app.include_router(wallet_router)
app.include_router(orders_router)
app.include_router(single_order_router)

from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi import HTTPException, Request
from pydantic import BaseModel
from typing import Optional
import os
import json

FRONTEND_DIST = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))

@app.get("/api/health")
async def health():
    """Simple liveness check."""
    return {"status": "ok", "version": app.version}

class HeartbeatPayload(BaseModel):
    tab_id: str
    status: Optional[str] = None

@app.post("/api/heartbeat")
async def post_heartbeat(payload: HeartbeatPayload):
    HeartbeatManager.get_instance().record_heartbeat(payload.tab_id)
    return {"status": "ok"}

@app.post("/api/heartbeat/unload")
async def post_heartbeat_unload(request: Request):
    tab_id = None
    try:
        data = await request.json()
        tab_id = data.get("tab_id")
    except Exception:
        try:
            raw = (await request.body()).decode("utf-8")
            data = json.loads(raw)
            tab_id = data.get("tab_id")
        except Exception:
            tab_id = None

    if tab_id:
        HeartbeatManager.get_instance().record_unload(tab_id)
    return {"status": "unloaded"}

@app.get("/api/heartbeat/status")
async def get_heartbeat_status():
    return HeartbeatManager.get_instance().get_status()

if os.path.isdir(FRONTEND_DIST):
    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="static-assets")

    @app.get("/", include_in_schema=False)
    async def root():
        index_path = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.isfile(index_path):
            return FileResponse(index_path)
        return RedirectResponse(url="/docs")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # Never intercept API, docs, or OpenAPI endpoints
        if full_path.startswith("api/") or full_path.startswith("docs") or full_path == "openapi.json":
            raise HTTPException(status_code=404, detail="Not Found")
        target = os.path.join(FRONTEND_DIST, full_path)
        if full_path and os.path.isfile(target):
            return FileResponse(target)
        index_file = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.isfile(index_file):
            return FileResponse(index_file)
        raise HTTPException(status_code=404, detail="Frontend build not found")
else:
    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/docs")
