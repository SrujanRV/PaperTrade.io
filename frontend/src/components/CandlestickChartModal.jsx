import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  CrosshairMode,
} from 'lightweight-charts';
import { fetchPriceHistory } from '../api/client';

const GREEN = '#00c076';
const RED = '#f23645';
const GREEN_VOL = 'rgba(0, 192, 118, 0.45)';
const RED_VOL = 'rgba(242, 54, 69, 0.45)';

export function CandlestickChartModal({
  isOpen,
  ticker,
  quote,
  onClose,
  onTrade,
}) {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);

  const [range, setRange] = useState('1D'); // '1D' | '1W' | '1M'
  const [loading, setLoading] = useState(false);
  const [hoverData, setHoverData] = useState(null);
  const [latestData, setLatestData] = useState(null);

  const upper = ticker?.toUpperCase();
  const isIndian = upper?.endsWith('.NS') || upper?.endsWith('.BO');
  const currencySymbol = isIndian ? '₹' : '$';
  const currency = isIndian ? 'INR' : 'USD';

  // Format timestamp for display
  const formatTimeStr = useCallback((unixSec, rangeMode) => {
    if (!unixSec) return '—';
    const d = new Date(unixSec * 1000);
    if (rangeMode === '1M') {
      return d.toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });
    }
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }, []);

  // Initialize chart
  useEffect(() => {
    if (!isOpen || !chartContainerRef.current) return;

    const container = chartContainerRef.current;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight || 450,
      layout: {
        background: { type: 'solid', color: '#0b0c0f' },
        textColor: '#707788',
        fontSize: 11,
        fontFamily: "'IBM Plex Mono', monospace",
      },
      grid: {
        vertLines: { color: '#161920', style: 1 },
        horzLines: { color: '#161920', style: 1 },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: '#3b4252',
          width: 1,
          style: 2,
          labelBackgroundColor: '#1c2026',
        },
        horzLine: {
          color: '#3b4252',
          width: 1,
          style: 2,
          labelBackgroundColor: '#1c2026',
        },
      },
      rightPriceScale: {
        borderColor: '#232731',
        scaleMargins: {
          top: 0.08,
          bottom: 0.22, // Space for volume bars
        },
      },
      timeScale: {
        borderColor: '#232731',
        timeVisible: true,
        secondsVisible: false,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: GREEN,
      downColor: RED,
      borderUpColor: GREEN,
      borderDownColor: RED,
      wickUpColor: GREEN,
      wickDownColor: RED,
      priceFormat: {
        type: 'price',
        precision: 2,
        minMove: 0.01,
      },
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: '', // Overlay scale
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.78, // volume takes bottom 22%
        bottom: 0,
      },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    // Crosshair hover inspection
    chart.subscribeCrosshairMove((param) => {
      if (
        !param ||
        !param.time ||
        !param.seriesData ||
        !candleSeriesRef.current
      ) {
        setHoverData(null);
        return;
      }

      const candle = param.seriesData.get(candleSeriesRef.current);
      const vol = volumeSeriesRef.current
        ? param.seriesData.get(volumeSeriesRef.current)
        : null;

      if (candle && candle.open !== undefined) {
        setHoverData({
          time: param.time,
          open: candle.open,
          high: candle.high,
          low: candle.low,
          close: candle.close,
          volume: vol?.value || 0,
        });
      } else {
        setHoverData(null);
      }
    });

    // Resize observer
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight || 450,
        });
      }
    };

    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, [isOpen]);

  // Load candle data when ticker or range changes
  useEffect(() => {
    if (!isOpen || !upper || !candleSeriesRef.current) return;

    let isMounted = true;
    setLoading(true);
    setHoverData(null);

    async function loadCandles() {
      try {
        let interval = '5m';
        if (range === '1W') interval = '15m';
        if (range === '1M') interval = '1d';

        const candles = await fetchPriceHistory(
          upper,
          range.toLowerCase(),
          interval
        );

        if (!isMounted || !candleSeriesRef.current) return;

        if (candles && candles.length > 0) {
          // Sort ascending by time
          candles.sort((a, b) => a.time - b.time);

          // Deduplicate consecutive timestamps
          const dedupedCandles = [];
          const dedupedVolumes = [];

          for (const c of candles) {
            if (
              dedupedCandles.length === 0 ||
              c.time > dedupedCandles[dedupedCandles.length - 1].time
            ) {
              dedupedCandles.push({
                time: c.time,
                open: c.open,
                high: c.high,
                low: c.low,
                close: c.close,
              });
              dedupedVolumes.push({
                time: c.time,
                value: c.volume || 0,
                color: c.close >= c.open ? GREEN_VOL : RED_VOL,
              });
            }
          }

          candleSeriesRef.current.setData(dedupedCandles);
          if (volumeSeriesRef.current) {
            volumeSeriesRef.current.setData(dedupedVolumes);
          }

          chartRef.current?.timeScale().fitContent();

          const lastCandle = dedupedCandles[dedupedCandles.length - 1];
          const lastVol = dedupedVolumes[dedupedVolumes.length - 1];
          setLatestData({
            time: lastCandle.time,
            open: lastCandle.open,
            high: lastCandle.high,
            low: lastCandle.low,
            close: lastCandle.close,
            volume: lastVol?.value || 0,
          });
        } else {
          candleSeriesRef.current.setData([]);
          if (volumeSeriesRef.current) volumeSeriesRef.current.setData([]);
          setLatestData(null);
        }
      } catch (err) {
        console.error('Failed to load candlestick data:', err);
      } finally {
        if (isMounted) setLoading(false);
      }
    }

    loadCandles();

    return () => {
      isMounted = false;
    };
  }, [isOpen, upper, range]);

  // Handle Escape key
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen || !upper) return null;

  const currentPrice = quote?.current_price || latestData?.close || 0;
  const changePct = quote?.change_percent ?? 0;
  const isMarketOpen = quote?.market_status === 'open';

  // Active inspected candle (hover or latest)
  const inspected = hoverData || latestData;
  const candleDelta = inspected ? inspected.close - inspected.open : 0;
  const isCandleUp = candleDelta >= 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-5xl bg-[#0d0f12] border border-[#232731] shadow-2xl flex flex-col overflow-hidden max-h-[92vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Terminal Header Bar */}
        <div className="h-14 px-4 bg-[#111317] border-b border-border flex items-center justify-between shrink-0">
          {/* Left: Ticker & Price Info */}
          <div className="flex items-center space-x-3 min-w-0">
            <div className="flex items-baseline space-x-2">
              <span className="text-lg font-bold font-mono-tabular text-text-primary tracking-wide">
                {upper}
              </span>
              <span className="text-xs text-text-muted font-mono-tabular">
                {isIndian ? 'NSE/BSE' : 'US EQUITIES'}
              </span>
            </div>

            <div className="h-4 w-px bg-border hidden sm:block" />

            {/* Current Price & Change */}
            <div className="flex items-baseline space-x-2 font-mono-tabular">
              <span className="text-sm font-semibold text-text-primary">
                {currencySymbol}
                {currentPrice.toLocaleString(currency === 'INR' ? 'en-IN' : 'en-US', {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </span>
              <span
                className={`text-xs font-medium ${
                  changePct > 0
                    ? 'text-green'
                    : changePct < 0
                    ? 'text-red'
                    : 'text-text-muted'
                }`}
              >
                {changePct >= 0 ? `+${changePct.toFixed(2)}%` : `${changePct.toFixed(2)}%`}
              </span>
            </div>

            {/* Market Status Pill */}
            <div className="hidden md:inline-flex items-center space-x-1.5 px-2 py-0.5 rounded-sm bg-[#161920] border border-border text-[10px] font-mono-tabular">
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  isMarketOpen ? 'bg-green' : 'bg-[#525866]'
                }`}
              />
              <span className={isMarketOpen ? 'text-green font-medium' : 'text-text-muted'}>
                {isMarketOpen ? 'MARKET OPEN' : 'CLOSED'}
              </span>
            </div>
          </div>

          {/* Right: Range Switcher (1D, 1W, 1M), Trade Button, Close Button */}
          <div className="flex items-center space-x-2 sm:space-x-3 shrink-0">
            {/* Range Toggle */}
            <div className="inline-flex p-0.5 bg-surface border border-border font-mono-tabular">
              {['1D', '1W', '1M'].map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => setRange(r)}
                  className={`px-2.5 py-1 text-xs font-semibold uppercase tracking-wider transition-colors ${
                    range === r
                      ? 'bg-[#232731] text-text-primary border border-border'
                      : 'text-text-muted hover:text-text-primary'
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>

            {/* [ TRADE ] Action Button */}
            {onTrade && (
              <button
                type="button"
                onClick={() => onTrade(upper)}
                className="px-3 py-1 bg-accent hover:bg-accent/90 text-white text-xs font-mono-tabular font-semibold uppercase tracking-wider transition-colors flex items-center space-x-1.5"
              >
                <span>TRADE</span>
              </button>
            )}

            {/* Close Modal Button */}
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 text-text-muted hover:text-text-primary hover:bg-[#232731] transition-colors"
              title="Close chart (Esc)"
            >
              ✕
            </button>
          </div>
        </div>

        {/* OHLC & Volume Crosshair Inspection Strip */}
        <div className="h-8 px-4 bg-[#0a0b0e] border-b border-border flex items-center justify-between text-[11px] font-mono-tabular text-text-muted shrink-0 overflow-x-auto">
          <div className="flex items-center space-x-4 min-w-max">
            <div>
              <span className="text-[#525866] mr-1">TIME:</span>
              <span className="text-text-primary">
                {inspected ? formatTimeStr(inspected.time, range) : '—'}
              </span>
            </div>
            <div>
              <span className="text-[#525866] mr-1">O:</span>
              <span className="text-text-primary">
                {inspected ? `${currencySymbol}${inspected.open.toFixed(2)}` : '—'}
              </span>
            </div>
            <div>
              <span className="text-[#525866] mr-1">H:</span>
              <span className="text-text-primary">
                {inspected ? `${currencySymbol}${inspected.high.toFixed(2)}` : '—'}
              </span>
            </div>
            <div>
              <span className="text-[#525866] mr-1">L:</span>
              <span className="text-text-primary">
                {inspected ? `${currencySymbol}${inspected.low.toFixed(2)}` : '—'}
              </span>
            </div>
            <div>
              <span className="text-[#525866] mr-1">C:</span>
              <span
                className={
                  inspected
                    ? isCandleUp
                      ? 'text-green font-semibold'
                      : 'text-red font-semibold'
                    : 'text-text-primary'
                }
              >
                {inspected ? `${currencySymbol}${inspected.close.toFixed(2)}` : '—'}
              </span>
            </div>
            <div>
              <span className="text-[#525866] mr-1">VOL:</span>
              <span className="text-text-primary">
                {inspected ? inspected.volume.toLocaleString() : '—'}
              </span>
            </div>
            {inspected && (
              <div
                className={`text-[10px] px-1.5 py-0.2 rounded-sm ${
                  isCandleUp ? 'bg-green/15 text-green' : 'bg-red/15 text-red'
                }`}
              >
                {isCandleUp ? `+${candleDelta.toFixed(2)}` : candleDelta.toFixed(2)}
              </div>
            )}
          </div>

          <div className="hidden lg:block text-[10px] text-[#525866] uppercase">
            {range === '1D'
              ? '5M INTRADAY OHLC + VOLUME'
              : range === '1W'
              ? '15M MULTI-DAY OHLC + VOLUME'
              : 'DAILY OHLC + VOLUME'}
          </div>
        </div>

        {/* Candlestick Canvas Area */}
        <div className="relative flex-1 min-h-[380px] sm:min-h-[460px] bg-[#0b0c0f] w-full overflow-hidden">
          {loading && (
            <div className="absolute inset-0 bg-[#0b0c0f]/75 backdrop-blur-[2px] flex items-center justify-center z-20 font-mono-tabular text-xs text-text-muted space-x-2">
              <span className="w-2 h-2 rounded-full bg-accent animate-ping" />
              <span>FETCHING {range} CANDLESTICK DATA FOR {upper}...</span>
            </div>
          )}

          <div
            ref={chartContainerRef}
            className="w-full h-full min-h-[380px] sm:min-h-[460px]"
          />
        </div>

        {/* Modal Footer Status Bar */}
        <div className="h-7 px-4 bg-[#0d0e12] border-t border-border flex items-center justify-between text-[10px] text-text-muted font-mono-tabular select-none shrink-0">
          <span>LIGHTWEIGHT CHARTS v5 &middot; CANDLESTICK OHLC + HISTOGRAM VOLUME</span>
          <span>PRESS [ESC] TO CLOSE</span>
        </div>
      </div>
    </div>
  );
}
