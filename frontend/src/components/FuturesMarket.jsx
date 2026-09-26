import React, { useState, useEffect, useCallback } from 'react';
import { RefreshCw, TrendingUp, TrendingDown, Activity, ShieldCheck, DollarSign } from 'lucide-react';
import { fetchFuturesMarket } from '../api/client';

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

export function FuturesMarket({
  defaultMarket = 'IN',
  onSelectContract,
  wallet,
}) {
  const [activeMarket, setActiveMarket] = useState(defaultMarket);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setActiveMarket(defaultMarket);
  }, [defaultMarket]);

  const loadData = useCallback(async (mkt) => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetchFuturesMarket(mkt);
      setData(res);
    } catch (err) {
      setError(err.message || 'Failed to fetch futures data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData(activeMarket);
  }, [activeMarket, loadData]);

  const handleTradeIndianContract = (c, indexSymbol) => {
    if (!onSelectContract) return;
    onSelectContract({
      isDerivative: true,
      instrument_type: 'future',
      option_type: null,
      underlying: indexSymbol,
      symbol: c.contract,
      expiry_date: c.expiry,
      lot_size: c.lot_size || (indexSymbol === 'NIFTY' ? 65 : 30),
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

          {/* Sub-tabs: Indian Index Futures vs US Continuous Futures */}
          <div className="inline-flex p-0.5 bg-base border border-border font-mono-tabular">
            <button
              onClick={() => setActiveMarket('IN')}
              className={`px-3 py-1 text-xs font-semibold uppercase tracking-wider transition-colors ${
                activeMarket === 'IN'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              Indian Index Futures (NSE)
            </button>
            <button
              onClick={() => setActiveMarket('US')}
              className={`px-3 py-1 text-xs font-semibold uppercase tracking-wider transition-colors ${
                activeMarket === 'US'
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
            onClick={() => loadData(activeMarket)}
            disabled={loading}
            className="p-1 hover:bg-surface-hover text-text-muted hover:text-text-primary transition-colors border border-border"
            title="Refresh futures"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

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
            onClick={() => loadData(activeMarket)}
            className="px-3 py-1 bg-base border border-border text-text-primary hover:bg-[#232731]"
          >
            RETRY
          </button>
        </div>
      ) : activeMarket === 'IN' ? (
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
                        const notional = c.ltp ? roundVal(c.ltp * lot) : 0;
                        const reqMargin = roundVal(notional * 0.12);
                        const basisPositive = c.basis !== null && c.basis > 0;

                        return (
                          <tr
                            key={c.contract || c.expiry}
                            className="border-b border-border hover:bg-surface-hover transition-colors"
                          >
                            <td className="px-3 py-2 font-bold text-text-primary">{c.contract}</td>
                            <td className="px-3 py-2 text-text-muted">{c.expiry}</td>
                            <td className="px-3 py-2 text-right font-bold text-text-primary">
                              ₹{formatMoney(c.ltp, 'INR')}
                            </td>
                            <td className={`px-3 py-2 text-right font-bold ${
                              basisPositive ? 'text-green' : c.basis < 0 ? 'text-red' : 'text-text-muted'
                            }`}>
                              {c.basis !== null ? `${basisPositive ? '+' : ''}₹${formatMoney(c.basis, 'INR')}` : '—'}
                            </td>
                            <td className="px-3 py-2 text-right text-text-muted">{formatInt(c.oi)}</td>
                            <td className="px-3 py-2 text-right text-text-muted">{formatInt(c.volume_contracts)}</td>
                            <td className="px-3 py-2 text-right text-text-muted">₹{formatMoney(notional, 'INR')}</td>
                            <td className="px-3 py-2 text-right font-bold text-amber-400">₹{formatMoney(reqMargin, 'INR')}</td>
                            <td className="px-3 py-2 text-right">
                              <button
                                onClick={() => handleTradeIndianContract(c, sym)}
                                className="px-3 py-1 bg-accent hover:bg-accent/90 text-white font-sans text-xs uppercase font-semibold transition-colors"
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
      ) : (
        /* US Continuous Futures */
        <div className="border border-border bg-surface overflow-hidden">
          <div className="px-4 py-2.5 bg-[#111317] border-b border-border flex items-center justify-between">
            <span className="font-bold text-sm text-text-primary">
              CME / NYMEX CONTINUOUS FUTURES (PERPETUAL WITH DAILY MTM)
            </span>
            <span className="text-[11px] font-mono-tabular text-text-muted">
              INSTANT LIQUIDITY // 12% INITIAL MARGIN
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse font-mono-tabular text-xs">
              <thead>
                <tr className="h-8 border-b border-border text-[11px] uppercase text-text-muted font-sans font-medium bg-[#14161b]">
                  <th className="px-3">Symbol</th>
                  <th className="px-3">Contract Name</th>
                  <th className="px-3 text-right">LTP</th>
                  <th className="px-3 text-right">24h Chg%</th>
                  <th className="px-3 text-right">Multiplier</th>
                  <th className="px-3 text-right">Notional Value</th>
                  <th className="px-3 text-right">Initial Margin (12%)</th>
                  <th className="px-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {(data?.contracts || []).map((c) => {
                  const chgPct = c.change_pct || 0;
                  return (
                    <tr
                      key={c.symbol}
                      className="border-b border-border hover:bg-surface-hover transition-colors"
                    >
                      <td className="px-3 py-2.5 font-bold text-text-primary text-sm">{c.symbol}</td>
                      <td className="px-3 py-2.5 text-text-muted">{c.name}</td>
                      <td className="px-3 py-2.5 text-right font-bold text-text-primary">
                        ${formatMoney(c.ltp, 'USD')}
                      </td>
                      <td className={`px-3 py-2.5 text-right font-bold ${
                        chgPct > 0 ? 'text-green' : chgPct < 0 ? 'text-red' : 'text-text-muted'
                      }`}>
                        {chgPct > 0 ? `+${chgPct.toFixed(2)}%` : `${chgPct.toFixed(2)}%`}
                      </td>
                      <td className="px-3 py-2.5 text-right text-text-muted">{c.contract_size}x</td>
                      <td className="px-3 py-2.5 text-right text-text-muted font-medium">
                        ${formatMoney(c.notional_value, 'USD')}
                      </td>
                      <td className="px-3 py-2.5 text-right font-bold text-amber-400">
                        ${formatMoney(c.initial_margin_required, 'USD')}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <button
                          onClick={() => handleTradeUSContract(c)}
                          className="px-3 py-1 bg-accent hover:bg-accent/90 text-white font-sans text-xs uppercase font-semibold transition-colors"
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

function roundVal(n) {
  return Number(Number(n).toFixed(2));
}
