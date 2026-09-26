# PaperTrade.io

A professional-grade, multi-asset paper trading platform and terminal for mastering equity, short selling, and derivatives (Futures & Options) trading across Indian (NSE/BSE) and US markets.

> **No real money. No real brokerage. Just learn.**

---

## Key Capabilities

* **Dual-Market Multi-Currency Architecture**: Independent INR (`IN`) and USD (`US`) wallets with pooled collateral, real-time available buying power, and zero FX friction.
* **Cash Equities & Advanced Order Types**: Market, Limit, and Stop-Loss orders evaluated against real-time incoming price ticks.
* **Margin Trading & Short Selling**: Reg T margin requirements (150% initial, 125% maintenance), borrow fees, and automated liquidation on margin breach.
* **Intraday & Delivery Holding Modes**: MIS intraday trading with automated market-close square-off and multi-day delivery holdings.
* **Derivatives (F&O) Trading Engine**:
  * **Options**: Long call/put with upfront premium deduction; Covered Call writing with automatic underlying holding verification (0 margin); Naked options writing with 20% spot notional initial margin and 15% maintenance margin.
  * **Futures**: Margin-based from first trade (12% initial margin / 10% maintenance margin) with daily cash Mark-to-Market (MTM) settlement directly into cash balances.
  * **Settlement Engine**: Cash-settled intrinsic value expiration for options and closing index settlements for Indian futures.
  * **Real-Time Option Chains**: NIFTY, BANKNIFTY, curated NSE F&O equities (RELIANCE, TCS, INFY, etc.), and US Options (AAPL, MSFT, TSLA, etc.) with ATM strike highlighting, Greeks, and Bid/Ask depth.
  * **Futures Market Viewer**: Term structure with basis and annualized cost-of-carry percentages.
  * **Execution Realism**: Directional Bid/Ask order execution for zero-LTP / thinly-traded strikes, preventing ₹0 / $0 fills.
  * **Venue-Specific Market Hours**: Strict trading window enforcement across NSE (09:15–15:30 IST), US Equity Options (09:30–16:00 ET), and CME Globex Futures (Sunday 17:00 CT – Friday 16:00 CT with daily 16:00–17:00 CT halt).

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.11+ · FastAPI · Uvicorn · Pydantic v2 |
| **Database** | SQLite (via SQLAlchemy 2.x ORM) · StaticPool in-memory testing |
| **Market Feeds** | `yfinance 1.7+` · NSE Public Option-Chain API (with automated cookie/session management) |
| **Frontend** | React 18 · Vite · Tailwind CSS · Lucide Icons |
| **Real-time** | Server-Sent Events (SSE) with bidirectional tick-flash indicators |

---

## Project Structure

```
backend/
  main.py                   # FastAPI app entry point + startup migrations
  config.py                 # Market hours (NSE, BSE, NYSE, NASDAQ, CME), cache TTL, CORS, SSE intervals
  database.py               # SQLAlchemy engine, SessionLocal, get_db dependency
  requirements.txt
  db.sqlite                 # Created automatically on first run (gitignored)

  models/
    orm.py                  # SQLAlchemy ORM: Wallet, Holding, Order, Transaction, DerivativeContract, DerivativePosition, DerivativeOrder, DerivativeTransaction
    schemas.py              # Pydantic v2 schemas for equities, wallets, orders, and derivatives

  services/
    price_feed.py           # yfinance wrapper → PriceQuote (batch, cached, SSE, CME Globex & exchange hours)
    derivatives_feed.py     # NSE option chain client, US options chains, futures curves, eligible F&O tickers
    order_engine.py         # Equity market/limit/stop orders, short selling, intraday square-off
    derivatives_engine.py   # Options & futures execution, pooled margin, daily MTM, expiry settlement, liquidations
    portfolio.py            # Live P&L, realized P&L, wallet snapshot

  routers/
    prices.py               # GET /api/prices, SSE stream, market-status, validate
    wallet.py               # POST /api/wallet/setup, GET /api/wallet/{market}, /summary
    orders.py               # POST /api/orders, GET /api/orders/{market}
    derivatives.py          # F&O orders, option chains, futures markets, positions, MTM, expiry settlement

  test_price_feed.py            # Phase 1 smoke tests (7 scenarios)
  test_wallet.py                # Phase 2a wallet tests (9 scenarios)
  test_order_engine.py          # Phase 2b equity order engine tests (10 scenarios)
  test_sse_stream.py            # Phase 3 SSE streaming tests (3 scenarios)
  test_short_selling.py         # Phase 5 margin trading & short selling tests
  test_derivatives_engine.py    # Phase 6c/6d/6e unit test suite (11 comprehensive scenarios)
  test_zero_ltp_fill.py         # Bid/Ask fill execution verification suite for zero-LTP strikes

frontend/
  src/
    api/
      client.js             # API client for equities, wallets, orders, and derivatives
    components/
      Header.jsx            # Persistent header with dual-wallet cash & margin badges, UTC clock
      Watchlist.jsx         # 38px dense terminal table, right-aligned tabular numerics, 400ms tick-flash
      OptionChain.jsx       # Calls/Puts grid, ATM highlight, NSE index/stock & US options tabs, company search
      FuturesMarket.jsx     # Term structure view for Indian index & stock futures and US continuous futures
      OrderTicket.jsx       # Unified order ticket supporting equity, short selling, options, and futures
      Portfolio.jsx         # Holdings table, active derivatives positions with Margin Level % health, P&L
      OrderHistory.jsx      # Audit log with rejection diagnostics across all asset classes
      WalletSetupModal.jsx  # Modal for setting initial starting INR & USD balances
    hooks/
      usePriceStream.js     # SSE EventSource wrapper with tick-direction detection
    App.jsx                 # Terminal layout with tab navigation (Watchlist, Option Chain, Futures, Portfolio, Orders)
    index.css               # Design tokens, tabular-nums utility, tick-flash keyframes
```

