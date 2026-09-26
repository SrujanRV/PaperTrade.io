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

# Default contract sizes & multipliers
NSE_LOT_SIZES = {
    "NIFTY": 65,
    "BANKNIFTY": 30,
    "FINNIFTY": 60,
    "MIDCPNIFTY": 120,
}

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
        Fetches option chain for NIFTY or BANKNIFTY.
        """
        sym = symbol.upper()
        contract_info = self.get_option_chain_contract_info(sym)
        expiries = contract_info.get("expiryDates", [])
        if not expiries:
            expiries = ["29-Sep-2026"]

        target_expiry = expiry if expiry and expiry in expiries else expiries[0]
        cache_key = f"oc_{sym}_{target_expiry}"
        cached = self._cache.get(cache_key)
        now = time.time()

        if cached and (now - cached["timestamp"]) < self.cache_ttl:
            return {**cached["data"], "is_stale": False, "cached_at": cached["iso_time"]}

        self._init_session()
        url = f"https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol={sym}&expiry={target_expiry}"
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
                    "lot_size": NSE_LOT_SIZES.get(sym, 65),
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
            logger.warning("Error requesting NSE option chain: %s", e)

        if cached:
            return {
                **cached["data"],
                "is_stale": True,
                "cached_at": cached["iso_time"],
                "warning": "Live NSE request failed or rate-limited; displaying cached snapshot",
            }

        # Synthetic fallback generation if NSE is offline or blocked
        spot_q = get_quote("^NSEI" if sym == "NIFTY" else "^NSEBANK")
        spot = spot_q.price if spot_q and spot_q.price > 0 else (23140.0 if sym == "NIFTY" else 55500.0)
        step = 50 if sym == "NIFTY" else 100
        atm = round(spot / step) * step

        synthetic_strikes = []
        for offset in range(-15, 16):
            strk = atm + (offset * step)
            dist = strk - spot
            # Synthetic Intrinsic + extrinsic approximation
            c_val = max(1.0, round(max(0, -dist) + max(5.0, 150.0 - abs(dist)*0.15), 1))
            p_val = max(1.0, round(max(0, dist) + max(5.0, 150.0 - abs(dist)*0.15), 1))
            synthetic_strikes.append({
                "strike": float(strk),
                "ce": {
                    "ltp": c_val,
                    "iv": 11.5,
                    "oi": int(max(1000, 150000 - abs(dist) * 80)),
                    "change": round(offset * -0.5, 2),
                    "pChange": round(offset * -0.2, 2),
                    "bid": round(c_val * 0.99, 1),
                    "ask": round(c_val * 1.01, 1),
                },
                "pe": {
                    "ltp": p_val,
                    "iv": 10.8,
                    "oi": int(max(1000, 140000 - abs(dist) * 75)),
                    "change": round(offset * 0.5, 2),
                    "pChange": round(offset * 0.2, 2),
                    "bid": round(p_val * 0.99, 1),
                    "ask": round(p_val * 1.01, 1),
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
            "lot_size": NSE_LOT_SIZES.get(sym, 65),
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
