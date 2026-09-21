import React from 'react';
import { usePriceStream } from '../hooks/usePriceStream';

const DEFAULT_TICKERS = ['AAPL', 'TSLA', 'RELIANCE.NS', 'TCS.NS'];

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

export function Watchlist() {
  const { prices, status } = usePriceStream(DEFAULT_TICKERS);

  return (
    <div className="w-full max-w-4xl bg-surface border border-border rounded-none shadow-none overflow-hidden">
      {/* Terminal Widget Header */}
      <div className="h-10 px-3 bg-[#111317] border-b border-border flex items-center justify-between select-none">
        <div className="flex items-center space-x-2">
          <span className="text-xs font-semibold tracking-wider text-text-primary uppercase">
            Watchlist
          </span>
          <span className="text-[11px] font-mono-tabular text-text-muted px-1.5 py-0.5 bg-base border border-border">
            {DEFAULT_TICKERS.length} ASSETS
          </span>
        </div>

        {/* Live SSE Connection Indicator */}
        <div className="flex items-center text-[11px] font-mono-tabular">
          {status === 'connected' && (
            <span className="flex items-center text-text-muted">
              <span className="inline-block w-2 h-2 rounded-full bg-green mr-1.5 shadow-[0_0_6px_rgba(0,192,118,0.6)]" />
              LIVE (SSE Connected)
            </span>
          )}
          {status === 'connecting' && (
            <span className="flex items-center text-[#e5a50a]">
              <span className="inline-block w-2 h-2 rounded-full bg-[#e5a50a] animate-pulse mr-1.5" />
              CONNECTING...
            </span>
          )}
          {status === 'reconnecting' && (
            <span className="flex items-center text-[#e5a50a]">
              <span className="inline-block w-2 h-2 rounded-full bg-[#e5a50a] animate-ping mr-1.5" />
              RECONNECTING...
            </span>
          )}
          {status === 'error' && (
            <span className="flex items-center text-red">
              <span className="inline-block w-2 h-2 rounded-full bg-red mr-1.5" />
              DISCONNECTED
            </span>
          )}
        </div>
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
            </tr>
          </thead>
          <tbody>
            {DEFAULT_TICKERS.map((ticker) => {
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

              return (
                <tr
                  key={meta.symbol}
                  className="h-[38px] border-b border-border hover:bg-surface-hover transition-colors duration-150 group"
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
                </tr>
              );
            })}
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
