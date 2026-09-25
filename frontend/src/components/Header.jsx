import React, { useState, useEffect } from 'react';
import { Activity, Settings } from 'lucide-react';

function formatMoney(amount, currency) {
  if (amount === undefined || amount === null || isNaN(amount)) return '—';
  const locale = currency === 'INR' ? 'en-IN' : 'en-US';
  return Number(amount).toLocaleString(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function Header({
  inWallet,
  usWallet,
  pendingCount = 0,
  newFillsCount = 0,
  onNavigateToHistory,
  onOpenWalletSetup,
  onOpenSettings,
}) {
  const [currentTime, setCurrentTime] = useState('');

  useEffect(() => {
    function updateClock() {
      const now = new Date();
      try {
        const formatter = new Intl.DateTimeFormat('en-CA', {
          timeZone: 'Asia/Kolkata',
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false,
        });
        const formatted = formatter.format(now).replace(',', '');
        setCurrentTime(`${formatted} IST`);
      } catch {
        setCurrentTime(now.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) + ' IST');
      }
    }
    updateClock();
    const timer = setInterval(updateClock, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <header className="h-12 border-b border-border bg-[#101216] px-4 flex items-center justify-between select-none">
      {/* Left: Branding */}
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

      {/* Center/Right: Notification Pills + Dual Wallet Balance Badges */}
      <div className="flex items-center space-x-3 sm:space-x-4">
        {/* Fill Notification Pill */}
        {newFillsCount > 0 && (
          <button
            type="button"
            onClick={onNavigateToHistory}
            title="View newly executed orders"
            className="flex items-center space-x-1.5 px-2.5 py-1 bg-green/15 border border-green/50 text-green hover:bg-green/25 text-[11px] font-mono-tabular font-bold uppercase tracking-wider transition-colors animate-pulse"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-green" />
            <span>{newFillsCount} ORDER{newFillsCount > 1 ? 'S' : ''} FILLED</span>
          </button>
        )}

        {/* Pending Orders Pill */}
        {pendingCount > 0 && newFillsCount === 0 && (
          <div
            title="Open pending limit/stop orders waiting for trigger"
            className="hidden sm:flex items-center space-x-1.5 px-2 py-1 bg-accent/10 border border-accent/40 text-accent text-[11px] font-mono-tabular font-medium uppercase tracking-wider"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
            <span>{pendingCount} PENDING</span>
          </div>
        )}
        {/* Indian Market Wallet */}
        <div className="flex items-center space-x-2 px-2.5 py-1 bg-surface border border-border">
          <span className="text-[10px] font-mono-tabular uppercase text-text-muted font-medium">
            IN CASH:
          </span>
          {inWallet ? (
            <span className="text-xs font-mono-tabular font-semibold text-text-primary">
              ₹{formatMoney(inWallet.current_cash_balance, 'INR')}
            </span>
          ) : (
            <button
              type="button"
              onClick={() => onOpenWalletSetup && onOpenWalletSetup('IN')}
              title="Initialize Indian Wallet"
              className="text-xs font-mono-tabular font-semibold text-accent hover:underline uppercase"
            >
              [SETUP]
            </button>
          )}
        </div>

        {/* US Market Wallet */}
        <div className="flex items-center space-x-2 px-2.5 py-1 bg-surface border border-border">
          <span className="text-[10px] font-mono-tabular uppercase text-text-muted font-medium">
            US CASH:
          </span>
          {usWallet ? (
            <span className="text-xs font-mono-tabular font-semibold text-text-primary">
              ${formatMoney(usWallet.current_cash_balance, 'USD')}
            </span>
          ) : (
            <button
              type="button"
              onClick={() => onOpenWalletSetup && onOpenWalletSetup('US')}
              title="Initialize US Wallet"
              className="text-xs font-mono-tabular font-semibold text-accent hover:underline uppercase"
            >
              [SETUP]
            </button>
          )}
        </div>

        {/* US Buying Power (only shown when margin_used > 0) */}
        {usWallet && (usWallet.margin_used || 0) > 0 && (
          <div
            title={`Total Locked Margin Collateral: $${formatMoney(usWallet.margin_used, 'USD')}`}
            className="flex items-center space-x-2 px-2.5 py-1 bg-surface border border-accent/40"
          >
            <span className="text-[10px] font-mono-tabular uppercase text-accent font-medium">
              US BUYING POWER:
            </span>
            <span className="text-xs font-mono-tabular font-semibold text-text-primary">
              ${formatMoney(usWallet.available_buying_power ?? (usWallet.current_cash_balance - usWallet.margin_used), 'USD')}
            </span>
          </div>
        )}

        {/* Global Clock */}
        <div className="hidden md:flex items-center text-[11px] font-mono-tabular text-text-muted border-l border-border pl-4">
          <span>{currentTime}</span>
        </div>

        {/* Settings Button */}
        <button
          onClick={onOpenSettings}
          title="Terminal Settings & Portfolio Management"
          className="p-1.5 text-text-muted hover:text-text-primary hover:bg-surface-hover border border-border transition-colors"
        >
          <Settings className="w-3.5 h-3.5" />
        </button>
      </div>
    </header>
  );
}
