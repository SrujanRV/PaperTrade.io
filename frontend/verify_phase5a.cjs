const puppeteer = require('puppeteer-core');
const path = require('path');
const { execSync } = require('child_process');

const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const artifactDir = 'C:\\Users\\sruja\\.gemini\\antigravity\\brain\\5182a1a7-7298-4a93-b2df-7e0a8d19ae8d';
const venvPython = path.join(__dirname, '..', 'backend', 'venv', 'Scripts', 'python.exe');

async function run() {
  console.log('Launching Edge browser for Phase 5a Intraday Short Selling verification...');
  const browser = await puppeteer.launch({
    executablePath: edgePath,
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 1050 });

    console.log('1. Setting up clean test state in IN wallet...');
    execSync(`"${venvPython}" -c "from database import SessionLocal; from models.orm import Wallet, Holding, HoldingLot, Order, Transaction; from datetime import datetime, timezone, date; db = SessionLocal(); w = db.query(Wallet).filter(Wallet.market == 'IN').first(); db.query(Holding).filter(Holding.wallet_id == w.id).delete(); db.query(Order).filter(Order.wallet_id == w.id).delete(); db.query(Transaction).filter(Transaction.wallet_id == w.id).delete(); w.current_cash_balance = 100000.0; db.commit(); db.close()"`, {
      cwd: path.join(__dirname, '..', 'backend'),
    });

    console.log('Navigating to http://localhost:5173...');
    await page.goto('http://localhost:5173', { waitUntil: 'networkidle2' });
    await new Promise((r) => setTimeout(r, 1500));

    // Dismiss setup modal if visible
    const setupModalClose = await page.$('button[title="Close dialog"]');
    if (setupModalClose) {
      console.log('Dismissing setup modal...');
      await setupModalClose.click();
      await new Promise((r) => setTimeout(r, 600));
    }

    // Ensure Indian Market is selected
    console.log('Selecting Indian Market watchlist...');
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const inBtn = btns.find((b) => b.textContent.includes('Indian Market') || b.textContent.includes('IN (INR)'));
      if (inBtn) inBtn.click();
    });
    await new Promise((r) => setTimeout(r, 1000));

    // Open RELIANCE.NS row to open Order Ticket
    console.log('Opening RELIANCE.NS Order Ticket...');
    const rows = await page.$$('tbody tr');
    if (rows.length > 0) {
      await rows[0].click();
    }
    await new Promise((r) => setTimeout(r, 1500));

    // Switch Order Ticket to SELL side
    console.log('Selecting SELL side for Short Selling...');
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const sellBtn = btns.find((b) => b.textContent.trim() === 'SELL');
      if (sellBtn) sellBtn.click();
    });
    await new Promise((r) => setTimeout(r, 1000));

    // Set quantity to 10
    console.log('Setting short sell quantity to 10...');
    await page.evaluate(() => {
      const input = document.querySelector('input[type="number"]');
      if (input) {
        input.value = '10';
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
    await new Promise((r) => setTimeout(r, 800));

    // ── 1. Capture Order Ticket configured for Short Sell ──
    console.log('Capturing order_ticket_short_sell.png...');
    await page.screenshot({
      path: path.join(artifactDir, 'order_ticket_short_sell.png'),
    });

    // ── 2. Create active short position & closed trades in DB for visual inspection ──
    console.log('Injecting short holding, orders, and covered trades for portfolio/history verification...');
    execSync(`"${venvPython}" -c "from database import SessionLocal; from models.orm import Wallet, Holding, HoldingLot, Order, Transaction; from datetime import datetime, timezone, date; db = SessionLocal(); w = db.query(Wallet).filter(Wallet.market == 'IN').first(); now = datetime.now(timezone.utc); h = Holding(wallet_id=w.id, ticker='RELIANCE.NS', quantity=10.0, avg_buy_price=2450.0, is_short=True, is_intraday=True, square_off_date=date.today()); db.add(h); db.flush(); lot = HoldingLot(holding_id=h.id, quantity=10.0, buy_price=2450.0, is_short=True, is_intraday=True, square_off_date=date.today(), created_at=now); db.add(lot); o1 = Order(wallet_id=w.id, ticker='RELIANCE.NS', order_type='market', side='sell', quantity=10.0, executed_price=2450.0, status='filled', is_short=True, is_intraday=True, square_off_date=date.today(), created_at=now, executed_at=now); db.add(o1); db.flush(); t1 = Transaction(wallet_id=w.id, order_id=o1.id, ticker='RELIANCE.NS', side='sell', quantity=10.0, price=2450.0, total_value=24500.0, cash_balance_after=124500.0, is_short=True, avg_buy_price=2450.0, timestamp=now); db.add(t1); o2 = Order(wallet_id=w.id, ticker='TCS.NS', order_type='market', side='sell', quantity=5.0, executed_price=3900.0, status='filled', is_short=True, is_intraday=True, square_off_date=date.today(), created_at=now, executed_at=now); db.add(o2); db.flush(); t2 = Transaction(wallet_id=w.id, order_id=o2.id, ticker='TCS.NS', side='sell', quantity=5.0, price=3900.0, total_value=19500.0, cash_balance_after=144000.0, is_short=True, avg_buy_price=3900.0, timestamp=now); db.add(t2); o3 = Order(wallet_id=w.id, ticker='TCS.NS', order_type='market', side='buy', quantity=5.0, executed_price=3820.0, status='filled', is_short=True, triggered_by='auto_square_off', created_at=now, executed_at=now); db.add(o3); db.flush(); t3 = Transaction(wallet_id=w.id, order_id=o3.id, ticker='TCS.NS', side='buy', quantity=5.0, price=3820.0, total_value=19100.0, cash_balance_after=124900.0, is_short=True, avg_buy_price=3900.0, realized_pnl=400.0, triggered_by='auto_square_off', timestamp=now); db.add(t3); w.current_cash_balance = 124900.0; db.commit(); db.close()"`, {
      cwd: path.join(__dirname, '..', 'backend'),
    });

    // Close Order Ticket
    console.log('Closing Order Ticket sidebar...');
    await page.evaluate(() => {
      const closeBtn = document.querySelector('button.p-1.text-text-muted');
      if (closeBtn) closeBtn.click();
    });
    await new Promise((r) => setTimeout(r, 800));

    // ── 3. Switch to Portfolio Tab ──
    console.log('Navigating to Portfolio tab...');
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const portBtn = btns.find((b) => b.textContent.toUpperCase().includes('PORTFOLIO'));
      if (portBtn) portBtn.click();
    });
    await new Promise((r) => setTimeout(r, 1500));

    // Select Indian Market in Portfolio
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const inBtn = btns.find((b) => b.textContent.includes('Indian Market') || b.textContent.includes('IN (INR)'));
      if (inBtn) inBtn.click();
    });
    await new Promise((r) => setTimeout(r, 2000));

    console.log('Capturing portfolio_short_position.png...');
    await page.screenshot({
      path: path.join(artifactDir, 'portfolio_short_position.png'),
    });

    // ── 4. Switch to Order History Tab ──
    console.log('Navigating to Order History tab...');
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const histBtn = btns.find((b) => b.textContent.toUpperCase().includes('ORDERS') || b.textContent.toUpperCase().includes('HISTORY'));
      if (histBtn) histBtn.click();
    });
    await new Promise((r) => setTimeout(r, 1500));

    // Select Indian Market in Order History
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const inBtn = btns.find((b) => b.textContent.includes('Indian Market') || b.textContent.includes('IN (INR)'));
      if (inBtn) inBtn.click();
    });
    await new Promise((r) => setTimeout(r, 2000));

    console.log('Capturing order_history_short_cover.png...');
    await page.screenshot({
      path: path.join(artifactDir, 'order_history_short_cover.png'),
    });

    // ── 5. Switch to Trade Log Tab ──
    console.log('Navigating to Trade Log tab...');
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const tradeBtn = btns.find((b) => b.textContent.toUpperCase().includes('TRADE LOG') || b.textContent.toUpperCase().includes('TRADES'));
      if (tradeBtn) tradeBtn.click();
    });
    await new Promise((r) => setTimeout(r, 1500));

    // Select Indian Market in Trade Log
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const inBtn = btns.find((b) => b.textContent.includes('Indian Market') || b.textContent.includes('IN (INR)'));
      if (inBtn) inBtn.click();
    });
    await new Promise((r) => setTimeout(r, 2000));

    console.log('Capturing trade_log_short_covered.png...');
    await page.screenshot({
      path: path.join(artifactDir, 'trade_log_short_covered.png'),
    });

    console.log('All Phase 5a verification screenshots captured successfully!');
  } catch (err) {
    console.error('Verification failed with error:', err);
    process.exit(1);
  } finally {
    await browser.close();
  }
}

run();
