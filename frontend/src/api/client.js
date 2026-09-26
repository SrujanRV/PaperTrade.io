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
  holding_days = null,
  square_off_date = null,
  is_intraday = false,
}) {
  const payload = {
    market,
    ticker,
    side,
    quantity: Number(quantity),
    order_type,
    is_intraday: Boolean(is_intraday),
  };
  if (requested_price !== null && requested_price !== undefined && requested_price !== '') {
    payload.requested_price = Number(requested_price);
  }
  if (trigger_price !== null && trigger_price !== undefined && trigger_price !== '') {
    payload.trigger_price = Number(trigger_price);
  }
  if (holding_days !== null && holding_days !== undefined && holding_days !== '') {
    payload.holding_days = Number(holding_days);
  }
  if (square_off_date) {
    payload.square_off_date = String(square_off_date);
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

export async function calculateSquareOffDate(market, days = 0, startDate = null) {
  let url = `/api/orders/calculate-square-off?market=${encodeURIComponent(market)}&days=${encodeURIComponent(days)}`;
  if (startDate) {
    url += `&start_date=${encodeURIComponent(startDate)}`;
  }
  const res = await fetch(url);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to calculate square-off date');
  }
  return await res.json();
}

export async function triggerAutoSquareOff(market = null) {
  let url = '/api/orders/trigger-square-off';
  if (market) {
    url += `?market=${encodeURIComponent(market)}`;
  }
  const res = await fetch(url, { method: 'POST' });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to trigger auto square-off');
  }
  return await res.json();
}

// ── Derivatives (F&O) API ────────────────────────────────────────────────────

export async function fetchOptionChain(market = 'IN', symbol = 'NIFTY', expiry = null) {
  let url = `/api/derivatives/chain?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}`;
  if (expiry) {
    url += `&expiry=${encodeURIComponent(expiry)}`;
  }
  const res = await fetch(url);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to fetch option chain for ${symbol}`);
  }
  return await res.json();
}

export async function fetchFuturesMarket(market = 'IN', symbol = null) {
  let url = `/api/derivatives/futures?market=${encodeURIComponent(market)}`;
  if (symbol) {
    url += `&symbol=${encodeURIComponent(symbol)}`;
  }
  const res = await fetch(url);
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to fetch futures market for ${market}`);
  }
  return await res.json();
}

export async function fetchDerivativePositions(market = 'IN') {
  const res = await fetch(`/api/derivatives/${encodeURIComponent(market)}/positions`);
  if (res.status === 404) return [];
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to fetch derivative positions for ${market}`);
  }
  return await res.json();
}

export async function fetchDerivativeOrders(market = 'IN') {
  const res = await fetch(`/api/derivatives/${encodeURIComponent(market)}/orders`);
  if (res.status === 404) return [];
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to fetch derivative orders for ${market}`);
  }
  return await res.json();
}

export async function fetchDerivativeTransactions(market = 'IN') {
  const res = await fetch(`/api/derivatives/${encodeURIComponent(market)}/transactions`);
  if (res.status === 404) return [];
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Failed to fetch derivative transactions for ${market}`);
  }
  return await res.json();
}

export async function placeDerivativeOrder({
  market,
  contract_id = null,
  underlying = null,
  instrument_type = null,
  option_type = null,
  strike_price = null,
  expiry_date = null,
  lot_size = null,
  symbol = null,
  side,
  action,
  quantity,
  order_type = 'market',
  price = null,
  underlying_price = null,
}) {
  const payload = {
    market,
    side,
    action,
    quantity: Number(quantity),
    order_type,
  };
  if (contract_id) payload.contract_id = Number(contract_id);
  if (underlying) payload.underlying = String(underlying);
  if (instrument_type) payload.instrument_type = String(instrument_type);
  if (option_type) payload.option_type = String(option_type);
  if (strike_price !== null && strike_price !== undefined) payload.strike_price = Number(strike_price);
  if (expiry_date) payload.expiry_date = String(expiry_date);
  if (lot_size) payload.lot_size = Number(lot_size);
  if (symbol) payload.symbol = String(symbol);
  if (price !== null && price !== undefined && price !== '') payload.price = Number(price);
  if (underlying_price !== null && underlying_price !== undefined && underlying_price !== '') {
    payload.underlying_price = Number(underlying_price);
  }

  const res = await fetch('/api/derivatives/order', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    let msg = 'Derivative order placement failed';
    if (errorData.detail) {
      if (typeof errorData.detail === 'string') {
        msg = errorData.detail;
      } else if (Array.isArray(errorData.detail)) {
        msg = errorData.detail.map((e) => e.msg || JSON.stringify(e)).join('; ');
      }
    }
    throw new Error(msg);
  }
  return await res.json();
}






