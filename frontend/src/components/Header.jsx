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

export function Header({ inWallet, usWallet, onOpenWalletSetup, onOpenSettings }) {
  const [currentTime, setCurrentTime] = useState('');

  useEffect(() => {
    function updateClock() {
      const now = new Date();
      setCurrentTime(
        now.toISOString().replace('T', ' ').substring(0, 19) + ' UTC'
      );
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

      {/* Center/Right: Dual Wallet Balance Badges */}
      <div className="flex items-center space-x-4">
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
