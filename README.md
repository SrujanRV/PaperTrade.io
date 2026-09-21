# PaperTrade.io

A single-user paper trading web application for learning stock trading across Indian (NSE/BSE) and US markets.

> **No real money. No real brokerage. Just learn.**

## Tech Stack
| Layer | Technology |
|---|---|
| Backend | Python 3.11+ · FastAPI · Uvicorn |
| Database | SQLite (via SQLAlchemy 2.x) |
| Data | `yfinance 1.7+` (US + Indian `.NS`/`.BO` tickers) |
| Frontend | React + Vite *(Phase 3 — not yet built)* |
| Real-time | Server-Sent Events (SSE) |

---

## Project Structure
```
backend/
  main.py                   # FastAPI app entry point + startup migrations
  config.py                 # Market hours, cache TTL, CORS, SSE intervals
  database.py               # SQLAlchemy engine, SessionLocal, get_db dependency
  requirements.txt
  db.sqlite                 # Created automatically on first run (gitignored)

  models/
    orm.py                  # SQLAlchemy ORM: Wallet, Holding, Order, Transaction
    schemas.py              # Pydantic v2 request/response schemas

  services/
    price_feed.py           # yfinance wrapper → PriceQuote (batch, cached, SSE)
    order_engine.py         # Market buy/sell logic, rejection handling
    portfolio.py            # Live P&L, realized P&L, wallet snapshot

  routers/
    prices.py               # GET /api/prices, SSE stream, market-status, validate
    wallet.py               # POST /api/wallet/setup, GET /api/wallet/{market}, /summary
    orders.py               # POST /api/orders, GET /api/orders/{market}

  test_price_feed.py        # Phase 1 smoke tests (7 scenarios)
  test_wallet.py            # Phase 2a smoke tests (9 scenarios)
  test_order_engine.py      # Phase 2b smoke tests (10 scenarios)
  test_sse_stream.py        # Step 3 SSE streaming tests (3 scenarios)

frontend/
  package.json
  vite.config.js
  tailwind.config.js
  src/
    api/
      client.js             # API helpers for wallets and orders
    components/
      Header.jsx            # Persistent header with dual-wallet cash badges & UTC clock
      Watchlist.jsx         # 38px dense terminal table, right-aligned tabular numerics, 400ms tick-flash
      OrderTicket.jsx       # Side-panel order ticket, live total, market-hours lock, fill & reject states
      Portfolio.jsx         # Live holdings table, unrealized P&L, realized P&L, wallet summary
      WalletSetupModal.jsx  # First-run modal for setting starting INR & USD balances
    hooks/
      usePriceStream.js     # SSE EventSource wrapper with tick-direction detection
    App.jsx                 # Terminal layout, sub-navigation tabs, and wallet refresh
    index.css               # Token variables, tabular-nums utility, tick-flash keyframes
    main.jsx
```

---

## Build Phases
| Phase | Scope | Status |
|---|---|---|
| **1** | Price feed · yfinance · market hours | ✅ Done |
| **2a** | SQLite models · dual wallets (INR + USD) · setup endpoints | ✅ Done |
| **2b** | Order engine · portfolio P&L · order history | ✅ Done |
| **3** | Real-time SSE price streaming (`/api/prices/stream?tickers=...`) | ✅ Done |
| **4a** | React Terminal UI · Watchlist Component · SSE Hook | ✅ Done |
| **4b** | Wallet Setup Modal · Order Ticket Panel · Persistent Balances | ✅ Done |
| **4c** | Portfolio/Holdings View · Live P&L · Wallet Summaries | ✅ Done |
| **5** | Order History & Transaction Audit Log | ⬜ Planned |
| **6** | Limit/stop-loss orders · Charts · Indicators · Backtesting | ⬜ Planned |

---

## Getting Started

### 1. Start Backend API (FastAPI)
```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# venv/bin/activate          # macOS/Linux
pip install -r requirements.txt

# Run smoke tests
python test_price_feed.py
python test_wallet.py
python test_order_engine.py
python test_sse_stream.py

# Start the API server on http://localhost:8000
uvicorn main:app --reload
```

### 2. Start Frontend Terminal (Vite + React)
```bash
cd frontend
npm install
npm run dev
```

Open your browser to: **http://localhost:5173** (proxies `/api` to backend port 8000).

Swagger UI → **http://localhost:8000/docs**

---

## API Reference

### Prices
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/prices?symbols=RELIANCE.NS,AAPL` | Batch quote fetch (cached) |
| `GET` | `/api/prices/stream?tickers=AAPL,TSLA,RELIANCE.NS` | SSE live price stream (pushes every 5s per ticker, graceful disconnect) |
| `GET` | `/api/prices/market-status?exchange=NSE` | Is the exchange open right now? |
| `GET` | `/api/prices/validate?symbol=INFY.NS` | Check if a ticker is valid |

### Wallets
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/wallet/setup` | Create or reset a wallet `{"market":"IN","starting_balance":500000}` |
| `GET` | `/api/wallet/{market}` | Wallet state + raw holdings list |
| `GET` | `/api/wallet/{market}/summary` | Full snapshot: cash + live P&L + totals |

### Orders
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/orders` | Place a market buy or sell order |
| `GET` | `/api/orders/{market}` | Order history (filled + rejected), newest first |

### Health
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Liveness check |

---

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Data source | `yfinance` only | Supports both US plain tickers and `.NS`/`.BO` Indian tickers; no API key needed |
| Indian data delay | ~15 min via Yahoo Finance | Acceptable for a learning tool; avoids fragile NSE scraping |
| Two wallets | INR wallet (Indian) + USD wallet (US) | No FX complexity; each fully independent |
| Market hours | Enforced (NSE 09:15–15:30 IST, NYSE 09:30–16:00 ET) | Realistic behaviour; orders outside hours are rejected |
| Price updates | SSE (Server-Sent Events) | Simpler than WebSockets; efficient vs. client polling |
| Price cache | 30 s in-memory TTL | Prevents Yahoo Finance rate-limiting with multiple SSE clients |
| Cost basis | Weighted average (`avg_buy_price`) | Standard retail brokerage method |
| Realized P&L | Stored on `Transaction` at fill time | Accurate even after position is fully closed and Holding row deleted |
| Schema migrations | `ALTER TABLE` at startup (idempotent) | No migration framework needed for single-user SQLite |

---

## Ticker Format Reference
| Market | Exchange | Example | Format |
|---|---|---|---|
| NSE (India) | NSE | `RELIANCE.NS` | `{SYMBOL}.NS` |
| BSE (India) | BSE | `RELIANCE.BO` | `{SYMBOL}.BO` |
| NYSE / NASDAQ (US) | NYSE / NASDAQ | `AAPL`, `TSLA` | plain symbol |