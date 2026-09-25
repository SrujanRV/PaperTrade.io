import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Header } from './components/Header';
import { Watchlist } from './components/Watchlist';
import { Portfolio } from './components/Portfolio';
import { OrderHistory } from './components/OrderHistory';
import { TradeLog } from './components/TradeLog';
import { OrderTicket } from './components/OrderTicket';
import { WalletSetupModal } from './components/WalletSetupModal';
import { SettingsModal } from './components/SettingsModal';
import { CandlestickChartModal } from './components/CandlestickChartModal';
import { fetchWallet, fetchPendingOrders, fetchOrders } from './api/client';
import { usePriceStream } from './hooks/usePriceStream';
import { useHeartbeat } from './hooks/useHeartbeat';

const LEGACY_STORAGE_KEY = 'papertrade_watchlist';
const STORAGE_KEY_IN = 'papertrade_watchlist_IN';
const STORAGE_KEY_US = 'papertrade_watchlist_US';
const STORAGE_KEY_DEFAULT_TAB = 'papertrade_default_tab';

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

function loadInitialDefaultTab() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_DEFAULT_TAB);
    if (saved && ['watchlist', 'portfolio', 'history', 'trades'].includes(saved)) {
      return saved;
    }
  } catch (e) {}
  return 'watchlist';
}

