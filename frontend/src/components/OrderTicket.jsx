import React, { useState, useEffect } from 'react';
import { X } from 'lucide-react';
import { placeOrder } from '../api/client';
import { LivePriceChart } from './LivePriceChart';

export function OrderTicket({
  ticker,
  quote,
  wallet,
  onClose,
  onOrderExecuted,
  onOpenWalletSetup,
}) {
  const [side, setSide] = useState('buy'); // 'buy' | 'sell'
  const [quantity, setQuantity] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [filledOrder, setFilledOrder] = useState(null);

  // Reset state when ticker changes
  useEffect(() => {
    setSide('buy');
    setQuantity(1);
    setErrorMsg(null);
    setFilledOrder(null);
  }, [ticker]);

  if (!ticker) return null;

  const upper = ticker.toUpperCase();
  const isIndian = upper.endsWith('.NS') || upper.endsWith('.BO');
  const market = isIndian ? 'IN' : 'US';
  const currency = isIndian ? 'INR' : 'USD';
  const currencySymbol = isIndian ? '₹' : '$';
  const exchange = isIndian ? (upper.endsWith('.BO') ? 'BSE' : 'NSE') : 'NASDAQ';

  const price = quote?.current_price ?? 0;
  const isMarketOpen = quote?.market_status === 'open';
  const totalCost = Number((price * (Number(quantity) || 0)).toFixed(2));
  const cashBalance = wallet?.current_cash_balance ?? 0;

  // Check available holding if selling
  const existingHolding = wallet?.holdings?.find(
    (h) => h.ticker.toUpperCase() === upper
  );
  const ownedQuantity = existingHolding?.quantity ?? 0;

  // Validation checks
  const hasInsufficientFunds = side === 'buy' && totalCost > cashBalance;
  const hasInsufficientHoldings = side === 'sell' && (Number(quantity) || 0) > ownedQuantity;

  async function handleOrderSubmit(e) {
    e.preventDefault();
    setErrorMsg(null);
    setFilledOrder(null);

    const qty = Number(quantity);
    if (!qty || qty <= 0) {
      setErrorMsg('Please enter a valid quantity greater than zero.');
      return;
    }

    if (!isMarketOpen) {
      setErrorMsg('Market is currently closed. Orders cannot be submitted.');
      return;
    }

    if (hasInsufficientFunds) {
      setErrorMsg(
        `Insufficient funds. Order total is ${currencySymbol}${totalCost.toLocaleString()} but available cash is ${currencySymbol}${cashBalance.toLocaleString()}.`
      );
      return;
    }

    if (hasInsufficientHoldings) {
      setErrorMsg(
        `Insufficient holdings. You only own ${ownedQuantity} shares of ${upper}.`
      );
      return;
    }

    setSubmitting(true);

    try {
      const order = await placeOrder({
        market,
        ticker: upper,
        side,
        quantity: qty,
      });

      if (order.status === 'filled') {
        setFilledOrder(order);
        if (onOrderExecuted) {
          onOrderExecuted(order);
        }
      } else {
        // Map reject_reason to user-friendly terminal explanation
        const reasons = {
          market_closed: 'Market is closed. Trading is only permitted during regular market hours.',
          insufficient_funds: `Insufficient funds in ${currency} wallet to complete this purchase.`,
          insufficient_holdings: `Insufficient holdings. You do not hold enough shares of ${upper} to sell.`,
          invalid_ticker: `Invalid ticker symbol. Unable to fetch executable quote from exchange.`,
          wrong_market: `Ticker / wallet mismatch.`,
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
      ) : filledOrder ? (
        <div className="p-5 text-center space-y-4 font-mono-tabular">
          <div className="inline-flex items-center space-x-2 text-xs font-semibold tracking-wider text-green uppercase">
            <span className="w-2 h-2 rounded-full bg-green shadow-[0_0_6px_rgba(0,192,118,0.6)]" />
            <span>
              ORDER FILLED @ {currencySymbol}
              {Number(filledOrder.executed_price).toFixed(2)}
            </span>
          </div>
          <div>
            <p className="text-[11px] text-text-muted">
              {filledOrder.side.toUpperCase()} {filledOrder.quantity} {upper}
            </p>
          </div>

          <div className="p-3 bg-base border border-border text-left text-xs space-y-1">
            <div className="flex justify-between text-text-muted">
              <span>ORDER ID:</span>
              <span className="text-text-primary">#{filledOrder.id}</span>
            </div>
            <div className="flex justify-between text-text-muted">
              <span>STATUS:</span>
              <span className="text-green uppercase font-semibold">FILLED</span>
            </div>
            <div className="flex justify-between text-text-muted">
              <span>TOTAL:</span>
              <span className="text-text-primary">
                {currencySymbol}
                {(filledOrder.executed_price * filledOrder.quantity).toFixed(2)}
              </span>
            </div>
          </div>

          <button
            onClick={() => setFilledOrder(null)}
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

          {/* Buy / Sell Segmented Control */}
          <div className="grid grid-cols-2 gap-1 p-1 bg-base border border-border">
            <button
              type="button"
              onClick={() => {
                setSide('buy');
                setErrorMsg(null);
              }}
              className={`h-8 text-xs font-semibold tracking-wider uppercase transition-colors ${
                side === 'buy'
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

          {/* Cost Breakdown */}
          <div className="p-3 bg-base border border-border space-y-1.5 text-xs font-mono-tabular">
            <div className="flex justify-between text-text-muted">
              <span>ORDER TYPE:</span>
              <span className="text-text-primary font-medium">MARKET</span>
            </div>
            <div className="flex justify-between text-text-muted">
              <span>UNIT PRICE:</span>
              <span className="text-text-primary">
                {currencySymbol}
                {price.toFixed(2)}
              </span>
            </div>
            <div className="flex justify-between text-text-muted border-t border-border/60 pt-1.5">
              <span className="font-medium text-text-primary">EST. TOTAL:</span>
              <span className="font-semibold text-text-primary">
                {currencySymbol}
                {totalCost.toLocaleString(currency === 'INR' ? 'en-IN' : 'en-US', {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </span>
            </div>
            <div className="flex justify-between text-[11px] text-text-muted pt-0.5">
              <span>AVAILABLE CASH:</span>
              <span className={hasInsufficientFunds ? 'text-red font-medium' : 'text-text-primary font-medium'}>
                {currencySymbol}
                {cashBalance.toLocaleString(currency === 'INR' ? 'en-IN' : 'en-US', {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </span>
            </div>
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={submitting || !isMarketOpen || hasInsufficientFunds || hasInsufficientHoldings}
            className={`w-full h-10 text-xs font-bold tracking-wider uppercase transition-colors select-none ${
              !isMarketOpen
                ? 'bg-border text-text-muted cursor-not-allowed'
                : side === 'buy'
                ? 'bg-green hover:bg-green/90 text-black disabled:opacity-50 disabled:cursor-not-allowed'
                : 'bg-red hover:bg-red/90 text-white disabled:opacity-50 disabled:cursor-not-allowed'
            }`}
          >
            {submitting
              ? 'TRANSMITTING ORDER...'
              : !isMarketOpen
              ? 'MARKET CLOSED'
              : hasInsufficientFunds
              ? 'INSUFFICIENT FUNDS'
              : hasInsufficientHoldings
              ? 'INSUFFICIENT HOLDINGS'
              : `${side.toUpperCase()} ${quantity} ${upper} // ${currencySymbol}${totalCost.toFixed(2)}`}
          </button>
        </form>
      )}
    </div>
  );
}
