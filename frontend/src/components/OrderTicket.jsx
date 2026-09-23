import React, { useState, useEffect, useRef, useCallback } from 'react';
import { X } from 'lucide-react';
import { placeOrder, calculateSquareOffDate } from '../api/client';
import { LivePriceChart } from './LivePriceChart';

export function OrderTicket({
  ticker,
  quote,
  wallet,
  onClose,
  onOrderExecuted,
  onOpenWalletSetup,
  onOpenChart,
}) {
  const [orderType, setOrderType] = useState('market'); // 'market' | 'limit' | 'stop_loss'
  const [side, setSide] = useState('buy'); // 'buy' | 'sell'
  const [quantity, setQuantity] = useState(1);
  const [limitPrice, setLimitPrice] = useState('');
  const [triggerPrice, setTriggerPrice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [completedOrder, setCompletedOrder] = useState(null);

  // Holding duration state: 'none' | 'intraday' | '1_day' | 'custom'
  const [durationMode, setDurationMode] = useState('none');
  const [customDays, setCustomDays] = useState(2);
  const [calculatedSquareOff, setCalculatedSquareOff] = useState(null);
  const squareOffCacheRef = useRef(new Map());
  const debounceTimerRef = useRef(null);

  // Reset state when ticker changes
  useEffect(() => {
    setOrderType('market');
    setSide('buy');
    setQuantity(1);
    setLimitPrice(quote?.current_price ? String(quote.current_price) : '');
    setTriggerPrice(quote?.current_price ? String(Number((quote.current_price * 0.95).toFixed(2))) : '');
    setDurationMode('none');
    setCustomDays(2);
    setCalculatedSquareOff(null);
    setErrorMsg(null);
    setCompletedOrder(null);
  }, [ticker]);

  // Initialize prices when quote first arrives if not already set
  useEffect(() => {
    if (quote?.current_price) {
      setLimitPrice((prev) => (prev ? prev : String(quote.current_price)));
      setTriggerPrice((prev) =>
        prev ? prev : String(Number((quote.current_price * 0.95).toFixed(2)))
      );
    }
  }, [quote?.current_price]);

  if (!ticker) return null;

  const upper = ticker.toUpperCase();
  const isIndian = upper.endsWith('.NS') || upper.endsWith('.BO');
  const market = isIndian ? 'IN' : 'US';
  const currency = isIndian ? 'INR' : 'USD';
  const currencySymbol = isIndian ? '₹' : '$';
  const exchange = isIndian ? (upper.endsWith('.BO') ? 'BSE' : 'NSE') : 'NASDAQ';

  const price = quote?.current_price ?? 0;
  const isMarketOpen = quote?.market_status === 'open';

  // Effective price for calculation
  const effectivePrice =
    orderType === 'limit' && Number(limitPrice) > 0
      ? Number(limitPrice)
      : orderType === 'stop_loss' && Number(triggerPrice) > 0
      ? Number(triggerPrice)
      : price;

  const totalCost = Number((effectivePrice * (Number(quantity) || 0)).toFixed(2));
  const cashBalance = wallet?.current_cash_balance ?? 0;

  // Check available holding if selling or covering
  const existingHolding = wallet?.holdings?.find(
    (h) => h.ticker.toUpperCase() === upper
  );
  const isHoldingShort = Boolean(existingHolding?.is_short);
  const ownedQuantity = isHoldingShort ? 0 : (existingHolding?.quantity ?? 0);
  const shortQuantityHeld = isHoldingShort ? (existingHolding?.quantity ?? 0) : 0;

  // Short selling & cover buy operation flags
  const isShortSellOperation =
    market === 'IN' &&
    side === 'sell' &&
    ((Number(quantity) || 0) > ownedQuantity || isHoldingShort);

  const isCoverBuyOperation =
    side === 'buy' && isHoldingShort;

  // Fetch resolved square-off date with in-memory caching and debouncing
  const fetchResolvedDate = useCallback((mkt, days) => {
    const cacheKey = `${mkt}:${days}`;
    if (squareOffCacheRef.current.has(cacheKey)) {
      setCalculatedSquareOff(squareOffCacheRef.current.get(cacheKey));
      return;
    }
    calculateSquareOffDate(mkt, days)
      .then((data) => {
        squareOffCacheRef.current.set(cacheKey, data);
        setCalculatedSquareOff(data);
      })
      .catch((err) => {
        console.error('Failed to calculate square-off date:', err);
      });
  }, []);

  useEffect(() => {
    if (side !== 'buy' || isCoverBuyOperation || durationMode === 'none') {
      setCalculatedSquareOff(null);
      return;
    }

    const days = durationMode === 'intraday' ? 0 : durationMode === '1_day' ? 1 : customDays;
    const cacheKey = `${market}:${days}`;

    // Instant update if in cache
    if (squareOffCacheRef.current.has(cacheKey)) {
      setCalculatedSquareOff(squareOffCacheRef.current.get(cacheKey));
      return;
    }

    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    debounceTimerRef.current = setTimeout(() => {
      fetchResolvedDate(market, days);
    }, 100);

    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
  }, [side, isCoverBuyOperation, durationMode, customDays, market, fetchResolvedDate]);

  // Validation checks
  const hasInsufficientFunds = side === 'buy' && totalCost > cashBalance;
  const hasInsufficientMargin = isShortSellOperation && totalCost > cashBalance;
  const hasInsufficientHoldings =
    side === 'sell' &&
    (Number(quantity) || 0) > ownedQuantity &&
    (market === 'US' || orderType === 'stop_loss');

  async function handleOrderSubmit(e) {
    e.preventDefault();
    setErrorMsg(null);
    setCompletedOrder(null);

    const qty = Number(quantity);
    if (!qty || qty <= 0) {
      setErrorMsg('Please enter a valid quantity greater than zero.');
      return;
    }

    if (orderType === 'market' && !isMarketOpen) {
      setErrorMsg('Market is currently closed. Market orders require regular market hours.');
      return;
    }

    if (orderType === 'limit') {
      const lp = Number(limitPrice);
      if (!lp || lp <= 0) {
        setErrorMsg('Please enter a valid limit price greater than zero.');
        return;
      }
    }

    if (orderType === 'stop_loss') {
      if (side !== 'sell') {
        setErrorMsg('Stop-loss orders are sell-only to protect existing positions.');
        return;
      }
      const tp = Number(triggerPrice);
      if (!tp || tp <= 0) {
        setErrorMsg('Please enter a valid trigger price greater than zero.');
        return;
      }
    }

    if (hasInsufficientFunds) {
      setErrorMsg(
        `Insufficient funds. Estimated total is ${currencySymbol}${totalCost.toLocaleString()} but available cash is ${currencySymbol}${cashBalance.toLocaleString()}.`
      );
      return;
    }

    if (hasInsufficientMargin) {
      setErrorMsg(
        `Insufficient margin. Opening this short position requires 1x cash margin of ${currencySymbol}${totalCost.toLocaleString()}, but available cash is ${currencySymbol}${cashBalance.toLocaleString()}.`
      );
      return;
    }

    if (hasInsufficientHoldings) {
      if (market === 'US') {
        setErrorMsg(
          `Insufficient holdings. You only own ${ownedQuantity} shares of ${upper}. Short selling is not currently supported for US equities.`
        );
      } else {
        setErrorMsg(
          `Insufficient holdings. Stop-loss orders can only protect shares you currently hold (${ownedQuantity} shares).`
        );
      }
      return;
    }

    setSubmitting(true);

    try {
      const orderPayload = {
        market,
        ticker: upper,
        side,
        quantity: qty,
        order_type: orderType,
        requested_price: orderType === 'limit' ? Number(limitPrice) : orderType === 'stop_loss' ? Number(triggerPrice) : null,
        trigger_price: orderType === 'stop_loss' ? Number(triggerPrice) : null,
      };

      if (side === 'buy' && !isCoverBuyOperation && durationMode !== 'none' && calculatedSquareOff) {
        orderPayload.holding_days = durationMode === 'intraday' ? 0 : durationMode === '1_day' ? 1 : customDays;
        orderPayload.square_off_date = calculatedSquareOff.square_off_date;
        orderPayload.is_intraday = durationMode === 'intraday';
      }

      const order = await placeOrder(orderPayload);

      if (order.status === 'filled' || order.status === 'pending') {
        setCompletedOrder(order);
        if (onOrderExecuted) {
          onOrderExecuted(order);
        }
      } else {
        // Map reject_reason to user-friendly terminal explanation
        const reasons = {
          market_closed: 'Market is closed. Trading is only permitted during regular market hours.',
          insufficient_funds: `Insufficient funds in ${currency} wallet to complete this purchase.`,
          insufficient_margin: `Insufficient cash balance to meet the 1x margin requirement for short selling.`,
          insufficient_holdings: `Insufficient holdings. You do not hold enough shares of ${upper} to sell.`,
          intraday_only_for_short: `Short selling is intraday-only in Indian equities. Multi-day duration is not permitted.`,
          us_short_not_supported: `Short selling is currently only supported for Indian markets (NSE/BSE). US shorting requires a margin account.`,
          no_short_position: `No open short position to cover.`,
          invalid_ticker: `Invalid ticker symbol. Unable to fetch executable quote from exchange.`,
          wrong_market: `Ticker / wallet mismatch.`,
          stop_loss_sell_only: `Stop-loss orders can only be placed on the SELL side.`,
          invalid_limit_price: `Invalid limit price specified.`,
          invalid_trigger_price: `Invalid trigger price specified.`,
        };
        setErrorMsg(
          reasons[order.reject_reason] ||
            `Order rejected by exchange: ${order.reject_reason || 'Unknown reason'}`
        );
      }
    } catch (err) {
      setErrorMsg(err.message || 'Transmission error while sending order to engine.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="w-80 sm:w-96 bg-surface border border-border flex flex-col select-none text-text-primary h-fit shadow-xl">
      {/* Ticket Header */}
      <div className="h-10 px-3 bg-[#111317] border-b border-border flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <span className="text-xs font-semibold tracking-wider text-text-primary uppercase">
            Order Ticket
          </span>
          <span className="text-[10px] font-mono-tabular text-text-muted px-1 bg-base border border-border">
            {exchange}
          </span>
        </div>
        <button
          onClick={onClose}
          className="p-1 text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Asset Info & Live Price */}
      <div className="p-4 border-b border-border bg-[#0f1115]">
        <div className="flex items-baseline justify-between">
          <div>
            <div className="text-base font-bold tracking-tight text-text-primary">
              {upper}
            </div>
            <div className="text-[11px] font-mono-tabular text-text-muted mt-0.5">
              Market: {market} ({currency})
            </div>
          </div>

          <div className="text-right font-mono-tabular">
            <div className="text-base font-semibold text-text-primary">
              {currencySymbol}
              {price.toLocaleString(currency === 'INR' ? 'en-IN' : 'en-US', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </div>
            <div className="flex items-center justify-end space-x-1 mt-0.5">
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  isMarketOpen ? 'bg-green' : 'bg-[#525866]'
                }`}
              />
              <span
                className={`text-[10px] uppercase font-medium ${
                  isMarketOpen ? 'text-green' : 'text-text-muted'
                }`}
              >
                {isMarketOpen ? 'OPEN' : 'CLOSED'}
              </span>
            </div>
          </div>
        </div>

        {/* Market Closed Warning */}
        {!isMarketOpen && (
          <div className="mt-3 p-2 bg-[#1b1c20] border border-border text-[11px] text-text-muted flex items-center space-x-2 font-mono-tabular">
            <span className="w-1.5 h-1.5 rounded-full bg-red shrink-0" />
            <span>
              <strong className="text-red uppercase font-semibold mr-1.5">MARKET CLOSED —</strong>
              order execution blocked until session open.
            </span>
          </div>
        )}
      </div>

      {/* Live Session Price Chart (Lightweight Charts) */}
      <LivePriceChart
        ticker={upper}
        quote={quote}
        currencySymbol={currencySymbol}
        onExpandChart={onOpenChart}
      />

      {/* Missing Wallet Inline Notice */}
      {!wallet ? (
        <div className="p-5 bg-[#121418] border-t border-border space-y-4 font-mono-tabular">
          <div className="flex items-start space-x-2.5">
            <span className="w-2 h-2 rounded-full bg-accent shrink-0 mt-1" />
            <div>
              <div className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                NO {market} WALLET INITIALIZED
              </div>
              <div className="text-[11px] text-text-muted mt-1 leading-relaxed">
                You need a {currency} paper trading wallet to place orders for{' '}
                <span className="text-text-primary font-semibold">{upper}</span>. Set up a starting balance to begin trading.
              </div>
            </div>
          </div>

          <div className="p-3 bg-base border border-border text-[11px] text-text-muted space-y-1">
            <div className="flex justify-between">
              <span>REQUIRED ASSET:</span>
              <span className="text-text-primary font-semibold">{upper}</span>
            </div>
            <div className="flex justify-between">
              <span>MARKET EXCH:</span>
              <span className="text-text-primary">{exchange}</span>
            </div>
            <div className="flex justify-between">
              <span>CURRENCY:</span>
              <span className="text-text-primary">{currency}</span>
            </div>
          </div>

          <div className="pt-2 space-y-2">
            <button
              type="button"
              onClick={() => onOpenWalletSetup && onOpenWalletSetup(market)}
              className="w-full h-9 bg-accent hover:bg-accent/90 text-white text-xs font-semibold uppercase tracking-wider transition-colors select-none"
            >
              SET UP {market} WALLET
            </button>
            <button
              type="button"
              onClick={onClose}
              className="w-full h-8 bg-base hover:bg-surface-hover border border-border text-text-muted hover:text-text-primary text-xs font-semibold uppercase tracking-wider transition-colors select-none"
            >
              DISMISS & BROWSE WATCHLIST
            </button>
          </div>
        </div>
      ) : completedOrder ? (
        <div className="p-5 text-center space-y-4 font-mono-tabular">
          {completedOrder.status === 'filled' ? (
            <div className="inline-flex items-center space-x-2 text-xs font-semibold tracking-wider text-green uppercase">
              <span className="w-2 h-2 rounded-full bg-green shadow-[0_0_6px_rgba(0,192,118,0.6)]" />
              <span>
                ORDER FILLED @ {currencySymbol}
                {Number(completedOrder.executed_price).toFixed(2)}
              </span>
            </div>
          ) : (
            <div className="inline-flex items-center space-x-2 text-xs font-semibold tracking-wider text-accent uppercase">
              <span className="w-2 h-2 rounded-full bg-accent shadow-[0_0_6px_rgba(59,130,246,0.6)] animate-pulse" />
              <span>PENDING ORDER CREATED</span>
            </div>
          )}

          <div>
            <p className="text-[11px] text-text-muted">
              {completedOrder.order_type.toUpperCase()} {completedOrder.side.toUpperCase()} {completedOrder.quantity} {upper}
            </p>
          </div>

          <div className="p-3 bg-base border border-border text-left text-xs space-y-1">
            <div className="flex justify-between text-text-muted">
              <span>ORDER ID:</span>
              <span className="text-text-primary">#{completedOrder.id}</span>
            </div>
            <div className="flex justify-between text-text-muted">
              <span>STATUS:</span>
              <span
                className={`uppercase font-semibold ${
                  completedOrder.status === 'filled' ? 'text-green' : 'text-accent'
                }`}
              >
                {completedOrder.status === 'filled' ? 'FILLED' : 'PENDING TRIGGER'}
              </span>
            </div>
            {completedOrder.status === 'filled' ? (
              <div className="flex justify-between text-text-muted">
                <span>TOTAL:</span>
                <span className="text-text-primary">
                  {currencySymbol}
                  {(completedOrder.executed_price * completedOrder.quantity).toFixed(2)}
                </span>
              </div>
            ) : (
              <div className="flex justify-between text-text-muted">
                <span>TARGET:</span>
                <span className="text-text-primary font-semibold">
                  {completedOrder.order_type === 'limit'
                    ? completedOrder.side === 'buy'
                      ? `≤ ${currencySymbol}${Number(completedOrder.requested_price).toFixed(2)}`
                      : `≥ ${currencySymbol}${Number(completedOrder.requested_price).toFixed(2)}`
                    : `≤ ${currencySymbol}${Number(completedOrder.trigger_price).toFixed(2)}`}
                </span>
              </div>
            )}
            {completedOrder.square_off_date && (
              <div className="flex justify-between text-text-muted border-t border-border/40 pt-1">
                <span>AUTO SQUARE-OFF:</span>
                <span className="text-accent font-semibold">
                  {completedOrder.square_off_date} {completedOrder.is_intraday ? '(INTRADAY)' : ''}
                </span>
              </div>
            )}
          </div>

          {completedOrder.status === 'pending' && (
            <p className="text-[10px] text-text-muted leading-tight">
              Order will trigger and execute against live price ticks when regular market hours are open.
            </p>
          )}

          <button
            onClick={() => setCompletedOrder(null)}
            className="w-full h-8 bg-surface-hover hover:bg-border text-xs text-text-primary uppercase tracking-wider font-semibold transition-colors"
          >
            PLACE ANOTHER ORDER
          </button>
        </div>
      ) : (
        /* Order Form */
        <form onSubmit={handleOrderSubmit} className="p-4 space-y-4">
          {/* Error / Rejection Banner */}
          {errorMsg && (
            <div className="p-2.5 bg-red/10 border border-red/40 text-xs font-mono-tabular flex items-start space-x-2">
              <span className="w-1.5 h-1.5 rounded-full bg-red shrink-0 mt-1.5" />
              <div className="leading-snug">
                <span className="font-semibold block uppercase text-red">ORDER REJECTED</span>
                <span className="text-text-primary text-[11px] mt-0.5 block">{errorMsg}</span>
              </div>
            </div>
          )}

          {/* Order Type Segmented Control */}
          <div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1 font-mono-tabular">
              ORDER TYPE
            </div>
            <div className="grid grid-cols-3 gap-1 p-1 bg-base border border-border">
              {[
                { id: 'market', label: 'MARKET' },
                { id: 'limit', label: 'LIMIT' },
                { id: 'stop_loss', label: 'STOP-LOSS' },
              ].map((t) => {
                const active = orderType === t.id;
                return (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => {
                      setOrderType(t.id);
                      setErrorMsg(null);
                      if (t.id === 'stop_loss') {
                        setSide('sell');
                      }
                    }}
                    className={`h-7 text-[10px] font-semibold tracking-wider uppercase transition-colors ${
                      active
                        ? 'bg-border text-text-primary'
                        : 'text-text-muted hover:text-text-primary'
                    }`}
                  >
                    {t.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Buy / Sell Segmented Control */}
          <div className="grid grid-cols-2 gap-1 p-1 bg-base border border-border">
            <button
              type="button"
              disabled={orderType === 'stop_loss'}
              onClick={() => {
                setSide('buy');
                setErrorMsg(null);
              }}
              className={`h-8 text-xs font-semibold tracking-wider uppercase transition-colors ${
                orderType === 'stop_loss'
                  ? 'opacity-30 cursor-not-allowed text-text-muted'
                  : side === 'buy'
                  ? 'bg-green text-black'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              BUY
            </button>
            <button
              type="button"
              onClick={() => {
                setSide('sell');
                setErrorMsg(null);
              }}
              className={`h-8 text-xs font-semibold tracking-wider uppercase transition-colors ${
                side === 'sell'
                  ? 'bg-red text-white'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              SELL
            </button>
          </div>

          {/* Limit Price Input */}
          {orderType === 'limit' && (
            <div className="font-mono-tabular">
              <div className="flex justify-between items-center text-[11px] text-text-muted mb-1.5">
                <label className="uppercase tracking-wider">
                  LIMIT PRICE ({currencySymbol})
                </label>
                <span className="text-[10px]">
                  {side === 'buy' ? 'Fill if price ≤' : 'Fill if price ≥'}
                </span>
              </div>
              <input
                type="number"
                step="any"
                required
                value={limitPrice}
                onChange={(e) => setLimitPrice(e.target.value)}
                className="w-full h-9 px-3 bg-base border border-border text-xs text-text-primary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                placeholder={price ? price.toFixed(2) : '0.00'}
              />
            </div>
          )}

          {/* Trigger Price Input for Stop-Loss */}
          {orderType === 'stop_loss' && (
            <div className="font-mono-tabular">
              <div className="flex justify-between items-center text-[11px] text-text-muted mb-1.5">
                <label className="uppercase tracking-wider">
                  STOP TRIGGER PRICE ({currencySymbol})
                </label>
                <span className="text-[10px] text-accent">
                  Triggers sell if price ≤
                </span>
              </div>
              <input
                type="number"
                step="any"
                required
                value={triggerPrice}
                onChange={(e) => setTriggerPrice(e.target.value)}
                className="w-full h-9 px-3 bg-base border border-border text-xs text-text-primary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                placeholder={price ? (price * 0.95).toFixed(2) : '0.00'}
              />
            </div>
          )}

          {/* Quantity Input */}
          <div className="font-mono-tabular">
            <div className="flex justify-between items-center text-[11px] text-text-muted mb-1.5">
              <label className="uppercase tracking-wider">Quantity</label>
              {side === 'sell' && (
                <span>
                  Owned: <strong className="text-text-primary">{ownedQuantity}</strong>
                </span>
              )}
            </div>
            <div className="flex items-center space-x-2">
              <input
                type="number"
                min="1"
                step="1"
                required
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                className="flex-1 h-9 px-3 bg-base border border-border text-xs text-text-primary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>

            {/* Quick quantity presets */}
            <div className="grid grid-cols-4 gap-1 mt-1.5">
              {[1, 5, 10, 50].map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setQuantity(preset)}
                  className="h-6 bg-base border border-border text-[10px] text-text-muted hover:text-text-primary hover:border-text-muted transition-colors"
                >
                  +{preset}
                </button>
              ))}
            </div>
          </div>

          {/* Short Sell Intraday Warning Banner */}
          {isShortSellOperation && (
            <div className="p-2.5 bg-accent/10 border border-accent/40 text-[11px] space-y-1 font-mono-tabular">
              <div className="flex items-center space-x-1.5 font-bold text-accent">
                <span>⚡ INTRADAY SHORT POSITION (NSE/BSE)</span>
              </div>
              <div className="text-[10px] text-text-muted leading-tight">
                Short selling is strictly intraday on Indian equities. Auto squared-off at 15:15 IST before session close. 1x cash margin required.
              </div>
            </div>
          )}

          {/* Cover Buy Info Banner */}
          {isCoverBuyOperation && (
            <div className="p-2.5 bg-green/10 border border-green/40 text-[11px] space-y-1 font-mono-tabular">
              <div className="flex items-center space-x-1.5 font-bold text-green">
                <span>🛡️ COVER BUY (SQUARE-OFF SHORT)</span>
              </div>
              <div className="text-[10px] text-text-muted leading-tight">
                You currently hold a SHORT position of {shortQuantityHeld} shares. This BUY order will buy back shares to close your short liability.
              </div>
            </div>
          )}

          {/* Holding Duration Selector (BUY side only, when not covering a short) */}
          {side === 'buy' && !isCoverBuyOperation && (
            <div className="font-mono-tabular space-y-2">
              <div className="flex justify-between items-center text-[10px] text-text-muted uppercase tracking-wider">
                <span>HOLDING DURATION</span>
                <span className="text-[9px] text-[#707788]">
                  {durationMode === 'none'
                    ? 'OPEN-ENDED HOLD'
                    : durationMode === 'intraday'
                    ? 'AUTO SQUARES OFF TODAY'
                    : `SQUARES OFF IN ${durationMode === '1_day' ? '1 TRADING DAY' : `${customDays} TRADING DAYS`}`}
                </span>
              </div>

              {/* Segmented Duration Buttons */}
              <div className="grid grid-cols-4 gap-1 p-1 bg-base border border-border">
                {[
                  { id: 'none', label: 'NONE' },
                  { id: 'intraday', label: 'INTRADAY' },
                  { id: '1_day', label: '1 DAY' },
                  { id: 'custom', label: 'CUSTOM' },
                ].map((d) => {
                  const active = durationMode === d.id;
                  return (
                    <button
                      key={d.id}
                      type="button"
                      onClick={() => setDurationMode(d.id)}
                      className={`h-7 text-[10px] font-semibold tracking-wider uppercase transition-colors ${
                        active
                          ? 'bg-border text-text-primary'
                          : 'text-text-muted hover:text-text-primary'
                      }`}
                    >
                      {d.label}
                    </button>
                  );
                })}
              </div>

              {/* Custom Days Input Stepper */}
              {durationMode === 'custom' && (
                <div className="flex items-center space-x-2 pt-0.5">
                  <label className="text-[11px] text-text-muted uppercase">
                    Trading Days:
                  </label>
                  <div className="flex items-center space-x-1">
                    <button
                      type="button"
                      onClick={() => setCustomDays((prev) => Math.max(1, prev - 1))}
                      className="w-7 h-7 bg-base border border-border text-xs text-text-primary hover:bg-surface transition-colors flex items-center justify-center font-bold"
                    >
                      -
                    </button>
                    <input
                      type="number"
                      min="1"
                      max="90"
                      value={customDays}
                      onChange={(e) => {
                        const val = parseInt(e.target.value, 10);
                        if (!isNaN(val) && val >= 1) setCustomDays(val);
                      }}
                      className="w-14 h-7 bg-base border border-border text-center text-xs font-semibold text-text-primary focus:outline-none focus:border-accent"
                    />
                    <button
                      type="button"
                      onClick={() => setCustomDays((prev) => Math.min(90, prev + 1))}
                      className="w-7 h-7 bg-base border border-border text-xs text-text-primary hover:bg-surface transition-colors flex items-center justify-center font-bold"
                    >
                      +
                    </button>
                  </div>
                </div>
              )}

              {/* Resolved Square-Off Date & Shift Warning */}
              {durationMode !== 'none' && calculatedSquareOff && (
                <div className="p-2.5 bg-[#12151b] border border-border/80 text-[11px] space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-text-muted">AUTO SQUARE-OFF:</span>
                    <span className="text-accent font-semibold">
                      {calculatedSquareOff.formatted_date} (~{market === 'IN' ? '3:15 PM IST' : '3:45 PM ET'})
                    </span>
                  </div>
                  {calculatedSquareOff.is_shifted && calculatedSquareOff.shift_reason && (
                    <div className="text-[10px] text-amber-400/90 leading-tight pt-0.5">
                      ⚠️ {calculatedSquareOff.shift_reason}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Cost Breakdown */}
          <div className="p-3 bg-base border border-border space-y-1.5 text-xs font-mono-tabular">
            <div className="flex justify-between text-text-muted">
              <span>ORDER TYPE:</span>
              <span className="text-text-primary font-medium uppercase">{orderType.replace('_', '-')}</span>
            </div>
            <div className="flex justify-between text-text-muted">
              <span>
                {orderType === 'limit'
                  ? 'LIMIT PRICE:'
                  : orderType === 'stop_loss'
                  ? 'TRIGGER PRICE:'
                  : 'CURRENT PRICE:'}
              </span>
              <span className="text-text-primary">
                {currencySymbol}
                {effectivePrice.toFixed(2)}
              </span>
            </div>
            <div className="flex justify-between text-text-muted border-t border-border/60 pt-1.5">
              <span className="font-medium text-text-primary">
                {isShortSellOperation
                  ? 'SHORT SALE PROCEEDS (1X MARGIN):'
                  : isCoverBuyOperation
                  ? 'EST. COVER COST:'
                  : side === 'buy'
                  ? 'EST. TOTAL COST:'
                  : 'EST. PROCEEDS:'}
              </span>
              <span className="font-semibold text-text-primary">
                {currencySymbol}
                {totalCost.toLocaleString(currency === 'INR' ? 'en-IN' : 'en-US', {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </span>
            </div>
            {(side === 'buy' || isShortSellOperation) && (
              <div className="flex justify-between text-[11px] text-text-muted pt-0.5">
                <span>AVAILABLE CASH:</span>
                <span className={hasInsufficientFunds || hasInsufficientMargin ? 'text-red font-medium' : 'text-text-primary font-medium'}>
                  {currencySymbol}
                  {cashBalance.toLocaleString(currency === 'INR' ? 'en-IN' : 'en-US', {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </span>
              </div>
            )}
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={
              submitting ||
              (orderType === 'market' && !isMarketOpen) ||
              hasInsufficientFunds ||
              hasInsufficientMargin ||
              hasInsufficientHoldings
            }
            className={`w-full h-10 text-xs font-bold tracking-wider uppercase transition-colors select-none ${
              orderType === 'market' && !isMarketOpen
                ? 'bg-border text-text-muted cursor-not-allowed'
                : hasInsufficientFunds || hasInsufficientMargin || hasInsufficientHoldings
                ? 'bg-border text-text-muted cursor-not-allowed'
                : isCoverBuyOperation
                ? 'bg-green hover:bg-green/90 text-black disabled:opacity-50 disabled:cursor-not-allowed'
                : isShortSellOperation
                ? 'bg-red hover:bg-red/90 text-white disabled:opacity-50 disabled:cursor-not-allowed'
                : side === 'buy'
                ? 'bg-green hover:bg-green/90 text-black disabled:opacity-50 disabled:cursor-not-allowed'
                : 'bg-red hover:bg-red/90 text-white disabled:opacity-50 disabled:cursor-not-allowed'
            }`}
          >
            {submitting
              ? 'TRANSMITTING ORDER...'
              : orderType === 'market' && !isMarketOpen
              ? 'MARKET CLOSED'
              : hasInsufficientFunds
              ? 'INSUFFICIENT FUNDS'
              : hasInsufficientMargin
              ? 'INSUFFICIENT MARGIN'
              : hasInsufficientHoldings
              ? 'INSUFFICIENT HOLDINGS'
              : isCoverBuyOperation
              ? `COVER BUY ${quantity} ${upper} // ${currencySymbol}${totalCost.toFixed(2)}`
              : isShortSellOperation
              ? `SHORT SELL ${quantity} ${upper} // ${currencySymbol}${totalCost.toFixed(2)}`
              : orderType === 'market'
              ? `${side.toUpperCase()} ${quantity} ${upper} // ${currencySymbol}${totalCost.toFixed(2)}`
              : orderType === 'limit'
              ? `SUBMIT LIMIT ${side.toUpperCase()} // ${currencySymbol}${effectivePrice.toFixed(2)}`
              : `SUBMIT STOP-LOSS SELL // ${currencySymbol}${effectivePrice.toFixed(2)}`}
          </button>
        </form>
      )}
    </div>
  );
}
