import React, { useState, useEffect, useCallback } from 'react';
import { BarChart2, ShieldAlert, Layers } from 'lucide-react';
import { fetchWalletSummary, fetchDerivativePositions } from '../api/client';

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
  onSelectContract,
  onOpenChart,
  onGoToWatchlist,
  onOpenWalletSetup,
  livePrices = {},
  refreshKey = 0,
}) {
  const [summary, setSummary] = useState(null);
  const [derivativePositions, setDerivativePositions] = useState([]);
  const [positionsSubTab, setPositionsSubTab] = useState('equities'); // 'equities' | 'derivatives'
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const currency = selectedMarket === 'IN' ? 'INR' : 'USD';
  const currencySymbol = selectedMarket === 'IN' ? '₹' : '$';

  // Fetch summary and derivative positions from backend
  const loadPortfolioData = useCallback(async () => {
    try {
      setError(null);
      const [summaryData, derivData] = await Promise.all([
        fetchWalletSummary(selectedMarket),
        fetchDerivativePositions(selectedMarket).catch(() => []),
      ]);
      setSummary(summaryData);
      setDerivativePositions(derivData || []);
    } catch (err) {
      setError(err.message || 'Failed to load portfolio data');
    } finally {
      setLoading(false);
    }
  }, [selectedMarket]);

  useEffect(() => {
    setLoading(true);
    loadPortfolioData();
  }, [loadPortfolioData, refreshKey]);

  const holdings = summary?.holdings || [];

  // Compute live values overlaying SSE prices onto equity holdings
  let totalHoldingsValue = 0;
  let totalUnrealizedPnL = 0;

  const liveHoldings = holdings.map((h) => {
    const liveQuote = livePrices[h.ticker.toUpperCase()];
    const currentPrice = liveQuote ? liveQuote.current_price : h.current_price;
    const isShort = Boolean(h.is_short);
    const costBasis = Number((h.avg_buy_price * h.quantity).toFixed(2));
    const currentValue = isShort
      ? Number((-1 * currentPrice * h.quantity).toFixed(2))
      : Number((currentPrice * h.quantity).toFixed(2));
    const unrealizedPnL = isShort
      ? Number(((h.avg_buy_price - currentPrice) * h.quantity).toFixed(2))
      : Number((currentValue - costBasis).toFixed(2));
    const unrealizedPnLPct =
      costBasis > 0 ? (unrealizedPnL / costBasis) * 100 : 0;

    totalHoldingsValue += currentValue;
    totalUnrealizedPnL += unrealizedPnL;

    let liveMarginLevelPct = h.margin_level_pct;
    let liveDistancePct = h.distance_to_margin_call_pct;
    let liveMaintenanceReq = h.maintenance_margin_required;
    let liveLiquidationPrice = h.liquidation_price;

    if (isShort && selectedMarket === 'US' && h.margin_locked && currentPrice > 0) {
      const currPosVal = currentPrice * h.quantity;
      liveMaintenanceReq = Number((1.25 * currPosVal).toFixed(2));
      liveMarginLevelPct = Number(((h.margin_locked / currPosVal) * 100).toFixed(1));
      liveLiquidationPrice = Number((h.margin_locked / (1.25 * h.quantity)).toFixed(2));
      liveDistancePct = Number((((liveLiquidationPrice - currentPrice) / currentPrice) * 100).toFixed(1));
    }

    return {
      ...h,
      current_price: currentPrice,
      current_value: currentValue,
      unrealized_pnl: unrealizedPnL,
      unrealized_pnl_pct: unrealizedPnLPct,
      margin_level_pct: liveMarginLevelPct,
      distance_to_margin_call_pct: liveDistancePct,
      maintenance_margin_required: liveMaintenanceReq,
      liquidation_price: liveLiquidationPrice,
      tickDirection: liveQuote?.tickDirection || 'none',
      tickId: liveQuote?.tickId || 0,
    };
  });

  // Calculate derivatives total P&L and market value
  let totalDerivsUnrealizedPnL = 0;
  let totalDerivsMarginLocked = 0;
  for (const dp of derivativePositions) {
    totalDerivsUnrealizedPnL += (dp.unrealized_pnl || 0);
    totalDerivsMarginLocked += (dp.margin_locked || 0);
  }

  const cashBalance = summary?.cash_balance ?? 0;
  const marginUsed = summary?.margin_used ?? totalDerivsMarginLocked;
  const totalWalletValue = Number((cashBalance + totalHoldingsValue).toFixed(2));
  const totalRealizedPnL = summary?.total_realized_pnl ?? 0;

  function handleCloseDerivativePosition(pos) {
    if (onSelectContract) {
      const isOption = pos.contract.instrument_type === 'option';
      const action = isOption
        ? (pos.side === 'long' ? 'sell_to_close' : 'buy_to_close')
        : 'close';

      onSelectContract({
        isDerivative: true,
        contract_id: pos.contract_id,
        instrument_type: pos.contract.instrument_type,
        option_type: pos.contract.option_type,
        underlying: pos.contract.underlying,
        strike_price: pos.contract.strike_price,
        expiry_date: pos.contract.expiry_date,
        symbol: pos.contract.symbol,
        lot_size: pos.contract.lot_size,
        market: selectedMarket,
        price: pos.current_price,
        current_price: pos.current_price,
        underlying_price: pos.current_price,
        initial_action: action,
        quantity: pos.quantity,
        existing_side: pos.side,
      });
    }
  }

  return (
    <div className="w-full max-w-6xl space-y-4 text-text-primary select-none font-sans">
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
          <span>SOURCE: /api/wallet/{selectedMarket}/summary // POOLED MARGIN</span>
        </div>
      </div>

      {/* Account Metric Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        {/* Total Wallet Value */}
        <div className="bg-surface border border-border p-3.5 flex flex-col justify-between">
          <div className="text-[11px] font-mono-tabular text-text-muted uppercase tracking-wider">
            Total Account Value
          </div>
          <div className="text-lg font-bold font-mono-tabular text-text-primary mt-1">
            {currencySymbol}
            {formatMoney(totalWalletValue, currency)}
          </div>
          <div className="text-[10px] text-text-muted mt-0.5">
            Cash + equity positions
          </div>
        </div>

        {/* Cash Balance */}
        <div className="bg-surface border border-border p-3.5 flex flex-col justify-between">
          <div className="text-[11px] font-mono-tabular text-text-muted uppercase tracking-wider">
            Cash Balance
          </div>
          <div className="text-lg font-bold font-mono-tabular text-text-primary mt-1">
            {currencySymbol}
            {formatMoney(cashBalance, currency)}
          </div>
          <div className="text-[10px] text-text-muted mt-0.5">
            Liquid settled funds
          </div>
        </div>

        {/* Unified Margin Used (Pooled) */}
        <div className="bg-surface border border-border p-3.5 flex flex-col justify-between">
          <div className="text-[11px] font-mono-tabular text-text-muted uppercase tracking-wider">
            Margin Locked (Pooled)
          </div>
          <div className={`text-lg font-bold font-mono-tabular mt-1 ${marginUsed > 0 ? 'text-amber-400' : 'text-text-primary'}`}>
            {currencySymbol}
            {formatMoney(marginUsed, currency)}
          </div>
          <div className="text-[10px] text-text-muted mt-0.5">
            Collateral (shorts & derivatives)
          </div>
        </div>

        {/* Unrealized P&L */}
        <div className="bg-surface border border-border p-3.5 flex flex-col justify-between">
          <div className="text-[11px] font-mono-tabular text-text-muted uppercase tracking-wider">
            Total Unrealized P&L
          </div>
          <div
            className={`text-lg font-bold font-mono-tabular mt-1 ${
              (totalUnrealizedPnL + totalDerivsUnrealizedPnL) > 0
                ? 'text-green'
                : (totalUnrealizedPnL + totalDerivsUnrealizedPnL) < 0
                ? 'text-red'
                : 'text-text-muted'
            }`}
          >
            {currencySymbol}
            {formatSignedMoney(totalUnrealizedPnL + totalDerivsUnrealizedPnL, currency)}
          </div>
          <div className="text-[10px] text-text-muted mt-0.5">
            Equities + Derivatives
          </div>
        </div>

        {/* Realized P&L */}
        <div className="bg-surface border border-border p-3.5 flex flex-col justify-between">
          <div className="text-[11px] font-mono-tabular text-text-muted uppercase tracking-wider">
            Realized P&L
          </div>
          <div
            className={`text-lg font-bold font-mono-tabular mt-1 ${
              totalRealizedPnL > 0
                ? 'text-green'
                : totalRealizedPnL < 0
                ? 'text-red'
                : 'text-text-muted'
            }`}
          >
            {currencySymbol}
            {formatSignedMoney(totalRealizedPnL, currency)}
          </div>
          <div className="text-[10px] text-text-muted mt-0.5">
            Settled closed trades
          </div>
        </div>
      </div>

      {/* Positions Section with Equities vs Derivatives Sub-Tabs */}
      <div className="bg-surface border border-border overflow-hidden">
        {/* Table Subheader with Sub-Tabs */}
        <div className="h-10 px-3 bg-[#111317] border-b border-border flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-text-primary mr-1">
              POSITIONS:
            </span>
            <div className="inline-flex p-0.5 bg-base border border-border font-mono-tabular">
              <button
                onClick={() => setPositionsSubTab('equities')}
                className={`px-3 py-1 text-xs font-semibold uppercase tracking-wider transition-colors ${
                  positionsSubTab === 'equities'
                    ? 'bg-[#232731] text-text-primary'
                    : 'text-text-muted hover:text-text-primary'
                }`}
              >
                Equities ({liveHoldings.length})
              </button>
              <button
                onClick={() => setPositionsSubTab('derivatives')}
                className={`px-3 py-1 text-xs font-semibold uppercase tracking-wider transition-colors flex items-center space-x-1 ${
                  positionsSubTab === 'derivatives'
                    ? 'bg-[#232731] text-text-primary'
                    : 'text-text-muted hover:text-text-primary'
                }`}
              >
                <Layers className="w-3.5 h-3.5 mr-1" />
                <span>Derivatives ({derivativePositions.length})</span>
              </button>
            </div>
          </div>

          <span className="text-[11px] font-mono-tabular text-text-muted">
            {positionsSubTab === 'equities' ? 'EQUITY HOLDINGS & SHORTS' : 'OPTIONS & FUTURES CONTRACTS'}
          </span>
        </div>

        {loading && !summary ? (
          <div className="p-10 text-center space-y-3 font-mono-tabular text-text-muted">
            <span className="inline-block w-4 h-4 border-2 border-accent border-t-transparent rounded-full animate-spin mb-2" />
            <div>LOADING PORTFOLIO VALUATION...</div>
          </div>
        ) : !summary ? (
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
        ) : positionsSubTab === 'equities' ? (
          /* ── EQUITIES TABLE ── */
          liveHoldings.length === 0 ? (
            <div className="p-10 text-center space-y-3 font-mono-tabular">
              <div className="flex items-center justify-center space-x-2 text-xs text-text-muted">
                <span className="w-1.5 h-1.5 rounded-full bg-text-muted" />
                <span>NO OPEN EQUITY POSITIONS — place your first order from the watchlist</span>
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
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse font-mono-tabular">
                <thead>
                  <tr className="h-8 border-b border-border text-[11px] uppercase text-text-muted font-sans font-medium select-none bg-[#0f1014]">
                    <th className="px-3 font-medium">Symbol</th>
                    <th className="px-3 text-right font-medium">Qty</th>
                    <th className="px-3 text-right font-medium">Avg Entry Price</th>
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
                        {/* Symbol + Badges */}
                        <td className="px-3 py-1.5 align-middle">
                          <div className="flex flex-col">
                            <div className="flex items-center space-x-1.5">
                              <span className="font-semibold text-text-primary leading-tight">
                                {h.ticker}
                              </span>
                              {h.is_short && (
                                <span className="px-1.5 py-0.2 rounded text-[9px] font-mono-tabular font-bold tracking-wider uppercase border bg-red/15 text-red border-red/40">
                                  SHORT
                                </span>
                              )}
                            </div>

                            {/* US Short Margin Level Gauge */}
                            {h.is_short && selectedMarket === 'US' && h.margin_level_pct !== null && h.margin_level_pct !== undefined && (
                              <div className="mt-1 flex items-center space-x-1.5 flex-wrap gap-y-1">
                                <span
                                  title={`Locked Margin Collateral: $${formatMoney(h.margin_locked, currency)} | Maintenance Req (125%): $${formatMoney(h.maintenance_margin_required, currency)}`}
                                  className={`px-1.5 py-0.5 rounded text-[9px] font-mono-tabular font-bold tracking-wider uppercase border flex items-center ${
                                    h.margin_level_pct < 125
                                      ? 'bg-red/20 text-red border-red/60 animate-pulse'
                                      : h.margin_level_pct < 140
                                      ? 'bg-amber-500/20 text-amber-400 border-amber-500/50'
                                      : 'bg-emerald-500/15 text-emerald-400 border-emerald-500/40'
                                  }`}
                                >
                                  <span className="w-1.5 h-1.5 rounded-full inline-block mr-1 bg-current" />
                                  <span>MARGIN LEVEL: {h.margin_level_pct.toFixed(1)}%</span>
                                </span>

                                <span
                                  title={`Liquidation Price: $${formatMoney(h.liquidation_price, currency)}`}
                                  className={`px-1.5 py-0.5 rounded text-[9px] font-mono-tabular font-medium tracking-wider uppercase border ${
                                    h.distance_to_margin_call_pct <= 5
                                      ? 'bg-red/20 text-red border-red/60'
                                      : h.distance_to_margin_call_pct <= 15
                                      ? 'bg-amber-500/15 text-amber-400 border-amber-500/40'
                                      : 'bg-surface border-border text-text-muted'
                                  }`}
                                >
                                  {h.distance_to_margin_call_pct <= 0
                                    ? '⚠️ LIQUIDATION BREACH'
                                    : `${h.distance_to_margin_call_pct > 0 ? '+' : ''}${h.distance_to_margin_call_pct.toFixed(1)}% TO CALL ($${formatMoney(h.liquidation_price, currency)})`}
                                </span>
                              </div>
                            )}

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
                        <td className="px-3 py-0 text-right align-middle font-medium">
                          <span className={h.is_short ? 'text-red' : 'text-text-primary'}>
                            {h.is_short ? `-${h.quantity}` : h.quantity}
                          </span>
                        </td>

                        {/* Avg Entry Price */}
                        <td className="px-3 py-0 text-right align-middle text-text-primary font-medium">
                          {currencySymbol}
                          {formatMoney(h.avg_buy_price, currency)}
                        </td>

                        {/* Current Live Price */}
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

                        {/* Unrealized P&L */}
                        <td className="px-3 py-0 text-right align-middle">
                          <span className={`font-semibold ${pnlColor}`}>
                            {currencySymbol}
                            {formatSignedMoney(h.unrealized_pnl, currency)}{' '}
                            <span className="text-[11px] font-normal">
                              ({formatSignedPct(h.unrealized_pnl_pct)})
                            </span>
                          </span>
                        </td>

                        {/* Action */}
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
                              className={`px-2 py-1 text-[10px] uppercase font-sans font-medium transition-colors ${
                                h.is_short
                                  ? 'bg-green/10 border border-green/50 text-green hover:bg-green hover:text-black'
                                  : 'bg-base border border-border text-text-primary hover:border-accent hover:text-white'
                              }`}
                            >
                              {h.is_short ? 'COVER' : 'TRADE'}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )
        ) : (
          /* ── DERIVATIVES TABLE ── */
          derivativePositions.length === 0 ? (
            <div className="p-10 text-center space-y-3 font-mono-tabular">
              <div className="flex items-center justify-center space-x-2 text-xs text-text-muted">
                <span className="w-1.5 h-1.5 rounded-full bg-text-muted" />
                <span>NO OPEN DERIVATIVE POSITIONS (OPTIONS OR FUTURES)</span>
              </div>
              <div className="text-[11px] text-text-muted">
                Open option chains or futures market to place your first derivative trade.
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse font-mono-tabular">
                <thead>
                  <tr className="h-8 border-b border-border text-[11px] uppercase text-text-muted font-sans font-medium select-none bg-[#0f1014]">
                    <th className="px-3 font-medium">Contract</th>
                    <th className="px-3 font-medium">Side</th>
                    <th className="px-3 text-right font-medium">Qty (Lots & Units)</th>
                    <th className="px-3 text-right font-medium">Entry Price</th>
                    <th className="px-3 text-right font-medium">Current LTP</th>
                    <th className="px-3 text-right font-medium">Unrealized P&L</th>
                    <th className="px-3 text-right font-medium">Margin Locked</th>
                    <th className="px-3 text-center font-medium">Margin Level</th>
                    <th className="px-3 text-right font-medium">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {derivativePositions.map((pos) => {
                    const c = pos.contract;
                    const isOption = c.instrument_type === 'option';
                    const isFuture = c.instrument_type === 'future';
                    const isLong = pos.side === 'long';
                    const totalUnits = pos.quantity * (c.lot_size || 1);

                    const pnlColor =
                      pos.unrealized_pnl > 0
                        ? 'text-green'
                        : pos.unrealized_pnl < 0
                        ? 'text-red'
                        : 'text-text-muted';

                    // Margin Level gauge thresholds (Phase 5b pattern)
                    const marginLevel = pos.margin_level_pct;
                    const requiresMargin = (pos.margin_locked > 0) || (!isLong && !pos.is_covered);

                    return (
                      <tr
                        key={pos.id}
                        className="border-b border-border hover:bg-surface-hover transition-colors text-xs"
                      >
                        {/* Contract Details & Type Badges */}
                        <td className="px-3 py-2">
                          <div className="flex flex-col">
                            <div className="flex items-center space-x-1.5 flex-wrap gap-y-1">
                              <span className="font-bold text-text-primary text-xs">
                                {c.symbol}
                              </span>

                              {/* Instrument Badge */}
                              {isOption ? (
                                <span className={`px-1.5 py-0.2 rounded text-[9px] font-mono-tabular font-bold tracking-wider uppercase border ${
                                  c.option_type === 'call'
                                    ? 'bg-emerald-950/40 text-emerald-400 border-emerald-500/40'
                                    : 'bg-red-950/40 text-red border-red/40'
                                }`}>
                                  OPTION {c.option_type?.toUpperCase()}
                                </span>
                              ) : (
                                <span className="px-1.5 py-0.2 rounded text-[9px] font-mono-tabular font-bold tracking-wider uppercase border bg-accent/20 text-accent border-accent/40">
                                  FUTURES
                                </span>
                              )}

                              {pos.is_covered && (
                                <span className="px-1.5 py-0.2 rounded text-[9px] font-mono-tabular font-bold tracking-wider uppercase border bg-green/15 text-green border-green/40">
                                  COVERED
                                </span>
                              )}
                            </div>

                            <span className="text-[10px] text-text-muted mt-0.5">
                              {c.underlying} {c.strike_price ? `• Strike ${formatMoney(c.strike_price, currency)}` : ''} {c.expiry_date ? `• Exp: ${c.expiry_date}` : '• Perpetual'}
                            </span>
                          </div>
                        </td>

                        {/* Side */}
                        <td className="px-3 py-2">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono-tabular uppercase tracking-wider ${
                            isLong ? 'bg-green/15 text-green' : 'bg-red/15 text-red'
                          }`}>
                            {pos.side.toUpperCase()}
                          </span>
                        </td>

                        {/* Qty in Lots & Total Units */}
                        <td className="px-3 py-2 text-right">
                          <div className="font-bold text-text-primary">
                            {pos.quantity} {pos.quantity === 1 ? 'Lot' : 'Lots'}
                          </div>
                          <div className="text-[10px] text-text-muted">
                            ({totalUnits} units)
                          </div>
                        </td>

                        {/* Entry Price */}
                        <td className="px-3 py-2 text-right text-text-primary font-medium">
                          {currencySymbol}{formatMoney(pos.entry_price, currency)}
                        </td>

                        {/* Current LTP */}
                        <td className="px-3 py-2 text-right font-bold text-text-primary">
                          {currencySymbol}{formatMoney(pos.current_price, currency)}
                        </td>

                        {/* Unrealized P&L */}
                        <td className="px-3 py-2 text-right">
                          <span className={`font-semibold ${pnlColor}`}>
                            {currencySymbol}{formatSignedMoney(pos.unrealized_pnl, currency)}{' '}
                            <span className="text-[11px] font-normal">
                              ({formatSignedPct(pos.unrealized_pnl_pct)})
                            </span>
                          </span>
                        </td>

                        {/* Margin Locked */}
                        <td className="px-3 py-2 text-right font-bold text-text-primary">
                          {pos.margin_locked > 0 ? (
                            <span className="text-amber-400">
                              {currencySymbol}{formatMoney(pos.margin_locked, currency)}
                            </span>
                          ) : (
                            <span className="text-text-muted">₹0.00</span>
                          )}
                        </td>

                        {/* Margin Level Gauge */}
                        <td className="px-3 py-2 text-center">
                          {pos.is_covered ? (
                            <span className="px-2 py-0.5 rounded text-[9px] font-bold font-mono-tabular border bg-green/10 text-green border-green/40">
                              COVERED (0 MARGIN)
                            </span>
                          ) : requiresMargin && marginLevel !== null && marginLevel !== undefined ? (
                            <span
                              title={`Margin Locked: ${currencySymbol}${formatMoney(pos.margin_locked, currency)} | Maint Req: ${currencySymbol}${formatMoney(pos.maintenance_margin_required, currency)}`}
                              className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono-tabular uppercase border inline-flex items-center space-x-1 ${
                                marginLevel < 100
                                  ? 'bg-red/20 text-red border-red/60 animate-pulse'
                                  : marginLevel < 120
                                  ? 'bg-amber-500/20 text-amber-400 border-amber-500/50'
                                  : 'bg-emerald-500/15 text-emerald-400 border-emerald-500/40'
                              }`}
                            >
                              <span className="w-1.5 h-1.5 rounded-full inline-block bg-current mr-1" />
                              <span>{marginLevel.toFixed(1)}%</span>
                            </span>
                          ) : (
                            <span className="text-text-muted text-[11px]">—</span>
                          )}
                        </td>

                        {/* Close Action */}
                        <td className="px-3 py-2 text-right">
                          <button
                            onClick={() => handleCloseDerivativePosition(pos)}
                            className="px-3 py-1 bg-red/10 border border-red/50 text-red hover:bg-red hover:text-white text-xs uppercase font-sans font-semibold transition-colors"
                          >
                            CLOSE
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )
        )}

        {/* Footer */}
        <div className="h-7 px-3 bg-[#0d0e12] border-t border-border flex items-center justify-between text-[11px] text-text-muted font-mono-tabular select-none">
          <span>PORTFOLIO VALUATION ENGINE</span>
          <span>POOLED MARGIN ACCOUNT</span>
        </div>
      </div>
    </div>
  );
}
