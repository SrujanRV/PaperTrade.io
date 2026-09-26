import React, { useState, useEffect, useRef, useCallback } from 'react';
import { X, Layers, ShieldCheck, AlertTriangle } from 'lucide-react';
import { placeOrder, placeDerivativeOrder, calculateSquareOffDate } from '../api/client';
import { LivePriceChart } from './LivePriceChart';

function formatMoney(amount, currency = 'USD') {
  if (amount === undefined || amount === null || isNaN(amount)) return '0.00';
  const locale = currency === 'INR' ? 'en-IN' : 'en-US';
  return Number(amount).toLocaleString(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function OrderTicket({
  ticker,
  contract = null,
  quote,
  wallet,
  onClose,
  onOrderExecuted,
  onOpenWalletSetup,
  onOpenChart,
}) {
  // Determine if this ticket is in derivative mode
  const effectiveContract = contract || (ticker && typeof ticker === 'object' && ticker.isDerivative ? ticker : null);
  const isDerivative = Boolean(effectiveContract);

  // Common order state
  const [orderType, setOrderType] = useState('market'); // 'market' | 'limit' | 'stop_loss'
  const [side, setSide] = useState('buy'); // 'buy' | 'sell'
  const [quantity, setQuantity] = useState(1);
  const [limitPrice, setLimitPrice] = useState('');
  const [triggerPrice, setTriggerPrice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [completedOrder, setCompletedOrder] = useState(null);

  // Derivative-specific action state
  // Options: 'buy_to_open' | 'sell_to_open' | 'buy_to_close' | 'sell_to_close'
  // Futures: 'long' | 'short' | 'close'
  const [derivAction, setDerivAction] = useState('buy_to_open');

  // Holding duration state (for equities)
  const [durationMode, setDurationMode] = useState('none');
  const [customDays, setCustomDays] = useState(2);
  const [calculatedSquareOff, setCalculatedSquareOff] = useState(null);
  const squareOffCacheRef = useRef(new Map());
  const debounceTimerRef = useRef(null);

  // Reset state when ticker or contract changes
  useEffect(() => {
    setOrderType('market');
    setQuantity(1);
    setErrorMsg(null);
    setCompletedOrder(null);
    setDurationMode('none');
    setCustomDays(2);
    setCalculatedSquareOff(null);

    if (isDerivative) {
      const initAct = effectiveContract.initial_action ||
        (effectiveContract.instrument_type === 'future' ? 'long' : 'buy_to_open');
      setDerivAction(initAct);
      if (effectiveContract.quantity) {
        setQuantity(effectiveContract.quantity);
      }
      const initialP = effectiveContract.current_price || effectiveContract.price || 0;
      setLimitPrice(initialP > 0 ? String(initialP) : '');
    } else {
      setSide('buy');
      setLimitPrice(quote?.current_price ? String(quote.current_price) : '');
      setTriggerPrice(quote?.current_price ? String(Number((quote.current_price * 0.95).toFixed(2))) : '');
    }
  }, [ticker, contract, isDerivative, effectiveContract]);

  // Keep limit price initialized when quote arrives
  useEffect(() => {
    if (!isDerivative && quote?.current_price && !limitPrice) {
      setLimitPrice(String(quote.current_price));
      setTriggerPrice(String(Number((quote.current_price * 0.95).toFixed(2))));
    }
  }, [quote?.current_price, isDerivative, limitPrice]);

  if (!ticker && !contract) return null;

  // ══════════════════════════════════════════════════════════════════════════
  // DERIVATIVE MODE LOGIC
  // ══════════════════════════════════════════════════════════════════════════
  if (isDerivative) {
    const instType = effectiveContract.instrument_type; // 'option' | 'future'
    const optType = effectiveContract.option_type; // 'call' | 'put'
    const lotSize = effectiveContract.lot_size || 1;
    const mkt = effectiveContract.market || 'IN';
    const curr = mkt === 'IN' ? 'INR' : 'USD';
    const currSym = mkt === 'IN' ? '₹' : '$';
    const und = effectiveContract.underlying || '';
    const contractSym = effectiveContract.symbol || `${und} CONTRACT`;

    const liveP = (() => {
      if (instType === 'option') {
        const isBuying = (derivAction === 'buy_to_open' || derivAction === 'buy_to_close');
        if (isBuying) {
          if (effectiveContract.ask && effectiveContract.ask > 0) return effectiveContract.ask;
          if (effectiveContract.price && effectiveContract.price > 0) return effectiveContract.price;
          if (effectiveContract.bid && effectiveContract.bid > 0) return effectiveContract.bid;
        } else {
          if (effectiveContract.bid && effectiveContract.bid > 0) return effectiveContract.bid;
          if (effectiveContract.price && effectiveContract.price > 0) return effectiveContract.price;
          if (effectiveContract.ask && effectiveContract.ask > 0) return effectiveContract.ask;
        }
      }
      return effectiveContract.current_price || effectiveContract.price || 0;
    })();
    const effP = orderType === 'limit' && Number(limitPrice) > 0 ? Number(limitPrice) : liveP;
    const numLots = Math.max(1, Number(quantity) || 1);
    const totalUnits = numLots * lotSize;

    const cashBalance = wallet?.current_cash_balance ?? 0;
    const marginUsed = wallet?.margin_used ?? 0;
    const availableBuyingPower = wallet?.available_buying_power ?? Math.max(0, cashBalance - marginUsed);

    // Covered Call check: does user hold underlying equity in this wallet?
    const undUpper = und.toUpperCase();
    const undHolding = wallet?.holdings?.find(
      (h) => !h.is_short && (h.ticker.toUpperCase() === undUpper || h.ticker.toUpperCase() === `${undUpper}.NS` || h.ticker.toUpperCase() === `${undUpper}.BO`)
    );
    const sharesOwned = undHolding ? undHolding.quantity : 0;
    const isCovered = (instType === 'option' && derivAction === 'sell_to_open') && (sharesOwned >= totalUnits);

    // Margin Requirements
    let derivMarginReq = 0;
    let derivTotalCost = 0;
    let hasInsufficientCash = false;
    let hasInsufficientMargin = false;

    if (instType === 'option') {
      if (derivAction === 'buy_to_open') {
        derivTotalCost = Number((effP * totalUnits).toFixed(2));
        derivMarginReq = 0;
        hasInsufficientCash = derivTotalCost > cashBalance;
      } else if (derivAction === 'sell_to_open') {
        if (isCovered) {
          derivMarginReq = 0;
        } else {
          // Naked Write: strictly 20% of spot notional
          const spotP = effectiveContract.underlying_price || effP;
          const notional = spotP * totalUnits;
          derivMarginReq = Number((0.20 * notional).toFixed(2));
          hasInsufficientMargin = derivMarginReq > availableBuyingPower;
        }
      }
    } else {
      // Future: 12% initial margin on notional
      if (derivAction === 'long' || derivAction === 'short') {
        const notional = effP * totalUnits;
        derivMarginReq = Number((0.12 * notional).toFixed(2));
        hasInsufficientMargin = derivMarginReq > availableBuyingPower;
      }
    }

    const handleDerivSubmit = async (e) => {
      e.preventDefault();
      if (hasInsufficientCash) {
        setErrorMsg(`Insufficient cash balance. Premium requires ${currSym}${formatMoney(derivTotalCost, curr)}, but available cash is ${currSym}${formatMoney(cashBalance, curr)}.`);
        return;
      }
      if (hasInsufficientMargin) {
        setErrorMsg(`Insufficient buying power. Order requires ${currSym}${formatMoney(derivMarginReq, curr)} margin collateral, but available buying power is ${currSym}${formatMoney(availableBuyingPower, curr)}.`);
        return;
      }

      setSubmitting(true);
      setErrorMsg(null);

      try {
        let effSide = 'buy';
        let effAction = 'buy_to_open';

        if (instType === 'option') {
          if (derivAction === 'buy_to_open') {
            effSide = 'buy';
            effAction = 'buy_to_open';
          } else if (derivAction === 'sell_to_open') {
            effSide = 'sell';
            effAction = 'sell_to_open';
          } else if (derivAction === 'buy_to_close') {
            effSide = 'buy';
            effAction = 'buy_to_close';
          } else if (derivAction === 'sell_to_close') {
            effSide = 'sell';
            effAction = 'sell_to_close';
          }
        } else {
          // Future
          if (derivAction === 'long') {
            effSide = 'buy';
            effAction = 'buy_to_open';
          } else if (derivAction === 'short') {
            effSide = 'sell';
            effAction = 'sell_to_open';
          } else if (derivAction === 'close') {
            const isShortPos = effectiveContract.existing_side === 'short';
            effSide = isShortPos ? 'buy' : 'sell';
            effAction = isShortPos ? 'buy_to_close' : 'sell_to_close';
          }
        }

        const payload = {
          market: mkt,
          contract_id: effectiveContract.contract_id || null,
          underlying: und,
          instrument_type: instType,
          option_type: optType,
          strike_price: effectiveContract.strike_price,
          expiry_date: effectiveContract.expiry_date,
          lot_size: lotSize,
          symbol: effectiveContract.symbol,
          side: effSide,
          action: effAction,
          quantity: numLots,
          order_type: orderType,
          price: Number(effP) > 0 ? Number(effP) : (orderType === 'limit' ? Number(limitPrice) : null),
          bid: effectiveContract.bid || null,
          ask: effectiveContract.ask || null,
          underlying_price: effectiveContract.underlying_price,
        };

        const resOrder = await placeDerivativeOrder(payload);
        if (resOrder.status === 'filled') {
          setCompletedOrder(resOrder);
          if (onOrderExecuted) onOrderExecuted(resOrder);
        } else {
          setErrorMsg(resOrder.reject_reason || 'Derivative order rejected');
        }
      } catch (err) {
        setErrorMsg(err.message || 'Derivative order execution failed');
      } finally {
        setSubmitting(false);
      }
    };

    return (
      <div className="w-full lg:w-96 bg-surface border border-border flex flex-col font-sans select-none shrink-0 shadow-lg">
        {/* Header Bar */}
        <div className="h-10 px-4 bg-[#111317] border-b border-border flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Layers className="w-4 h-4 text-accent" />
            <span className="text-xs font-semibold uppercase tracking-wider text-text-primary">
              F&O ORDER TICKET
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-text-muted hover:text-text-primary hover:bg-base rounded transition-colors"
          >
            <X size={15} />
          </button>
        </div>

        {/* Contract Details Header */}
        <div className="p-4 border-b border-border bg-[#14161b]">
          <div className="flex items-center justify-between">
            <span className="font-bold text-sm text-text-primary">
              {contractSym}
            </span>
            {instType === 'option' ? (
              <span className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono-tabular uppercase tracking-wider border ${
                optType === 'call'
                  ? 'bg-emerald-950/40 text-emerald-400 border-emerald-500/40'
                  : 'bg-red-950/40 text-red border-red/40'
              }`}>
                OPTION {optType?.toUpperCase()}
              </span>
            ) : (
              <span className="px-2 py-0.5 rounded text-[10px] font-bold font-mono-tabular uppercase tracking-wider border bg-accent/20 text-accent border-accent/40">
                FUTURES
              </span>
            )}
          </div>

          <div className="flex items-center justify-between mt-2 font-mono-tabular text-xs">
            <span className="text-text-muted">
              {effectiveContract.expiry_date ? `Exp: ${effectiveContract.expiry_date}` : 'Continuous / Perpetual'}
            </span>
            <span className="text-text-primary font-bold text-sm">
              {currSym}{formatMoney(liveP, curr)}
            </span>
          </div>
          {(effectiveContract.bid != null || effectiveContract.ask != null) && (
            <div className="flex items-center justify-between mt-1 text-[11px] font-mono-tabular text-text-muted">
              <span>Bid: <span className="text-emerald-400 font-semibold">{currSym}{formatMoney(effectiveContract.bid || 0, curr)}</span></span>
              <span>Ask: <span className="text-rose-400 font-semibold">{currSym}{formatMoney(effectiveContract.ask || 0, curr)}</span></span>
            </div>
          )}
        </div>

        {/* Uninitialized Wallet Warning */}
        {!wallet ? (
          <div className="p-6 text-center space-y-4 font-mono-tabular">
            <div className="text-xs text-text-muted">
              NO {mkt === 'IN' ? 'INDIAN' : 'US'} WALLET INITIALIZED
            </div>
            {onOpenWalletSetup && (
              <button
                type="button"
                onClick={() => onOpenWalletSetup(mkt)}
                className="w-full h-9 bg-accent hover:bg-accent/90 text-white text-xs font-semibold uppercase tracking-wider font-sans"
              >
                INITIALIZE {mkt} WALLET
              </button>
            )}
          </div>
        ) : completedOrder ? (
          /* Confirmation Screen */
          <div className="p-5 text-center space-y-4 font-mono-tabular">
            <div className="inline-flex items-center space-x-2 text-xs font-semibold tracking-wider text-green uppercase">
              <span className="w-2 h-2 rounded-full bg-green shadow-[0_0_6px_rgba(0,192,118,0.6)]" />
              <span>ORDER FILLED @ {currSym}{formatMoney(completedOrder.executed_price, curr)}</span>
            </div>
            <div className="p-3 bg-base border border-border text-left text-xs space-y-1">
              <div className="flex justify-between text-text-muted">
                <span>ORDER ID:</span>
                <span className="text-text-primary">#{completedOrder.id}</span>
              </div>
              <div className="flex justify-between text-text-muted">
                <span>CONTRACT:</span>
                <span className="text-text-primary font-bold">{contractSym}</span>
              </div>
              <div className="flex justify-between text-text-muted">
                <span>ACTION:</span>
                <span className="text-accent uppercase font-bold">{completedOrder.action}</span>
              </div>
              <div className="flex justify-between text-text-muted">
                <span>LOTS / UNITS:</span>
                <span className="text-text-primary">{completedOrder.quantity} Lots ({completedOrder.quantity * lotSize} units)</span>
              </div>
              <div className="flex justify-between text-text-muted">
                <span>MARGIN LOCKED:</span>
                <span className="text-amber-400 font-bold">{currSym}{formatMoney(completedOrder.margin_required, curr)}</span>
              </div>
            </div>
            <button
              onClick={() => setCompletedOrder(null)}
              className="w-full h-8 bg-surface-hover hover:bg-border text-xs text-text-primary uppercase tracking-wider font-semibold transition-colors font-sans"
            >
              PLACE ANOTHER ORDER
            </button>
          </div>
        ) : (
          /* Derivative Order Form */
          <form onSubmit={handleDerivSubmit} className="p-4 space-y-4 font-sans">
            {errorMsg && (
              <div className="p-2.5 bg-red/10 border border-red/40 text-xs font-mono-tabular flex items-start space-x-2">
                <span className="w-1.5 h-1.5 rounded-full bg-red shrink-0 mt-1.5" />
                <div className="leading-snug">
                  <span className="font-semibold block uppercase text-red">ORDER REJECTED</span>
                  <span className="text-text-primary text-[11px] mt-0.5 block">{errorMsg}</span>
                </div>
              </div>
            )}

            {/* Action Selector Adapted for Derivatives */}
            <div>
              <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1 font-mono-tabular">
                DERIVATIVE ACTION
              </div>
              {instType === 'option' ? (
                <div className="grid grid-cols-2 gap-1 p-1 bg-base border border-border font-mono-tabular">
                  {[
                    { id: 'buy_to_open', label: 'BUY TO OPEN' },
                    { id: 'sell_to_open', label: 'SELL (WRITE)' },
                    { id: 'buy_to_close', label: 'BUY TO CLOSE' },
                    { id: 'sell_to_close', label: 'SELL TO CLOSE' },
                  ].map((act) => (
                    <button
                      key={act.id}
                      type="button"
                      onClick={() => {
                        setDerivAction(act.id);
                        setErrorMsg(null);
                      }}
                      className={`h-7 text-[10px] font-bold tracking-wider uppercase transition-colors ${
                        derivAction === act.id
                          ? (act.id.startsWith('buy') ? 'bg-green text-black' : 'bg-red text-white')
                          : 'text-text-muted hover:text-text-primary'
                      }`}
                    >
                      {act.label}
                    </button>
                  ))}
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-1 p-1 bg-base border border-border font-mono-tabular">
                  {[
                    { id: 'long', label: 'LONG (BUY)' },
                    { id: 'short', label: 'SHORT (SELL)' },
                    { id: 'close', label: 'CLOSE POS' },
                  ].map((act) => (
                    <button
                      key={act.id}
                      type="button"
                      onClick={() => {
                        setDerivAction(act.id);
                        setErrorMsg(null);
                      }}
                      className={`h-7 text-[10px] font-bold tracking-wider uppercase transition-colors ${
                        derivAction === act.id
                          ? (act.id === 'long' ? 'bg-green text-black' : act.id === 'short' ? 'bg-red text-white' : 'bg-accent text-white')
                          : 'text-text-muted hover:text-text-primary'
                      }`}
                    >
                      {act.label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Quantity in LOTS with Multiplier */}
            <div>
              <div className="flex justify-between items-center text-[11px] text-text-muted mb-1 font-mono-tabular">
                <span className="uppercase tracking-wider">QUANTITY (IN LOTS)</span>
                <span className="text-[10px] text-accent font-semibold">1 LOT = {lotSize} UNITS</span>
              </div>
              <div className="grid grid-cols-5 gap-1.5">
                <input
                  type="number"
                  min="1"
                  step="1"
                  required
                  value={quantity}
                  onChange={(e) => setQuantity(Math.max(1, parseInt(e.target.value) || 1))}
                  className="col-span-2 h-9 px-3 bg-base border border-border text-xs text-text-primary font-mono-tabular focus:border-accent focus:outline-none"
                />
                {[1, 2, 5].map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => setQuantity(preset)}
                    className={`h-9 text-xs font-mono-tabular border border-border transition-colors ${
                      Number(quantity) === preset ? 'bg-[#232731] text-accent font-bold' : 'bg-base text-text-muted hover:text-text-primary'
                    }`}
                  >
                    {preset}L
                  </button>
                ))}
              </div>
              <div className="text-[11px] text-text-muted mt-1 font-mono-tabular">
                TOTAL CONTRACT UNITS: <span className="text-text-primary font-bold">{totalUnits}</span>
              </div>
            </div>

            {/* Order Type: Market vs Limit */}
            <div>
              <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1 font-mono-tabular">
                ORDER TYPE
              </div>
              <div className="grid grid-cols-2 gap-1 p-1 bg-base border border-border font-mono-tabular">
                <button
                  type="button"
                  onClick={() => setOrderType('market')}
                  className={`h-7 text-[10px] font-semibold tracking-wider uppercase transition-colors ${
                    orderType === 'market' ? 'bg-[#232731] text-text-primary' : 'text-text-muted hover:text-text-primary'
                  }`}
                >
                  MARKET
                </button>
                <button
                  type="button"
                  onClick={() => setOrderType('limit')}
                  className={`h-7 text-[10px] font-semibold tracking-wider uppercase transition-colors ${
                    orderType === 'limit' ? 'bg-[#232731] text-text-primary' : 'text-text-muted hover:text-text-primary'
                  }`}
                >
                  LIMIT
                </button>
              </div>
            </div>

            {orderType === 'limit' && (
              <div className="font-mono-tabular">
                <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1 block">
                  LIMIT PRICE ({currSym})
                </label>
                <input
                  type="number"
                  step="any"
                  required
                  value={limitPrice}
                  onChange={(e) => setLimitPrice(e.target.value)}
                  className="w-full h-9 px-3 bg-base border border-border text-xs text-text-primary focus:border-accent focus:outline-none"
                  placeholder={liveP ? String(liveP) : '0.00'}
                />
              </div>
            )}

            {/* ── CRITICAL PRE-SUBMISSION MARGIN IMPACT BANNER ── */}
            <div className="font-mono-tabular">
              {instType === 'option' ? (
                derivAction === 'sell_to_open' ? (
                  isCovered ? (
                    <div className="p-3 bg-emerald-950/20 border border-emerald-500/40 text-emerald-400 text-xs space-y-1">
                      <div className="flex items-center space-x-1.5 font-bold">
                        <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
                        <span>COVERED CALL WRITE</span>
                      </div>
                      <div className="text-[11px] text-text-primary">
                        Using {totalUnits} units of {und} from your holdings ({sharesOwned} held). No additional margin required.
                      </div>
                    </div>
                  ) : (
                    <div className={`p-3 border text-xs space-y-1 ${
                      hasInsufficientMargin
                        ? 'bg-red/10 border-red/40 text-red'
                        : 'bg-amber-500/10 border-amber-500/40 text-amber-400'
                    }`}>
                      <div className="flex items-center space-x-1.5 font-bold">
                        <AlertTriangle className="w-4 h-4 shrink-0" />
                        <span>NAKED WRITE (20% SPOT NOTIONAL)</span>
                      </div>
                      <div className="text-[11px] text-text-primary">
                        Requires <span className="font-bold text-amber-400">{currSym}{formatMoney(derivMarginReq, curr)}</span> margin collateral.
                      </div>
                      <div className="text-[10px] text-text-muted flex justify-between">
                        <span>AVAILABLE BUYING POWER:</span>
                        <span className={hasInsufficientMargin ? 'text-red font-bold' : 'text-text-primary font-bold'}>
                          {currSym}{formatMoney(availableBuyingPower, curr)}
                        </span>
                      </div>
                    </div>
                  )
                ) : derivAction === 'buy_to_open' ? (
                  <div className={`p-3 border text-xs space-y-1 ${
                    hasInsufficientCash ? 'bg-red/10 border-red/40 text-red' : 'bg-base border-border text-text-primary'
                  }`}>
                    <div className="flex justify-between">
                      <span className="text-text-muted">PREMIUM PAYABLE (UPFRONT):</span>
                      <span className="font-bold text-green">{currSym}{formatMoney(derivTotalCost, curr)}</span>
                    </div>
                    <div className="text-[10px] text-text-muted">
                      Paid directly from cash balance. 0 margin required.
                    </div>
                    <div className="flex justify-between text-[10px] text-text-muted pt-1 border-t border-border/40">
                      <span>CASH AVAILABLE:</span>
                      <span className={hasInsufficientCash ? 'text-red font-bold' : 'text-text-primary font-bold'}>
                        {currSym}{formatMoney(cashBalance, curr)}
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="p-2.5 bg-base border border-border text-xs text-text-muted">
                    CLOSING POSITION — Settles realized P&L and releases locked margin.
                  </div>
                )
              ) : (
                /* Futures Margin Banner */
                derivAction === 'close' ? (
                  <div className="p-2.5 bg-base border border-border text-xs text-text-muted">
                    CLOSING POSITION — Settles final P&L into cash and releases all locked margin.
                  </div>
                ) : (
                  <div className={`p-3 border text-xs space-y-1 ${
                    hasInsufficientMargin ? 'bg-red/10 border-red/40 text-red' : 'bg-amber-500/10 border-amber-500/40 text-amber-400'
                  }`}>
                    <div className="flex items-center space-x-1.5 font-bold">
                      <AlertTriangle className="w-4 h-4 shrink-0" />
                      <span>INITIAL MARGIN (12% NOTIONAL)</span>
                    </div>
                    <div className="text-[11px] text-text-primary">
                      Requires <span className="font-bold text-amber-400">{currSym}{formatMoney(derivMarginReq, curr)}</span> margin collateral. Daily cash MTM applies.
                    </div>
                    <div className="text-[10px] text-text-muted flex justify-between">
                      <span>AVAILABLE BUYING POWER:</span>
                      <span className={hasInsufficientMargin ? 'text-red font-bold' : 'text-text-primary font-bold'}>
                        {currSym}{formatMoney(availableBuyingPower, curr)}
                      </span>
                    </div>
                  </div>
                )
              )}
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={submitting || hasInsufficientCash || hasInsufficientMargin}
              className={`w-full h-10 text-xs font-bold tracking-wider uppercase transition-colors select-none font-mono-tabular ${
                hasInsufficientCash || hasInsufficientMargin
                  ? 'bg-border text-text-muted cursor-not-allowed'
                  : derivAction.startsWith('buy') || derivAction === 'long'
                  ? 'bg-green hover:bg-green/90 text-black'
                  : derivAction === 'close' || derivAction.endsWith('close')
                  ? 'bg-accent hover:bg-accent/90 text-white'
                  : 'bg-red hover:bg-red/90 text-white'
              }`}
            >
              {submitting
                ? 'TRANSMITTING ORDER...'
                : hasInsufficientCash
                ? 'INSUFFICIENT FUNDS'
                : hasInsufficientMargin
                ? 'INSUFFICIENT MARGIN'
                : instType === 'option'
                ? (derivAction === 'buy_to_open' ? `BUY TO OPEN (${quantity} ${quantity === 1 ? 'LOT' : 'LOTS'})`
                  : derivAction === 'sell_to_open' ? `SELL TO OPEN (${isCovered ? 'COVERED' : 'NAKED'})`
                  : derivAction === 'buy_to_close' ? 'BUY TO CLOSE'
                  : 'SELL TO CLOSE')
                : (derivAction === 'long' ? `GO LONG (${quantity} ${quantity === 1 ? 'LOT' : 'LOTS'})`
                  : derivAction === 'short' ? `GO SHORT (${quantity} ${quantity === 1 ? 'LOT' : 'LOTS'})`
                  : 'CLOSE POSITION')}
            </button>
          </form>
        )}
      </div>
    );
  }

  // ══════════════════════════════════════════════════════════════════════════
  // EQUITY TICKET MODE (Standard Watchlist / Holding Ticket)
  // ══════════════════════════════════════════════════════════════════════════
  const upper = ticker.toUpperCase();
  const isIndian = upper.endsWith('.NS') || upper.endsWith('.BO');
  const market = isIndian ? 'IN' : 'US';
  const currency = isIndian ? 'INR' : 'USD';
  const currencySymbol = isIndian ? '₹' : '$';
  const exchange = isIndian ? (upper.endsWith('.BO') ? 'BSE' : 'NSE') : 'NASDAQ';

  const price = quote?.current_price ?? 0;
  const isMarketOpen = quote?.market_status === 'open';

  const effectivePrice =
    orderType === 'limit' && Number(limitPrice) > 0
      ? Number(limitPrice)
      : orderType === 'stop_loss' && Number(triggerPrice) > 0
      ? Number(triggerPrice)
      : price;

  const totalCost = Number((effectivePrice * (Number(quantity) || 0)).toFixed(2));
  const cashBalance = wallet?.current_cash_balance ?? 0;

  const existingHolding = wallet?.holdings?.find(
    (h) => h.ticker.toUpperCase() === upper
  );
  const isHoldingShort = Boolean(existingHolding?.is_short);
  const ownedQuantity = isHoldingShort ? 0 : (existingHolding?.quantity ?? 0);

  const isShortSellOperation =
    side === 'sell' &&
    orderType !== 'stop_loss' &&
    ((Number(quantity) || 0) > ownedQuantity || isHoldingShort);

  const shortQty = isHoldingShort
    ? (Number(quantity) || 0)
    : Math.max(0, (Number(quantity) || 0) - ownedQuantity);

  const isCoverBuyOperation = side === 'buy' && isHoldingShort;
  const isUSShort = market === 'US' && isShortSellOperation;
  const isINShort = market === 'IN' && isShortSellOperation;

  const requiredShortMargin = isUSShort
    ? Number((1.5 * effectivePrice * shortQty).toFixed(2))
    : isINShort
    ? Number((effectivePrice * shortQty).toFixed(2))
    : 0;

  const availableBuyingPower = market === 'US'
    ? (wallet?.available_buying_power ?? Math.max(0, (wallet?.current_cash_balance ?? 0) - (wallet?.margin_used ?? 0)))
    : cashBalance;

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
    const isDurationApplicable =
      (side === 'buy' && !isCoverBuyOperation) || (isShortSellOperation && market === 'US');
    if (!isDurationApplicable || durationMode === 'none') {
      setCalculatedSquareOff(null);
      return;
    }

    const days = durationMode === 'intraday' ? 0 : durationMode === '1_day' ? 1 : customDays;
    const cacheKey = `${market}:${days}`;

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
  }, [side, isCoverBuyOperation, isShortSellOperation, durationMode, customDays, market, fetchResolvedDate]);

  const hasInsufficientFunds = side === 'buy' && totalCost > cashBalance;
  const hasInsufficientMargin = isShortSellOperation && requiredShortMargin > availableBuyingPower;
  const hasInsufficientHoldings =
    orderType === 'stop_loss' && (Number(quantity) || 0) > ownedQuantity;

  async function handleOrderSubmit(e) {
    e.preventDefault();
    if (orderType === 'market' && !isMarketOpen) {
      setErrorMsg('Market is closed. Market orders are only accepted during active trading hours.');
      return;
    }
    const qty = Number(quantity);
    if (!qty || qty <= 0) {
      setErrorMsg('Quantity must be a positive integer.');
      return;
    }
    if (hasInsufficientFunds) {
      setErrorMsg(`Insufficient funds. Estimated total is ${currencySymbol}${totalCost.toLocaleString()} but available cash is ${currencySymbol}${cashBalance.toLocaleString()}.`);
      return;
    }
    if (hasInsufficientMargin) {
      setErrorMsg(isUSShort
        ? `Insufficient buying power. Opening this short position requires 150% initial margin of ${currencySymbol}${requiredShortMargin.toLocaleString()}, but available buying power is ${currencySymbol}${availableBuyingPower.toLocaleString()}.`
        : `Insufficient margin. Opening this short position requires 1x cash margin of ${currencySymbol}${requiredShortMargin.toLocaleString()}, but available cash is ${currencySymbol}${cashBalance.toLocaleString()}.`
      );
      return;
    }
    if (hasInsufficientHoldings) {
      setErrorMsg(`Insufficient holdings. Stop-loss orders can only protect shares you currently hold (${ownedQuantity} shares).`);
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

      if (((side === 'buy' && !isCoverBuyOperation) || isUSShort) && durationMode !== 'none' && calculatedSquareOff) {
        orderPayload.holding_days = durationMode === 'intraday' ? 0 : durationMode === '1_day' ? 1 : customDays;
        orderPayload.square_off_date = calculatedSquareOff.square_off_date;
        orderPayload.is_intraday = durationMode === 'intraday';
      }

      const order = await placeOrder(orderPayload);
      if (order.status === 'filled' || order.status === 'pending') {
        setCompletedOrder(order);
        if (onOrderExecuted) onOrderExecuted(order);
      } else {
        setErrorMsg(order.reject_reason || 'Order rejected');
      }
    } catch (err) {
      setErrorMsg(err.message || 'Order submission failed');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="w-full lg:w-80 bg-surface border border-border flex flex-col font-sans select-none shrink-0 shadow-lg">
      {/* Header Bar */}
      <div className="h-10 px-4 bg-[#111317] border-b border-border flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-text-primary">
          ORDER TICKET
        </span>
        <button
          onClick={onClose}
          className="p-1 text-text-muted hover:text-text-primary hover:bg-base rounded transition-colors"
        >
          <X size={15} />
        </button>
      </div>

      {/* Asset Metadata Header */}
      <div className="p-4 border-b border-border bg-[#14161b]">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <span className="font-bold text-base text-text-primary">{upper}</span>
            <span className="text-[10px] font-mono-tabular px-1.5 py-0.5 bg-base border border-border text-text-muted">
              {exchange}
            </span>
          </div>
          {onOpenChart && (
            <button
              type="button"
              onClick={() => onOpenChart(upper)}
              className="text-[10px] text-accent hover:underline uppercase tracking-wider font-semibold"
            >
              FULL CHART
            </button>
          )}
        </div>
        <div className="flex items-center justify-between mt-2 font-mono-tabular">
          <span className="text-sm font-bold text-text-primary">
            {currencySymbol}{price > 0 ? price.toFixed(2) : '—'}
          </span>
          <span className={`text-[10px] uppercase font-semibold ${isMarketOpen ? 'text-green' : 'text-text-muted'}`}>
            {isMarketOpen ? '● MARKET OPEN' : '○ MARKET CLOSED'}
          </span>
        </div>
      </div>

      {/* Uninitialized Wallet Warning */}
      {!wallet ? (
        <div className="p-6 text-center space-y-4 font-mono-tabular">
          <div className="text-xs text-text-muted">
            NO {market === 'IN' ? 'INDIAN' : 'US'} WALLET INITIALIZED
          </div>
          {onOpenWalletSetup && (
            <button
              type="button"
              onClick={() => onOpenWalletSetup(market)}
              className="w-full h-9 bg-accent hover:bg-accent/90 text-white text-xs font-semibold uppercase tracking-wider font-sans"
            >
              INITIALIZE {market} WALLET
            </button>
          )}
        </div>
      ) : completedOrder ? (
        /* Confirmation Screen */
        <div className="p-5 text-center space-y-4 font-mono-tabular">
          <div className="inline-flex items-center space-x-2 text-xs font-semibold tracking-wider text-green uppercase">
            <span className="w-2 h-2 rounded-full bg-green shadow-[0_0_6px_rgba(0,192,118,0.6)]" />
            <span>ORDER FILLED @ {currencySymbol}{Number(completedOrder.executed_price).toFixed(2)}</span>
          </div>
          <div className="p-3 bg-base border border-border text-left text-xs space-y-1">
            <div className="flex justify-between text-text-muted">
              <span>ORDER ID:</span>
              <span className="text-text-primary">#{completedOrder.id}</span>
            </div>
            <div className="flex justify-between text-text-muted">
              <span>ACTION:</span>
              <span className="text-text-primary uppercase font-bold">{completedOrder.side}</span>
            </div>
            <div className="flex justify-between text-text-muted">
              <span>QUANTITY:</span>
              <span className="text-text-primary">{completedOrder.quantity}</span>
            </div>
          </div>
          <button
            onClick={() => setCompletedOrder(null)}
            className="w-full h-8 bg-surface-hover hover:bg-border text-xs text-text-primary uppercase tracking-wider font-semibold transition-colors font-sans"
          >
            PLACE ANOTHER ORDER
          </button>
        </div>
      ) : (
        /* Equity Order Form */
        <form onSubmit={handleOrderSubmit} className="p-4 space-y-4">
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
            <div className="grid grid-cols-3 gap-1 p-1 bg-base border border-border font-mono-tabular">
              {['market', 'limit', 'stop_loss'].map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => {
                    setOrderType(t);
                    setErrorMsg(null);
                    if (t === 'stop_loss') setSide('sell');
                  }}
                  className={`h-7 text-[10px] font-semibold tracking-wider uppercase transition-colors ${
                    orderType === t ? 'bg-[#232731] text-text-primary' : 'text-text-muted hover:text-text-primary'
                  }`}
                >
                  {t.replace('_', '-')}
                </button>
              ))}
            </div>
          </div>

          {/* Buy / Sell Segmented Control */}
          <div className="grid grid-cols-2 gap-1 p-1 bg-base border border-border font-mono-tabular">
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
                side === 'sell' ? 'bg-red text-white' : 'text-text-muted hover:text-text-primary'
              }`}
            >
              SELL
            </button>
          </div>

          {/* Limit Price */}
          {orderType === 'limit' && (
            <div className="font-mono-tabular">
              <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1 block">
                LIMIT PRICE ({currencySymbol})
              </label>
              <input
                type="number"
                step="any"
                required
                value={limitPrice}
                onChange={(e) => setLimitPrice(e.target.value)}
                className="w-full h-9 px-3 bg-base border border-border text-xs text-text-primary focus:border-accent focus:outline-none"
                placeholder={price ? price.toFixed(2) : '0.00'}
              />
            </div>
          )}

          {/* Quantity */}
          <div>
            <div className="text-[11px] text-text-muted uppercase tracking-wider mb-1 font-mono-tabular">
              SHARES QUANTITY
            </div>
            <input
              type="number"
              min="1"
              step="1"
              required
              value={quantity}
              onChange={(e) => setQuantity(Math.max(1, parseInt(e.target.value) || 1))}
              className="w-full h-9 px-3 bg-base border border-border text-xs text-text-primary font-mono-tabular focus:border-accent focus:outline-none"
            />
          </div>

          {/* Estimated Total & Buying Power */}
          <div className="p-3 bg-base border border-border font-mono-tabular text-xs space-y-1">
            <div className="flex justify-between text-text-muted">
              <span>ESTIMATED VALUE:</span>
              <span className="text-text-primary font-bold">{currencySymbol}{formatMoney(totalCost, currency)}</span>
            </div>
            <div className="flex justify-between text-text-muted">
              <span>AVAILABLE FUNDS:</span>
              <span className={hasInsufficientFunds || hasInsufficientMargin ? 'text-red font-bold' : 'text-text-primary font-bold'}>
                {currencySymbol}{formatMoney(isUSShort ? availableBuyingPower : cashBalance, currency)}
              </span>
            </div>
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={submitting || (orderType === 'market' && !isMarketOpen) || hasInsufficientFunds || hasInsufficientMargin}
            className={`w-full h-10 text-xs font-bold tracking-wider uppercase transition-colors select-none font-mono-tabular ${
              orderType === 'market' && !isMarketOpen
                ? 'bg-border text-text-muted cursor-not-allowed'
                : hasInsufficientFunds || hasInsufficientMargin
                ? 'bg-border text-text-muted cursor-not-allowed'
                : side === 'buy'
                ? 'bg-green hover:bg-green/90 text-black'
                : 'bg-red hover:bg-red/90 text-white'
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
              : `${side.toUpperCase()} ${quantity} ${upper}`}
          </button>
        </form>
      )}
    </div>
  );
}
