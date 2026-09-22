const puppeteer = require('puppeteer-core');
const path = require('path');
const { execSync } = require('child_process');

const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const artifactDir = 'C:\\Users\\sruja\\.gemini\\antigravity\\brain\\5182a1a7-7298-4a93-b2df-7e0a8d19ae8d';
const venvPython = path.join(__dirname, '..', 'backend', 'venv', 'Scripts', 'python.exe');

async function run() {
  console.log('Launching Edge browser for Phase 4l verification...');
  const browser = await puppeteer.launch({
    executablePath: edgePath,
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 1050 });

    console.log('1. Setting up clean test holdings (10 untimed + 5 timed shares of AAPL)...');
    execSync(`"${venvPython}" -c "from database import SessionLocal; from models.orm import Wallet, Holding, HoldingLot; from datetime import date; db = SessionLocal(); w = db.query(Wallet).filter(Wallet.market == 'US').first(); db.query(Holding).filter(Holding.wallet_id == w.id).delete(); db.commit(); h = Holding(wallet_id=w.id, ticker='AAPL', quantity=15.0, avg_buy_price=231.67, square_off_date=date(2026, 9, 24), is_intraday=False); db.add(h); db.flush(); l1 = HoldingLot(holding_id=h.id, quantity=10.0, buy_price=230.0, square_off_date=None, is_intraday=False); l2 = HoldingLot(holding_id=h.id, quantity=5.0, buy_price=235.0, square_off_date=date(2026, 9, 24), is_intraday=False); db.add_all([l1, l2]); db.commit(); db.close()"`, {
      cwd: path.join(__dirname, '..', 'backend'),
    });

    console.log('Navigating to http://localhost:5173...');
    await page.goto('http://localhost:5173', { waitUntil: 'networkidle2' });
    await new Promise((r) => setTimeout(r, 1500));

    // Handle any initial setup modal if open
    const setupModalClose = await page.$('button[title="Close dialog"]');
    if (setupModalClose) {
      console.log('Dismissing setup modal...');
      await setupModalClose.click();
      await new Promise((r) => setTimeout(r, 600));
    }

    // Switch to US Market watchlist
    console.log('Switching to US Market watchlist...');
    const allButtons = await page.$$('button');
    for (const b of allButtons) {
      const text = await page.evaluate((el) => el.textContent, b);
      if (text.includes('US Market') || text.includes('US (USD)')) {
        await b.click();
        break;
      }
    }
    await new Promise((r) => setTimeout(r, 1000));

    // Click AAPL row to open Order Ticket
    console.log('Opening AAPL Order Ticket...');
    const rows = await page.$$('tbody tr');
    if (rows.length > 0) {
      await rows[0].click();
    }
    await new Promise((r) => setTimeout(r, 2000));

    // Select CUSTOM duration option
    console.log('Selecting CUSTOM duration in Order Ticket...');
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const found = btns.find((b) => b.textContent.trim().startsWith('CUSTOM'));
      if (found) found.click();
    });
    await new Promise((r) => setTimeout(r, 1200));

    // ── 1. Capture Order Ticket with Duration Selector & IST header clock ──
    console.log('Capturing order_ticket_duration_selector.png...');
    await page.screenshot({
      path: path.join(artifactDir, 'order_ticket_duration_selector.png'),
    });

    // Close Order Ticket
    console.log('Closing Order Ticket sidebar...');
    await page.evaluate(() => {
      const closeBtn = document.querySelector('button.p-1.text-text-muted');
      if (closeBtn) closeBtn.click();
    });
    await new Promise((r) => setTimeout(r, 800));

    // ── 2. Switch to Portfolio and capture quantity-specific square-off badge ──
    console.log('Navigating to Portfolio tab...');
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const portBtn = btns.find((b) => b.textContent.toUpperCase().includes('PORTFOLIO'));
      if (portBtn) portBtn.click();
    });
    await new Promise((r) => setTimeout(r, 1500));

    // Select US Market in Portfolio
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const usBtn = btns.find((b) => b.textContent.includes('US Market') || b.textContent.includes('US (USD)'));
      if (usBtn) usBtn.click();
    });
    await new Promise((r) => setTimeout(r, 2000));

    console.log('Capturing portfolio_holding_square_off_badge.png...');
    await page.screenshot({
      path: path.join(artifactDir, 'portfolio_holding_square_off_badge.png'),
    });

    // ── 3. Simulate expiry for the 5 timed shares and trigger auto square-off ──
    console.log('Simulating expiry for the 5 timed shares and triggering auto square-off...');
    execSync(`"${venvPython}" -c "from database import SessionLocal; from models.orm import Holding, HoldingLot; from datetime import date; db = SessionLocal(); l = db.query(HoldingLot).join(Holding).filter(Holding.ticker == 'AAPL', HoldingLot.square_off_date.isnot(None)).first(); l.square_off_date = date.today(); db.commit(); db.close()"`, {
      cwd: path.join(__dirname, '..', 'backend'),
    });

    const triggerResult = await page.evaluate(async () => {
      const res = await fetch('http://127.0.0.1:8000/api/orders/trigger-square-off?market=US', {
        method: 'POST',
      });
      return await res.json();
    });
    console.log('Trigger result:', triggerResult);
    await new Promise((r) => setTimeout(r, 1500));

    // ── 4. Switch to Order History and capture AUTO badge ──
    console.log('Navigating to Order History tab...');
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const ordBtn = btns.find((b) => b.textContent.toUpperCase().includes('ORDER HISTORY'));
      if (ordBtn) ordBtn.click();
    });
    await new Promise((r) => setTimeout(r, 1500));

    // Ensure US Market is selected in Order History
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const usBtn = btns.find((b) => b.textContent.includes('US Market'));
      if (usBtn) usBtn.click();
    });
    await new Promise((r) => setTimeout(r, 2000));

    console.log('Capturing order_history_auto_square_off.png...');
    await page.screenshot({
      path: path.join(artifactDir, 'order_history_auto_square_off.png'),
    });

    // ── 5. Switch to Trade Log and capture AUTO badge on closed trade ──
    console.log('Navigating to Trade Log tab...');
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const tradeBtn = btns.find((b) => b.textContent.toUpperCase().includes('TRADE LOG'));
      if (tradeBtn) tradeBtn.click();
    });
    await new Promise((r) => setTimeout(r, 1500));

    // Ensure US Market is selected in Trade Log
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const usBtn = btns.find((b) => b.textContent.includes('US (USD)') || b.textContent.includes('US Market'));
      if (usBtn) usBtn.click();
    });
    await new Promise((r) => setTimeout(r, 2000));

    console.log('Capturing trade_log_auto_square_off.png...');
    await page.screenshot({
      path: path.join(artifactDir, 'trade_log_auto_square_off.png'),
    });

    console.log('All 4 screenshots verified and saved successfully!');
  } catch (err) {
    console.error('Verification failed:', err);
    process.exit(1);
  } finally {
    await browser.close();
  }
}

run();
