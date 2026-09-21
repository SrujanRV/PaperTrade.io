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

export async function placeOrder({ market, ticker, side, quantity }) {
  const res = await fetch('/api/orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      market,
      ticker,
      side,
      quantity: Number(quantity),
    }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Order placement failed`);
  }
  return await res.json();
}
