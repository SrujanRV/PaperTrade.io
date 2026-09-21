# PaperTrade.io

A single-user paper trading web application for learning stock trading across Indian (NSE/BSE) and US markets.

> **No real money. No real brokerage. Just learn.**

## Tech Stack
| Layer | Technology |
|---|---|
| Backend | Python 3.11+ · FastAPI · Uvicorn |
| Database | SQLite (via SQLAlchemy) |
| Data | `yfinance` (US + Indian `.NS`/`.BO` tickers) |
| Frontend | React + Vite |
| Real-time | Server-Sent Events (SSE) |

## Project Structure
```
backend/
  main.py               # FastAPI app entry point
  config.py             # All tunable constants (poll intervals, market hours, etc.)
  requirements.txt
  services/
    price_feed.py       # yfinance wrapper + normalizer → PriceQuote
  routers/
    prices.py           # GET /api/prices, SSE stream, market-status, validate
  test_price_feed.py    # Phase 1 smoke test

frontend/               # (Phase 3+)
  src/
    components/
    api/
```

## Build Phases
| Phase | Scope | Status |
|---|---|---|
| 1 | Price feed layer (yfinance, SSE, market hours) | ✅ Done |
| 2 | SQLite models · Wallets · Order engine · Portfolio P&L | ⬜ Planned |
| 3 | React frontend shell · Watchlist · Balance setup | ⬜ Planned |
| 4 | Trading UI · Order form · Portfolio view · Transaction log | ⬜ Planned |
| 5 | Limit/stop-loss orders · Charts · Indicators · Backtesting | ⬜ Planned |

## Getting Started (Backend — Phase 1)

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt

# Smoke-test the price feed
python test_price_feed.py

# Start the API server
uvicorn main:app --reload
```

### Sample API calls
```bash
# Batch quotes
curl "http://localhost:8000/api/prices?symbols=RELIANCE.NS,TCS.NS,AAPL,TSLA"

# Market status
curl "http://localhost:8000/api/prices/market-status?exchange=NSE"

# Validate a symbol
curl "http://localhost:8000/api/prices/validate?symbol=INFY.NS"

# SSE stream (open in browser or curl)
curl -N "http://localhost:8000/api/prices/stream?symbols=RELIANCE.NS,AAPL"
```

## Key Design Decisions
- **Single data source:** `yfinance` handles both US (plain tickers) and Indian (`.NS`/`.BO`) stocks.
- **Two independent wallets:** INR wallet (Indian stocks) and USD wallet (US stocks) — no FX conversion.
- **Market hours enforced:** Orders blocked outside NSE/BSE (09:15–15:30 IST) and NYSE/NASDAQ (09:30–16:00 ET) hours.
- **SSE for real-time updates:** Server pushes price updates every 30 s; keepalive pings every 15 s.
- **In-memory cache (TTL = 30 s):** Prevents Yahoo Finance rate-limiting when multiple clients connect.