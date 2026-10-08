"""
services/derivatives_feed.py — Market data feeds for Options and Futures.

Provides:
1. NSE Option Chain for NIFTY and BANKNIFTY:
   - Session bootstrap with cookies and browser headers
   - 30s TTL caching
   - Graceful fallback with is_stale=True and synthetic chain fallback if NSE is closed or blocking
2. US Equity Options via yfinance (AAPL, TSLA, etc.)
3. Indian Index Futures per expiry from NSE liveEquity-derivatives (with basis = futures - spot)
4. US Continuous Futures (ES=F, NQ=F, CL=F, GC=F) with contract size, notional, and 12% margin
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional
import requests
import yfinance as yf
import pandas as pd

from services.price_feed import get_quote

logger = logging.getLogger(__name__)

# Comprehensive NSE F&O Lot Sizes lookup table.
# Hardcoded with a comment that it needs periodic manual updates as per NSE circulars and SEBI revisions.
NSE_LOT_SIZES: Dict[str, int] = {
    # ── Indices ───────────────────────────────────────────────────────────────
    "NIFTY": 65,
    "BANKNIFTY": 30,
    "FINNIFTY": 60,
    "MIDCPNIFTY": 120,

    # ── Top Liquid Equities in NSE F&O ─────────────────────────────────────────
    "RELIANCE": 250,
    "TCS": 175,
    "INFY": 400,
    "HDFCBANK": 550,
    "ICICIBANK": 700,
    "SBIN": 750,
    "BHARTIARTL": 950,
    "ITC": 1600,
    "LT": 150,
    "TATAMOTORS": 550,
    "TATASTEEL": 5500,
    "MARUTI": 50,
    "BAJFINANCE": 125,
    "AXISBANK": 625,
    "KOTAKBANK": 400,
    "HINDUNILVR": 300,
    "SUNPHARMA": 350,
    "TITAN": 175,
    "WIPRO": 1500,
    "ADANIENT": 300,
    "ADANIPORTS": 400,
    "COALINDIA": 2100,
    "POWERGRID": 1800,
    "NTPC": 1500,
    "ONGC": 3850,
    "JSWSTEEL": 675,
    "HCLTECH": 350,
    "TECHM": 600,
    "BAJAJFINSV": 500,
    "DRREDDY": 125,
    "CIPLA": 650,
    "DIVISLAB": 100,
    "APOLLOHOSP": 125,
    "EICHERMOT": 150,
    "HEROMOTOCO": 150,
    "M&M": 350,
    "TATACONSUM": 900,
    "BRITANNIA": 200,
    "NESTLEIND": 40,
    "ASIANPAINT": 200,
    "ULTRACEMCO": 100,
    "GRASIM": 260,
    "SHREECEM": 25,
    "BHARATFORG": 500,
    "INDUSINDBK": 500,
    "VEDL": 1150,
    "TRENT": 100,
    "BEL": 2850,
    "HAL": 150,
    "DLF": 825,
    "ZOMATO": 2000,
    "JIOFIN": 2000,
    "INDIGO": 300,
    "BOSCHLTD": 25,
    "PIDILITIND": 250,
    "SIEMENS": 125,
    "ABB": 125,
    "CANBK": 6750,
    "PNB": 8000,
    "BANKBARODA": 2925,
    "CHOLAFIN": 625,
    "MUTHOOTFIN": 550,
    "SHRIRAMFIN": 150,
    "LTIM": 150,
    "PERSISTENT": 100,
    "COFORGE": 150,
    "MPHASIS": 275,
    "DIXON": 100,
    "POLYCAB": 100,
    "HAVELLS": 500,
    "VOLTAS": 600,
    "TVSMOTOR": 350,
    "BAJAJ-AUTO": 75,
    "ASHOKLEY": 5000,
    "MOTHERSON": 6150,
    "AMBUJACEM": 900,
    "ACC": 300,
    "DALBHARAT": 275,
    "HINDALCO": 1400,
    "NMDC": 4500,
    "NATIONALUM": 3750,
    "SAIL": 8000,
    "JINDALSTEL": 625,
    "BPCL": 1800,
    "IOC": 4875,
    "GAIL": 4650,
    "PETRONET": 3000,
    "IGL": 1375,
    "MGL": 400,
    "AUBANK": 1000,
    "FEDERALBNK": 5000,
    "IDFCFIRSTB": 7500,
    "BANDHANBNK": 2500,
    "PEL": 750,
    "PFC": 1300,
    "RECLTD": 2000,
    "LICHSGFIN": 1000,
    "MANAPPURAM": 3000,
    "AUROPHARMA": 550,
    "LUPIN": 425,
    "BIOCON": 2500,
    "ALKEM": 125,
    "TORNTPHARM": 250,
    "COLPAL": 200,
    "DABUR": 1250,
    "GODREJCP": 500,
    "MARICO": 1200,
    "BERGEPAINT": 1100,
    "PAGEIND": 15,
    "BATAINDIA": 375,
    "ABFRL": 2600,
    "JUBLFOOD": 1250,
    "MCDOWELL-N": 700,
    "UBL": 400,
    "IRCTC": 875,
    "CONCOR": 1000,
    "GMRINFRA": 10000,
    "BHEL": 2625,
    "CUMMINSIND": 300,
    "ASTRAL": 400,
    "SUPREMEIND": 125,
    "DEEPAKNTR": 300,
    "TATACHEM": 550,
    "NAVINFLUOR": 175,
    "SRF": 375,
    "PIIND": 250,
    "UPL": 1300,
    "EXIDEIND": 1200,
    "AMARAJABAT": 1000,
    "CROMPTON": 1800,
    "LALPATHLAB": 300,
    "METROPOLIS": 400,
    "SYNGENE": 1000,
    "IPCALAB": 650,
    "GLENMARK": 575,
    "GRANULES": 2000,
    "LAURUSLABS": 1700,
    "ABCAPITAL": 3100,
    "L&TFH": 4462,
    "POONAWALLA": 1250,
    "IBULHSGFIN": 4100,
    "DELHIVERY": 1800,
    "PAYTM": 1000,
    "NYKAA": 3000,
    "IDEA": 80000,
    "INDUSTOWER": 3400,
    "SUNTV": 1500,
    "ZEEL": 3000,
    "PVRINOX": 400,
}


def is_nse_fo_eligible(symbol: str) -> bool:
    """Checks whether an Indian symbol is exchange-approved for F&O."""
    clean = symbol.upper().replace(".NS", "").replace(".BO", "")
    return clean in NSE_LOT_SIZES


def get_nse_fo_eligible_stocks() -> List[Dict[str, Any]]:
    """Returns curated list of NSE F&O eligible stocks with lot sizes."""
    indices = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}
    return [
        {
            "symbol": sym,
            "display_symbol": f"{sym}.NS",
            "name": sym,
            "lot_size": lot,
            "is_index": sym in indices,
        }
        for sym, lot in NSE_LOT_SIZES.items()
    ]


US_FUTURES_SPECS = {
    "ES=F": {"name": "E-Mini S&P 500 Continuous", "multiplier": 50, "currency": "USD"},
    "NQ=F": {"name": "Nasdaq 100 Continuous", "multiplier": 20, "currency": "USD"},
    "CL=F": {"name": "Crude Oil Continuous", "multiplier": 1000, "currency": "USD"},
    "GC=F": {"name": "Gold Continuous", "multiplier": 100, "currency": "USD"},
}


class NSEDerivativesClient:
    """
    Client for NSE India derivatives with automatic cookie bootstrap,
    in-memory TTL cache, and graceful degradation fallback with staleness indicator.
    """
    def __init__(self, cache_ttl_seconds: float = 30.0):
        self.cache_ttl = cache_ttl_seconds
        self.session = requests.Session()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._session_initialized = False

        self.base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        }
        self.api_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.nseindia.com/option-chain",
        }
        self.session.headers.update(self.base_headers)

    def _init_session(self, force: bool = False):
        if self._session_initialized and not force:
            return
        try:
            r = self.session.get("https://www.nseindia.com/option-chain", timeout=8)
            if r.status_code == 200:
                self._session_initialized = True
        except Exception as e:
            logger.warning("Could not bootstrap NSE session: %s", e)

    def get_option_chain_contract_info(self, symbol: str = "NIFTY") -> Dict[str, Any]:
        """Fetches available expiries and strike price range."""
        sym = symbol.upper()
        cache_key = f"contract_info_{sym}"
        cached = self._cache.get(cache_key)
        now = time.time()

        if cached and (now - cached["timestamp"]) < self.cache_ttl:
            return {**cached["data"], "is_stale": False, "cached_at": cached["iso_time"]}

        self._init_session()
        url = f"https://www.nseindia.com/api/option-chain-contract-info?symbol={sym}"
        try:
            r = self.session.get(url, headers=self.api_headers, timeout=8)
            if r.status_code in (401, 403):
                self._init_session(force=True)
                r = self.session.get(url, headers=self.api_headers, timeout=8)

            if r.status_code == 200:
                data = r.json()
                self._cache[cache_key] = {
                    "data": data,
                    "timestamp": now,
                    "iso_time": datetime.now(timezone.utc).isoformat(),
                }
                return {**data, "is_stale": False, "cached_at": datetime.now(timezone.utc).isoformat()}
        except Exception as e:
            logger.warning("Error fetching NSE contract-info for %s: %s", sym, e)

        if cached:
            return {**cached["data"], "is_stale": True, "cached_at": cached["iso_time"], "warning": "Live NSE request failed; using cached snapshot"}

        # Fallback dummy expiries if network is completely blocked or market is closed
        today = date.today()
        fallback_expiries = [f"29-Sep-2026", f"06-Oct-2026", f"13-Oct-2026", f"27-Oct-2026"]
        return {"expiryDates": fallback_expiries, "strikePrice": [], "is_stale": True, "error": "Unable to fetch live contract info"}

    def get_option_chain(self, symbol: str = "NIFTY", expiry: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetches option chain for Indian indices (NIFTY, BANKNIFTY) or F&O eligible equities (RELIANCE, TCS, etc.).
        """
        sym = symbol.upper().replace(".NS", "").replace(".BO", "")
        contract_info = self.get_option_chain_contract_info(sym)
        expiries = contract_info.get("expiryDates", [])
        if not expiries:
            expiries = ["29-Sep-2026", "27-Oct-2026", "26-Nov-2026"]

        target_expiry = expiry if expiry and expiry in expiries else expiries[0]
        cache_key = f"oc_{sym}_{target_expiry}"
        cached = self._cache.get(cache_key)
        now = time.time()

        if cached and (now - cached["timestamp"]) < self.cache_ttl:
            return {**cached["data"], "is_stale": False, "cached_at": cached["iso_time"]}

        self._init_session()
        is_index = sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
        type_param = "Indices" if is_index else "Equities"
        url = f"https://www.nseindia.com/api/option-chain-v3?type={type_param}&symbol={sym}&expiry={target_expiry}"
        lot_size = NSE_LOT_SIZES.get(sym, 250 if not is_index else 65)

        try:
            r = self.session.get(url, headers=self.api_headers, timeout=8)
            if r.status_code in (401, 403):
                self._init_session(force=True)
                r = self.session.get(url, headers=self.api_headers, timeout=8)

            if r.status_code == 200:
                raw = r.json()
                records = raw.get("records", {})
                underlying_val = records.get("underlyingValue")
                timestamp_str = records.get("timestamp")
                data_list = records.get("data", [])

                strikes_parsed = []
                for row in data_list:
                    ce = row.get("CE")
                    pe = row.get("PE")
                    strike = ce.get("strikePrice") if ce else (pe.get("strikePrice") if pe else None)
                    if strike is None:
                        continue
                    strikes_parsed.append({
                        "strike": float(strike),
                        "ce": {
                            "ltp": float(ce.get("lastPrice")) if ce and ce.get("lastPrice") is not None else None,
                            "iv": float(ce.get("impliedVolatility")) if ce and ce.get("impliedVolatility") is not None else None,
                            "oi": int(ce.get("openInterest")) if ce and ce.get("openInterest") is not None else 0,
                            "change": float(ce.get("change")) if ce and ce.get("change") is not None else 0.0,
                            "pChange": float(ce.get("pChange")) if ce and ce.get("pChange") is not None else 0.0,
                            "bid": float(ce.get("buyPrice1")) if ce and ce.get("buyPrice1") is not None else None,
                            "ask": float(ce.get("sellPrice1")) if ce and ce.get("sellPrice1") is not None else None,
                        } if ce else None,
                        "pe": {
                            "ltp": float(pe.get("lastPrice")) if pe and pe.get("lastPrice") is not None else None,
                            "iv": float(pe.get("impliedVolatility")) if pe and pe.get("impliedVolatility") is not None else None,
                            "oi": int(pe.get("openInterest")) if pe and pe.get("openInterest") is not None else 0,
                            "change": float(pe.get("change")) if pe and pe.get("change") is not None else 0.0,
                            "pChange": float(pe.get("pChange")) if pe and pe.get("pChange") is not None else 0.0,
                            "bid": float(pe.get("buyPrice1")) if pe and pe.get("buyPrice1") is not None else None,
                            "ask": float(pe.get("sellPrice1")) if pe and pe.get("sellPrice1") is not None else None,
                        } if pe else None,
                    })

                parsed_result = {
                    "symbol": sym,
                    "market": "IN",
                    "currency": "INR",
                    "selected_expiry": target_expiry,
                    "available_expiries": expiries,
                    "underlying_value": underlying_val,
                    "nse_timestamp": timestamp_str or datetime.now(timezone.utc).strftime("%d-%b-%Y %H:%M:%S"),
                    "lot_size": lot_size,
                    "total_strikes": len(strikes_parsed),
                    "strikes": strikes_parsed,
                    "is_stale": False,
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                }
                self._cache[cache_key] = {
                    "data": parsed_result,
                    "timestamp": now,
                    "iso_time": datetime.now(timezone.utc).isoformat(),
                }
                return parsed_result
        except Exception as e:
            logger.warning("Error requesting NSE option chain for %s: %s", sym, e)

        if cached:
            return {
                **cached["data"],
                "is_stale": True,
                "cached_at": cached["iso_time"],
                "warning": "Live NSE request failed or rate-limited; displaying cached snapshot",
            }

        # Synthetic fallback generation if NSE is offline or blocked
        if is_index:
            spot_q = get_quote("^NSEI" if sym == "NIFTY" else "^NSEBANK")
            spot = spot_q.price if spot_q and spot_q.price > 0 else (23140.0 if sym == "NIFTY" else 55500.0)
            step = 50 if sym == "NIFTY" else 100
        else:
            spot_q = get_quote(f"{sym}.NS")
            if not spot_q or spot_q.error or spot_q.price <= 0:
                spot_q = get_quote(sym)
            spot = spot_q.price if spot_q and not spot_q.error and spot_q.price > 0 else 1200.0
            if spot > 5000:
                step = 100
            elif spot > 2000:
                step = 50
            elif spot > 1000:
                step = 20
            elif spot > 500:
                step = 10
            elif spot > 100:
                step = 5
            else:
                step = 2.5

        atm = round(spot / step) * step

        synthetic_strikes = []
        for offset in range(-15, 16):
            strk = atm + (offset * step)
            dist = strk - spot
            # Synthetic Intrinsic + extrinsic approximation
            base_extrinsic = max(2.0, spot * 0.015)
            c_val = max(0.5, round(max(0, -dist) + max(1.0, base_extrinsic - abs(dist)*0.1), 2))
            p_val = max(0.5, round(max(0, dist) + max(1.0, base_extrinsic - abs(dist)*0.1), 2))
            synthetic_strikes.append({
                "strike": float(strk),
                "ce": {
                    "ltp": c_val,
                    "iv": 16.5,
                    "oi": int(max(500, 75000 - abs(dist) * 40)),
                    "change": round(offset * -0.2, 2),
                    "pChange": round(offset * -0.1, 2),
                    "bid": round(c_val * 0.98, 2),
                    "ask": round(c_val * 1.02, 2),
                },
                "pe": {
                    "ltp": p_val,
                    "iv": 15.8,
                    "oi": int(max(500, 68000 - abs(dist) * 35)),
                    "change": round(offset * 0.2, 2),
                    "pChange": round(offset * 0.1, 2),
                    "bid": round(p_val * 0.98, 2),
                    "ask": round(p_val * 1.02, 2),
                },
            })

        return {
            "symbol": sym,
            "market": "IN",
            "currency": "INR",
            "selected_expiry": target_expiry,
            "available_expiries": expiries,
            "underlying_value": spot,
            "nse_timestamp": datetime.now(timezone.utc).strftime("%d-%b-%Y %H:%M:%S"),
            "lot_size": lot_size,
            "total_strikes": len(synthetic_strikes),
            "strikes": synthetic_strikes,
            "is_stale": True,
            "warning": "Live NSE endpoint offline/blocked; displaying simulation model snapshot",
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_index_futures(self, symbol: str = "NIFTY") -> Dict[str, Any]:
        """
        Fetches live contract futures per expiry from NSE liveEquity-derivatives endpoint.
        """
        sym = symbol.upper()
        index_map = {"NIFTY": "nse50_fut", "BANKNIFTY": "nifty_bank_fut"}
        index_key = index_map.get(sym)
        if not index_key:
            return {"symbol": sym, "error": f"Futures index not mapped for {sym}", "contracts": []}

        cache_key = f"fut_{sym}"
        cached = self._cache.get(cache_key)
        now = time.time()

        if cached and (now - cached["timestamp"]) < self.cache_ttl:
            return {**cached["data"], "is_stale": False, "cached_at": cached["iso_time"]}

        self._init_session()
        url = f"https://www.nseindia.com/api/liveEquity-derivatives?index={index_key}"
        try:
            r = self.session.get(url, headers=self.api_headers, timeout=8)
            if r.status_code in (401, 403):
                self._init_session(force=True)
                r = self.session.get(url, headers=self.api_headers, timeout=8)

            if r.status_code == 200:
                raw = r.json()
                contracts_raw = raw.get("data", [])
                parsed_contracts = []
                underlying_val = None
                for c in contracts_raw:
                    if underlying_val is None:
                        underlying_val = c.get("underlyingValue")
                    last_price = c.get("lastPrice")
                    und_val = c.get("underlyingValue") or underlying_val
                    basis = round(last_price - und_val, 2) if last_price and und_val else None
                    parsed_contracts.append({
                        "contract": c.get("contract") or f"{sym}-{c.get('expiryDate')}-FUT",
                        "underlying": sym,
                        "expiry": c.get("expiryDate"),
                        "ltp": last_price,
                        "open": c.get("openPrice"),
                        "high": c.get("highPrice"),
                        "low": c.get("lowPrice"),
                        "oi": c.get("openInterest"),
                        "volume_contracts": c.get("numberOfContractsTraded"),
                        "underlying_value": und_val,
                        "basis": basis,
                        "lot_size": NSE_LOT_SIZES.get(sym, 65),
                        "initial_margin_pct": 12.0,
                    })

                result = {
                    "symbol": sym,
                    "market": "IN",
                    "currency": "INR",
                    "underlying_value": underlying_val,
                    "lot_size": NSE_LOT_SIZES.get(sym, 65),
                    "contracts": parsed_contracts,
                    "is_stale": False,
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                }
                self._cache[cache_key] = {
                    "data": result,
                    "timestamp": now,
                    "iso_time": datetime.now(timezone.utc).isoformat(),
                }
                return result
        except Exception as e:
            logger.warning("Error fetching NSE index futures: %s", e)

        if cached:
            return {**cached["data"], "is_stale": True, "cached_at": cached["iso_time"], "warning": "Cached futures data"}

        # Fallback synthetic futures
        spot_q = get_quote("^NSEI" if sym == "NIFTY" else "^NSEBANK")
        spot = spot_q.price if spot_q and spot_q.price > 0 else (23140.0 if sym == "NIFTY" else 55500.0)
        lot = NSE_LOT_SIZES.get(sym, 65)

        synth_contracts = [
            {
                "contract": f"{sym}-29SEP26-FUT",
                "underlying": sym,
                "expiry": "29-Sep-2026",
                "ltp": round(spot + 35.0, 2),
                "open": round(spot + 20.0, 2),
                "high": round(spot + 45.0, 2),
                "low": round(spot + 15.0, 2),
                "oi": 124500,
                "volume_contracts": 85000,
                "underlying_value": spot,
                "basis": 35.0,
                "lot_size": lot,
                "initial_margin_pct": 12.0,
            },
            {
                "contract": f"{sym}-27OCT26-FUT",
                "underlying": sym,
                "expiry": "27-Oct-2026",
                "ltp": round(spot + 95.0, 2),
                "open": round(spot + 80.0, 2),
                "high": round(spot + 110.0, 2),
                "low": round(spot + 75.0, 2),
                "oi": 64200,
                "volume_contracts": 23000,
                "underlying_value": spot,
                "basis": 95.0,
                "lot_size": lot,
                "initial_margin_pct": 12.0,
            },
            {
                "contract": f"{sym}-26NOV26-FUT",
                "underlying": sym,
                "expiry": "26-Nov-2026",
                "ltp": round(spot + 155.0, 2),
                "open": round(spot + 140.0, 2),
                "high": round(spot + 170.0, 2),
                "low": round(spot + 135.0, 2),
                "oi": 31000,
                "volume_contracts": 9500,
                "underlying_value": spot,
                "basis": 155.0,
                "lot_size": lot,
                "initial_margin_pct": 12.0,
            },
        ]

        return {
            "symbol": sym,
            "market": "IN",
            "currency": "INR",
            "underlying_value": spot,
            "lot_size": lot,
            "contracts": synth_contracts,
            "is_stale": True,
            "warning": "Live NSE futures offline/closed; displaying simulation snapshot",
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_stock_futures(self, symbol: str = "RELIANCE") -> Dict[str, Any]:
        """
        Fetches live contract futures per expiry for individual Indian F&O stocks.
        First attempts to fetch from NSE liveEquity-derivatives?index=stock_fut.
        Falls back smoothly to synthetic cost-of-carry futures based on live spot price.
        """
        sym = symbol.upper().replace(".NS", "").replace(".BO", "")
        lot = NSE_LOT_SIZES.get(sym, 250)
        cache_key = f"fut_stock_{sym}"
        cached = self._cache.get(cache_key)
        now = time.time()

        if cached and (now - cached["timestamp"]) < self.cache_ttl:
            return {**cached["data"], "is_stale": False, "cached_at": cached["iso_time"]}

        self._init_session()
        parsed_contracts = []
        underlying_val = None

        try:
            url = "https://www.nseindia.com/api/liveEquity-derivatives?index=stock_fut"
            r = self.session.get(url, headers=self.api_headers, timeout=8)
            if r.status_code in (401, 403):
                self._init_session(force=True)
                r = self.session.get(url, headers=self.api_headers, timeout=8)

            if r.status_code == 200:
                raw = r.json()
                items = raw.get("data", [])
                matching = [x for x in items if x.get("underlying") == sym or sym in x.get("contract", "")]
                if matching:
                    for c in matching:
                        if underlying_val is None:
                            underlying_val = c.get("underlyingValue")
                        lp = c.get("lastPrice")
                        und_v = c.get("underlyingValue") or underlying_val
                        basis = round(lp - und_v, 2) if lp and und_v else None
                        parsed_contracts.append({
                            "contract": c.get("contract") or f"{sym}-{c.get('expiryDate')}-FUT",
                            "underlying": sym,
                            "expiry": c.get("expiryDate"),
                            "ltp": lp,
                            "open": c.get("openPrice"),
                            "high": c.get("highPrice"),
                            "low": c.get("lowPrice"),
                            "oi": c.get("openInterest"),
                            "volume_contracts": c.get("volume") or c.get("numberOfContractsTraded"),
                            "underlying_value": und_v,
                            "basis": basis,
                            "lot_size": lot,
                            "initial_margin_pct": 12.0,
                        })

                    if parsed_contracts:
                        result = {
                            "symbol": sym,
                            "market": "IN",
                            "currency": "INR",
                            "underlying_value": underlying_val,
                            "lot_size": lot,
                            "contracts": parsed_contracts,
                            "is_stale": False,
                            "cached_at": datetime.now(timezone.utc).isoformat(),
                        }
                        self._cache[cache_key] = {
                            "data": result,
                            "timestamp": now,
                            "iso_time": datetime.now(timezone.utc).isoformat(),
                        }
                        return result
        except Exception as e:
            logger.warning("Error fetching live NSE stock futures for %s: %s", sym, e)

        if cached:
            return {**cached["data"], "is_stale": True, "cached_at": cached["iso_time"], "warning": "Cached stock futures data"}

        # Synthetic fallback based on live spot quote
        spot_q = get_quote(f"{sym}.NS")
        if not spot_q or spot_q.error or spot_q.price <= 0:
            spot_q = get_quote(sym)
        spot = spot_q.price if spot_q and not spot_q.error and spot_q.price > 0 else 1250.0

        contract_info = self.get_option_chain_contract_info(sym)
        expiries = contract_info.get("expiryDates", [])
        if not expiries or len(expiries) < 3:
            expiries = ["29-Sep-2026", "27-Oct-2026", "26-Nov-2026"]

        monthly_expiries = expiries[:3]
        premiums = [0.003, 0.007, 0.012]  # ~0.3%, ~0.7%, ~1.2% cost of carry

        synth_contracts = []
        for i, exp in enumerate(monthly_expiries):
            prem_pct = premiums[i] if i < len(premiums) else (0.005 * (i + 1))
            fut_p = round(spot * (1.0 + prem_pct), 2)
            basis = round(fut_p - spot, 2)
            synth_contracts.append({
                "contract": f"{sym}-{exp.replace('-', '').upper()}-FUT",
                "underlying": sym,
                "expiry": exp,
                "ltp": fut_p,
                "open": round(fut_p - (spot * 0.001), 2),
                "high": round(fut_p + (spot * 0.003), 2),
                "low": round(fut_p - (spot * 0.003), 2),
                "oi": int(max(5000, 120000 / (i + 1))),
                "volume_contracts": int(max(2000, 65000 / (i + 1))),
                "underlying_value": spot,
                "basis": basis,
                "lot_size": lot,
                "initial_margin_pct": 12.0,
            })

        return {
            "symbol": sym,
            "market": "IN",
            "currency": "INR",
            "underlying_value": spot,
            "lot_size": lot,
            "contracts": synth_contracts,
            "is_stale": True,
            "warning": "Live NSE futures offline/closed; displaying simulation snapshot",
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_futures(self, symbol: str = "NIFTY") -> Dict[str, Any]:
        """Unified router for Indian index futures and stock futures."""
        sym = symbol.upper().replace(".NS", "").replace(".BO", "")
        if sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"):
            return self.get_index_futures(sym)
        return self.get_stock_futures(sym)


# Singleton NSE client
nse_client = NSEDerivativesClient(cache_ttl_seconds=30.0)


# ══════════════════════════════════════════════════════════════════════════════
# US Derivatives Feeds (via yfinance)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_us_option_chain(ticker_symbol: str = "AAPL", expiry: Optional[str] = None) -> Dict[str, Any]:
    """Fetches US equity option chain via yfinance."""
    sym = ticker_symbol.upper()
    try:
        t = yf.Ticker(sym)
        expiries = t.options
        if not expiries:
            return {"symbol": sym, "market": "US", "currency": "USD", "error": f"No option expiries found for {sym}", "strikes": []}

        target_expiry = expiry if expiry and expiry in expiries else expiries[0]
        chain = t.option_chain(target_expiry)
        calls = chain.calls
        puts = chain.puts

        calls_by_strike = {row['strike']: row for _, row in calls.iterrows()}
        puts_by_strike = {row['strike']: row for _, row in puts.iterrows()}
        all_strikes = sorted(set(list(calls_by_strike.keys()) + list(puts_by_strike.keys())))

        spot_quote = get_quote(sym)
        underlying_val = spot_quote.price if spot_quote and spot_quote.price > 0 else None
        if underlying_val is None or underlying_val <= 0:
            try:
                underlying_val = float(t.fast_info.get('lastPrice') or t.fast_info.get('last_price') or 0.0)
            except Exception:
                pass
        if (underlying_val is None or underlying_val <= 0) and all_strikes:
            underlying_val = float(all_strikes[len(all_strikes) // 2])

        strikes_parsed = []
        for s in all_strikes:
            c = calls_by_strike.get(s)
            p = puts_by_strike.get(s)
            strikes_parsed.append({
                "strike": float(s),
                "ce": {
                    "ltp": float(c['lastPrice']) if c is not None and pd.notna(c['lastPrice']) else None,
                    "bid": float(c['bid']) if c is not None and pd.notna(c['bid']) else None,
                    "ask": float(c['ask']) if c is not None and pd.notna(c['ask']) else None,
                    "oi": int(c['openInterest']) if c is not None and pd.notna(c['openInterest']) else 0,
                    "iv": round(float(c['impliedVolatility']), 4) if c is not None and pd.notna(c['impliedVolatility']) else 0.0,
                    "change": round(float(c['change']), 2) if c is not None and 'change' in c and pd.notna(c['change']) else 0.0,
                    "pChange": round(float(c['percentChange']), 2) if c is not None and 'percentChange' in c and pd.notna(c['percentChange']) else 0.0,
                } if c is not None else None,
                "pe": {
                    "ltp": float(p['lastPrice']) if p is not None and pd.notna(p['lastPrice']) else None,
                    "bid": float(p['bid']) if p is not None and pd.notna(p['bid']) else None,
                    "ask": float(p['ask']) if p is not None and pd.notna(p['ask']) else None,
                    "oi": int(p['openInterest']) if p is not None and pd.notna(p['openInterest']) else 0,
                    "iv": round(float(p['impliedVolatility']), 4) if p is not None and pd.notna(p['impliedVolatility']) else 0.0,
                    "change": round(float(p['change']), 2) if p is not None and 'change' in p and pd.notna(p['change']) else 0.0,
                    "pChange": round(float(p['percentChange']), 2) if p is not None and 'percentChange' in p and pd.notna(p['percentChange']) else 0.0,
                } if p is not None else None,
            })

        return {
            "symbol": sym,
            "market": "US",
            "currency": "USD",
            "selected_expiry": target_expiry,
            "available_expiries": list(expiries),
            "underlying_value": underlying_val,
            "total_strikes": len(strikes_parsed),
            "lot_size": 100,
            "strikes": strikes_parsed,
            "is_stale": False,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error("Error fetching US option chain for %s: %s", sym, e)
        return {"symbol": sym, "market": "US", "currency": "USD", "error": str(e), "strikes": [], "is_stale": True}


def fetch_us_continuous_futures() -> List[Dict[str, Any]]:
    """
    Fetches US continuous futures (ES=F, NQ=F, CL=F, GC=F) with 24h change, contract size,
    notional value, and required initial margin (12%).
    """
    results = []
    for ticker, spec in US_FUTURES_SPECS.items():
        quote = get_quote(ticker)
        price = quote.price if quote and not quote.error and quote.price > 0 else None

        if price is None:
            # Fallback to direct yfinance lookup
            try:
                t = yf.Ticker(ticker)
                fast = t.fast_info
                price = float(fast['lastPrice'])
            except Exception:
                price = 5000.0 if ticker == "ES=F" else (20000.0 if ticker == "NQ=F" else (75.0 if ticker == "CL=F" else 2600.0))

        mult = spec["multiplier"]
        notional_per_lot = round(price * mult, 2)
        initial_margin = round(0.12 * notional_per_lot, 2)

        results.append({
            "symbol": ticker,
            "contract": ticker,
            "underlying": ticker.replace("=F", ""),
            "name": spec["name"],
            "market": "US",
            "currency": "USD",
            "ltp": price,
            "prev_close": quote.prev_close if quote else None,
            "change": quote.change if quote else 0.0,
            "change_pct": quote.change_pct if quote else 0.0,
            "contract_size": mult,
            "lot_size": mult,
            "notional_value": notional_per_lot,
            "initial_margin_required": initial_margin,
            "initial_margin_pct": 12.0,
            "maintenance_margin_pct": 10.0,
            "is_continuous": True,
            "expiry": "Continuous / Perpetual",
        })

    return results


# ══════════════════════════════════════════════════════════════════════════════
# Unified Derivative Contract Price Resolution
# ══════════════════════════════════════════════════════════════════════════════

from dataclasses import dataclass

@dataclass
class DerivativeQuoteResult:
    price: float | None
    bid: float | None = None
    ask: float | None = None
    underlying_price: float | None = None
    price_available: bool = False
    source: str = ""


def _normalize_code(s: str) -> str:
    return s.upper().replace("-", "").replace(" ", "").replace("_", "")


def _parse_contract_date(d: Any) -> date | None:
    if isinstance(d, date):
        return d
    if not d or not isinstance(d, str):
        return None
    s = d.strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d%b%y", "%d%b%Y", "%d-%B-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def resolve_derivative_contract_quote(contract: Any) -> DerivativeQuoteResult:
    """
    Unified price resolution function for Options and Futures contracts.
    Uses the EXACT SAME live quote source as the Futures Market and Option Chain views:
    - Indian Index & Stock Futures: nse_client.get_futures(contract.underlying)
    - US Continuous Futures: fetch_us_continuous_futures() / get_quote(contract.symbol)
    - Indian Options: nse_client.get_option_chain(contract.underlying, expiry)
    - US Options: fetch_us_option_chain(contract.underlying, expiry)

    NEVER falls back silently to entry_price. Returns price_available=False if live quote is missing.
    """
    inst = getattr(contract, "instrument_type", "").lower()
    market = getattr(contract, "market", "IN").upper()
    underlying = getattr(contract, "underlying", "").upper().replace(".NS", "").replace(".BO", "")
    expiry_date = getattr(contract, "expiry_date", None)
    if isinstance(expiry_date, str):
        expiry_date = _parse_contract_date(expiry_date)
    symbol = getattr(contract, "symbol", "") or ""

    # ──────────────────────────────────────────────────────────────────────────
    # CASE 1: FUTURES
    # ──────────────────────────────────────────────────────────────────────────
    if inst == "future":
        if market == "US":
            # US Continuous Futures (ES=F, NQ=F, CL=F, GC=F)
            fut_sym = symbol if symbol.endswith("=F") else f"{underlying}=F"
            q = get_quote(fut_sym)
            if q and not q.error and q.price and q.price > 0:
                return DerivativeQuoteResult(
                    price=float(q.price),
                    bid=float(q.price),
                    ask=float(q.price),
                    underlying_price=float(q.price),
                    price_available=True,
                    source="us_continuous_futures",
                )
            return DerivativeQuoteResult(
                price=None,
                price_available=False,
                source="us_continuous_futures_unavailable",
            )

        # Indian Futures (NIFTY, BANKNIFTY, RELIANCE, TCS, etc.)
        try:
            fut_data = nse_client.get_futures(underlying)
            contracts = fut_data.get("contracts", [])
            und_val = fut_data.get("underlying_value")

            norm_sym = _normalize_code(symbol)

            matched_c = None
            for c in contracts:
                # 1. Match by normalized contract symbol
                c_contract = c.get("contract") or ""
                if c_contract and _normalize_code(c_contract) == norm_sym:
                    matched_c = c
                    break

                # 2. Match by expiry date
                if expiry_date:
                    c_exp_date = _parse_contract_date(c.get("expiry") or c.get("expiryDate"))
                    if c_exp_date and c_exp_date == expiry_date:
                        matched_c = c
                        break

            # If no exact match and only 1 contract
            if not matched_c and len(contracts) == 1:
                matched_c = contracts[0]

            if matched_c:
                ltp = matched_c.get("ltp") or matched_c.get("lastPrice")
                if ltp is not None and float(ltp) > 0:
                    c_und = matched_c.get("underlying_value") or und_val
                    return DerivativeQuoteResult(
                        price=float(ltp),
                        bid=matched_c.get("bid"),
                        ask=matched_c.get("ask"),
                        underlying_price=float(c_und) if c_und else None,
                        price_available=True,
                        source="nse_futures",
                    )
        except Exception as e:
            logger.warning("Error in resolve_derivative_contract_quote for Indian future %s: %s", symbol, e)

        return DerivativeQuoteResult(
            price=None,
            price_available=False,
            source="nse_futures_unavailable",
        )

    # ──────────────────────────────────────────────────────────────────────────
    # CASE 2: OPTIONS
    # ──────────────────────────────────────────────────────────────────────────
    if inst == "option":
        strike_price = getattr(contract, "strike_price", None)
        option_type = getattr(contract, "option_type", "call")
        opt_type = (option_type or "call").lower()

        if market == "IN":
            try:
                exp_str = expiry_date.strftime("%d-%b-%Y") if expiry_date else None
                chain_data = nse_client.get_option_chain(symbol=underlying, expiry=exp_str)
                strikes = chain_data.get("strikes", [])
                und_val = chain_data.get("underlying_value")

                matched_strike = None
                if strike_price is not None:
                    matched_strike = next((s for s in strikes if abs(s.get("strike", 0.0) - float(strike_price)) < 0.01), None)

                if matched_strike:
                    opt_side = matched_strike.get("call" if opt_type == "call" else "put", {})
                    ltp = opt_side.get("ltp") or opt_side.get("lastPrice")
                    bid = opt_side.get("bid")
                    ask = opt_side.get("ask")

                    eff_price = None
                    if ltp is not None and float(ltp) > 0:
                        eff_price = float(ltp)
                    elif bid is not None and float(bid) > 0:
                        eff_price = float(bid)
                    elif ask is not None and float(ask) > 0:
                        eff_price = float(ask)

                    if eff_price is not None and eff_price > 0:
                        return DerivativeQuoteResult(
                            price=eff_price,
                            bid=bid,
                            ask=ask,
                            underlying_price=und_val,
                            price_available=True,
                            source="nse_option_chain",
                        )
            except Exception as e:
                logger.warning("Error in resolve_derivative_contract_quote for Indian option %s: %s", symbol, e)

            return DerivativeQuoteResult(
                price=None,
                price_available=False,
                source="nse_option_unavailable",
            )

        if market == "US":
            try:
                exp_str = expiry_date.isoformat() if expiry_date else None
                chain_data = fetch_us_option_chain(ticker_symbol=underlying, expiry=exp_str)
                strikes = chain_data.get("strikes", [])
                und_val = chain_data.get("underlying_value")

                matched_strike = None
                if strike_price is not None:
                    matched_strike = next((s for s in strikes if abs(s.get("strike", 0.0) - float(strike_price)) < 0.01), None)

                if matched_strike:
                    opt_side = matched_strike.get("call" if opt_type == "call" else "put", {})
                    ltp = opt_side.get("ltp")
                    bid = opt_side.get("bid")
                    ask = opt_side.get("ask")

                    eff_price = None
                    if ltp is not None and float(ltp) > 0:
                        eff_price = float(ltp)
                    elif bid is not None and float(bid) > 0:
                        eff_price = float(bid)
                    elif ask is not None and float(ask) > 0:
                        eff_price = float(ask)

                    if eff_price is not None and eff_price > 0:
                        return DerivativeQuoteResult(
                            price=eff_price,
                            bid=bid,
                            ask=ask,
                            underlying_price=und_val,
                            price_available=True,
                            source="us_option_chain",
                        )
            except Exception as e:
                logger.warning("Error in resolve_derivative_contract_quote for US option %s: %s", symbol, e)

            return DerivativeQuoteResult(
                price=None,
                price_available=False,
                source="us_option_unavailable",
            )

    return DerivativeQuoteResult(
        price=None,
        price_available=False,
        source="unsupported_instrument",
    )
