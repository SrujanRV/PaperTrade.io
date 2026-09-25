import React, { useState, useEffect, useCallback } from 'react';
import { fetchTrades } from '../api/client';

function formatMoney(value, currency) {
  if (value === undefined || value === null || isNaN(value)) return '—';
  const locale = currency === 'INR' ? 'en-IN' : 'en-US';
  return Number(value).toLocaleString(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatDate(isoString) {
  if (!isoString) return '—';
  try {
    const d = new Date(isoString);
    return d.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
  } catch {
    return isoString;
  }
}

export function TradeLog({
  selectedMarket,
  wallet,
  onSelectMarket,
  onGoToWatchlist,
  onGoToPortfolio,
  onOpenWalletSetup,
  refreshKey,
}) {
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const currency = selectedMarket === 'IN' ? 'INR' : 'USD';
  const currencySymbol = selectedMarket === 'IN' ? '₹' : '$';

  const loadTrades = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchTrades(selectedMarket);
      setTrades(data);
    } catch (err) {
      console.error('Error fetching trade log:', err);
      setError(err.message || 'Failed to load trade log');
    } finally {
      setLoading(false);
    }
  }, [selectedMarket]);

  useEffect(() => {
    loadTrades();
  }, [loadTrades, refreshKey]);

  // Aggregate metrics
  const totalTrades = trades.length;
  const totalRealizedPnL = trades.reduce((sum, t) => sum + (t.realized_pnl || 0), 0);
  const totalProceeds = trades.reduce((sum, t) => sum + (t.total_value || 0), 0);
  const winCount = trades.filter((t) => (t.realized_pnl || 0) > 0).length;
  const lossCount = trades.filter((t) => (t.realized_pnl || 0) < 0).length;
  const winRate = totalTrades > 0 ? ((winCount / totalTrades) * 100).toFixed(1) : '0.0';

  return (
    <div className="w-full space-y-4">
      {/* View Header & Market Switcher */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 select-none">
        <div className="flex items-center space-x-2">
          {/* Market Selector Pill */}
          <div className="inline-flex p-0.5 bg-surface border border-border font-mono-tabular text-xs">
            <button
              onClick={() => onSelectMarket('IN')}
              className={`px-3 py-1 font-semibold uppercase tracking-wider transition-colors ${
                selectedMarket === 'IN'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              IN (INR)
            </button>
            <button
              onClick={() => onSelectMarket('US')}
              className={`px-3 py-1 font-semibold uppercase tracking-wider transition-colors ${
                selectedMarket === 'US'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              US (USD)
            </button>
          </div>

          <span className="text-[11px] font-mono-tabular text-text-muted">
            // CLOSED ROUND-TRIP TRADES
          </span>
        </div>

        <div className="text-[11px] font-mono-tabular text-text-muted">
          <span>STATUS: IMMUTABLE AUDIT LOG</span>
        </div>
      </div>

      {/* Summary Metrics Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {/* Total Closed Trades */}
        <div className="bg-surface border border-border p-3 font-mono-tabular">
          <div className="text-[10px] text-text-muted uppercase tracking-wider">
            Closed Trades
          </div>
          <div className="text-xl font-bold text-text-primary mt-1">
            {totalTrades}
          </div>
          <div className="text-[10px] text-text-muted mt-0.5">
            Round-trip sell executions
          </div>
        </div>

        {/* Total Realized P&L */}
        <div className="bg-surface border border-border p-3 font-mono-tabular">
          <div className="text-[10px] text-text-muted uppercase tracking-wider">
            Total Realized P&L
          </div>
          <div
            className={`text-xl font-bold mt-1 ${
              totalRealizedPnL > 0
                ? 'text-green'
                : totalRealizedPnL < 0
                ? 'text-red'
                : 'text-text-primary'
            }`}
          >
            {totalRealizedPnL > 0 ? '+' : ''}
            {currencySymbol}
            {formatMoney(totalRealizedPnL, currency)}
          </div>
          <div className="text-[10px] text-text-muted mt-0.5">
            Proceeds: {currencySymbol}{formatMoney(totalProceeds, currency)}
          </div>
        </div>

        {/* Win Rate */}
        <div className="bg-surface border border-border p-3 font-mono-tabular">
          <div className="text-[10px] text-text-muted uppercase tracking-wider">
            Win Rate
          </div>
          <div className="text-xl font-bold text-text-primary mt-1">
            {winRate}%
          </div>
          <div className="text-[10px] text-text-muted mt-0.5">
            {winCount} WIN &middot; {lossCount} LOSS
          </div>
        </div>
      </div>

      {/* Trades Table */}
      <div className="bg-surface border border-border overflow-hidden">
        <div className="h-10 px-3 bg-[#111317] border-b border-border flex items-center justify-between select-none">
          <div className="flex items-center space-x-2">
            <span className="text-xs font-semibold tracking-wider text-text-primary uppercase">
              Closed Trades Ledger ({selectedMarket})
            </span>
            <span className="text-[11px] font-mono-tabular text-text-muted px-1.5 py-0.5 bg-base border border-border">
              {trades.length} CLOSED
            </span>
          </div>

          <div className="text-[11px] font-mono-tabular text-text-muted">
            FIFO / WEIGHTED-AVG COST BASIS
          </div>
        </div>

        {loading ? (
          <div className="p-8 text-center text-xs font-mono-tabular text-text-muted">
            LOADING CLOSED TRADES...
          </div>
        ) : error ? (
          <div className="p-6 text-center text-xs font-mono-tabular text-red">
            ERROR: {error}
          </div>
        ) : !wallet ? (
          /* Uninitialized Wallet State */
          <div className="p-8 text-center space-y-3 font-mono-tabular">
            <p className="text-xs text-text-muted uppercase tracking-wide">
              NO {selectedMarket === 'IN' ? 'INDIAN' : 'US'} WALLET INITIALIZED — Set up your paper trading balance to begin recording trades.
            </p>
            {onOpenWalletSetup && (
              <div className="pt-2">
                <button
                  type="button"
                  onClick={() => onOpenWalletSetup(selectedMarket)}
                  className="px-4 py-1.5 bg-accent hover:bg-accent/90 text-white text-xs uppercase font-semibold transition-colors"
                >
                  INITIALIZE {selectedMarket} WALLET
                </button>
              </div>
            )}
          </div>
        ) : trades.length === 0 ? (
          <div className="p-8 text-center space-y-3 font-mono-tabular">
            <p className="text-xs text-text-muted uppercase tracking-wide">
              NO CLOSED TRADES RECORDED — Sell holdings from your portfolio to realize P&L and log closed positions.
            </p>
            <div className="flex items-center justify-center space-x-3 pt-2">
              {onGoToPortfolio && (
                <button
                  onClick={onGoToPortfolio}
                  className="px-3 py-1.5 bg-[#232731] hover:bg-[#2c3240] text-text-primary text-xs uppercase font-medium border border-border transition-colors"
                >
                  VIEW PORTFOLIO
                </button>
              )}
              {onGoToWatchlist && (
                <button
                  onClick={onGoToWatchlist}
                  className="px-3 py-1.5 bg-transparent hover:bg-surface-hover text-text-muted hover:text-text-primary text-xs uppercase font-medium border border-border transition-colors"
                >
                  GO TO WATCHLIST
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="h-8 border-b border-border text-[11px] uppercase text-text-muted font-medium select-none bg-[#0f1014]">
                  <th className="px-3 font-medium">Timestamp (UTC)</th>
                  <th className="px-3 font-medium">Symbol</th>
                  <th className="px-3 text-right font-medium">Qty Closed</th>
                  <th className="px-3 text-right font-medium">Entry Price</th>
                  <th className="px-3 text-right font-medium">Exit Price</th>
                  <th className="px-3 text-right font-medium">Realized P&L</th>
                  <th className="px-3 text-right font-medium">Value</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => {
                  const isPositive = (t.realized_pnl || 0) > 0;
                  const isNegative = (t.realized_pnl || 0) < 0;
                  const pnlColor = isPositive
                    ? 'text-green'
                    : isNegative
                    ? 'text-red'
                    : 'text-text-primary';

                  const upper = t.ticker.toUpperCase();
                  const isIndian = upper.endsWith('.NS') || upper.endsWith('.BO');
                  const displaySymbol = isIndian ? upper.replace(/\.(NS|BO)$/, '') : upper;
                  const suffix = isIndian ? upper.substring(upper.indexOf('.')) : '';

                  const pnlSign = isPositive ? '+' : '';
                  const pnlPctFormatted = t.realized_pnl_percent !== undefined
                    ? `${pnlSign}${t.realized_pnl_percent.toFixed(2)}%`
                    : '';

                  // For Long: entry is buy_p, exit is sell_p. For Short: entry is sell_p, exit is buy_p (cover)
                  const entryPrice = t.is_short ? t.sell_price : t.avg_buy_price;
                  const exitPrice = t.is_short ? t.avg_buy_price : t.sell_price;

                  return (
                    <tr
                      key={t.id}
                      className="h-[38px] border-b border-border hover:bg-surface-hover transition-colors font-mono-tabular"
                    >
                      {/* Timestamp */}
                      <td className="px-3 py-0 align-middle text-[11px] text-text-muted whitespace-nowrap">
                        {formatDate(t.timestamp)}
                      </td>

                      {/* Symbol */}
                      <td className="px-3 py-0 align-middle">
                        <div className="flex items-center space-x-1.5">
                          <span className="text-xs font-semibold text-text-primary">
                            {displaySymbol}
                          </span>
                          {suffix && (
                            <span className="text-[10px] text-text-muted">
                              {suffix}
                            </span>
                          )}
                          {t.is_short && (
                            <span className="px-1.5 py-0.2 bg-red/15 border border-red/40 text-red text-[9px] font-bold tracking-wider rounded font-mono-tabular">
                              SHORT
                            </span>
                          )}
                          {t.triggered_by === 'auto_square_off' && (
                            <span className="px-1.5 py-0.2 bg-purple-900/40 border border-purple-500/50 text-purple-300 text-[9px] font-bold tracking-wider rounded font-mono-tabular">
                              AUTO
                            </span>
                          )}
                          {t.triggered_by === 'margin_call_liquidation' && (
                            <span className="px-1.5 py-0.2 bg-red/20 border border-red/60 text-red text-[9px] font-bold tracking-wider rounded font-mono-tabular">
                              MARGIN CALL
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Quantity Closed */}
                      <td className="px-3 py-0 text-right align-middle text-xs font-medium text-text-primary">
                        {t.quantity}
                      </td>

                      {/* Entry Price */}
                      <td className="px-3 py-0 text-right align-middle text-xs font-medium text-text-primary">
                        {currencySymbol}
                        {formatMoney(entryPrice, currency)}
                      </td>

                      {/* Exit Price */}
                      <td className="px-3 py-0 text-right align-middle text-xs font-medium text-text-primary">
                        {currencySymbol}
                        {formatMoney(exitPrice, currency)}
                      </td>

                      {/* Realized P&L (Value + %) */}
                      <td className="px-3 py-0 text-right align-middle">
                        <div className={`text-xs font-medium ${pnlColor}`}>
                          <span>
                            {pnlSign}{currencySymbol}{formatMoney(t.realized_pnl, currency)}
                          </span>
                          {pnlPctFormatted && (
                            <span className="text-[10px] ml-1 opacity-90">
                              ({pnlPctFormatted})
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Proceeds / Total Value */}
                      <td className="px-3 py-0 text-right align-middle text-xs text-text-primary">
                        {currencySymbol}
                        {formatMoney(t.total_value, currency)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Footer Info */}
        <div className="h-7 px-3 bg-[#0d0e12] border-t border-border flex items-center justify-between text-[11px] text-text-muted font-mono-tabular select-none">
          <span>TRANSACTION LOG // REALIZED P&L</span>
          <span>PAPERTRADE TERMINAL v0.2</span>
        </div>
      </div>
    </div>
  );
}