export default function App() {
  useHeartbeat();
  const [inWallet, setInWallet] = useState(null);
  const [usWallet, setUsWallet] = useState(null);
  const [checkingWallets, setCheckingWallets] = useState(true);

  // Setup modal state
  const [showWalletModal, setShowWalletModal] = useState(false);
  const [walletModalTarget, setWalletModalTarget] = useState('BOTH'); // 'IN' | 'US' | 'BOTH'

  // Settings modal state
  const [showSettingsModal, setShowSettingsModal] = useState(false);

  // Dynamic user-editable watchlists split by market ('IN' and 'US')
  const [watchlists, setWatchlists] = useState(loadInitialWatchlists);
  const [watchlistMarket, setWatchlistMarket] = useState('IN');

  // Navigation tab state: 'watchlist' | 'portfolio' | 'history' | 'trades'
  const [activeTab, setActiveTab] = useState(loadInitialDefaultTab);

  // Portfolio selected market: 'IN' | 'US'
  const [portfolioMarket, setPortfolioMarket] = useState('IN');

  // Active ticker open in OrderTicket side panel
  const [selectedTicker, setSelectedTicker] = useState(null);

  // Active ticker open in full CandlestickChartModal
  const [fullChartTicker, setFullChartTicker] = useState(null);

  // Trigger to force re-fetch of portfolio summary when orders execute
  const [refreshKey, setRefreshKey] = useState(0);

  const handleUpdateDefaultTab = useCallback((tabId) => {
    setActiveTab(tabId);
    try {
      localStorage.setItem(STORAGE_KEY_DEFAULT_TAB, tabId);
    } catch (e) {
      console.error('Failed to save default tab to localStorage:', e);
    }
  }, []);

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

  const handleResetWatchlistsToDefaults = useCallback(() => {
    setWatchlists({ IN: DEFAULT_IN, US: DEFAULT_US });
    try {
      localStorage.setItem(STORAGE_KEY_IN, JSON.stringify(DEFAULT_IN));
      localStorage.setItem(STORAGE_KEY_US, JSON.stringify(DEFAULT_US));
    } catch (e) {
      console.error('Failed to reset watchlists to defaults:', e);
    }
  }, []);

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

      // On initial load, if neither wallet exists and user hasn't dismissed setup in this session, show setup modal
      const dismissed = sessionStorage.getItem('papertrade_setup_dismissed');
      if (!inData && !usData && !dismissed) {
        setShowWalletModal(true);
        setWalletModalTarget('BOTH');
      }
    } catch (err) {
      console.error('Error fetching wallets:', err);
    } finally {
      setCheckingWallets(false);
    }
  }, []);

  // Pending orders tracking & fill notifications
  const [pendingOrders, setPendingOrders] = useState([]);
  const [newFills, setNewFills] = useState([]);

  const checkPendingOrders = useCallback(async () => {
    try {
      const [inPending, usPending] = await Promise.all([
        fetchPendingOrders('IN').catch(() => []),
        fetchPendingOrders('US').catch(() => []),
      ]);
      const currentPending = [...(inPending || []), ...(usPending || [])];

      setPendingOrders((prevPending) => {
        if (prevPending.length > 0) {
          const currentIds = new Set(currentPending.map((o) => o.id));
          const missing = prevPending.filter((o) => !currentIds.has(o.id));
          if (missing.length > 0) {
            Promise.all([
              fetchOrders('IN').catch(() => []),
              fetchOrders('US').catch(() => []),
            ]).then(([inAll, usAll]) => {
              const allOrders = [...(inAll || []), ...(usAll || [])];
              const newlyFilled = missing
                .map((m) => allOrders.find((o) => o.id === m.id))
                .filter((o) => o && o.status === 'filled');

              if (newlyFilled.length > 0) {
                setNewFills((prev) => [...prev, ...newlyFilled]);
                refreshWallets();
                setRefreshKey((k) => k + 1);
              }
            });
          }
        }
        return currentPending;
      });
    } catch (e) {
      // Non-critical background polling
    }
  }, [refreshWallets]);

  useEffect(() => {
    checkPendingOrders();
    const interval = setInterval(checkPendingOrders, 5000);
    return () => clearInterval(interval);
  }, [checkPendingOrders, refreshKey]);

  useEffect(() => {
    refreshWallets();
  }, [refreshWallets]);

  const handleOpenWalletSetup = useCallback((target = 'BOTH') => {
    setWalletModalTarget(target);
    setShowWalletModal(true);
  }, []);

  const handleCloseWalletModal = useCallback(() => {
    setShowWalletModal(false);
    try {
      sessionStorage.setItem('papertrade_setup_dismissed', 'true');
    } catch (e) {}
  }, []);

  // Determine which wallet corresponds to the selected ticker in OrderTicket
  const isSelectedIndian =
    selectedTicker?.toUpperCase().endsWith('.NS') ||
    selectedTicker?.toUpperCase().endsWith('.BO');
  const activeWallet = isSelectedIndian ? inWallet : usWallet;
  const activeQuote = selectedTicker ? prices[selectedTicker.toUpperCase()] : null;

  function handleOrderExecuted() {
    refreshWallets();
    checkPendingOrders();
    setRefreshKey((k) => k + 1);
  }

  const activePortfolioWallet = portfolioMarket === 'IN' ? inWallet : usWallet;

  return (
    <div className="min-h-screen bg-base text-text-primary flex flex-col font-sans selection:bg-accent/30 selection:text-white">
      {/* Persistent Terminal Header with Wallets & Notifications */}
      <Header
        inWallet={inWallet}
        usWallet={usWallet}
        pendingCount={pendingOrders.length}
        newFillsCount={newFills.length}
        onNavigateToHistory={() => {
          setActiveTab('history');
          setNewFills([]);
        }}
        onOpenWalletSetup={handleOpenWalletSetup}
        onOpenSettings={() => setShowSettingsModal(true)}
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
              onClick={() => {
                setActiveTab('history');
                setNewFills([]);
              }}
              className={`px-4 py-1.5 text-xs font-semibold uppercase tracking-wider transition-colors flex items-center space-x-1.5 ${
                activeTab === 'history'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              <span>Order History</span>
              {newFills.length > 0 ? (
                <span className="px-1.5 py-0.2 text-[9px] bg-green text-black font-bold font-mono-tabular animate-pulse">
                  {newFills.length} NEW
                </span>
              ) : pendingOrders.length > 0 ? (
                <span className="px-1.5 py-0.2 text-[9px] bg-accent/20 text-accent font-semibold font-mono-tabular">
                  {pendingOrders.length}
                </span>
              ) : null}
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
                onOpenChart={(ticker) => setFullChartTicker(ticker)}
              />
            )}

            {activeTab === 'portfolio' && (
              <Portfolio
                selectedMarket={portfolioMarket}
                onSelectMarket={(m) => setPortfolioMarket(m)}
                onSelectTicker={(ticker) => setSelectedTicker(ticker)}
                onOpenChart={(ticker) => setFullChartTicker(ticker)}
                onGoToWatchlist={() => setActiveTab('watchlist')}
                onOpenWalletSetup={handleOpenWalletSetup}
                livePrices={prices}
                refreshKey={refreshKey}
              />
            )}

            {activeTab === 'history' && (
              <OrderHistory
                selectedMarket={portfolioMarket}
                wallet={activePortfolioWallet}
                onSelectMarket={(m) => setPortfolioMarket(m)}
                onGoToWatchlist={() => setActiveTab('watchlist')}
                onOpenWalletSetup={handleOpenWalletSetup}
                onOrderUpdated={handleOrderExecuted}
                refreshKey={refreshKey}
              />
            )}

            {activeTab === 'trades' && (
              <TradeLog
                selectedMarket={portfolioMarket}
                wallet={activePortfolioWallet}
                onSelectMarket={(m) => setPortfolioMarket(m)}
                onGoToWatchlist={() => setActiveTab('watchlist')}
                onGoToPortfolio={() => setActiveTab('portfolio')}
                onOpenWalletSetup={handleOpenWalletSetup}
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
                onOpenWalletSetup={handleOpenWalletSetup}
                onOpenChart={(ticker) => setFullChartTicker(ticker)}
              />
            </div>
          )}
        </div>
      </main>

      {/* Dedicated Candlestick Chart Modal */}
      <CandlestickChartModal
        isOpen={Boolean(fullChartTicker)}
        ticker={fullChartTicker}
        quote={fullChartTicker ? prices[fullChartTicker.toUpperCase()] : null}
        onClose={() => setFullChartTicker(null)}
        onTrade={(tickerToTrade) => {
          setSelectedTicker(tickerToTrade);
          setFullChartTicker(null);
        }}
      />

      {/* Dedicated Dismissible Wallet Setup Modal */}
      <WalletSetupModal
        isOpen={showWalletModal}
        targetMarket={walletModalTarget}
        onClose={handleCloseWalletModal}
        onComplete={() => {
          setShowWalletModal(false);
          refreshWallets();
          setRefreshKey((k) => k + 1);
        }}
        initialIN={inWallet?.starting_balance || 500000}
        initialUS={usWallet?.starting_balance || 10000}
      />

      {/* Restructured Settings Modal */}
      <SettingsModal
        isOpen={showSettingsModal}
        onClose={() => setShowSettingsModal(false)}
        inWallet={inWallet}
        usWallet={usWallet}
        onWalletUpdated={() => {
          refreshWallets();
          setRefreshKey((k) => k + 1);
        }}
        onResetWatchlists={handleResetWatchlistsToDefaults}
        defaultTab={activeTab}
        onUpdateDefaultTab={handleUpdateDefaultTab}
      />
    </div>
  );
}
