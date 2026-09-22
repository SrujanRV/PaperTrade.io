import React, { useState, useEffect, useCallback } from 'react';
import { BarChart2 } from 'lucide-react';
import { fetchWalletSummary } from '../api/client';

function formatMoney(amount, currency) {
  if (amount === undefined || amount === null || isNaN(amount)) return '0.00';
  const locale = currency === 'INR' ? 'en-IN' : 'en-US';
  return Number(amount).toLocaleString(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatSignedMoney(amount, currency) {
  if (amount === undefined || amount === null || isNaN(amount)) return '0.00';
  const num = Number(amount);
  const sign = num > 0 ? '+' : num < 0 ? '-' : '';
  const abs = Math.abs(num);
  const locale = currency === 'INR' ? 'en-IN' : 'en-US';
  return `${sign}${abs.toLocaleString(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatSignedPct(pct) {
  if (pct === undefined || pct === null || isNaN(pct)) return '0.00%';
  const num = Number(pct);
  const sign = num > 0 ? '+' : '';
  return `${sign}${num.toFixed(2)}%`;
}

export function Portfolio({
  selectedMarket = 'IN',
  onSelectMarket,
  onSelectTicker,
  onOpenChart,
  onGoToWatchlist,
  onOpenWalletSetup,
  livePrices = {},
  refreshKey = 0,
}) {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const currency = selectedMarket === 'IN' ? 'INR' : 'USD';
  const currencySymbol = selectedMarket === 'IN' ? '₹' : '$';

  // Fetch summary from backend
  const loadSummary = useCallback(async () => {
    try {
      setError(null);
      const data = await fetchWalletSummary(selectedMarket);
      setSummary(data);
    } catch (err) {
      setError(err.message || 'Failed to load portfolio summary');
    } finally {
      setLoading(false);
    }
  }, [selectedMarket]);

  useEffect(() => {
    setLoading(true);
    loadSummary();
  }, [loadSummary, refreshKey]);

  const holdings = summary?.holdings || [];

  // Compute live values overlaying SSE prices onto holdings
  let totalHoldingsValue = 0;
  let totalUnrealizedPnL = 0;

  const liveHoldings = holdings.map((h) => {
    const liveQuote = livePrices[h.ticker.toUpperCase()];
    const currentPrice = liveQuote ? liveQuote.current_price : h.current_price;
    const costBasis = Number((h.avg_buy_price * h.quantity).toFixed(2));
    const currentValue = Number((currentPrice * h.quantity).toFixed(2));
    const unrealizedPnL = Number((currentValue - costBasis).toFixed(2));
    const unrealizedPnLPct =
      costBasis > 0 ? (unrealizedPnL / costBasis) * 100 : 0;

    totalHoldingsValue += currentValue;
    totalUnrealizedPnL += unrealizedPnL;

    return {
      ...h,
      current_price: currentPrice,
      current_value: currentValue,
      unrealized_pnl: unrealizedPnL,
      unrealized_pnl_pct: unrealizedPnLPct,
      tickDirection: liveQuote?.tickDirection || 'none',
      tickId: liveQuote?.tickId || 0,
    };
  });

  const cashBalance = summary?.cash_balance ?? 0;
  const totalWalletValue = Number((cashBalance + totalHoldingsValue).toFixed(2));
  const totalRealizedPnL = summary?.total_realized_pnl ?? 0;

  return (
    <div className="w-full max-w-6xl space-y-4 text-text-primary select-none">
      {/* Top Bar: Market Selector (IN vs US) & Status */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-surface border border-border px-4 py-2.5">
        <div className="flex items-center space-x-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-text-primary">
            Portfolio View
          </span>
          <span className="text-border">|</span>
          {/* Segmented Market Selector */}
          <div className="inline-flex p-0.5 bg-base border border-border font-mono-tabular">
            <button
              onClick={() => onSelectMarket('IN')}
              className={`px-3 py-1 text-xs font-semibold uppercase tracking-wider transition-colors ${
                selectedMarket === 'IN'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              Indian Market (INR)
            </button>
            <button
              onClick={() => onSelectMarket('US')}
              className={`px-3 py-1 text-xs font-semibold uppercase tracking-wider transition-colors ${
                selectedMarket === 'US'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              US Market (USD)
            </button>
          </div>
        </div>

        <div className="text-[11px] font-mono-tabular text-text-muted">
          <span>SOURCE: /api/wallet/{selectedMarket}/summary</span>
        </div>
      </div>

      {/* Summary Metrics Banner */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 font-mono-tabular">
        {/* Total Wallet Value */}
        <div className="p-3 bg-surface border border-border">
          <div className="text-[10px] text-text-muted uppercase font-sans tracking-wider">
            Total Wallet Value
          </div>
          <div className="text-base font-semibold text-text-primary mt-1">
            {summary ? `${currencySymbol}${formatMoney(totalWalletValue, currency)}` : '—'}
          </div>
          <div className="text-[10px] text-text-muted mt-0.5">
            {summary ? 'Cash + Holdings' : 'Wallet uninitialized'}
          </div>
        </div>

        {/* Available Cash */}
        <div className="p-3 bg-surface border border-border">
          <div className="text-[10px] text-text-muted uppercase font-sans tracking-wider">
            Available Cash
          </div>
          <div className="text-base font-semibold text-text-primary mt-1">
            {summary ? `${currencySymbol}${formatMoney(cashBalance, currency)}` : '—'}
          </div>
          <div className="text-[10px] text-text-muted mt-0.5">
            {summary ? 'Ready to trade' : 'No balance set'}
          </div>
        </div>

        {/* Total Unrealized P&L */}
        <div className="p-3 bg-surface border border-border">
          <div className="text-[10px] text-text-muted uppercase font-sans tracking-wider">
            Unrealized P&L
          </div>
          <div
            className={`text-base font-semibold mt-1 ${
              !summary
                ? 'text-text-muted'
                : totalUnrealizedPnL > 0
                ? 'text-green'
                : totalUnrealizedPnL < 0
                ? 'text-red'
                : 'text-text-primary'
            }`}
          >
            {summary ? `${currencySymbol}${formatSignedMoney(totalUnrealizedPnL, currency)}` : '—'}
          </div>
          <div className="text-[10px] text-text-muted mt-0.5">
            {summary
              ? `Holdings value: ${currencySymbol}${formatMoney(totalHoldingsValue, currency)}`
              : 'No open holdings'}
          </div>
        </div>

        {/* Total Realized P&L */}
        <div className="p-3 bg-surface border border-border">
          <div className="text-[10px] text-text-muted uppercase font-sans tracking-wider">
            Realized P&L (All-Time)
          </div>
          <div
            className={`text-base font-semibold mt-1 ${
              !summary
                ? 'text-text-muted'
                : totalRealizedPnL > 0
                ? 'text-green'
                : totalRealizedPnL < 0
                ? 'text-red'
                : 'text-text-primary'
            }`}
          >
            {summary ? `${currencySymbol}${formatSignedMoney(totalRealizedPnL, currency)}` : '—'}
          </div>
          <div className="text-[10px] text-text-muted mt-0.5">
            {summary ? 'From closed sales' : 'No trade history'}
          </div>
        </div>
      </div>

      {/* Holdings Table or Empty State */}
      <div className="bg-surface border border-border overflow-hidden">
        {/* Table Subheader */}
        <div className="h-9 px-3 bg-[#111317] border-b border-border flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-text-primary">
            Open Positions ({summary ? liveHoldings.length : 0})
          </span>
          <span className="text-[11px] font-mono-tabular text-text-muted">
            LIVE UNREALIZED P&L TRACKING
          </span>
        </div>

        {!summary ? (
          /* Uninitialized Wallet State */
          <div className="p-10 text-center space-y-4 font-mono-tabular">
            <div className="flex items-center justify-center space-x-2 text-xs text-text-muted">
              <span className="w-1.5 h-1.5 rounded-full bg-accent" />
              <span>
                NO {selectedMarket === 'IN' ? 'INDIAN' : 'US'} WALLET INITIALIZED — Set up your paper balance to begin investing
              </span>
            </div>
            {onOpenWalletSetup && (
              <button
                type="button"
                onClick={() => onOpenWalletSetup(selectedMarket)}
                className="px-4 py-1.5 bg-accent hover:bg-accent/90 text-white text-xs uppercase tracking-wider font-sans font-semibold transition-colors"
              >
                INITIALIZE {selectedMarket} WALLET
              </button>
            )}
          </div>
        ) : liveHoldings.length === 0 ? (
          /* Empty Positions State */
          <div className="p-10 text-center space-y-3 font-mono-tabular">
            <div className="flex items-center justify-center space-x-2 text-xs text-text-muted">
              <span className="w-1.5 h-1.5 rounded-full bg-text-muted" />
              <span>
                NO OPEN POSITIONS — place your first order from the watchlist
              </span>
            </div>
            {onGoToWatchlist && (
              <button
                onClick={onGoToWatchlist}
                className="px-4 py-1.5 bg-[#232731] hover:bg-border text-xs text-text-primary uppercase tracking-wider font-sans font-semibold transition-colors"
              >
                Go to Watchlist
              </button>
            )}
          </div>
        ) : (
          /* Positions Table */
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse font-mono-tabular">
              <thead>
                <tr className="h-8 border-b border-border text-[11px] uppercase text-text-muted font-sans font-medium select-none bg-[#0f1014]">
                  <th className="px-3 font-medium">Symbol</th>
                  <th className="px-3 text-right font-medium">Qty</th>
                  <th className="px-3 text-right font-medium">Avg Buy Price</th>
                  <th className="px-3 text-right font-medium">Current Price</th>
                  <th className="px-3 text-right font-medium">Market Value</th>
                  <th className="px-3 text-right font-medium">Unrealized P&L</th>
                  <th className="px-3 text-right font-medium">Action</th>
                </tr>
              </thead>
              <tbody>
                {liveHoldings.map((h) => {
                  const pnlColor =
                    h.unrealized_pnl > 0
                      ? 'text-green'
                      : h.unrealized_pnl < 0
                      ? 'text-red'
                      : 'text-text-muted';

                  const tickClass =
                    h.tickDirection === 'up'
                      ? 'animate-tick-up'
                      : h.tickDirection === 'down'
                      ? 'animate-tick-down'
                      : '';

                  return (
                    <tr
                      key={h.id || h.ticker}
                      className="min-h-[40px] border-b border-border hover:bg-surface-hover transition-colors text-xs"
                    >
                      {/* Symbol + Square-Off Badge */}
                      <td className="px-3 py-1.5 align-middle">
                        <div className="flex flex-col">
                          <span className="font-semibold text-text-primary leading-tight">
                            {h.ticker}
                          </span>
                          {h.square_off_date && (
                            <div className="mt-0.5 flex items-center">
                              {(() => {
                                const isToday = h.is_intraday || h.square_off_date <= new Date().toISOString().split('T')[0];
                                const hasPartial = h.square_off_quantity && h.square_off_quantity < h.quantity;
                                const dateStr = new Date(h.square_off_date + 'T00:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short' }).toUpperCase();
                                const label = isToday
                                  ? (hasPartial ? `AUTO SQ-OFF: ${h.square_off_quantity} SHS TODAY` : 'AUTO SQ-OFF: TODAY (CLOSE)')
                                  : (hasPartial ? `SQ-OFF: ${h.square_off_quantity} SHS (${dateStr})` : `SQ-OFF: ${dateStr}`);
                                return (
                                  <span className={`px-1.5 py-0.2 rounded text-[9px] font-mono-tabular font-bold tracking-wider uppercase border ${
                                    isToday
                                      ? 'bg-accent/15 text-accent border-accent/40'
                                      : 'bg-purple-900/30 text-purple-300 border-purple-500/40'
                                  }`}>
                                    {label}
                                  </span>
                                );
                              })()}
                            </div>
                          )}
                        </div>
                      </td>

                      {/* Quantity */}
                      <td className="px-3 py-0 text-right align-middle text-text-primary">
                        {h.quantity}
                      </td>

                      {/* Avg Buy Price */}
                      <td className="px-3 py-0 text-right align-middle text-text-primary font-medium">
                        {currencySymbol}
                        {formatMoney(h.avg_buy_price, currency)}
                      </td>

                      {/* Current Live Price (with tick flash) */}
                      <td className="px-3 py-0 text-right align-middle">
                        <span
                          key={`${h.ticker}-${h.tickId}`}
                          className={`inline-block px-1 py-0.5 rounded-sm ${tickClass} text-text-primary`}
                        >
                          {currencySymbol}
                          {formatMoney(h.current_price, currency)}
                        </span>
                      </td>

                      {/* Current Market Value */}
                      <td className="px-3 py-0 text-right align-middle text-text-primary font-medium">
                        {currencySymbol}
                        {formatMoney(h.current_value, currency)}
                      </td>

                      {/* Unrealized P&L (amount + %) */}
                      <td className="px-3 py-0 text-right align-middle">
                        <span className={`font-semibold ${pnlColor}`}>
                          {currencySymbol}
                          {formatSignedMoney(h.unrealized_pnl, currency)}{' '}
                          <span className="text-[11px] font-normal">
                            ({formatSignedPct(h.unrealized_pnl_pct)})
                          </span>
                        </span>
                      </td>

                      {/* Trade Action */}
                      <td className="px-3 py-0 text-right align-middle">
                        <div className="flex items-center justify-end space-x-1.5">
                          <button
                            type="button"
                            onClick={() => onOpenChart && onOpenChart(h.ticker)}
                            title={`Open candlestick chart for ${h.ticker}`}
                            className="p-1 text-text-muted hover:text-accent hover:bg-base border border-transparent hover:border-border transition-colors flex items-center justify-center"
                          >
                            <BarChart2 size={13} />
                          </button>
                          <button
                            onClick={() => onSelectTicker && onSelectTicker(h.ticker)}
                            className="px-2 py-1 bg-base border border-border text-[10px] text-text-primary hover:border-accent hover:text-white uppercase font-sans font-medium transition-colors"
                          >
                            TRADE
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Footer */}
        <div className="h-7 px-3 bg-[#0d0e12] border-t border-border flex items-center justify-between text-[11px] text-text-muted font-mono-tabular select-none">
          <span>PORTFOLIO VALUATION ENGINE</span>
          <span>WEIGHTED AVERAGE COST BASIS</span>
        </div>
      </div>
    </div>
  );
}
