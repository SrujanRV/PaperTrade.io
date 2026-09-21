import React, { useState } from 'react';
import { setupWallet } from '../api/client';

export function WalletSetupModal({ isOpen, onComplete, initialIN = 500000, initialUS = 10000 }) {
  const [inBalance, setInBalance] = useState(initialIN);
  const [usBalance, setUsBalance] = useState(initialUS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  if (!isOpen) return null;

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    if (inBalance <= 0 || usBalance <= 0) {
      setError('Starting balances must be greater than zero.');
      return;
    }

    setLoading(true);
    try {
      // Setup both wallets sequentially
      await setupWallet('IN', inBalance);
      await setupWallet('US', usBalance);
      onComplete();
    } catch (err) {
      setError(err.message || 'Failed to initialize wallets');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="w-full max-w-md bg-surface border border-border text-text-primary shadow-2xl">
        {/* Terminal Header */}
        <div className="h-10 px-4 bg-[#111317] border-b border-border flex items-center justify-between select-none">
          <div className="flex items-center space-x-2 text-xs font-semibold tracking-wider text-text-primary uppercase">
            <span className="w-1.5 h-1.5 rounded-full bg-accent" />
            <span>Terminal Setup // Wallet Initialization</span>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-5">
          <div className="text-xs text-text-muted leading-relaxed">
            Paper trading operates with two independent virtual wallets (no cross-currency FX conversion). Set your starting paper cash for each market:
          </div>

          {error && (
            <div className="p-3 bg-red/10 border border-red/40 text-red text-xs font-mono-tabular flex items-start space-x-2">
              <span className="w-1.5 h-1.5 rounded-full bg-red shrink-0 mt-1" />
              <span>{error}</span>
            </div>
          )}

          <div className="space-y-4 font-mono-tabular">
            {/* IN Wallet Balance */}
            <div>
              <label className="block text-[11px] font-sans uppercase tracking-wider text-text-muted mb-1.5">
                Indian Market Balance (INR)
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2.5 text-xs text-text-muted">₹</span>
                <input
                  type="number"
                  min="1"
                  step="1000"
                  required
                  value={inBalance}
                  onChange={(e) => setInBalance(e.target.value)}
                  className="w-full h-9 pl-7 pr-3 bg-base border border-border text-xs text-text-primary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                  placeholder="500000"
                />
              </div>
              <span className="text-[10px] text-text-muted mt-1 block">
                Recommended: ₹5,00,000 for learning NSE/BSE stocks
              </span>
            </div>

            {/* US Wallet Balance */}
            <div>
              <label className="block text-[11px] font-sans uppercase tracking-wider text-text-muted mb-1.5">
                US Market Balance (USD)
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2.5 text-xs text-text-muted">$</span>
                <input
                  type="number"
                  min="1"
                  step="100"
                  required
                  value={usBalance}
                  onChange={(e) => setUsBalance(e.target.value)}
                  className="w-full h-9 pl-7 pr-3 bg-base border border-border text-xs text-text-primary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                  placeholder="10000"
                />
              </div>
              <span className="text-[10px] text-text-muted mt-1 block">
                Recommended: $10,000 for learning NYSE/NASDAQ stocks
              </span>
            </div>
          </div>

          {/* Action buttons */}
          <div className="pt-2">
            <button
              type="submit"
              disabled={loading}
              className="w-full h-10 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-semibold tracking-wider uppercase transition-colors select-none"
            >
              {loading ? 'INITIALIZING TERMINAL...' : 'START PAPER TRADING'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
