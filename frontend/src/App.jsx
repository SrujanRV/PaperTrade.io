import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Header } from './components/Header';
import { Watchlist } from './components/Watchlist';
import { Portfolio } from './components/Portfolio';
import { OrderHistory } from './components/OrderHistory';
import { OrderTicket } from './components/OrderTicket';
import { WalletSetupModal } from './components/WalletSetupModal';
import { fetchWallet } from './api/client';
import { usePriceStream } from './hooks/usePriceStream';

const DEFAULT_TICKERS = ['AAPL', 'TSLA', 'RELIANCE.NS', 'TCS.NS'];
const STORAGE_KEY = 'papertrade_watchlist';

function loadInitialWatchlist() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed;
      }
    }
  } catch (err) {
    console.error('Failed to load watchlist from localStorage:', err);
  }
  return DEFAULT_TICKERS;
}

export default function App() {
  const [inWallet, setInWallet] = useState(null);
  const [usWallet, setUsWallet] = useState(null);
  const [checkingWallets, setCheckingWallets] = useState(true);
  const [showWalletModal, setShowWalletModal] = useState(false);

  // Dynamic user-editable watchlist stored in localStorage
  const [watchlist, setWatchlist] = useState(loadInitialWatchlist);

  // Navigation tab state: 'watchlist' | 'portfolio' | 'history'
  const [activeTab, setActiveTab] = useState('watchlist');

  // Portfolio selected market: 'IN' | 'US'
  const [portfolioMarket, setPortfolioMarket] = useState('IN');

  // Active ticker open in OrderTicket side panel
  const [selectedTicker, setSelectedTicker] = useState(null);

  // Trigger to force re-fetch of portfolio summary when orders execute
  const [refreshKey, setRefreshKey] = useState(0);

  const handleAddTicker = useCallback((ticker) => {
    const sym = ticker.trim().toUpperCase();
    setWatchlist((prev) => {
      if (prev.includes(sym)) return prev;
      const next = [...prev, sym];
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch (e) {
        console.error('Failed to save watchlist to localStorage:', e);
      }
      return next;
    });
  }, []);

  const handleRemoveTicker = useCallback((ticker) => {
    const sym = ticker.trim().toUpperCase();
    setWatchlist((prev) => {
      const next = prev.filter((t) => t !== sym);
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch (e) {
        console.error('Failed to save watchlist to localStorage:', e);
      }
      return next;
    });
    if (selectedTicker?.toUpperCase() === sym) {
      setSelectedTicker(null);
    }
  }, [selectedTicker]);

  // Combine watchlist tickers with all currently held tickers for comprehensive SSE streaming
  const subscribedTickers = useMemo(() => {
    const set = new Set(watchlist);
    inWallet?.holdings?.forEach((h) => set.add(h.ticker));
    usWallet?.holdings?.forEach((h) => set.add(h.ticker));
    return Array.from(set);
  }, [watchlist, inWallet, usWallet]);

  // Live SSE stream for all active assets
  const { prices, status: connectionStatus } = usePriceStream(subscribedTickers);

  // Fetch wallets state
  const refreshWallets = useCallback(async () => {
    try {
      const [inData, usData] = await Promise.all([
        fetchWallet('IN'),
        fetchWallet('US'),
      ]);
      setInWallet(inData);
      setUsWallet(usData);

      // If either wallet doesn't exist yet, trigger setup modal
      if (!inData || !usData) {
        setShowWalletModal(true);
      } else {
        setShowWalletModal(false);
      }
    } catch (err) {
      console.error('Error fetching wallets:', err);
    } finally {
      setCheckingWallets(false);
    }
  }, []);

  useEffect(() => {
    refreshWallets();
  }, [refreshWallets]);

  // Determine which wallet corresponds to the selected ticker in OrderTicket
  const isSelectedIndian =
    selectedTicker?.toUpperCase().endsWith('.NS') ||
    selectedTicker?.toUpperCase().endsWith('.BO');
  const activeWallet = isSelectedIndian ? inWallet : usWallet;
  const activeQuote = selectedTicker ? prices[selectedTicker.toUpperCase()] : null;

  function handleOrderExecuted() {
    refreshWallets();
    setRefreshKey((k) => k + 1);
  }

  return (
    <div className="min-h-screen bg-base text-text-primary flex flex-col font-sans selection:bg-accent/30 selection:text-white">
      {/* Persistent Terminal Header with Wallets */}
      <Header
        inWallet={inWallet}
        usWallet={usWallet}
        onOpenWalletSetup={() => setShowWalletModal(true)}
      />

      {/* Main Terminal Workspace */}
      <main className="flex-1 p-4 md:p-6 max-w-7xl w-full mx-auto space-y-4">
        {/* Terminal Sub-Navigation Bar */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-border pb-3">
          {/* Navigation Tabs */}
          <div className="inline-flex p-0.5 bg-surface border border-border font-mono-tabular">
            <button
              onClick={() => setActiveTab('watchlist')}
              className={`px-4 py-1.5 text-xs font-semibold uppercase tracking-wider transition-colors ${
                activeTab === 'watchlist'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              Watchlist
            </button>
            <button
              onClick={() => setActiveTab('portfolio')}
              className={`px-4 py-1.5 text-xs font-semibold uppercase tracking-wider transition-colors ${
                activeTab === 'portfolio'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              Portfolio & Positions
            </button>
            <button
              onClick={() => setActiveTab('history')}
              className={`px-4 py-1.5 text-xs font-semibold uppercase tracking-wider transition-colors ${
                activeTab === 'history'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              Order History
            </button>
          </div>

          <div className="text-[11px] font-mono-tabular text-text-muted">
            <span>TERMINAL WORKSPACE // {activeTab.toUpperCase()}</span>
          </div>
        </div>

        {/* View Content: Watchlist, Portfolio, or Order History + Dockable Order Ticket */}
        <div className="flex flex-col lg:flex-row gap-6 items-start">
          {/* Main Table Area */}
          <div className="flex-1 w-full">
            {activeTab === 'watchlist' && (
              <Watchlist
                tickers={watchlist}
                prices={prices}
                connectionStatus={connectionStatus}
                selectedTicker={selectedTicker}
                onSelectTicker={(ticker) => setSelectedTicker(ticker)}
                onAddTicker={handleAddTicker}
                onRemoveTicker={handleRemoveTicker}
              />
            )}

            {activeTab === 'portfolio' && (
              <Portfolio
                selectedMarket={portfolioMarket}
                onSelectMarket={(m) => setPortfolioMarket(m)}
                onSelectTicker={(ticker) => setSelectedTicker(ticker)}
                onGoToWatchlist={() => setActiveTab('watchlist')}
                livePrices={prices}
                refreshKey={refreshKey}
              />
            )}

            {activeTab === 'history' && (
              <OrderHistory
                selectedMarket={portfolioMarket}
                onSelectMarket={(m) => setPortfolioMarket(m)}
                onGoToWatchlist={() => setActiveTab('watchlist')}
                refreshKey={refreshKey}
              />
            )}
          </div>

          {/* Dockable Order Ticket Side Panel */}
          {selectedTicker && (
            <div className="w-full lg:w-auto shrink-0">
              <OrderTicket
                ticker={selectedTicker}
                quote={activeQuote}
                wallet={activeWallet}
                onClose={() => setSelectedTicker(null)}
                onOrderExecuted={handleOrderExecuted}
              />
            </div>
          )}
        </div>
      </main>

      {/* Wallet Setup First-Run Modal */}
      <WalletSetupModal
        isOpen={showWalletModal}
        onComplete={() => {
          refreshWallets();
          setRefreshKey((k) => k + 1);
        }}
        initialIN={inWallet?.starting_balance || 500000}
        initialUS={usWallet?.starting_balance || 10000}
      />
    </div>
  );
}
