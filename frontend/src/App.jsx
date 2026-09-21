import React, { useState, useEffect, useCallback } from 'react';
import { Header } from './components/Header';
import { Watchlist } from './components/Watchlist';
import { OrderTicket } from './components/OrderTicket';
import { WalletSetupModal } from './components/WalletSetupModal';
import { fetchWallet } from './api/client';
import { usePriceStream } from './hooks/usePriceStream';

const DEFAULT_TICKERS = ['AAPL', 'TSLA', 'RELIANCE.NS', 'TCS.NS'];

export default function App() {
  const [inWallet, setInWallet] = useState(null);
  const [usWallet, setUsWallet] = useState(null);
  const [checkingWallets, setCheckingWallets] = useState(true);
  const [showWalletModal, setShowWalletModal] = useState(false);
  const [selectedTicker, setSelectedTicker] = useState('AAPL'); // default open ticker

  // Live SSE stream for watchlist and active order ticket
  const { prices } = usePriceStream(DEFAULT_TICKERS);

  // Fetch wallets status
  const refreshWallets = useCallback(async () => {
    try {
      const [inData, usData] = await Promise.all([
        fetchWallet('IN'),
        fetchWallet('US'),
      ]);
      setInWallet(inData);
      setUsWallet(usData);

      // If either wallet doesn't exist yet, trigger the setup modal
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

  // Determine which wallet corresponds to the selected ticker
  const isSelectedIndian =
    selectedTicker?.toUpperCase().endsWith('.NS') ||
    selectedTicker?.toUpperCase().endsWith('.BO');
  const activeWallet = isSelectedIndian ? inWallet : usWallet;
  const activeQuote = selectedTicker ? prices[selectedTicker.toUpperCase()] : null;

  return (
    <div className="min-h-screen bg-base text-text-primary flex flex-col font-sans selection:bg-accent/30 selection:text-white">
      {/* Persistent Terminal Header with Wallets */}
      <Header
        inWallet={inWallet}
        usWallet={usWallet}
        onOpenWalletSetup={() => setShowWalletModal(true)}
      />

      {/* Main Terminal Workspace */}
      <main className="flex-1 p-4 md:p-6 max-w-7xl w-full mx-auto">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-sm font-semibold tracking-wide text-text-primary uppercase">
              Trading Terminal
            </h1>
            <p className="text-xs text-text-muted mt-0.5 font-mono-tabular">
              Select any asset to inspect and place simulated market orders
            </p>
          </div>
        </div>

        {/* Dual Layout: Watchlist on Left, Order Ticket on Right */}
        <div className="flex flex-col lg:flex-row gap-6 items-start">
          {/* Watchlist Table */}
          <div className="flex-1 w-full">
            <Watchlist
              selectedTicker={selectedTicker}
              onSelectTicker={(ticker) => setSelectedTicker(ticker)}
            />
          </div>

          {/* Docked Order Ticket Side Panel */}
          {selectedTicker && (
            <div className="w-full lg:w-auto shrink-0">
              <OrderTicket
                ticker={selectedTicker}
                quote={activeQuote}
                wallet={activeWallet}
                onClose={() => setSelectedTicker(null)}
                onOrderExecuted={() => {
                  refreshWallets();
                }}
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
        }}
        initialIN={inWallet?.starting_balance || 500000}
        initialUS={usWallet?.starting_balance || 10000}
      />
    </div>
  );
}
