import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { RefreshCw, AlertTriangle, Layers, Search, Check } from 'lucide-react';
import { fetchOptionChain, searchTickers } from '../api/client';

function formatNumber(num) {
  if (num === null || num === undefined || isNaN(num)) return '—';
  return Number(num).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatInt(num) {
  if (num === null || num === undefined || isNaN(num)) return '—';
  return Number(num).toLocaleString('en-US');
}

const TOP_IN_FO_STOCKS = [
  { symbol: 'RELIANCE', name: 'Reliance Industries', lot: 250 },
  { symbol: 'TCS', name: 'Tata Consultancy Services', lot: 175 },
  { symbol: 'INFY', name: 'Infosys Ltd', lot: 400 },
  { symbol: 'HDFCBANK', name: 'HDFC Bank', lot: 550 },
  { symbol: 'ICICIBANK', name: 'ICICI Bank', lot: 700 },
  { symbol: 'SBIN', name: 'State Bank of India', lot: 750 },
  { symbol: 'TATAMOTORS', name: 'Tata Motors', lot: 550 },
];

const TOP_US_OPTIONS_STOCKS = [
  { symbol: 'MSFT', name: 'Microsoft Corporation', lot: 100 },
  { symbol: 'AAPL', name: 'Apple Inc.', lot: 100 },
  { symbol: 'NVDA', name: 'NVIDIA Corporation', lot: 100 },
  { symbol: 'TSLA', name: 'Tesla Inc.', lot: 100 },
  { symbol: 'AMZN', name: 'Amazon.com Inc.', lot: 100 },
  { symbol: 'GOOGL', name: 'Alphabet Inc.', lot: 100 },
];

export function OptionChain({
  market = 'IN',
  onSelectContract,
  wallet,
}) {
  // Mode: 'NIFTY' | 'BANKNIFTY' | 'IN_STOCKS' | 'US_OPTIONS'
  const [mode, setMode] = useState(market === 'US' ? 'US_OPTIONS' : 'NIFTY');
  const [selectedSymbol, setSelectedSymbol] = useState(market === 'US' ? 'MSFT' : 'NIFTY');
  const [selectedExpiry, setSelectedExpiry] = useState('');
  const [chainData, setChainData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Search state for company-level options
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const searchContainerRef = useRef(null);
  const debounceTimerRef = useRef(null);

  const activeMarket = mode === 'US_OPTIONS' ? 'US' : 'IN';

  // Handle outside click for search dropdown
  useEffect(() => {
    function handleClickOutside(e) {
      if (searchContainerRef.current && !searchContainerRef.current.contains(e.target)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Debounced search when searching for companies
  useEffect(() => {
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    const query = searchQuery.trim();
    if (!query) {
      setSearchResults([]);
      setIsSearching(false);
      setShowDropdown(false);
      return;
    }

    setIsSearching(true);
    setShowDropdown(true);

    debounceTimerRef.current = setTimeout(async () => {
      try {
        const results = await searchTickers(query, activeMarket);
        setSearchResults(results);
      } catch (err) {
        console.error('OptionChain search error:', err);
        setSearchResults([]);
      } finally {
        setIsSearching(false);
      }
    }, 250);

    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
  }, [searchQuery, activeMarket]);

  // Load option chain
  const loadChain = useCallback(async (sym, exp, mkt) => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchOptionChain(mkt, sym, exp || null);
      setChainData(data);
      if (data?.selected_expiry && !exp) {
        setSelectedExpiry(data.selected_expiry);
      }
    } catch (err) {
      setError(err.message || `Failed to fetch option chain for ${sym}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedSymbol) {
      loadChain(selectedSymbol, selectedExpiry, activeMarket);
    }
  }, [selectedSymbol, selectedExpiry, activeMarket, loadChain]);

  // Mode change handler
  const handleModeChange = (newMode) => {
    setMode(newMode);
    setSelectedExpiry('');
    setChainData(null);
    setSearchQuery('');
    setShowDropdown(false);

    if (newMode === 'NIFTY') {
      setSelectedSymbol('NIFTY');
    } else if (newMode === 'BANKNIFTY') {
      setSelectedSymbol('BANKNIFTY');
    } else if (newMode === 'IN_STOCKS') {
      setSelectedSymbol('RELIANCE');
    } else if (newMode === 'US_OPTIONS') {
      setSelectedSymbol('MSFT');
    }
  };

  const handleSelectSearchResult = (item) => {
    const rawSym = (item.symbol || '').replace('.NS', '').replace('.BO', '').toUpperCase();
    setSelectedSymbol(rawSym);
    setSelectedExpiry('');
    setSearchQuery('');
    setShowDropdown(false);
  };

  const expiries = chainData?.available_expiries || [];
  const strikes = chainData?.strikes || [];
  const underlyingValue = chainData?.underlying_value ?? 0;
  const isStale = Boolean(chainData?.is_stale);
  const lotSize = chainData?.lot_size || (activeMarket === 'IN' ? 65 : 100);
  const currencySymbol = activeMarket === 'IN' ? '₹' : '$';

  // Identify ATM strike
  const atmStrike = useMemo(() => {
    if (!strikes.length || !underlyingValue) return null;
    let closest = strikes[0].strike;
    let minDiff = Math.abs(closest - underlyingValue);
    for (const row of strikes) {
      const diff = Math.abs(row.strike - underlyingValue);
      if (diff < minDiff) {
        minDiff = diff;
        closest = row.strike;
      }
    }
    return closest;
  }, [strikes, underlyingValue]);

  function handleContractClick(row, optionType) {
    if (!onSelectContract) return;
    const optionData = optionType === 'call' ? row.ce : row.pe;
    if (!optionData) return;

    const optSymbol = `${selectedSymbol}-${selectedExpiry}-${row.strike}-${optionType.toUpperCase()}`;
    const fillPrice = optionData.ltp || optionData.ask || optionData.bid || 10.0;

    onSelectContract({
      isDerivative: true,
      instrument_type: 'option',
      option_type: optionType,
      underlying: selectedSymbol,
      strike_price: row.strike,
      expiry_date: selectedExpiry,
      symbol: optSymbol,
      lot_size: lotSize,
      market: activeMarket,
      price: fillPrice,
      current_price: fillPrice,
      underlying_price: underlyingValue,
      bid: optionData.bid,
      ask: optionData.ask,
      iv: optionData.iv,
      oi: optionData.oi,
    });
  }

  return (
    <div className="w-full space-y-3 font-sans text-text-primary select-none">
      {/* Top Header & Navigation Bar */}
      <div className="bg-surface border border-border px-4 py-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center space-x-1.5 font-semibold text-xs tracking-wider uppercase text-text-primary">
            <Layers className="w-4 h-4 text-accent" />
            <span>OPTION CHAIN</span>
          </div>

          <span className="text-border">|</span>

          {/* Mode Switcher Tabs */}
          <div className="inline-flex p-0.5 bg-base border border-border font-mono-tabular">
            <button
              onClick={() => handleModeChange('NIFTY')}
              className={`px-2.5 py-1 text-xs font-semibold uppercase tracking-wider transition-colors ${
                mode === 'NIFTY'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              NIFTY
            </button>
            <button
              onClick={() => handleModeChange('BANKNIFTY')}
              className={`px-2.5 py-1 text-xs font-semibold uppercase tracking-wider transition-colors ${
                mode === 'BANKNIFTY'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              BANKNIFTY
            </button>
            <button
              onClick={() => handleModeChange('IN_STOCKS')}
              className={`px-2.5 py-1 text-xs font-semibold uppercase tracking-wider transition-colors ${
                mode === 'IN_STOCKS'
                  ? 'bg-[#232731] text-accent'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              NSE Stocks
            </button>
            <button
              onClick={() => handleModeChange('US_OPTIONS')}
              className={`px-2.5 py-1 text-xs font-semibold uppercase tracking-wider transition-colors ${
                mode === 'US_OPTIONS'
                  ? 'bg-[#232731] text-accent'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              US Options
            </button>
          </div>

          {/* Expiry Selector Dropdown */}
          {expiries.length > 0 && (
            <div className="flex items-center space-x-1.5 text-xs font-mono-tabular">
              <span className="text-text-muted">Expiry:</span>
              <select
                value={selectedExpiry}
                onChange={(e) => setSelectedExpiry(e.target.value)}
                className="bg-base border border-border text-text-primary px-2 py-1 text-xs focus:outline-none focus:border-accent"
              >
                {expiries.map((exp) => (
                  <option key={exp} value={exp}>
                    {exp}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* Spot Price & Staleness Status */}
        <div className="flex items-center space-x-3 font-mono-tabular text-xs">
          {underlyingValue > 0 && (
            <div className="flex items-center space-x-1.5 bg-base border border-border px-2.5 py-1">
              <span className="text-text-muted">{selectedSymbol} SPOT:</span>
              <span className="font-bold text-text-primary">
                {currencySymbol}{formatNumber(underlyingValue)}
              </span>
            </div>
          )}

          <div className="text-[11px] text-text-muted bg-base border border-border px-2 py-1">
            1 LOT = {lotSize}
          </div>

          {/* STALE DATA Badge if cached/stale */}
          {isStale && (
            <span
              title={chainData?.warning || 'Using cached/fallback options data snapshot'}
              className="px-2 py-0.5 rounded text-[10px] font-bold font-mono-tabular tracking-wider uppercase border bg-amber-500/15 text-amber-400 border-amber-500/40 flex items-center space-x-1"
            >
              <AlertTriangle className="w-3 h-3 text-amber-400" />
              <span>STALE DATA</span>
            </span>
          )}

          <button
            onClick={() => loadChain(selectedSymbol, selectedExpiry, activeMarket)}
            disabled={loading}
            className="p-1 hover:bg-surface-hover text-text-muted hover:text-text-primary transition-colors border border-border"
            title="Refresh option chain"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Company Search Bar & Quick Chips (for NSE Stocks and US Options modes) */}
      {(mode === 'IN_STOCKS' || mode === 'US_OPTIONS') && (
        <div className="bg-surface border border-border px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 text-xs">
          {/* Search Input with Floating Dropdown */}
          <div ref={searchContainerRef} className="relative w-full sm:w-80">
            <div className="flex items-center bg-base border border-border px-2.5 py-1.5 focus-within:border-accent">
              <Search className="w-3.5 h-3.5 text-text-muted mr-2 shrink-0" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onFocus={() => {
                  if (searchResults.length > 0) setShowDropdown(true);
                }}
                placeholder={
                  mode === 'IN_STOCKS'
                    ? 'Search Indian stock (e.g. Reliance, TCS, Infy)...'
                    : 'Search US company (e.g. MSFT, AAPL, NVDA)...'
                }
                className="bg-transparent text-text-primary text-xs w-full focus:outline-none uppercase font-mono-tabular placeholder:normal-case placeholder:text-text-muted"
              />
              {isSearching && <RefreshCw className="w-3.5 h-3.5 text-accent animate-spin shrink-0 ml-1" />}
            </div>

            {/* Dropdown Results */}
            {showDropdown && searchResults.length > 0 && (
              <div className="absolute left-0 right-0 top-full mt-1 bg-surface border border-border shadow-2xl z-30 max-h-60 overflow-y-auto divide-y divide-border/50">
                {searchResults.map((item) => {
                  const cleanSym = (item.symbol || '').replace('.NS', '').replace('.BO', '');
                  return (
                    <div
                      key={item.symbol}
                      onClick={() => handleSelectSearchResult(item)}
                      className="px-3 py-2 hover:bg-[#232731] cursor-pointer flex items-center justify-between transition-colors"
                    >
                      <div>
                        <div className="font-bold text-text-primary font-mono-tabular flex items-center space-x-2">
                          <span>{cleanSym}</span>
                          <span className="text-[10px] px-1 py-0.2 bg-base border border-border text-text-muted font-normal">
                            {item.exchange || activeMarket}
                          </span>
                        </div>
                        <div className="text-[11px] text-text-muted truncate max-w-[200px]">{item.name}</div>
                      </div>
                      <div className="text-right font-mono-tabular">
                        {item.lot_size ? (
                          <span className="text-[10px] px-1.5 py-0.5 bg-accent/15 text-accent font-bold border border-accent/40 rounded">
                            LOT {item.lot_size}
                          </span>
                        ) : (
                          <span className="text-[10px] text-text-muted">1 LOT</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Quick Select Chips */}
          <div className="flex items-center space-x-1.5 flex-wrap gap-y-1">
            <span className="text-text-muted font-mono-tabular text-[11px]">Quick Select:</span>
            {(mode === 'IN_STOCKS' ? TOP_IN_FO_STOCKS : TOP_US_OPTIONS_STOCKS).map((stock) => (
              <button
                key={stock.symbol}
                onClick={() => {
                  setSelectedSymbol(stock.symbol);
                  setSelectedExpiry('');
                }}
                className={`px-2 py-0.5 text-xs font-mono-tabular font-medium transition-colors border ${
                  selectedSymbol === stock.symbol
                    ? 'bg-accent/20 text-accent border-accent/60 font-bold'
                    : 'bg-base text-text-muted border-border hover:text-text-primary hover:border-text-muted'
                }`}
              >
                {stock.symbol}
                <span className="text-[10px] opacity-70 ml-1">({stock.lot})</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Warning message if stale */}
      {chainData?.warning && (
        <div className="px-3 py-1.5 bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs font-mono-tabular flex items-center space-x-2">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          <span>{chainData.warning}</span>
        </div>
      )}

      {/* Main Option Chain Table */}
      <div className="border border-border bg-surface overflow-hidden">
        {loading && strikes.length === 0 ? (
          <div className="p-12 text-center text-xs font-mono-tabular text-text-muted">
            <RefreshCw className="w-5 h-5 mx-auto mb-2 animate-spin text-accent" />
            LOADING OPTION CHAIN FOR {selectedSymbol}...
          </div>
        ) : error ? (
          <div className="p-8 text-center text-xs font-mono-tabular text-red space-y-2">
            <div>ERROR LOADING CHAIN: {error}</div>
            <button
              onClick={() => loadChain(selectedSymbol, selectedExpiry, activeMarket)}
              className="px-3 py-1 bg-base border border-border text-text-primary hover:bg-[#232731]"
            >
              RETRY
            </button>
          </div>
        ) : strikes.length === 0 ? (
          <div className="p-10 text-center text-xs font-mono-tabular text-text-muted">
            NO OPTION STRIKES FOUND FOR {selectedSymbol} ({selectedExpiry || 'DEFAULT'})
          </div>
        ) : (
          <div className="overflow-x-auto max-h-[620px] overflow-y-auto">
            <table className="w-full text-left border-collapse font-mono-tabular text-xs">
              <thead className="sticky top-0 bg-[#0f1014] z-10 border-b border-border select-none">
                {/* Section Super-Headers */}
                <tr className="border-b border-border/60 text-[10px] uppercase font-bold tracking-widest text-text-muted">
                  <th colSpan={5} className="text-center py-1 bg-emerald-950/20 text-emerald-400/90 border-r border-border">
                    CALLS (CE) — BULLISH
                  </th>
                  <th className="text-center py-1 bg-base border-r border-border">
                    STRIKE
                  </th>
                  <th colSpan={5} className="text-center py-1 bg-red-950/20 text-red/90">
                    PUTS (PE) — BEARISH
                  </th>
                </tr>
                {/* Column Headers */}
                <tr className="h-7 text-[11px] uppercase text-text-muted font-sans font-medium bg-[#14161b]">
                  {/* Calls columns */}
                  <th className="px-2 text-right">OI</th>
                  <th className="px-2 text-right">IV%</th>
                  <th className="px-2 text-right">Chg%</th>
                  <th className="px-2 text-right">Bid/Ask</th>
                  <th className="px-3 text-right border-r border-border font-bold text-emerald-400">Call LTP</th>

                  {/* Strike in Center */}
                  <th className="px-3 text-center border-r border-border font-bold bg-[#1a1c23] text-text-primary">
                    Strike
                  </th>

                  {/* Puts columns */}
                  <th className="px-3 text-left font-bold text-red">Put LTP</th>
                  <th className="px-2 text-left">Bid/Ask</th>
                  <th className="px-2 text-left">Chg%</th>
                  <th className="px-2 text-left">IV%</th>
                  <th className="px-2 text-right">OI</th>
                </tr>
              </thead>
              <tbody>
                {strikes.map((row) => {
                  const isAtm = row.strike === atmStrike;
                  const isItmCall = underlyingValue > 0 && row.strike < underlyingValue;
                  const isItmPut = underlyingValue > 0 && row.strike > underlyingValue;

                  const ce = row.ce || {};
                  const pe = row.pe || {};

                  const ceChg = ce.pChange || 0;
                  const peChg = pe.pChange || 0;

                  return (
                    <tr
                      key={row.strike}
                      className={`border-b border-border/50 text-xs transition-colors hover:bg-surface-hover ${
                        isAtm ? 'bg-[#232731]' : ''
                      }`}
                    >
                      {/* CALLS: OI */}
                      <td className={`px-2 py-1.5 text-right text-text-muted ${isItmCall ? 'bg-emerald-950/10' : ''}`}>
                        {formatInt(ce.oi)}
                      </td>

                      {/* CALLS: IV */}
                      <td className={`px-2 py-1.5 text-right text-text-muted ${isItmCall ? 'bg-emerald-950/10' : ''}`}>
                        {ce.iv ? `${(ce.iv * (ce.iv > 1 ? 1 : 100)).toFixed(1)}%` : '—'}
                      </td>

                      {/* CALLS: Change % */}
                      <td className={`px-2 py-1.5 text-right ${isItmCall ? 'bg-emerald-950/10' : ''} ${
                        ceChg > 0 ? 'text-green' : ceChg < 0 ? 'text-red' : 'text-text-muted'
                      }`}>
                        {ceChg > 0 ? `+${ceChg.toFixed(2)}%` : ceChg < 0 ? `${ceChg.toFixed(2)}%` : '0.00%'}
                      </td>

                      {/* CALLS: Bid/Ask */}
                      <td className={`px-2 py-1.5 text-right text-[11px] text-text-muted ${isItmCall ? 'bg-emerald-950/10' : ''}`}>
                        {ce.bid && ce.ask ? `${formatNumber(ce.bid)} / ${formatNumber(ce.ask)}` : '—'}
                      </td>

                      {/* CALLS: LTP (Clickable) */}
                      <td
                        onClick={() => handleContractClick(row, 'call')}
                        title={`Trade Call Option ${selectedSymbol} Strike ${row.strike}`}
                        className={`px-3 py-1.5 text-right border-r border-border cursor-pointer font-bold ${
                          isItmCall ? 'bg-emerald-950/20 text-emerald-300' : 'text-text-primary'
                        } hover:bg-accent/20 hover:text-accent`}
                      >
                        <div className="flex items-center justify-end space-x-1">
                          <span>{formatNumber(ce.ltp)}</span>
                          <span className="text-[9px] text-text-muted font-normal px-1 py-0.2 bg-base/80 border border-border">BUY/SELL</span>
                        </div>
                      </td>

                      {/* CENTER: Strike Price */}
                      <td
                        className={`px-3 py-1.5 text-center font-bold border-r border-border select-all ${
                          isAtm
                            ? 'bg-[#2d323f] text-accent ring-1 ring-accent/40 font-extrabold'
                            : 'bg-base text-text-primary'
                        }`}
                      >
                        <div className="flex items-center justify-center space-x-1">
                          <span>{formatNumber(row.strike)}</span>
                          {isAtm && (
                            <span className="text-[9px] px-1 py-0.2 bg-accent/20 text-accent font-bold uppercase tracking-wider">
                              ATM
                            </span>
                          )}
                        </div>
                      </td>

                      {/* PUTS: LTP (Clickable) */}
                      <td
                        onClick={() => handleContractClick(row, 'put')}
                        title={`Trade Put Option ${selectedSymbol} Strike ${row.strike}`}
                        className={`px-3 py-1.5 text-left cursor-pointer font-bold ${
                          isItmPut ? 'bg-red-950/20 text-red-300' : 'text-text-primary'
                        } hover:bg-accent/20 hover:text-accent`}
                      >
                        <div className="flex items-center justify-start space-x-1">
                          <span className="text-[9px] text-text-muted font-normal px-1 py-0.2 bg-base/80 border border-border">BUY/SELL</span>
                          <span>{formatNumber(pe.ltp)}</span>
                        </div>
                      </td>

                      {/* PUTS: Bid/Ask */}
                      <td className={`px-2 py-1.5 text-left text-[11px] text-text-muted ${isItmPut ? 'bg-red-950/10' : ''}`}>
                        {pe.bid && pe.ask ? `${formatNumber(pe.bid)} / ${formatNumber(pe.ask)}` : '—'}
                      </td>

                      {/* PUTS: Change % */}
                      <td className={`px-2 py-1.5 text-left ${isItmPut ? 'bg-red-950/10' : ''} ${
                        peChg > 0 ? 'text-green' : peChg < 0 ? 'text-red' : 'text-text-muted'
                      }`}>
                        {peChg > 0 ? `+${peChg.toFixed(2)}%` : peChg < 0 ? `${peChg.toFixed(2)}%` : '0.00%'}
                      </td>

                      {/* PUTS: IV */}
                      <td className={`px-2 py-1.5 text-left text-text-muted ${isItmPut ? 'bg-red-950/10' : ''}`}>
                        {pe.iv ? `${(pe.iv * (pe.iv > 1 ? 1 : 100)).toFixed(1)}%` : '—'}
                      </td>

                      {/* PUTS: OI */}
                      <td className={`px-2 py-1.5 text-right text-text-muted ${isItmPut ? 'bg-red-950/10' : ''}`}>
                        {formatInt(pe.oi)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
