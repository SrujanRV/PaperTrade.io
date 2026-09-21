import { useState, useEffect, useRef, useCallback } from 'react';

/**
 * Hook to consume the SSE price stream for a given list of tickers.
 *
 * @param {string[]} tickers - Array of ticker symbols, e.g. ['AAPL', 'TSLA', 'RELIANCE.NS']
 * @returns {{
 *   prices: Record<string, {
 *     ticker: string,
 *     current_price: number,
 *     change_percent: number,
 *     timestamp: string,
 *     market_status: 'open' | 'closed',
 *     tickDirection: 'up' | 'down' | 'none',
 *     tickId: number
 *   }>,
 *   status: 'connecting' | 'connected' | 'reconnecting' | 'error',
 *   error: string | null
 * }}
 */
export function usePriceStream(tickers = []) {
  const [prices, setPrices] = useState({});
  const [status, setStatus] = useState('connecting');
  const [error, setError] = useState(null);

  // Keep a ref to current prices so we can compute price deltas
  const pricesRef = useRef({});

  // Memoize tickers string to avoid reconnect loops
  const tickersKey = tickers.map(t => t.trim().toUpperCase()).filter(Boolean).sort().join(',');

  useEffect(() => {
    if (!tickersKey) {
      setStatus('disconnected');
      return;
    }

    const url = `/api/prices/stream?tickers=${encodeURIComponent(tickersKey)}`;
    setStatus('connecting');
    setError(null);

    const eventSource = new EventSource(url);

    eventSource.onopen = () => {
      setStatus('connected');
      setError(null);
    };

    eventSource.onmessage = (event) => {
      try {
        if (!event.data) return;
        const data = JSON.parse(event.data);

        // Required schema: { ticker, current_price, change_percent, timestamp, market_status }
        if (!data || !data.ticker) return;

        const symbol = data.ticker.toUpperCase();
        const prevQuote = pricesRef.current[symbol];
        const newPrice = Number(data.current_price);
        const prevPrice = prevQuote ? Number(prevQuote.current_price) : null;

        let tickDirection = 'none';
        let tickId = prevQuote ? prevQuote.tickId : 0;

        if (prevPrice !== null && newPrice !== prevPrice) {
          tickDirection = newPrice > prevPrice ? 'up' : 'down';
          tickId = Date.now(); // change key triggers re-animation
        }

        const updatedQuote = {
          ticker: symbol,
          current_price: newPrice,
          change_percent: Number(data.change_percent ?? 0),
          timestamp: data.timestamp,
          market_status: data.market_status || 'closed',
          tickDirection,
          tickId,
        };

        pricesRef.current = {
          ...pricesRef.current,
          [symbol]: updatedQuote,
        };

        setPrices((prev) => ({
          ...prev,
          [symbol]: updatedQuote,
        }));
      } catch (err) {
        console.error('Failed to parse SSE price frame:', err, event.data);
      }
    };

    eventSource.onerror = (err) => {
      // EventSource handles reconnection natively. Update status to reflect state.
      if (eventSource.readyState === EventSource.CONNECTING) {
        setStatus('reconnecting');
      } else if (eventSource.readyState === EventSource.CLOSED) {
        setStatus('error');
        setError('SSE stream closed');
      }
    };

    return () => {
      eventSource.close();
      setStatus('disconnected');
    };
  }, [tickersKey]);

  return { prices, status, error };
}
