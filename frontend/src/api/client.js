/**
 * API client for PaperTrade backend
 */

export async function fetchWallet(market) {
  const res = await fetch(`/api/wallet/${market}`);
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Failed to fetch ${market} wallet: ${res.statusText}`);
  }
  return await res.json();
}

export async function fetchWalletSummary(market) {
  const res = await fetch(`/api/wallet/${market}/summary`);
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Failed to fetch ${market} wallet summary: ${res.statusText}`);
  }
  return await res.json();
}

export async function fetchOrders(market) {
  const res = await fetch(`/api/orders/${market}`);
  if (res.status === 404) return [];
  if (!res.ok) {
    throw new Error(`Failed to fetch orders for ${market}: ${res.statusText}`);
  }
  return await res.json();
}

export async function setupWallet(market, startingBalance) {
  const res = await fetch('/api/wallet/setup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      market,
      starting_balance: Number(startingBalance),
    }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Setup failed for ${market}`);
  }
  return await res.json();
}

export async function placeOrder({
  market,
  ticker,
  side,
  quantity,
  order_type = 'market',
  requested_price = null,
  trigger_price = null,
}) {
  const payload = {
    market,
    ticker,
    side,
    quantity: Number(quantity),
    order_type,
  };
  if (requested_price !== null && requested_price !== undefined && requested_price !== '') {
    payload.requested_price = Number(requested_price);
  }
  if (trigger_price !== null && trigger_price !== undefined && trigger_price !== '') {
    payload.trigger_price = Number(trigger_price);
  }

  const res = await fetch('/api/orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Order placement failed`);
  }
  return await res.json();
}

export async function fetchPendingOrders(market) {
  const res = await fetch(`/api/orders/${market}/pending`);
  if (res.status === 404) return [];
  if (!res.ok) {
    throw new Error(`Failed to fetch pending orders for ${market}: ${res.statusText}`);
  }
  return await res.json();
}

export async function cancelPendingOrder(orderId) {
  const res = await fetch(`/api/order/${orderId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to cancel order #${orderId}`);
  }
  return await res.json();
}

export async function validateTicker(symbol) {
  const res = await fetch(`/api/prices/validate?symbol=${encodeURIComponent(symbol.trim().toUpperCase())}`);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Validation request failed for ${symbol}`);
  }
  return await res.json();
}

export async function fetchTrades(market) {
  const res = await fetch(`/api/wallet/${market}/trades`);
  if (res.status === 404) return [];
  if (!res.ok) {
    throw new Error(`Failed to fetch trades for ${market}: ${res.statusText}`);
  }
  return await res.json();
}

export async function searchTickers(query, market = 'US') {
  if (!query || !query.trim()) return [];
  const res = await fetch(`/api/prices/search?q=${encodeURIComponent(query.trim())}&market=${market}`);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Symbol search failed');
  }
  return await res.json();
}

export async function resetWalletBalance(market, cashBalance) {
  const res = await fetch(`/api/wallet/${market}/balance`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      cash_balance: Number(cashBalance),
    }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to update balance for ${market}`);
  }
  return await res.json();
}

export async function deleteWallet(market) {
  const res = await fetch(`/api/wallet/${market}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to delete ${market} wallet`);
  }
  return await res.json();
}

export async function fetchPreviousClose(ticker) {
  if (!ticker) return null;
  const res = await fetch(`/api/prices/${encodeURIComponent(ticker.trim().toUpperCase())}/previous-close`);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to fetch previous close for ${ticker}`);
  }
  return await res.json();
}

export async function fetchPriceHistory(ticker, range = '1d', interval = null) {
  if (!ticker) return [];
  let url = `/api/prices/${encodeURIComponent(ticker.trim().toUpperCase())}/history?range=${encodeURIComponent(range)}`;
  if (interval) {
    url += `&interval=${encodeURIComponent(interval)}`;
  }
  const res = await fetch(url);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to fetch price history for ${ticker}`);
  }
  return await res.json();
}





