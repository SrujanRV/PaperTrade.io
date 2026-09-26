import React, { useState, useEffect, useCallback, useRef } from 'react';
import { RefreshCw, TrendingUp, TrendingDown, Activity, ShieldCheck, DollarSign, Search } from 'lucide-react';
import { fetchFuturesMarket, searchTickers } from '../api/client';

function formatMoney(amount, currency = 'USD') {
  if (amount === undefined || amount === null || isNaN(amount)) return '0.00';
  const locale = currency === 'INR' ? 'en-IN' : 'en-US';
  return Number(amount).toLocaleString(locale, {
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

export function FuturesMarket({
  defaultMarket = 'IN',
  onSelectContract,
  wallet,
}) {
  // Tab: 'IN_INDEX' | 'IN_STOCK' | 'US_CONTINUOUS'
  const [activeTab, setActiveTab] = useState(defaultMarket === 'US' ? 'US_CONTINUOUS' : 'IN_INDEX');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Indian Stock Futures search state
  const [selectedStock, setSelectedStock] = useState('RELIANCE');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const searchContainerRef = useRef(null);
  const debounceTimerRef = useRef(null);

  // Sync when defaultMarket prop changes
  useEffect(() => {
    if (defaultMarket === 'US') {
      setActiveTab('US_CONTINUOUS');
    }
  }, [defaultMarket]);

  // Click outside search dropdown
  useEffect(() => {
    function handleClickOutside(e) {
      if (searchContainerRef.current && !searchContainerRef.current.contains(e.target)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Debounced search for Indian stocks
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
        const results = await searchTickers(query, 'IN');
        setSearchResults(results);
      } catch (err) {
        console.error('Futures search error:', err);
        setSearchResults([]);
      } finally {
        setIsSearching(false);
      }
    }, 250);

    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
  }, [searchQuery]);

  const loadData = useCallback(async (tab, stock) => {
    try {
      setLoading(true);
      setError(null);
      if (tab === 'US_CONTINUOUS') {
        const res = await fetchFuturesMarket('US');
        setData(res);
      } else if (tab === 'IN_STOCK') {
        const res = await fetchFuturesMarket('IN', stock || 'RELIANCE');
        setData(res);
      } else {
        const res = await fetchFuturesMarket('IN');
        setData(res);
      }
    } catch (err) {
      setError(err.message || 'Failed to fetch futures data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData(activeTab, selectedStock);
  }, [activeTab, selectedStock, loadData]);

  const handleSelectSearchResult = (item) => {
    const rawSym = (item.symbol || '').replace('.NS', '').replace('.BO', '').toUpperCase();
    setSelectedStock(rawSym);
    setSearchQuery('');
    setShowDropdown(false);
  };

  const handleTradeIndianContract = (c, underlyingSymbol) => {
    if (!onSelectContract) return;
    onSelectContract({
      isDerivative: true,
      instrument_type: 'future',
      option_type: null,
      underlying: underlyingSymbol,
      symbol: c.contract,
      expiry_date: c.expiry,
      lot_size: c.lot_size || (underlyingSymbol === 'NIFTY' ? 65 : 250),
      market: 'IN',
      price: c.ltp,
      current_price: c.ltp,
      underlying_price: c.underlying_value,
      basis: c.basis,
      oi: c.oi,
      initial_margin_pct: 12.0,
    });
  };

  const handleTradeUSContract = (c) => {
    if (!onSelectContract) return;
    onSelectContract({
      isDerivative: true,
      instrument_type: 'future',
      option_type: null,
      underlying: c.underlying || c.symbol.replace('=F', ''),
      symbol: c.symbol,
      expiry_date: null,
      lot_size: c.contract_size || 50,
      market: 'US',
      price: c.ltp,
      current_price: c.ltp,
      underlying_price: c.ltp,
      notional_value: c.notional_value,
      initial_margin_required: c.initial_margin_required,
      initial_margin_pct: 12.0,
    });
  };

  return (
    <div className="w-full space-y-4 font-sans text-text-primary select-none">
      {/* Top Header & Market Toggle */}
      <div className="bg-surface border border-border px-4 py-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center space-x-3">
          <div className="flex items-center space-x-1.5 font-semibold text-xs tracking-wider uppercase text-text-primary">
            <Activity className="w-4 h-4 text-accent" />
            <span>FUTURES MARKET</span>
          </div>

          <span className="text-border">|</span>

          {/* Sub-tabs: Index Futures, Stock Futures, US Continuous Futures */}
          <div className="inline-flex p-0.5 bg-base border border-border font-mono-tabular">
            <button
              onClick={() => setActiveTab('IN_INDEX')}
              className={`px-3 py-1 text-xs font-semibold uppercase tracking-wider transition-colors ${
                activeTab === 'IN_INDEX'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              Indian Index Futures (NSE)
            </button>
            <button
              onClick={() => setActiveTab('IN_STOCK')}
              className={`px-3 py-1 text-xs font-semibold uppercase tracking-wider transition-colors ${
                activeTab === 'IN_STOCK'
                  ? 'bg-[#232731] text-accent font-bold'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              Indian Stock Futures (NSE)
            </button>
            <button
              onClick={() => setActiveTab('US_CONTINUOUS')}
              className={`px-3 py-1 text-xs font-semibold uppercase tracking-wider transition-colors ${
                activeTab === 'US_CONTINUOUS'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              US Continuous Futures (CME)
            </button>
          </div>
        </div>

        <div className="flex items-center space-x-3 font-mono-tabular text-xs">
          <span className="text-[11px] text-text-muted">
            MARGIN RULE: 12% INITIAL / 10% MAINT // DAILY CASH MTM
          </span>

          <button
            onClick={() => loadData(activeTab, selectedStock)}
            disabled={loading}
            className="p-1 hover:bg-surface-hover text-text-muted hover:text-text-primary transition-colors border border-border"
            title="Refresh futures"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Stock Search Bar & Quick Chips for Indian Stock Futures */}
      {activeTab === 'IN_STOCK' && (
        <div className="bg-surface border border-border px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 text-xs">
          {/* Search Input with Dropdown */}
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
                placeholder="Search NSE stock for futures (e.g. Reliance, TCS)..."
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
                            {item.exchange || 'NSE'}
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
            {TOP_IN_FO_STOCKS.map((stock) => (
              <button
                key={stock.symbol}
                onClick={() => {
                  setSelectedStock(stock.symbol);
                }}
                className={`px-2 py-0.5 text-xs font-mono-tabular font-medium transition-colors border ${
                  selectedStock === stock.symbol
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

      {/* Main View Area */}
      {loading && !data ? (
        <div className="p-12 text-center text-xs font-mono-tabular text-text-muted border border-border bg-surface">
          <RefreshCw className="w-5 h-5 mx-auto mb-2 animate-spin text-accent" />
          LOADING FUTURES MARKET DATA...
        </div>
      ) : error ? (
        <div className="p-8 text-center text-xs font-mono-tabular text-red border border-border bg-surface space-y-2">
          <div>ERROR LOADING FUTURES: {error}</div>
          <button
            onClick={() => loadData(activeTab, selectedStock)}
            className="px-3 py-1 bg-base border border-border text-text-primary hover:bg-[#232731]"
          >
            RETRY
          </button>
        </div>
      ) : activeTab === 'IN_INDEX' ? (
        /* Indian Index Futures by Expiry */
        <div className="space-y-4">
          {(data?.indices || []).map((idx) => {
            const sym = idx.symbol;
            const contracts = idx.contracts || [];
            const undVal = idx.underlying_value;
            const lot = idx.lot_size || (sym === 'NIFTY' ? 65 : 30);

            return (
              <div key={sym} className="border border-border bg-surface overflow-hidden">
                <div className="px-4 py-2.5 bg-[#111317] border-b border-border flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <span className="font-bold text-sm text-text-primary">{sym} FUTURES</span>
                    <span className="text-xs text-text-muted font-mono-tabular">
                      (SPOT: ₹{formatMoney(undVal, 'INR')} | LOT SIZE: {lot})
                    </span>
                  </div>
                  <span className="text-[11px] font-mono-tabular text-text-muted">
                    {contracts.length} EXPIRIES ACTIVE
                  </span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse font-mono-tabular text-xs">
                    <thead>
                      <tr className="h-8 border-b border-border text-[11px] uppercase text-text-muted font-sans font-medium bg-[#14161b]">
                        <th className="px-3">Contract</th>
                        <th className="px-3">Expiry Date</th>
                        <th className="px-3 text-right">LTP</th>
                        <th className="px-3 text-right">Basis (Fut - Spot)</th>
                        <th className="px-3 text-right">Open Interest (OI)</th>
                        <th className="px-3 text-right">Volume</th>
                        <th className="px-3 text-right">Notional / Lot</th>
                        <th className="px-3 text-right">Req. Margin (12%)</th>
                        <th className="px-3 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {contracts.map((c) => {
                        const notional = c.ltp ? Math.round(c.ltp * lot * 100) / 100 : 0;
                        const reqMargin = Math.round(notional * 0.12 * 100) / 100;

                        return (
                          <tr
                            key={c.contract}
                            className="border-b border-border/50 hover:bg-[#1a1c23] transition-colors"
                          >
                            <td className="px-3 py-2 font-bold text-text-primary">
                              {c.contract}
                            </td>
                            <td className="px-3 py-2 text-text-muted">
                              {c.expiry || '—'}
                            </td>
                            <td className="px-3 py-2 text-right font-bold text-text-primary">
                              ₹{formatMoney(c.ltp, 'INR')}
                            </td>
                            <td className="px-3 py-2 text-right">
                              {c.basis !== null && c.basis !== undefined ? (
                                <span className={c.basis >= 0 ? 'text-green font-semibold' : 'text-red font-semibold'}>
                                  {c.basis >= 0 ? `+₹${formatMoney(c.basis, 'INR')}` : `-₹${formatMoney(Math.abs(c.basis), 'INR')}`}
                                </span>
                              ) : (
                                <span className="text-text-muted">—</span>
                              )}
                            </td>
                            <td className="px-3 py-2 text-right text-text-muted">
                              {formatInt(c.oi)}
                            </td>
                            <td className="px-3 py-2 text-right text-text-muted">
                              {formatInt(c.volume_contracts)}
                            </td>
                            <td className="px-3 py-2 text-right text-text-primary">
                              ₹{formatMoney(notional, 'INR')}
                            </td>
                            <td className="px-3 py-2 text-right font-bold text-amber-400">
                              ₹{formatMoney(reqMargin, 'INR')}
                            </td>
                            <td className="px-3 py-2 text-right">
                              <button
                                onClick={() => handleTradeIndianContract(c, sym)}
                                className="px-2.5 py-1 bg-accent/15 border border-accent/40 text-accent hover:bg-accent hover:text-white font-sans text-xs uppercase font-semibold transition-colors"
                              >
                                TRADE
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })}
        </div>
      ) : activeTab === 'IN_STOCK' ? (
        /* Indian Stock Futures for Selected Equity */
        <div className="border border-border bg-surface overflow-hidden">
          <div className="px-4 py-2.5 bg-[#111317] border-b border-border flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <span className="font-bold text-sm text-text-primary">{selectedStock} STOCK FUTURES</span>
              <span className="text-xs text-text-muted font-mono-tabular">
                (SPOT: ₹{formatMoney(data?.underlying_value, 'INR')} | LOT SIZE: {data?.lot_size || 250})
              </span>
            </div>
            <span className="text-[11px] font-mono-tabular text-text-muted">
              {data?.contracts?.length || 0} EXPIRIES ACTIVE
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse font-mono-tabular text-xs">
              <thead>
                <tr className="h-8 border-b border-border text-[11px] uppercase text-text-muted font-sans font-medium bg-[#14161b]">
                  <th className="px-3">Contract</th>
                  <th className="px-3">Expiry Date</th>
                  <th className="px-3 text-right">LTP</th>
                  <th className="px-3 text-right">Basis (Fut - Spot)</th>
                  <th className="px-3 text-right">Open Interest (OI)</th>
                  <th className="px-3 text-right">Volume</th>
                  <th className="px-3 text-right">Notional / Lot</th>
                  <th className="px-3 text-right">Req. Margin (12%)</th>
                  <th className="px-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {(data?.contracts || []).map((c) => {
                  const lot = c.lot_size || data?.lot_size || 250;
                  const notional = c.ltp ? Math.round(c.ltp * lot * 100) / 100 : 0;
                  const reqMargin = Math.round(notional * 0.12 * 100) / 100;

                  return (
                    <tr
                      key={c.contract}
                      className="border-b border-border/50 hover:bg-[#1a1c23] transition-colors"
                    >
                      <td className="px-3 py-2 font-bold text-text-primary">
                        {c.contract}
                      </td>
                      <td className="px-3 py-2 text-text-muted">
                        {c.expiry || '—'}
                      </td>
                      <td className="px-3 py-2 text-right font-bold text-text-primary">
                        ₹{formatMoney(c.ltp, 'INR')}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {c.basis !== null && c.basis !== undefined ? (
                          <span className={c.basis >= 0 ? 'text-green font-semibold' : 'text-red font-semibold'}>
                            {c.basis >= 0 ? `+₹${formatMoney(c.basis, 'INR')}` : `-₹${formatMoney(Math.abs(c.basis), 'INR')}`}
                          </span>
                        ) : (
                          <span className="text-text-muted">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right text-text-muted">
                        {formatInt(c.oi)}
                      </td>
                      <td className="px-3 py-2 text-right text-text-muted">
                        {formatInt(c.volume_contracts)}
                      </td>
                      <td className="px-3 py-2 text-right text-text-primary">
                        ₹{formatMoney(notional, 'INR')}
                      </td>
                      <td className="px-3 py-2 text-right font-bold text-amber-400">
                        ₹{formatMoney(reqMargin, 'INR')}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          onClick={() => handleTradeIndianContract(c, selectedStock)}
                          className="px-2.5 py-1 bg-accent/15 border border-accent/40 text-accent hover:bg-accent hover:text-white font-sans text-xs uppercase font-semibold transition-colors"
                        >
                          TRADE
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        /* US Continuous Futures */
        <div className="border border-border bg-surface overflow-hidden">
          <div className="px-4 py-2.5 bg-[#111317] border-b border-border flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <span className="font-bold text-sm text-text-primary">CME CONTINUOUS / PERPETUAL FUTURES</span>
              <span className="text-xs text-text-muted font-mono-tabular">
                (NO FORCED EXPIRY — DAILY CASH MTM)
              </span>
            </div>
            <span className="text-[11px] font-mono-tabular text-text-muted">
              4 BENCHMARK CONTRACTS
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse font-mono-tabular text-xs">
              <thead>
                <tr className="h-8 border-b border-border text-[11px] uppercase text-text-muted font-sans font-medium bg-[#14161b]">
                  <th className="px-3">Contract</th>
                  <th className="px-3">Description</th>
                  <th className="px-3 text-right">LTP</th>
                  <th className="px-3 text-right">Change (24h)</th>
                  <th className="px-3 text-right">Multiplier</th>
                  <th className="px-3 text-right">Notional / Lot</th>
                  <th className="px-3 text-right">Req. Margin (12%)</th>
                  <th className="px-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {(data?.contracts || []).map((c) => {
                  const chgColor = c.change_pct > 0 ? 'text-green' : c.change_pct < 0 ? 'text-red' : 'text-text-muted';

                  return (
                    <tr
                      key={c.symbol}
                      className="border-b border-border/50 hover:bg-[#1a1c23] transition-colors"
                    >
                      <td className="px-3 py-2.5 font-bold text-accent">
                        {c.symbol}
                      </td>
                      <td className="px-3 py-2.5 text-text-primary font-sans font-medium">
                        {c.name}
                      </td>
                      <td className="px-3 py-2.5 text-right font-bold text-text-primary">
                        ${formatMoney(c.ltp, 'USD')}
                      </td>
                      <td className={`px-3 py-2.5 text-right font-semibold ${chgColor}`}>
                        {c.change_pct > 0 ? `+${c.change_pct.toFixed(2)}%` : `${c.change_pct.toFixed(2)}%`}
                      </td>
                      <td className="px-3 py-2.5 text-right text-text-muted">
                        {c.multiplier || c.contract_size}x
                      </td>
                      <td className="px-3 py-2.5 text-right text-text-primary">
                        ${formatMoney(c.notional_value, 'USD')}
                      </td>
                      <td className="px-3 py-2.5 text-right font-bold text-amber-400">
                        ${formatMoney(c.initial_margin_required, 'USD')}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <button
                          onClick={() => handleTradeUSContract(c)}
                          className="px-2.5 py-1 bg-accent/15 border border-accent/40 text-accent hover:bg-accent hover:text-white font-sans text-xs uppercase font-semibold transition-colors"
                        >
                          TRADE
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
