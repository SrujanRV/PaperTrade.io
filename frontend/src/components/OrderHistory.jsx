import React, { useState, useEffect, useCallback } from 'react';
import { fetchOrders, cancelPendingOrder } from '../api/client';

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
    stop_loss_sell_only: 'Stop-loss is sell-only',
    invalid_limit_price: 'Invalid limit price',
    invalid_trigger_price: 'Invalid trigger price',
  };
  return map[reason] || reason;
}

export function OrderHistory({
  selectedMarket = 'IN',
  wallet,
  onSelectMarket,
  onGoToWatchlist,
  onOpenWalletSetup,
  onOrderUpdated,
  refreshKey = 0,
}) {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [statusFilter, setStatusFilter] = useState('all'); // 'all' | 'pending' | 'filled' | 'other'
  const [cancellingId, setCancellingId] = useState(null);

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

  async function handleCancelOrder(orderId) {
    try {
      setCancellingId(orderId);
      await cancelPendingOrder(orderId);
      await loadOrders();
      if (onOrderUpdated) {
        onOrderUpdated();
      }
    } catch (err) {
      alert(err.message || `Failed to cancel order #${orderId}`);
    } finally {
      setCancellingId(null);
    }
  }

  // Filter calculations
  const pendingCount = orders.filter((o) => o.status === 'pending').length;
  const filledCount = orders.filter((o) => o.status === 'filled').length;
  const otherCount = orders.filter((o) => o.status === 'rejected' || o.status === 'cancelled').length;

  const filteredOrders = orders.filter((o) => {
    if (statusFilter === 'all') return true;
    if (statusFilter === 'pending') return o.status === 'pending';
    if (statusFilter === 'filled') return o.status === 'filled';
    if (statusFilter === 'other') return o.status === 'rejected' || o.status === 'cancelled';
    return true;
  });

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

        {/* Sub-tab Filter Switcher */}
        <div className="inline-flex p-0.5 bg-base border border-border font-mono-tabular text-xs">
          <button
            onClick={() => setStatusFilter('all')}
            className={`px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider transition-colors ${
              statusFilter === 'all'
                ? 'bg-[#232731] text-text-primary'
                : 'text-text-muted hover:text-text-primary'
            }`}
          >
            ALL ({orders.length})
          </button>
          <button
            onClick={() => setStatusFilter('pending')}
            className={`px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider transition-colors flex items-center space-x-1 ${
              statusFilter === 'pending'
                ? 'bg-[#232731] text-accent'
                : pendingCount > 0
                ? 'text-accent hover:text-accent/80'
                : 'text-text-muted hover:text-text-primary'
            }`}
          >
            {pendingCount > 0 && <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />}
            <span>PENDING ({pendingCount})</span>
          </button>
          <button
            onClick={() => setStatusFilter('filled')}
            className={`px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider transition-colors ${
              statusFilter === 'filled'
                ? 'bg-[#232731] text-text-primary'
                : 'text-text-muted hover:text-text-primary'
            }`}
          >
            FILLED ({filledCount})
          </button>
          <button
            onClick={() => setStatusFilter('other')}
            className={`px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider transition-colors ${
              statusFilter === 'other'
                ? 'bg-[#232731] text-text-primary'
                : 'text-text-muted hover:text-text-primary'
            }`}
          >
            REJECTED / CANCELLED ({otherCount})
          </button>
        </div>
      </div>

      {/* Orders Table or Empty State */}
      <div className="bg-surface border border-border overflow-hidden">
        {/* Table Subheader */}
        <div className="h-9 px-3 bg-[#111317] border-b border-border flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-text-primary">
              Execution Log ({selectedMarket})
            </span>
            <span className="text-[10px] px-1.5 py-0.2 bg-base border border-border font-mono-tabular uppercase text-text-muted">
              {statusFilter}
            </span>
          </div>
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
        ) : filteredOrders.length === 0 ? (
          /* Empty State */
          <div className="p-10 text-center space-y-3 font-mono-tabular">
            <div className="flex items-center justify-center space-x-2 text-xs text-text-muted">
              <span className="w-1.5 h-1.5 rounded-full bg-text-muted" />
              <span>
                {statusFilter === 'pending'
                  ? 'NO OPEN PENDING ORDERS — limit and stop orders awaiting trigger will appear here'
                  : 'NO ORDER HISTORY FOR THIS FILTER'}
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
          /* Table of Orders */
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse font-mono-tabular">
              <thead>
                <tr className="h-8 border-b border-border text-[11px] uppercase text-text-muted font-sans font-medium select-none bg-[#0f1014]">
                  <th className="px-3 font-medium">Timestamp (UTC)</th>
                  <th className="px-3 font-medium">Symbol</th>
                  <th className="px-3 font-medium">Type</th>
                  <th className="px-3 font-medium">Side</th>
                  <th className="px-3 text-right font-medium">Quantity</th>
                  <th className="px-3 text-right font-medium">Target / Limit</th>
                  <th className="px-3 text-right font-medium">Executed Price</th>
                  <th className="px-3 font-medium">Status</th>
                  <th className="px-3 font-medium">Action / Details</th>
                </tr>
              </thead>
              <tbody>
                {filteredOrders.map((o) => {
                  const isFilled = o.status === 'filled';
                  const isPending = o.status === 'pending';
                  const isCancelled = o.status === 'cancelled';
                  const isRejected = o.status === 'rejected';
                  const isBuy = o.side.toLowerCase() === 'buy';

                  return (
                    <tr
                      key={o.id}
                      className={`h-[38px] border-b border-border transition-colors text-xs ${
                        isPending
                          ? 'bg-accent/5 hover:bg-accent/10'
                          : isFilled
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

                      {/* Type: MARKET / LIMIT / STOP_LOSS */}
                      <td className="px-3 py-0 align-middle text-[10px] uppercase font-semibold text-text-muted">
                        <span className="px-1.5 py-0.5 bg-base border border-border">
                          {(o.order_type || 'market').replace('_', '-')}
                        </span>
                      </td>

                      {/* Side */}
                      <td className="px-3 py-0 align-middle font-semibold uppercase text-xs">
                        <span className={isBuy ? 'text-green' : 'text-red'}>
                          {o.side.toUpperCase()}
                        </span>
                      </td>

                      {/* Quantity */}
                      <td className="px-3 py-0 text-right align-middle text-text-primary">
                        {o.quantity}
                      </td>

                      {/* Target / Limit Price */}
                      <td className="px-3 py-0 text-right align-middle text-text-muted">
                        {o.order_type === 'limit' && o.requested_price
                          ? `${currencySymbol}${formatMoney(o.requested_price, currency)}`
                          : o.order_type === 'stop_loss' && (o.trigger_price || o.requested_price)
                          ? `≤ ${currencySymbol}${formatMoney(o.trigger_price || o.requested_price, currency)}`
                          : '—'}
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
                              isFilled
                                ? 'bg-green'
                                : isPending
                                ? 'bg-accent animate-pulse'
                                : isCancelled
                                ? 'bg-text-muted'
                                : 'bg-red'
                            }`}
                          />
                          <span
                            className={`font-medium uppercase ${
                              isFilled
                                ? 'text-green'
                                : isPending
                                ? 'text-accent'
                                : isCancelled
                                ? 'text-text-muted'
                                : 'text-red'
                            }`}
                          >
                            {o.status.toUpperCase()}
                          </span>
                        </div>
                      </td>

                      {/* Action / Details */}
                      <td className="px-3 py-0 align-middle text-[11px]">
                        {isPending ? (
                          <button
                            type="button"
                            disabled={cancellingId === o.id}
                            onClick={() => handleCancelOrder(o.id)}
                            className="px-2 py-0.5 bg-red/10 hover:bg-red/20 border border-red/40 text-red text-[10px] uppercase font-bold tracking-wider transition-colors disabled:opacity-50"
                          >
                            {cancellingId === o.id ? 'CANCELLING...' : 'CANCEL'}
                          </button>
                        ) : isFilled ? (
                          <span className="text-text-muted">Executed @ market</span>
                        ) : isCancelled ? (
                          <span className="text-text-muted">Cancelled by user</span>
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

