import React, { useEffect, useRef, useState } from 'react';
import { createChart, AreaSeries } from 'lightweight-charts';

// In-memory session tick accumulator across ticker switches
const sessionTickHistory = new Map();

export function LivePriceChart({ ticker, quote, currencySymbol = '$' }) {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const [tickCount, setTickCount] = useState(0);

  const upper = ticker?.toUpperCase();

  // Initialize or recreate chart when ticker changes
  useEffect(() => {
    if (!chartContainerRef.current || !upper) return;

    // Initialize Lightweight Chart
    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: 150,
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
          top: 0.2,
          bottom: 0.15,
        },
      },
      timeScale: {
        borderColor: '#232731',
        timeVisible: true,
        secondsVisible: true,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
      handleScroll: false,
      handleScale: false,
    });

    const series = chart.addSeries(AreaSeries, {
      topColor: 'rgba(41, 98, 255, 0.25)',
      bottomColor: 'rgba(41, 98, 255, 0.0)',
      lineColor: '#2962ff',
      lineWidth: 2,
      priceFormat: {
        type: 'price',
        precision: 2,
        minMove: 0.01,
      },
    });

    chartRef.current = chart;
    seriesRef.current = series;

    // Load existing ticks for this ticker if available
    const existing = sessionTickHistory.get(upper) || [];
    if (existing.length > 0) {
      series.setData(existing);
      chart.timeScale().fitContent();
      setTickCount(existing.length);
    } else {
      setTickCount(0);
    }

    // Handle container resize
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
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [upper]);

  // Handle incoming live tick
  useEffect(() => {
    if (!seriesRef.current || !quote || !quote.current_price || !upper) return;

    const currentPrice = Number(quote.current_price);
    if (isNaN(currentPrice) || currentPrice <= 0) return;

    let history = sessionTickHistory.get(upper);
    if (!history) {
      history = [];
      sessionTickHistory.set(upper, history);
    }

    const nowSec = Math.floor(Date.now() / 1000);
    const lastItem = history[history.length - 1];

    let tickTime = nowSec;
    if (lastItem && tickTime <= lastItem.time) {
      tickTime = lastItem.time + 1;
    }

    // If history was empty, create an initial point 5s prior so the area line immediately renders
    if (history.length === 0) {
      const initialPoint = {
        time: tickTime - 5,
        value: currentPrice,
      };
      const currentPoint = {
        time: tickTime,
        value: currentPrice,
      };
      history.push(initialPoint, currentPoint);
      seriesRef.current.setData(history);
      chartRef.current?.timeScale().fitContent();
      setTickCount(history.length);
    } else {
      const newPoint = {
        time: tickTime,
        value: currentPrice,
      };
      history.push(newPoint);
      seriesRef.current.update(newPoint);
      chartRef.current?.timeScale().fitContent();
      setTickCount(history.length);
    }
  }, [quote, upper]);

  return (
    <div className="p-3 bg-[#0d0f12] border-b border-border">
      {/* Chart Header Bar */}
      <div className="flex items-center justify-between text-[10px] font-mono-tabular mb-1.5 select-none">
        <div className="flex items-center space-x-1.5 min-w-0">
          <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse shrink-0" />
          <span className="font-semibold text-text-primary tracking-wider uppercase text-[10px] shrink-0">
            LIVE SESSION CHART
          </span>
          <span className="text-text-muted text-[10px] truncate">
            // {tickCount} TICKS
          </span>
        </div>
        <span className="text-text-muted text-[10px] uppercase shrink-0 font-mono-tabular">
          5s FEED
        </span>
      </div>

      {/* Chart Canvas Container */}
      <div
        ref={chartContainerRef}
        className="w-full h-[150px] overflow-hidden relative"
      />
    </div>
  );
}
