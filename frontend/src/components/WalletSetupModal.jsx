import React, { useState, useEffect } from 'react';
import { X } from 'lucide-react';
import { setupWallet } from '../api/client';

export function WalletSetupModal({
  isOpen,
  onClose,
  onComplete,
  targetMarket = 'BOTH',
  initialIN = 500000,
  initialUS = 10000,
}) {
  const [activeMode, setActiveMode] = useState(targetMarket || 'BOTH');
  const [inBalance, setInBalance] = useState(initialIN);
  const [usBalance, setUsBalance] = useState(initialUS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Sync mode whenever targetMarket changes or modal opens
  useEffect(() => {
    if (isOpen) {
      setActiveMode(targetMarket || 'BOTH');
      setError(null);
    }
  }, [isOpen, targetMarket]);

  // Handle ESC key to dismiss
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);

    const needIN = activeMode === 'IN' || activeMode === 'BOTH';
    const needUS = activeMode === 'US' || activeMode === 'BOTH';

    const inNum = Number(inBalance);
    const usNum = Number(usBalance);

    if (needIN && (!inNum || inNum <= 0)) {
      setError('Indian wallet starting balance must be greater than zero.');
      return;
    }
    if (needUS && (!usNum || usNum <= 0)) {
      setError('US wallet starting balance must be greater than zero.');
      return;
    }

    setLoading(true);
    try {
      if (needIN && needUS) {
        await setupWallet('IN', inNum);
        await setupWallet('US', usNum);
      } else if (needIN) {
        await setupWallet('IN', inNum);
      } else if (needUS) {
        await setupWallet('US', usNum);
      }
      onComplete();
    } catch (err) {
      setError(err.message || 'Failed to initialize wallet(s)');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-md bg-surface border border-border text-text-primary shadow-2xl">
        {/* Terminal Header */}
        <div className="h-10 px-4 bg-[#111317] border-b border-border flex items-center justify-between select-none">
          <div className="flex items-center space-x-2 text-xs font-semibold tracking-wider text-text-primary uppercase">
            <span className="w-1.5 h-1.5 rounded-full bg-accent" />
            <span>Terminal Setup // Wallet Initialization</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            title="Dismiss Setup"
            className="p-1 text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Market Scope Selector */}
        <div className="px-5 pt-4 pb-2 border-b border-border/60 bg-[#121418]">
          <div className="text-[10px] font-mono-tabular text-text-muted uppercase tracking-wider mb-2">
            Configure Wallet Scope
          </div>
          <div className="grid grid-cols-3 gap-1 p-0.5 bg-base border border-border font-mono-tabular text-xs">
            <button
              type="button"
              onClick={() => setActiveMode('IN')}
              className={`py-1 font-semibold uppercase tracking-wider transition-colors ${
                activeMode === 'IN'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              India (INR)
            </button>
            <button
              type="button"
              onClick={() => setActiveMode('US')}
              className={`py-1 font-semibold uppercase tracking-wider transition-colors ${
                activeMode === 'US'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              US (USD)
            </button>
            <button
              type="button"
              onClick={() => setActiveMode('BOTH')}
              className={`py-1 font-semibold uppercase tracking-wider transition-colors ${
                activeMode === 'BOTH'
                  ? 'bg-[#232731] text-text-primary'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              Both
            </button>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div className="text-xs text-text-muted leading-relaxed">
            {activeMode === 'BOTH' && (
              <span>
                Paper trading operates with two independent virtual wallets. Set starting balances for both markets below:
              </span>
            )}
            {activeMode === 'IN' && (
              <span>
                Initialize your Indian paper trading wallet for NSE/BSE equities.
              </span>
            )}
            {activeMode === 'US' && (
              <span>
                Initialize your US paper trading wallet for NYSE/NASDAQ equities.
              </span>
            )}
          </div>

          {error && (
            <div className="p-2.5 bg-red/10 border border-red/40 text-red text-xs font-mono-tabular flex items-start space-x-2">
              <span className="w-1.5 h-1.5 rounded-full bg-red shrink-0 mt-1" />
              <span>{error}</span>
            </div>
          )}

          <div className="space-y-4 font-mono-tabular">
            {/* IN Wallet Balance */}
            {(activeMode === 'IN' || activeMode === 'BOTH') && (
              <div>
                <label className="block text-[11px] font-sans uppercase tracking-wider text-text-muted mb-1.5">
                  Indian Market Balance (INR)
                </label>
                <div className="relative">
                  <span className="absolute left-3 top-2.5 text-xs text-text-muted font-bold">₹</span>
                  <input
                    type="number"
                    min="1"
                    step="any"
                    required
                    value={inBalance}
                    onChange={(e) => setInBalance(e.target.value)}
                    className="w-full h-9 pl-7 pr-3 bg-base border border-border text-xs text-text-primary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                    placeholder="500000"
                  />
                </div>
                {/* Presets */}
                <div className="flex items-center space-x-1.5 mt-2">
                  <span className="text-[10px] text-text-muted">Presets:</span>
                  {[100000, 500000, 1000000].map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => setInBalance(preset)}
                      className="px-1.5 py-0.5 text-[10px] bg-base border border-border hover:border-accent text-text-muted hover:text-text-primary transition-colors"
                    >
                      ₹{(preset / 100000).toFixed(0)}L
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* US Wallet Balance */}
            {(activeMode === 'US' || activeMode === 'BOTH') && (
              <div>
                <label className="block text-[11px] font-sans uppercase tracking-wider text-text-muted mb-1.5">
                  US Market Balance (USD)
                </label>
                <div className="relative">
                  <span className="absolute left-3 top-2.5 text-xs text-text-muted font-bold">$</span>
                  <input
                    type="number"
                    min="1"
                    step="any"
                    required
                    value={usBalance}
                    onChange={(e) => setUsBalance(e.target.value)}
                    className="w-full h-9 pl-7 pr-3 bg-base border border-border text-xs text-text-primary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                    placeholder="10000"
                  />
                </div>
                {/* Presets */}
                <div className="flex items-center space-x-1.5 mt-2">
                  <span className="text-[10px] text-text-muted">Presets:</span>
                  {[5000, 10000, 25000].map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => setUsBalance(preset)}
                      className="px-1.5 py-0.5 text-[10px] bg-base border border-border hover:border-accent text-text-muted hover:text-text-primary transition-colors"
                    >
                      ${(preset / 1000).toFixed(0)}k
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Action buttons */}
          <div className="pt-3 flex items-center space-x-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 h-9 bg-base hover:bg-surface-hover border border-border text-text-muted hover:text-text-primary text-xs font-semibold tracking-wider uppercase transition-colors select-none"
            >
              CANCEL
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 h-9 bg-accent hover:bg-accent/90 disabled:opacity-50 text-white text-xs font-semibold tracking-wider uppercase transition-colors select-none"
            >
              {loading
                ? 'INITIALIZING...'
                : activeMode === 'BOTH'
                ? 'INITIALIZE BOTH'
                : `INITIALIZE ${activeMode}`}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
