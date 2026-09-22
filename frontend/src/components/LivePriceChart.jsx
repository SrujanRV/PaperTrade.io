import React, { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, AreaSeries, LineStyle } from 'lightweight-charts';
import { Maximize2 } from 'lucide-react';
import { fetchPreviousClose, fetchPriceHistory } from '../api/client';

// Color tokens matching terminal aesthetic and user specification
const GREEN = '#00c076';
const RED = '#f23645';
const GREEN_TOP = 'rgba(0, 192, 118, 0.25)';
const RED_TOP = 'rgba(242, 54, 69, 0.25)';
const TRANSPARENT = 'rgba(0, 0, 0, 0)';

export function LivePriceChart({
  ticker,
  quote,
  currencySymbol = '$',
  onExpandChart,
}) {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const priceLineRef = useRef(null);
  const lastTimeRef = useRef(0);

  const [range, setRange] = useState('1D'); // '1D' | '1W' | '1M'
  const [dataCount, setDataCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [prevCloseVal, setPrevCloseVal] = useState(null);

  const upper = ticker?.toUpperCase();

  // Helper to remove any existing price line
  const clearPriceLine = useCallback(() => {
    if (priceLineRef.current && seriesRef.current) {
      try {
        seriesRef.current.removePriceLine(priceLineRef.current);
      } catch (e) {
        // Ignored if already removed
      }
      priceLineRef.current = null;
    }
  }, []);

  // Initialize chart container
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: 155,
      layout: {
        background: { type: 'solid', color: '#0b0c0f' },
        textColor: '#707788',
        fontSize: 10,
        fontFamily: "'IBM Plex Mono', monospace",
      },
      grid: {
        vertLines: { color: '#161920', style: 1 },
        horzLines: { color: '#161920', style: 1 },
      },
      crosshair: {
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
          top: 0.18,
          bottom: 0.15,
        },
      },
      timeScale: {
        borderColor: '#232731',
        timeVisible: true,
        secondsVisible: false,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
      handleScroll: false,
      handleScale: false,
    });

    const series = chart.addSeries(AreaSeries, {
      topColor: GREEN_TOP,
      bottomColor: TRANSPARENT,
      lineColor: GREEN,
      lineWidth: 2,
      priceFormat: {
        type: 'price',
        precision: 2,
        minMove: 0.01,
      },
    });

    chartRef.current = chart;
    seriesRef.current = series;

    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(chartContainerRef.current);

    return () => {
      resizeObserver.disconnect();
      clearPriceLine();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [clearPriceLine]);

  // Fetch and load data when ticker or range changes
  useEffect(() => {
    if (!upper || !seriesRef.current || !chartRef.current) return;

    let isMounted = true;
    setLoading(true);
    clearPriceLine();

    async function loadData() {
      try {
        if (range === '1D') {
          const [prevCloseRes, candles] = await Promise.all([
            fetchPreviousClose(upper).catch(() => null),
            fetchPriceHistory(upper, '1d', '5m').catch(() => []),
          ]);

          if (!isMounted || !seriesRef.current) return;

          const prevClose = prevCloseRes?.previous_close || null;
          setPrevCloseVal(prevClose);

          let points = [];
          if (candles && candles.length > 0) {
            points = candles.map((c) => ({ time: c.time, value: c.close }));
          } else if (quote?.current_price) {
            const now = Math.floor(Date.now() / 1000);
            const curr = Number(quote.current_price);
            points = [
              { time: now - 300, value: prevClose || curr },
              { time: now, value: curr },
            ];
          }

          if (points.length > 0) {
            // Sort points ascending by time
            points.sort((a, b) => a.time - b.time);
            // Deduplicate consecutive timestamps
            const deduped = [];
            for (const pt of points) {
              if (deduped.length === 0 || pt.time > deduped[deduped.length - 1].time) {
                deduped.push(pt);
              }
            }
            seriesRef.current.setData(deduped);
            chartRef.current?.timeScale().fitContent();
            setDataCount(deduped.length);
            lastTimeRef.current = deduped[deduped.length - 1].time;

            const latestPrice = deduped[deduped.length - 1].value;
            const isUp = prevClose ? latestPrice >= prevClose : latestPrice >= deduped[0].value;
            seriesRef.current.applyOptions({
              lineColor: isUp ? GREEN : RED,
              topColor: isUp ? GREEN_TOP : RED_TOP,
              bottomColor: TRANSPARENT,
            });
          }

          // Add dotted reference line for previous close
          if (prevClose && prevClose > 0) {
            const formatted = prevClose.toLocaleString(undefined, {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            });
            priceLineRef.current = seriesRef.current.createPriceLine({
              price: prevClose,
              color: '#707788',
              lineWidth: 1,
              lineStyle: LineStyle.Dotted,
              axisLabelVisible: true,
              title: `PREV CLOSE ${currencySymbol}${formatted}`,
            });
          }
        } else {
          // 1W or 1M historical range
          const interval = range === '1W' ? '15m' : '1d';
          const candles = await fetchPriceHistory(upper, range.toLowerCase(), interval).catch(() => []);

          if (!isMounted || !seriesRef.current) return;

          if (candles && candles.length > 0) {
            const points = candles.map((c) => ({ time: c.time, value: c.close }));
            points.sort((a, b) => a.time - b.time);

            const deduped = [];
            for (const pt of points) {
              if (deduped.length === 0 || pt.time > deduped[deduped.length - 1].time) {
                deduped.push(pt);
              }
            }

            seriesRef.current.setData(deduped);
            chartRef.current?.timeScale().fitContent();
            setDataCount(deduped.length);
            lastTimeRef.current = deduped[deduped.length - 1].time;

            const startPrice = deduped[0].value;
            const endPrice = deduped[deduped.length - 1].value;
            const isUp = endPrice >= startPrice;

            seriesRef.current.applyOptions({
              lineColor: isUp ? GREEN : RED,
              topColor: isUp ? GREEN_TOP : RED_TOP,
              bottomColor: TRANSPARENT,
            });

            // Add dotted reference line at start price of period
            const formatted = startPrice.toLocaleString(undefined, {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            });
            priceLineRef.current = seriesRef.current.createPriceLine({
              price: startPrice,
              color: '#707788',
              lineWidth: 1,
              lineStyle: LineStyle.Dotted,
              axisLabelVisible: true,
              title: `START ${currencySymbol}${formatted}`,
            });
          }
        }
      } catch (err) {
        console.error('Error loading chart data:', err);
      } finally {
        if (isMounted) setLoading(false);
      }
    }

    loadData();

    return () => {
      isMounted = false;
    };
  }, [upper, range, clearPriceLine, currencySymbol]);

  // Handle incoming live tick in 1D mode
  useEffect(() => {
    if (range !== '1D' || !seriesRef.current || !quote?.current_price || !upper) return;

    const currentPrice = Number(quote.current_price);
    if (isNaN(currentPrice) || currentPrice <= 0) return;

    const nowSec = Math.floor(Date.now() / 1000);
    const tickTime = nowSec <= lastTimeRef.current ? lastTimeRef.current + 1 : nowSec;
    lastTimeRef.current = tickTime;

    try {
      seriesRef.current.update({
        time: tickTime,
        value: currentPrice,
      });
      chartRef.current?.timeScale().fitContent();
      setDataCount((prev) => prev + 1);

      // Dynamically update line/fill color based on day's performance vs prevClose
      const isUp = prevCloseVal ? currentPrice >= prevCloseVal : true;
      seriesRef.current.applyOptions({
        lineColor: isUp ? GREEN : RED,
        topColor: isUp ? GREEN_TOP : RED_TOP,
      });
    } catch (e) {
      // Ignore timestamp conflicts in hot reload
    }
  }, [quote, range, upper, prevCloseVal]);

  return (
    <div className="p-3 bg-[#0d0f12] border-b border-border select-none">
      {/* Chart Header Bar */}
      <div className="flex items-center justify-between text-[10px] font-mono-tabular mb-2">
        {/* Left: Feed info & status */}
        <div className="flex items-center space-x-1.5 min-w-0">
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              range === '1D' ? 'bg-accent animate-pulse' : 'bg-[#707788]'
            } shrink-0`}
          />
          <span className="font-semibold text-text-primary tracking-wider uppercase text-[10px] shrink-0">
            {range === '1D' ? 'INTRADAY' : range === '1W' ? '1-WEEK' : '1-MONTH'}
          </span>
          <span className="text-text-muted text-[10px] truncate">
            // {dataCount} {range === '1D' ? 'TICKS' : 'BARS'}
          </span>
        </div>

        {/* Right: Range Switcher (1D, 1W, 1M) & Expand Button */}
        <div className="flex items-center space-x-1.5">
          <div className="inline-flex p-0.5 bg-surface border border-border">
            {['1D', '1W', '1M'].map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setRange(r)}
                className={`px-1.5 py-0.5 text-[9px] font-mono-tabular uppercase transition-colors ${
                  range === r
                    ? 'bg-[#232731] text-text-primary font-bold border border-border'
                    : 'text-text-muted hover:text-text-primary'
                }`}
              >
                {r}
              </button>
            ))}
          </div>

          {/* Full Chart Trigger */}
          {onExpandChart && (
            <button
              type="button"
              onClick={() => onExpandChart(upper)}
              title={`Open full candlestick chart for ${upper}`}
              className="p-1 text-text-muted hover:text-accent hover:bg-[#232731] border border-border transition-colors flex items-center justify-center"
            >
              <Maximize2 size={11} />
            </button>
          )}
        </div>
      </div>

      {/* Chart Canvas Container */}
      <div className="relative w-full h-[155px] overflow-hidden">
        {loading && (
          <div className="absolute inset-0 bg-[#0b0c0f]/60 backdrop-blur-[1px] flex items-center justify-center z-10 font-mono-tabular text-[10px] text-text-muted">
            <span className="w-1.5 h-1.5 rounded-full bg-accent animate-ping mr-2" />
            LOADING {range} CHART...
          </div>
        )}
        <div ref={chartContainerRef} className="w-full h-[155px]" />
      </div>
    </div>
  );
}
