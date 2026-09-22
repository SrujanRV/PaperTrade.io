import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Header } from './components/Header';
import { Watchlist } from './components/Watchlist';
import { Portfolio } from './components/Portfolio';
import { OrderHistory } from './components/OrderHistory';
import { TradeLog } from './components/TradeLog';
import { OrderTicket } from './components/OrderTicket';
import { WalletSetupModal } from './components/WalletSetupModal';
import { fetchWallet } from './api/client';
import { usePriceStream } from './hooks/usePriceStream';

const LEGACY_STORAGE_KEY = 'papertrade_watchlist';
const STORAGE_KEY_IN = 'papertrade_watchlist_IN';
const STORAGE_KEY_US = 'papertrade_watchlist_US';

const DEFAULT_IN = ['RELIANCE.NS', 'TCS.NS'];
const DEFAULT_US = ['AAPL', 'TSLA'];

function loadInitialWatchlists() {
  let inList = null;
  let usList = null;

  try {
    const savedIn = localStorage.getItem(STORAGE_KEY_IN);
    if (savedIn) {
      const parsed = JSON.parse(savedIn);
      if (Array.isArray(parsed)) inList = parsed;
    }

    const savedUs = localStorage.getItem(STORAGE_KEY_US);
    if (savedUs) {
      const parsed = JSON.parse(savedUs);
      if (Array.isArray(parsed)) usList = parsed;
    }

    // Migrate from legacy single list if per-market lists aren't set up yet
    if (!inList && !usList) {
      const legacy = localStorage.getItem(LEGACY_STORAGE_KEY);
      if (legacy) {
        const parsedLegacy = JSON.parse(legacy);
        if (Array.isArray(parsedLegacy) && parsedLegacy.length > 0) {
          inList = parsedLegacy.filter((t) => t.toUpperCase().endsWith('.NS') || t.toUpperCase().endsWith('.BO'));
          usList = parsedLegacy.filter((t) => !t.toUpperCase().endsWith('.NS') && !t.toUpperCase().endsWith('.BO'));
        }
      }
    }
  } catch (err) {
    console.error('Failed to load or migrate watchlists from localStorage:', err);
  }

  if (!inList || inList.length === 0) inList = DEFAULT_IN;
  if (!usList || usList.length === 0) usList = DEFAULT_US;

  // Persist migrated format
  try {
    localStorage.setItem(STORAGE_KEY_IN, JSON.stringify(inList));
    localStorage.setItem(STORAGE_KEY_US, JSON.stringify(usList));
  } catch (e) {}

  return { IN: inList, US: usList };
}

export default function App() {
  const [inWallet, setInWallet] = useState(null);
  const [usWallet, setUsWallet] = useState(null);
  const [checkingWallets, setCheckingWallets] = useState(true);
  const [showWalletModal, setShowWalletModal] = useState(false);

  // Dynamic user-editable watchlists split by market ('IN' and 'US')
  const [watchlists, setWatchlists] = useState(loadInitialWatchlists);
  const [watchlistMarket, setWatchlistMarket] = useState('IN');

  // Navigation tab state: 'watchlist' | 'portfolio' | 'history' | 'trades'
  const [activeTab, setActiveTab] = useState('watchlist');

  // Portfolio selected market: 'IN' | 'US'
  const [portfolioMarket, setPortfolioMarket] = useState('IN');

  // Active ticker open in OrderTicket side panel
  const [selectedTicker, setSelectedTicker] = useState(null);

  // Trigger to force re-fetch of portfolio summary when orders execute
  const [refreshKey, setRefreshKey] = useState(0);

  const handleAddTicker = useCallback((ticker, targetMarket) => {
    const sym = ticker.trim().toUpperCase();
    const isIndian = sym.endsWith('.NS') || sym.endsWith('.BO');
    const market = targetMarket || (isIndian ? 'IN' : 'US');
    const storageKey = market === 'IN' ? STORAGE_KEY_IN : STORAGE_KEY_US;

    setWatchlists((prev) => {
      const currentList = prev[market] || [];
      if (currentList.includes(sym)) return prev;
      const nextList = [...currentList, sym];
      const next = { ...prev, [market]: nextList };
      try {
        localStorage.setItem(storageKey, JSON.stringify(nextList));
      } catch (e) {
        console.error('Failed to save watchlist to localStorage:', e);
      }
      return next;
    });
  }, []);

  const handleRemoveTicker = useCallback((ticker, targetMarket) => {
    const sym = ticker.trim().toUpperCase();
    const isIndian = sym.endsWith('.NS') || sym.endsWith('.BO');
    const market = targetMarket || (isIndian ? 'IN' : 'US');
    const storageKey = market === 'IN' ? STORAGE_KEY_IN : STORAGE_KEY_US;

    setWatchlists((prev) => {
      const currentList = prev[market] || [];
      const nextList = currentList.filter((t) => t !== sym);
      const next = { ...prev, [market]: nextList };
      try {
        localStorage.setItem(storageKey, JSON.stringify(nextList));
      } catch (e) {
        console.error('Failed to save watchlist to localStorage:', e);
      }
      return next;
    });

    if (selectedTicker?.toUpperCase() === sym) {
      setSelectedTicker(null);
    }
  }, [selectedTicker]);

  // Combine both market watchlist tickers with all currently held tickers for comprehensive SSE streaming
  const subscribedTickers = useMemo(() => {
    const set = new Set([...(watchlists.IN || []), ...(watchlists.US || [])]);
    inWallet?.holdings?.forEach((h) => set.add(h.ticker));
    usWallet?.holdings?.forEach((h) => set.add(h.ticker));
    return Array.from(set);
  }, [watchlists, inWallet, usWallet]);

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
            <button
              onClick={() => setActiveTab('trades')}
              className={`px-4 py-1.5 text-xs font-semibold uppercase tracking-wider transition-colors ${
                activeTab === 'trades'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              Trade Log (P&L)
            </button>
          </div>

          <div className="text-[11px] font-mono-tabular text-text-muted">
            <span>TERMINAL WORKSPACE // {activeTab.toUpperCase()}</span>
          </div>
        </div>

        {/* View Content: Watchlist, Portfolio, Order History, or Trade Log + Dockable Order Ticket */}
        <div className="flex flex-col lg:flex-row gap-6 items-start">
          {/* Main Table Area */}
          <div className="flex-1 w-full">
            {activeTab === 'watchlist' && (
              <Watchlist
                selectedMarket={watchlistMarket}
                onSelectMarket={(m) => setWatchlistMarket(m)}
                tickers={watchlists[watchlistMarket] || []}
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

            {activeTab === 'trades' && (
              <TradeLog
                selectedMarket={portfolioMarket}
                onSelectMarket={(m) => setPortfolioMarket(m)}
                onGoToWatchlist={() => setActiveTab('watchlist')}
                onGoToPortfolio={() => setActiveTab('portfolio')}
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
