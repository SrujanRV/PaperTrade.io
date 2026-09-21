import React, { useState, useEffect } from 'react';
import { Watchlist } from './components/Watchlist';
import { Activity } from 'lucide-react';

export default function App() {
  const [currentTime, setCurrentTime] = useState(new Date().toUTCString());

  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date().toUTCString().replace('GMT', 'UTC'));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="min-h-screen bg-base text-text-primary flex flex-col font-sans selection:bg-accent/30 selection:text-white">
      {/* Top Terminal Navigation Bar */}
      <header className="h-11 border-b border-border bg-[#101216] px-4 flex items-center justify-between select-none">
        <div className="flex items-center space-x-3">
          <div className="flex items-center space-x-2 text-text-primary">
            <Activity className="w-4 h-4 text-accent" />
            <span className="font-bold text-xs tracking-wider uppercase">
              PaperTrade<span className="text-text-muted font-normal">.io</span>
            </span>
          </div>
          <span className="text-border">|</span>
          <span className="text-[11px] font-mono-tabular text-text-muted uppercase tracking-wider">
            Terminal
          </span>
        </div>

        {/* Global Clock */}
        <div className="flex items-center space-x-4 text-[11px] font-mono-tabular text-text-muted">
          <span>{currentTime}</span>
        </div>
      </header>

      {/* Main Terminal Workspace */}
      <main className="flex-1 p-6 flex flex-col items-center justify-start max-w-6xl w-full mx-auto">
        <div className="w-full flex items-center justify-between mb-4">
          <div>
            <h1 className="text-sm font-semibold tracking-wide text-text-primary uppercase">
              Market Watch
            </h1>
            <p className="text-xs text-text-muted mt-0.5">
              Real-time polled tick stream from NSE & US markets via Server-Sent Events
            </p>
          </div>
        </div>

        {/* Watchlist Component */}
        <Watchlist />
      </main>
    </div>
  );
}
