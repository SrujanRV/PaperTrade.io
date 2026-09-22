import React, { useState, useEffect, useCallback } from 'react';
import { fetchOrders } from '../api/client';

function formatDate(dateStr) {
  if (!dateStr) return '—';
  try {
    const d = new Date(dateStr);
    return d.toISOString().replace('T', ' ').substring(0, 19);
  } catch {
    return dateStr;
  }
}

function formatMoney(amount, currency) {
  if (amount === undefined || amount === null || isNaN(amount)) return '—';
  const locale = currency === 'INR' ? 'en-IN' : 'en-US';
  return Number(amount).toLocaleString(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatRejectReason(reason) {
  if (!reason) return '—';
  const map = {
    market_closed: 'Market closed',
    insufficient_funds: 'Insufficient cash balance',
    insufficient_holdings: 'Insufficient shares owned',
    invalid_ticker: 'Unresolvable symbol',
    wrong_market: 'Wrong market wallet',
  };
  return map[reason] || reason;
}

export function OrderHistory({
  selectedMarket = 'IN',
  wallet,
  onSelectMarket,
  onGoToWatchlist,
  onOpenWalletSetup,
  refreshKey = 0,
}) {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const currency = selectedMarket === 'IN' ? 'INR' : 'USD';
  const currencySymbol = selectedMarket === 'IN' ? '₹' : '$';

  const loadOrders = useCallback(async () => {
    try {
      setError(null);
      const data = await fetchOrders(selectedMarket);
      setOrders(data || []);
    } catch (err) {
      setError(err.message || 'Failed to load order history');
    } finally {
      setLoading(false);
    }
  }, [selectedMarket]);

  useEffect(() => {
    setLoading(true);
    loadOrders();
  }, [loadOrders, refreshKey]);

  return (
    <div className="w-full max-w-6xl space-y-4 text-text-primary select-none">
      {/* Top Bar: Market Selector (IN vs US) & Status */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-surface border border-border px-4 py-2.5">
        <div className="flex items-center space-x-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-text-primary">
            Order History
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
          <span>{orders.length} TOTAL LOGGED ORDERS</span>
        </div>
      </div>

      {/* Orders Table or Empty State */}
      <div className="bg-surface border border-border overflow-hidden">
        {/* Table Subheader */}
        <div className="h-9 px-3 bg-[#111317] border-b border-border flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-text-primary">
            Execution Log ({selectedMarket})
          </span>
          <span className="text-[11px] font-mono-tabular text-text-muted">
            NEWEST FIRST // CHRONOLOGICAL
          </span>
        </div>

        {!wallet ? (
          /* Uninitialized Wallet State */
          <div className="p-10 text-center space-y-4 font-mono-tabular">
            <div className="flex items-center justify-center space-x-2 text-xs text-text-muted">
              <span className="w-1.5 h-1.5 rounded-full bg-accent" />
              <span>
                NO {selectedMarket === 'IN' ? 'INDIAN' : 'US'} WALLET INITIALIZED — Set up your paper balance to begin placing orders
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
        ) : orders.length === 0 ? (
          /* Empty State */
          <div className="p-10 text-center space-y-3 font-mono-tabular">
            <div className="flex items-center justify-center space-x-2 text-xs text-text-muted">
              <span className="w-1.5 h-1.5 rounded-full bg-text-muted" />
              <span>NO ORDER HISTORY — placed orders will appear here</span>
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
          /* Table of Orders */
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse font-mono-tabular">
              <thead>
                <tr className="h-8 border-b border-border text-[11px] uppercase text-text-muted font-sans font-medium select-none bg-[#0f1014]">
                  <th className="px-3 font-medium">Timestamp (UTC)</th>
                  <th className="px-3 font-medium">Symbol</th>
                  <th className="px-3 font-medium">Side</th>
                  <th className="px-3 text-right font-medium">Quantity</th>
                  <th className="px-3 text-right font-medium">Executed Price</th>
                  <th className="px-3 font-medium">Status</th>
                  <th className="px-3 font-medium">Note / Reason</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => {
                  const isFilled = o.status === 'filled';
                  const isBuy = o.side.toLowerCase() === 'buy';

                  return (
                    <tr
                      key={o.id}
                      className={`h-[38px] border-b border-border transition-colors text-xs ${
                        isFilled
                          ? 'hover:bg-surface-hover'
                          : 'opacity-70 bg-[#121316]/50 hover:opacity-90'
                      }`}
                    >
                      {/* Timestamp */}
                      <td className="px-3 py-0 align-middle text-text-muted text-[11px]">
                        {formatDate(o.created_at)}
                      </td>

                      {/* Symbol */}
                      <td className="px-3 py-0 align-middle font-semibold text-text-primary">
                        {o.ticker}
                      </td>

                      {/* Side: Green for Buy, Standard text for Sell */}
                      <td className="px-3 py-0 align-middle font-semibold uppercase text-xs">
                        <span className={isBuy ? 'text-green' : 'text-text-primary'}>
                          {o.side.toUpperCase()}
                        </span>
                      </td>

                      {/* Quantity */}
                      <td className="px-3 py-0 text-right align-middle text-text-primary">
                        {o.quantity}
                      </td>

                      {/* Executed Price */}
                      <td className="px-3 py-0 text-right align-middle text-text-primary">
                        {isFilled
                          ? `${currencySymbol}${formatMoney(o.executed_price, currency)}`
                          : '—'}
                      </td>

                      {/* Status (Dot + Text) */}
                      <td className="px-3 py-0 align-middle">
                        <div className="inline-flex items-center space-x-1.5 text-[11px]">
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${
                              isFilled ? 'bg-green' : 'bg-red'
                            }`}
                          />
                          <span
                            className={
                              isFilled
                                ? 'text-green font-medium uppercase'
                                : 'text-red font-medium uppercase'
                            }
                          >
                            {o.status.toUpperCase()}
                          </span>
                        </div>
                      </td>

                      {/* Reason / Note: Visible directly in the row */}
                      <td className="px-3 py-0 align-middle text-[11px]">
                        {isFilled ? (
                          <span className="text-text-muted">Order executed</span>
                        ) : (
                          <span className="text-red/90 font-medium">
                            {formatRejectReason(o.reject_reason)}
                          </span>
                        )}
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
          <span>AUDIT LOG / ORDER REPOSITORY</span>
          <span>IMMUTABLE DATABASE LEDGER</span>
        </div>
      </div>
    </div>
  );
}
