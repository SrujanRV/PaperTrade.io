import React, { useState } from 'react';
import { validateTicker } from '../api/client';

// Helper to determine exchange and currency from symbol
function getTickerMeta(symbol) {
  const upper = symbol.toUpperCase();
  if (upper.endsWith('.NS')) {
    return {
      symbol: upper,
      display: upper.replace('.NS', ''),
      exchange: 'NSE',
      currency: 'INR',
      currencySymbol: '₹',
    };
  }
  if (upper.endsWith('.BO')) {
    return {
      symbol: upper,
      display: upper.replace('.BO', ''),
      exchange: 'BSE',
      currency: 'INR',
      currencySymbol: '₹',
    };
  }
  return {
    symbol: upper,
    display: upper,
    exchange: 'NASDAQ',
    currency: 'USD',
    currencySymbol: '$',
  };
}

function formatPrice(value, currency) {
  if (value === undefined || value === null || isNaN(value)) return '—';
  const locale = currency === 'INR' ? 'en-IN' : 'en-US';
  return Number(value).toLocaleString(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatChangePct(value) {
  if (value === undefined || value === null || isNaN(value)) return '—';
  const num = Number(value);
  const sign = num > 0 ? '+' : '';
  return `${sign}${num.toFixed(2)}%`;
}

export function Watchlist({
  tickers = [],
  prices = {},
  connectionStatus = 'connected',
  selectedTicker,
  onSelectTicker,
  onAddTicker,
  onRemoveTicker,
}) {
  const [inputTicker, setInputTicker] = useState('');
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState(null);

  async function handleAdd(e) {
    e.preventDefault();
    const raw = inputTicker.trim().toUpperCase();
    if (!raw) {
      setError('ENTER A TICKER SYMBOL');
      return;
    }
    if (tickers.includes(raw)) {
      setError(`${raw} IS ALREADY IN WATCHLIST`);
      return;
    }

    setValidating(true);
    setError(null);
    try {
      const res = await validateTicker(raw);
      if (res.valid) {
        onAddTicker(raw);
        setInputTicker('');
        setError(null);
      } else {
        setError(res.reason ? `INVALID TICKER: ${res.reason}` : `TICKER "${raw}" NOT FOUND`);
      }
    } catch (err) {
      setError(`VALIDATION FAILED: ${err.message}`);
    } finally {
      setValidating(false);
    }
  }

  return (
    <div className="w-full max-w-4xl bg-surface border border-border rounded-none shadow-none overflow-hidden">
      {/* Terminal Widget Header */}
      <div className="h-10 px-3 bg-[#111317] border-b border-border flex items-center justify-between select-none">
        <div className="flex items-center space-x-2">
          <span className="text-xs font-semibold tracking-wider text-text-primary uppercase">
            Watchlist
          </span>
          <span className="text-[11px] font-mono-tabular text-text-muted px-1.5 py-0.5 bg-base border border-border">
            {tickers.length} ASSETS
          </span>
        </div>

        {/* Live SSE Connection Indicator */}
        <div className="flex items-center text-[11px] font-mono-tabular">
          {connectionStatus === 'connected' && (
            <span className="flex items-center text-text-muted">
              <span className="inline-block w-2 h-2 rounded-full bg-green mr-1.5 shadow-[0_0_6px_rgba(0,192,118,0.6)]" />
              LIVE (SSE Connected)
            </span>
          )}
          {connectionStatus === 'connecting' && (
            <span className="flex items-center text-[#e5a50a]">
              <span className="inline-block w-2 h-2 rounded-full bg-[#e5a50a] animate-pulse mr-1.5" />
              CONNECTING...
            </span>
          )}
          {connectionStatus === 'reconnecting' && (
            <span className="flex items-center text-[#e5a50a]">
              <span className="inline-block w-2 h-2 rounded-full bg-[#e5a50a] animate-ping mr-1.5" />
              RECONNECTING...
            </span>
          )}
          {connectionStatus === 'error' && (
            <span className="flex items-center text-red">
              <span className="inline-block w-2 h-2 rounded-full bg-red mr-1.5" />
              DISCONNECTED
            </span>
          )}
          {connectionStatus === 'disconnected' && (
            <span className="flex items-center text-text-muted">
              <span className="inline-block w-2 h-2 rounded-full bg-[#525866] mr-1.5" />
              IDLE
            </span>
          )}
        </div>
      </div>

      {/* Terminal Add Ticker Bar */}
      <div className="px-3 py-2 bg-[#0f1115] border-b border-border flex flex-wrap items-center justify-between gap-2 select-none">
        <form onSubmit={handleAdd} className="flex items-center space-x-2">
          <span className="text-[11px] font-mono-tabular text-text-muted tracking-wider">
            + ADD SYMBOL:
          </span>
          <input
            type="text"
            value={inputTicker}
            onChange={(e) => {
              setInputTicker(e.target.value.toUpperCase());
              if (error) setError(null);
            }}
            placeholder="e.g. MSFT, INFY.NS"
            disabled={validating}
            className="w-40 px-2 py-1 text-xs font-mono-tabular uppercase bg-[#15171c] border border-border text-text-primary placeholder:text-[#525866] focus:outline-none focus:border-accent disabled:opacity-50 tracking-wider"
          />
          <button
            type="submit"
            disabled={validating || !inputTicker.trim()}
            className="px-2.5 py-1 text-[11px] font-mono-tabular font-medium bg-[#232731] hover:bg-[#2e3442] text-text-primary border border-border uppercase tracking-wider transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center space-x-1.5"
          >
            {validating ? (
              <>
                <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
                <span>CHECKING...</span>
              </>
            ) : (
              <span>+ ADD</span>
            )}
          </button>
        </form>

        {/* Inline Error Message */}
        {error && (
          <div className="flex items-center space-x-1.5 text-[11px] font-mono-tabular text-red bg-red/10 border border-red/30 px-2 py-0.5">
            <span className="w-1.5 h-1.5 rounded-full bg-red shrink-0" />
            <span className="truncate max-w-xs">{error}</span>
            <button
              type="button"
              onClick={() => setError(null)}
              className="text-text-muted hover:text-text-primary ml-1 text-xs leading-none"
            >
              ✕
            </button>
          </div>
        )}
      </div>

      {/* Watchlist Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="h-8 border-b border-border text-[11px] uppercase text-text-muted font-medium select-none bg-[#0f1014]">
              <th className="px-3 font-medium">Symbol</th>
              <th className="px-3 font-medium">Exchange</th>
              <th className="px-3 text-right font-medium">Last Price</th>
              <th className="px-3 text-right font-medium">Change</th>
              <th className="px-3 text-right font-medium">Status</th>
              <th className="w-10 px-2 text-center font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {tickers.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-10 text-center text-xs font-mono-tabular text-text-muted">
                  NO ASSETS IN WATCHLIST — Enter a ticker symbol above to start streaming.
                </td>
              </tr>
            ) : (
              tickers.map((ticker) => {
                const meta = getTickerMeta(ticker);
                const quote = prices[meta.symbol];
                const price = quote?.current_price;
                const changePct = quote?.change_percent ?? 0;
                const isOpen = quote?.market_status === 'open';
                const isPositive = changePct > 0;
                const isNegative = changePct < 0;

                // Color token for change
                const changeColor = isPositive
                  ? 'text-green'
                  : isNegative
                  ? 'text-red'
                  : 'text-text-muted';

                // Determine tick flash animation class
                const tickAnimationClass =
                  quote?.tickDirection === 'up'
                    ? 'animate-tick-up'
                    : quote?.tickDirection === 'down'
                    ? 'animate-tick-down'
                    : '';

                const isSelected = selectedTicker?.toUpperCase() === meta.symbol;

                return (
                  <tr
                    key={meta.symbol}
                    onClick={() => onSelectTicker && onSelectTicker(meta.symbol, quote)}
                    className={`h-[38px] border-b border-border transition-colors duration-150 group cursor-pointer ${
                      isSelected
                        ? 'bg-[#1c2027] border-l-2 border-l-accent'
                        : 'hover:bg-surface-hover'
                    }`}
                  >
                    {/* Symbol Column */}
                    <td className="px-3 py-0 align-middle">
                      <div className="flex items-baseline space-x-2">
                        <span className="text-xs font-semibold text-text-primary group-hover:text-white">
                          {meta.display}
                        </span>
                        {meta.symbol.includes('.') && (
                          <span className="text-[10px] text-text-muted font-mono-tabular">
                            {meta.symbol.substring(meta.symbol.indexOf('.'))}
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Exchange Column */}
                    <td className="px-3 py-0 align-middle">
                      <span className="text-[11px] font-mono-tabular text-text-muted">
                        {meta.exchange}
                      </span>
                    </td>

                    {/* Last Price Column (Tabular, right-aligned, tick flash on price change) */}
                    <td className="px-3 py-0 text-right align-middle font-mono-tabular">
                      <div
                        key={`${meta.symbol}-${quote?.tickId || 0}`}
                        className={`inline-block px-1.5 py-0.5 rounded-sm text-xs font-medium text-text-primary transition-colors ${tickAnimationClass}`}
                      >
                        <span>{meta.currencySymbol}</span>
                        <span>{formatPrice(price, meta.currency)}</span>
                      </div>
                    </td>

                    {/* Change % Column (Tabular, right-aligned, colored) */}
                    <td className="px-3 py-0 text-right align-middle font-mono-tabular">
                      <span className={`text-xs font-medium ${changeColor}`}>
                        {formatChangePct(changePct)}
                      </span>
                    </td>

                    {/* Market Status Column (Understated dot + status text) */}
                    <td className="px-3 py-0 text-right align-middle">
                      <div className="inline-flex items-center space-x-1.5 text-[11px] font-mono-tabular">
                        <span
                          className={`w-1.5 h-1.5 rounded-full ${
                            isOpen ? 'bg-green' : 'bg-[#525866]'
                          }`}
                        />
                        <span className={isOpen ? 'text-green font-medium' : 'text-text-muted'}>
                          {isOpen ? 'OPEN' : 'CLOSED'}
                        </span>
                      </div>
                    </td>

                    {/* Remove Action Button */}
                    <td className="w-10 px-2 py-0 text-center align-middle">
                      <button
                        type="button"
                        title={`Remove ${meta.symbol} from watchlist`}
                        onClick={(e) => {
                          e.stopPropagation();
                          if (onRemoveTicker) onRemoveTicker(meta.symbol);
                        }}
                        className="opacity-0 group-hover:opacity-100 focus:opacity-100 text-text-muted hover:text-red hover:bg-[#232731] w-5 h-5 inline-flex items-center justify-center text-xs transition-all font-mono-tabular"
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Footer Info / Status Bar */}
      <div className="h-7 px-3 bg-[#0d0e12] border-t border-border flex items-center justify-between text-[11px] text-text-muted font-mono-tabular select-none">
        <span>5s POLLING INTERVAL</span>
        <span>PAPERTRADE TERMINAL v0.2</span>
      </div>
    </div>
  );
}
