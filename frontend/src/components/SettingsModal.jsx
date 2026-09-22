import React, { useState, useEffect } from 'react';
import { X, AlertTriangle, Check } from 'lucide-react';
import { resetWalletBalance, deleteWallet } from '../api/client';

export function SettingsModal({
  isOpen,
  onClose,
  inWallet,
  usWallet,
  onWalletUpdated,
  onResetWatchlists,
  defaultTab,
  onUpdateDefaultTab,
}) {
  const [activeSection, setActiveSection] = useState('portfolio'); // 'portfolio' | 'preferences'
  const [selectedMarket, setSelectedMarket] = useState('IN'); // 'IN' | 'US' | 'BOTH'
  
  // Balance reset state
  const [newBalance, setNewBalance] = useState('');
  const [updatingBalance, setUpdatingBalance] = useState(false);
  const [balanceSuccess, setBalanceSuccess] = useState(false);
  const [balanceError, setBalanceError] = useState(null);

  // Destructive delete confirmation state
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState(null);

  // Watchlist reset feedback state
  const [watchlistResetDone, setWatchlistResetDone] = useState(false);

  // Sync newBalance placeholder/value when market changes
  useEffect(() => {
    setConfirmDelete(false);
    setBalanceSuccess(false);
    setBalanceError(null);
    setDeleteError(null);

    if (selectedMarket === 'IN') {
      setNewBalance(inWallet ? String(inWallet.current_cash_balance) : '500000');
    } else if (selectedMarket === 'US') {
      setNewBalance(usWallet ? String(usWallet.current_cash_balance) : '10000');
    }
  }, [selectedMarket, inWallet, usWallet, isOpen]);

  // Handle ESC key to dismiss (or cancel delete confirmation if active)
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape' && isOpen) {
        if (confirmDelete) {
          setConfirmDelete(false);
        } else {
          onClose();
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, confirmDelete, onClose]);

  if (!isOpen) return null;

  const currentWallet = selectedMarket === 'IN' ? inWallet : usWallet;
  const currencySymbol = selectedMarket === 'IN' ? '₹' : '$';
  const currencyCode = selectedMarket === 'IN' ? 'INR' : 'USD';

  // Handle updating cash balance without wiping history
  async function handleUpdateBalance(e) {
    e.preventDefault();
    setBalanceError(null);
    setBalanceSuccess(false);

    const val = Number(newBalance);
    if (!val || val <= 0) {
      setBalanceError('Cash balance must be greater than zero.');
      return;
    }

    setUpdatingBalance(true);
    try {
      if (selectedMarket === 'BOTH') {
        if (inWallet) await resetWalletBalance('IN', val);
        if (usWallet) await resetWalletBalance('US', val);
      } else {
        await resetWalletBalance(selectedMarket, val);
      }
      setBalanceSuccess(true);
      if (onWalletUpdated) onWalletUpdated();
      setTimeout(() => setBalanceSuccess(false), 3000);
    } catch (err) {
      setBalanceError(err.message || 'Failed to update balance');
    } finally {
      setUpdatingBalance(false);
    }
  }

  // Handle deleting portfolio (hard reset)
  async function handleExecuteDelete() {
    setDeleteError(null);
    setDeleting(true);

    try {
      if (selectedMarket === 'BOTH') {
        if (inWallet) await deleteWallet('IN');
        if (usWallet) await deleteWallet('US');
      } else {
        await deleteWallet(selectedMarket);
      }
      setConfirmDelete(false);
      if (onWalletUpdated) onWalletUpdated();
    } catch (err) {
      setDeleteError(err.message || 'Failed to delete portfolio');
    } finally {
      setDeleting(false);
    }
  }

  function handleResetWatchlistClick() {
    if (onResetWatchlists) {
      onResetWatchlists();
      setWatchlistResetDone(true);
      setTimeout(() => setWatchlistResetDone(false), 3000);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 select-none"
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          if (confirmDelete) setConfirmDelete(false);
          else onClose();
        }
      }}
    >
      <div className="w-full max-w-xl bg-surface border border-border text-text-primary shadow-2xl flex flex-col font-sans max-h-[90vh] overflow-hidden">
        {/* Terminal Header */}
        <div className="h-10 px-4 bg-[#111317] border-b border-border flex items-center justify-between shrink-0">
          <div className="flex items-center space-x-2 text-xs font-semibold tracking-wider text-text-primary uppercase font-mono-tabular">
            <span className="w-1.5 h-1.5 rounded-full bg-accent" />
            <span>Terminal Configuration // Settings</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            title="Close Settings"
            className="p-1 text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Section Navigation Tabs */}
        <div className="flex border-b border-border bg-[#131519] shrink-0 font-mono-tabular text-xs">
          <button
            type="button"
            onClick={() => setActiveSection('portfolio')}
            className={`px-5 py-2.5 font-semibold uppercase tracking-wider transition-colors border-b-2 ${
              activeSection === 'portfolio'
                ? 'border-accent text-text-primary bg-surface'
                : 'border-transparent text-text-muted hover:text-text-primary'
            }`}
          >
            Portfolio Management
          </button>
          <button
            type="button"
            onClick={() => setActiveSection('preferences')}
            className={`px-5 py-2.5 font-semibold uppercase tracking-wider transition-colors border-b-2 ${
              activeSection === 'preferences'
                ? 'border-accent text-text-primary bg-surface'
                : 'border-transparent text-text-muted hover:text-text-primary'
            }`}
          >
            Terminal Preferences
          </button>
        </div>

        {/* Scrollable Modal Body */}
        <div className="p-6 overflow-y-auto space-y-6">
          {activeSection === 'portfolio' && (
            <div className="space-y-6">
              {/* Market Scope Selector */}
              <div>
                <label className="block text-[11px] font-mono-tabular uppercase tracking-wider text-text-muted mb-2">
                  Target Portfolio / Market
                </label>
                <div className="grid grid-cols-3 gap-1 p-0.5 bg-base border border-border font-mono-tabular text-xs">
                  <button
                    type="button"
                    onClick={() => setSelectedMarket('IN')}
                    className={`py-1.5 font-semibold uppercase tracking-wider transition-colors ${
                      selectedMarket === 'IN'
                        ? 'bg-[#232731] text-text-primary'
                        : 'text-text-muted hover:text-text-primary'
                    }`}
                  >
                    India (NSE)
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedMarket('US')}
                    className={`py-1.5 font-semibold uppercase tracking-wider transition-colors ${
                      selectedMarket === 'US'
                        ? 'bg-[#232731] text-text-primary'
                        : 'text-text-muted hover:text-text-primary'
                    }`}
                  >
                    US (USD)
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedMarket('BOTH')}
                    className={`py-1.5 font-semibold uppercase tracking-wider transition-colors ${
                      selectedMarket === 'BOTH'
                        ? 'bg-[#232731] text-text-primary'
                        : 'text-text-muted hover:text-text-primary'
                    }`}
                  >
                    Both Markets
                  </button>
                </div>
              </div>

              {/* Status Summary Banner */}
              <div className="p-3 bg-base border border-border font-mono-tabular text-xs space-y-1.5">
                <div className="flex items-center justify-between text-text-muted">
                  <span>PORTFOLIO STATUS:</span>
                  <span className="font-semibold text-text-primary uppercase">
                    {selectedMarket === 'BOTH' ? (
                      inWallet || usWallet ? (
                        <span className="text-green">ACTIVE</span>
                      ) : (
                        <span className="text-text-muted">UNINITIALIZED</span>
                      )
                    ) : currentWallet ? (
                      <span className="text-green">INITIALIZED & ACTIVE</span>
                    ) : (
                      <span className="text-text-muted">NOT INITIALIZED</span>
                    )}
                  </span>
                </div>
                {selectedMarket !== 'BOTH' && currentWallet && (
                  <>
                    <div className="flex items-center justify-between text-text-muted">
                      <span>CURRENT CASH:</span>
                      <span className="text-text-primary font-medium">
                        {currencySymbol}
                        {Number(currentWallet.current_cash_balance).toLocaleString()}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-text-muted">
                      <span>OPEN POSITIONS:</span>
                      <span className="text-text-primary font-medium">
                        {currentWallet.holdings?.length || 0}
                      </span>
                    </div>
                  </>
                )}
              </div>

              {/* Action 1: Reset Cash Balance (Non-destructive) */}
              {selectedMarket !== 'BOTH' && currentWallet && (
                <div className="p-4 bg-[#14161b] border border-border space-y-3">
                  <div>
                    <div className="text-xs font-semibold text-text-primary uppercase tracking-wider font-mono-tabular">
                      Reset Cash Balance
                    </div>
                    <p className="text-[11px] text-text-muted mt-0.5 leading-relaxed">
                      Adjusts available paper cash balance without clearing open positions, order history, or trade logs.
                    </p>
                  </div>

                  {balanceError && (
                    <div className="p-2 bg-red/10 border border-red/40 text-red text-xs font-mono-tabular">
                      {balanceError}
                    </div>
                  )}

                  <form onSubmit={handleUpdateBalance} className="space-y-2.5">
                    <div className="flex items-center space-x-2">
                      <div className="relative flex-1 font-mono-tabular">
                        <span className="absolute left-3 top-2 text-xs text-text-muted font-bold">
                          {currencySymbol}
                        </span>
                        <input
                          type="number"
                          min="1"
                          step="any"
                          value={newBalance}
                          onChange={(e) => setNewBalance(e.target.value)}
                          className="w-full h-8 pl-7 pr-3 bg-base border border-border text-xs text-text-primary focus:border-accent focus:outline-none"
                          placeholder="Amount"
                        />
                      </div>
                      <button
                        type="submit"
                        disabled={updatingBalance}
                        className="h-8 px-4 bg-[#232731] hover:bg-border text-text-primary text-xs font-mono-tabular uppercase tracking-wider transition-colors disabled:opacity-50 shrink-0"
                      >
                        {updatingBalance ? 'UPDATING...' : 'UPDATE BALANCE'}
                      </button>
                    </div>

                    {/* Presets */}
                    <div className="flex items-center space-x-1.5 font-mono-tabular">
                      <span className="text-[10px] text-text-muted">Presets:</span>
                      {(selectedMarket === 'IN' ? [100000, 500000, 1000000] : [5000, 10000, 25000]).map(
                        (preset) => (
                          <button
                            key={preset}
                            type="button"
                            onClick={() => setNewBalance(String(preset))}
                            className="px-1.5 py-0.5 text-[10px] bg-base border border-border hover:border-accent text-text-muted hover:text-text-primary transition-colors"
                          >
                            {currencySymbol}
                            {selectedMarket === 'IN'
                              ? `${(preset / 100000).toFixed(0)}L`
                              : `${(preset / 1000).toFixed(0)}k`}
                          </button>
                        )
                      )}
                    </div>
                  </form>

                  {balanceSuccess && (
                    <div className="flex items-center space-x-1.5 text-xs text-green font-mono-tabular">
                      <Check className="w-3.5 h-3.5" />
                      <span>Cash balance updated successfully.</span>
                    </div>
                  )}
                </div>
              )}

              {/* Action 2: Delete Portfolio (Destructive Hard Reset) */}
              {(selectedMarket === 'BOTH' ? inWallet || usWallet : currentWallet) ? (
                <div className="p-4 bg-[#181315] border border-red/30 space-y-3">
                  <div>
                    <div className="text-xs font-semibold text-red uppercase tracking-wider font-mono-tabular flex items-center space-x-1.5">
                      <AlertTriangle className="w-3.5 h-3.5 text-red" />
                      <span>Delete Portfolio // Hard Reset</span>
                    </div>
                    <p className="text-[11px] text-text-muted mt-1 leading-relaxed">
                      Permanently wipes all open positions, executed orders, and realized trade records for{' '}
                      <strong className="text-text-primary">
                        {selectedMarket === 'BOTH' ? 'BOTH markets' : `the ${selectedMarket} market`}
                      </strong>
                      . Resets wallet to an uninitialized state.
                    </p>
                  </div>

                  {deleteError && (
                    <div className="p-2 bg-red/10 border border-red/40 text-red text-xs font-mono-tabular">
                      {deleteError}
                    </div>
                  )}

                  {!confirmDelete ? (
                    <button
                      type="button"
                      onClick={() => setConfirmDelete(true)}
                      className="px-4 py-2 bg-red/15 hover:bg-red/25 border border-red/50 text-red hover:text-red text-xs font-mono-tabular font-semibold uppercase tracking-wider transition-colors"
                    >
                      DELETE {selectedMarket === 'BOTH' ? 'BOTH PORTFOLIOS' : `${selectedMarket} PORTFOLIO`}
                    </button>
                  ) : (
                    /* Two-step cancelable confirmation panel */
                    <div className="p-3.5 bg-black/60 border border-red/60 space-y-3 font-mono-tabular">
                      <div className="text-xs font-semibold text-red uppercase tracking-wider">
                        CONFIRM HARD RESET — CANNOT BE UNDONE
                      </div>
                      <p className="text-[11px] text-text-muted leading-relaxed">
                        Are you sure you want to permanently erase this portfolio? All holdings, order history, and P&L metrics will be lost.
                      </p>
                      <div className="flex items-center space-x-2 pt-1">
                        <button
                          type="button"
                          onClick={() => setConfirmDelete(false)}
                          className="flex-1 h-8 bg-base hover:bg-surface-hover border border-border text-text-muted hover:text-text-primary text-xs font-semibold uppercase tracking-wider transition-colors"
                        >
                          CANCEL
                        </button>
                        <button
                          type="button"
                          disabled={deleting}
                          onClick={handleExecuteDelete}
                          className="flex-1 h-8 bg-red hover:bg-red/90 disabled:opacity-50 text-white text-xs font-semibold uppercase tracking-wider transition-colors"
                        >
                          {deleting ? 'DELETING...' : 'CONFIRM PERMANENT DELETE'}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="p-4 bg-base border border-border font-mono-tabular text-xs text-text-muted">
                  No active wallet found for {selectedMarket === 'BOTH' ? 'these markets' : selectedMarket}. Initialize via the trade ticket or header setup.
                </div>
              )}
            </div>
          )}

          {activeSection === 'preferences' && (
            <div className="space-y-6">
              {/* Preference 1: Default Landing View */}
              <div className="p-4 bg-[#14161b] border border-border space-y-3 font-mono-tabular">
                <div>
                  <div className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                    Default Landing View
                  </div>
                  <p className="text-[11px] text-text-muted mt-0.5 leading-relaxed font-sans">
                    Choose which workspace view is displayed automatically when loading the terminal.
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-2 text-xs">
                  {[
                    { id: 'watchlist', label: 'Watchlist' },
                    { id: 'portfolio', label: 'Portfolio & Positions' },
                    { id: 'history', label: 'Order History' },
                    { id: 'trades', label: 'Trade Log (P&L)' },
                  ].map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => onUpdateDefaultTab && onUpdateDefaultTab(tab.id)}
                      className={`p-2.5 text-left border uppercase tracking-wider transition-colors flex items-center justify-between ${
                        defaultTab === tab.id
                          ? 'border-accent bg-accent/10 text-text-primary font-semibold'
                          : 'border-border bg-base text-text-muted hover:text-text-primary'
                      }`}
                    >
                      <span>{tab.label}</span>
                      {defaultTab === tab.id && <span className="w-1.5 h-1.5 rounded-full bg-accent" />}
                    </button>
                  ))}
                </div>
              </div>

              {/* Preference 2: Reset Watchlist to Defaults */}
              <div className="p-4 bg-[#14161b] border border-border space-y-3 font-mono-tabular">
                <div>
                  <div className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                    Restore Default Watchlists
                  </div>
                  <p className="text-[11px] text-text-muted mt-0.5 leading-relaxed font-sans">
                    Restores the initial curated asset lists (NSE: RELIANCE.NS, TCS.NS; US: AAPL, TSLA) if symbols were deleted.
                  </p>
                </div>

                <div className="flex items-center space-x-3">
                  <button
                    type="button"
                    onClick={handleResetWatchlistClick}
                    className="px-4 py-2 bg-[#232731] hover:bg-border text-xs text-text-primary font-semibold uppercase tracking-wider transition-colors border border-border"
                  >
                    RESTORE DEFAULT SYMBOLS
                  </button>

                  {watchlistResetDone && (
                    <div className="flex items-center space-x-1.5 text-xs text-green font-mono-tabular">
                      <Check className="w-3.5 h-3.5" />
                      <span>Watchlists restored to defaults.</span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="h-12 px-6 bg-[#111317] border-t border-border flex items-center justify-end shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="px-5 py-1.5 bg-[#232731] hover:bg-border text-xs text-text-primary uppercase tracking-wider font-semibold font-mono-tabular transition-colors"
          >
            CLOSE
          </button>
        </div>
      </div>
    </div>
  );
}