---

## Build Phases & Roadmap

| Phase | Scope | Status |
|---|---|---|
| **1** | Price feed · yfinance integration · market hours detection | ✅ Complete |
| **2a** | SQLite models · dual wallets (INR + USD) · setup endpoints | ✅ Complete |
| **2b** | Order engine · portfolio P&L · order history | ✅ Complete |
| **3** | Real-time SSE price streaming (`/api/prices/stream?tickers=...`) | ✅ Complete |
| **4** | React Terminal UI · Watchlist · Order Ticket · Portfolio · Order History | ✅ Complete |
| **5** | Advanced order types (Limit, Stop-Loss) · Short selling (Reg T margin) · Intraday auto-square-off | ✅ Complete |
| **6a** | Derivatives Data Sources · NSE Option Chain client · yfinance US options & futures feeds | ✅ Complete |
| **6b** | F&O Database Models · Unified pooled margin schema · Contract specifications | ✅ Complete |
| **6c** | F&O Order Engine · Option buying · Covered/Naked writing · Futures 12% margin · Daily MTM & Expiry cash settlement | ✅ Complete |
| **6d** | F&O Frontend UI · Option Chain view (ATM highlight) · Futures Market tab · Derivatives Portfolio with Margin Level % | ✅ Complete |
| **6e** | US Options Search · Indian Stock F&O · Bid/Ask zero-LTP execution · CME Globex & venue market hours enforcement | ✅ Complete |

---

## Getting Started

### 1. Prerequisites
* **Python 3.11+**
* **Node.js 18+ & npm**

### 2. Backend Setup
```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt

# Run the unit test suites
python test_order_engine.py
python test_short_selling.py
python test_derivatives_engine.py
python test_zero_ltp_fill.py

# Start backend on http://localhost:8000
python run_server.py
```

### 3. Frontend Setup
```bash
cd frontend
npm install
npm run build   # Production build verification
npm run dev     # Starts Vite dev server on http://localhost:5173
```

Open your browser to: **http://localhost:5173** (proxies `/api` requests to backend port 8000).  
Interactive Swagger API Docs: **http://localhost:8000/docs**

---

## API Reference

### Equities & Prices
* `GET /api/prices?symbols=RELIANCE.NS,AAPL`: Batch quotes (cached with 10s TTL).
* `GET /api/prices/stream?tickers=AAPL,TSLA,RELIANCE.NS`: Server-Sent Events live price stream.
* `GET /api/prices/market-status?exchange=NSE`: Current exchange session status.
* `GET /api/prices/validate?symbol=INFY.NS`: Ticker validation check.

### Wallets & Accounting
* `POST /api/wallet/setup`: Create or reset wallet balance `{"market":"IN","starting_balance":500000}`.
* `GET /api/wallet/{market}`: Wallet balances, available buying power, margin used, and holdings.
* `GET /api/wallet/{market}/summary`: Comprehensive snapshot with cash, collateral, and live P&L.

### Orders
* `POST /api/orders`: Place equity market, limit, or stop-loss order (supports long, short, intraday).
* `GET /api/orders/{market}`: Order execution history with audit log and rejection diagnostics.

### Derivatives (Futures & Options)
* `POST /api/derivatives/order`: Place options or futures order (`buy_to_open`, `sell_to_open`, `buy_to_close`, `sell_to_close`).
* `GET /api/derivatives/chain?market=IN&symbol=NIFTY`: Option chain with strikes, LTP, Bid, Ask, OI, IV.
* `GET /api/derivatives/futures?market=IN&symbol=RELIANCE`: Futures term structure and cost-of-carry.
* `GET /api/derivatives/in/fo-stocks`: Exchange-approved Indian equities eligible for F&O with official lot sizes.
* `GET /api/derivatives/{market}/positions`: Active derivative positions with live P&L and Margin Level % health.
* `POST /api/derivatives/settle-mtm`: Trigger daily futures mark-to-market settlement into wallet cash.
* `POST /api/derivatives/settle-expiry`: Trigger options intrinsic settlement and Indian futures closing settlement.
* `POST /api/derivatives/evaluate-margin-calls`: Evaluate maintenance margin breaches and execute auto-liquidations.

---

## Market Hours & Trading Schedules

| Venue / Instrument | Exchange | Active Hours | Notes |
|---|---|---|---|
| **Indian Equities & F&O** | NSE / BSE | 09:15 – 15:30 IST (Mon–Fri) | Orders blocked outside session |
| **US Equities & Options** | NYSE / NASDAQ | 09:30 – 16:00 ET (Mon–Fri) | Options trade on stock hours |
| **US Futures** | CME Globex | Sun 17:00 CT – Fri 16:00 CT | Continuous ~24/5; daily halt 16:00–17:00 CT Mon–Thu |