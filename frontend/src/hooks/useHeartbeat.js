import { useEffect } from 'react';

/**
 * useHeartbeat — Maintains an active browser tab heartbeat with the backend
 * and sends an unload beacon upon tab/window closure.
 */
export function useHeartbeat() {
  useEffect(() => {
    // Generate or retrieve persistent tab identifier for this browser session
    let tabId = sessionStorage.getItem('papertrade_tab_id');
    if (!tabId) {
      tabId = 'tab_' + Math.random().toString(36).substring(2, 9) + '_' + Date.now();
      sessionStorage.setItem('papertrade_tab_id', tabId);
    }

    const sendPing = () => {
      fetch('/api/heartbeat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tab_id: tabId }),
        keepalive: true,
      }).catch(() => {
        // Silent ignore network errors during page transitions
      });
    };

    // Immediate initial ping on mount
    sendPing();

    // Ping backend every 5 seconds
    const interval = setInterval(sendPing, 5000);

    // Reliable teardown signal via navigator.sendBeacon
    const handleUnload = () => {
      if (navigator.sendBeacon) {
        const payload = JSON.stringify({ tab_id: tabId, status: 'closing' });
        const blob = new Blob([payload], { type: 'application/json' });
        navigator.sendBeacon('/api/heartbeat/unload', blob);
      }
    };

    window.addEventListener('beforeunload', handleUnload);
    window.addEventListener('pagehide', handleUnload);

    return () => {
      clearInterval(interval);
      window.removeEventListener('beforeunload', handleUnload);
      window.removeEventListener('pagehide', handleUnload);
    };
  }, []);
}
