const puppeteer = require('puppeteer-core');
const path = require('path');

const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const artifactDir = 'C:\\Users\\sruja\\.gemini\\antigravity\\brain\\5182a1a7-7298-4a93-b2df-7e0a8d19ae8d';

async function run() {
  console.log('Launching Edge browser for Phase 4k verification...');
  const browser = await puppeteer.launch({
    executablePath: edgePath,
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 1100 });

    console.log('Navigating to http://localhost:5173...');
    await page.goto('http://localhost:5173', { waitUntil: 'networkidle2' });
    await new Promise((r) => setTimeout(r, 2000));

    // Handle initial setup modal if open
    const setupModalClose = await page.$('button[title="Close dialog"]');
    if (setupModalClose) {
      console.log('Dismissing initial wallet setup modal...');
      await setupModalClose.click();
      await new Promise((r) => setTimeout(r, 600));
    }

    // Switch to US Market watchlist
    console.log('Switching to US Market watchlist...');
    const allButtons = await page.$$('button');
    for (const b of allButtons) {
      const text = await page.evaluate((el) => el.textContent, b);
      if (text.includes('US Market')) {
        await b.click();
        break;
      }
    }
    await new Promise((r) => setTimeout(r, 1200));

    // Click AAPL row to open Order Ticket
    console.log('Opening AAPL Order Ticket...');
    const rows = await page.$$('tbody tr');
    if (rows.length > 0) {
      await rows[0].click();
    }
    await new Promise((r) => setTimeout(r, 2500));

    // ── 1. Order Ticket Chart 1D ──
    console.log('Capturing order_ticket_chart_1d.png...');
    await page.screenshot({
      path: path.join(artifactDir, 'order_ticket_chart_1d.png'),
    });

    // ── 2. Order Ticket Chart 1W ──
    console.log('Switching Order Ticket chart to 1W...');
    const orderTicketRangeButtons = await page.$$('div.p-3.bg-\\[\\#0d0f12\\] button');
    for (const b of orderTicketRangeButtons) {
      const text = await page.evaluate((el) => el.textContent, b);
      if (text.trim() === '1W') {
        await b.click();
        break;
      }
    }
    await new Promise((r) => setTimeout(r, 2500));

    console.log('Capturing order_ticket_chart_1w.png...');
    await page.screenshot({
      path: path.join(artifactDir, 'order_ticket_chart_1w.png'),
    });

    // ── 3. Order Ticket Chart 1M ──
    console.log('Switching Order Ticket chart to 1M...');
    const orderTicketRangeButtonsM = await page.$$('div.p-3.bg-\\[\\#0d0f12\\] button');
    for (const b of orderTicketRangeButtonsM) {
      const text = await page.evaluate((el) => el.textContent, b);
      if (text.trim() === '1M') {
        await b.click();
        break;
      }
    }
    await new Promise((r) => setTimeout(r, 2500));

    console.log('Capturing order_ticket_chart_1m.png...');
    await page.screenshot({
      path: path.join(artifactDir, 'order_ticket_chart_1m.png'),
    });

    // ── 4. Full Candlestick Modal 1D ──
    console.log('Clicking expand button on Order Ticket chart...');
    const expandBtn = await page.$('button[title*="full candlestick chart"]');
    if (expandBtn) {
      await expandBtn.click();
    } else {
      // Fallback to chart icon in watchlist row
      console.log('Using watchlist chart icon fallback...');
      const chartIconBtn = await page.$('button[title*="Open candlestick chart"]');
      if (chartIconBtn) await chartIconBtn.click();
    }
    await new Promise((r) => setTimeout(r, 3000));

    // Hover crosshair on candlestick chart canvas
    const canvas = await page.$('.fixed.inset-0 canvas');
    if (canvas) {
      const box = await canvas.boundingBox();
      if (box) {
        await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.4);
        await new Promise((r) => setTimeout(r, 500));
      }
    }

    console.log('Capturing full_candlestick_modal_1d.png...');
    await page.screenshot({
      path: path.join(artifactDir, 'full_candlestick_modal_1d.png'),
    });

    // ── 5. Full Candlestick Modal 1W ──
    console.log('Switching Candlestick modal to 1W range...');
    const modalRangeButtons = await page.$$('.fixed.inset-0 button');
    for (const b of modalRangeButtons) {
      const text = await page.evaluate((el) => el.textContent, b);
      if (text.trim() === '1W') {
        await b.click();
        break;
      }
    }
    await new Promise((r) => setTimeout(r, 3000));

    if (canvas) {
      const box = await canvas.boundingBox();
      if (box) {
        await page.mouse.move(box.x + box.width * 0.7, box.y + box.height * 0.45);
        await new Promise((r) => setTimeout(r, 500));
      }
    }

    console.log('Capturing full_candlestick_modal_1w.png...');
    await page.screenshot({
      path: path.join(artifactDir, 'full_candlestick_modal_1w.png'),
    });

    // ── 6. Full Candlestick Modal 1M ──
    console.log('Switching Candlestick modal to 1M range...');
    const modalRangeButtonsM = await page.$$('.fixed.inset-0 button');
    for (const b of modalRangeButtonsM) {
      const text = await page.evaluate((el) => el.textContent, b);
      if (text.trim() === '1M') {
        await b.click();
        break;
      }
    }
    await new Promise((r) => setTimeout(r, 3000));

    if (canvas) {
      const box = await canvas.boundingBox();
      if (box) {
        await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
        await new Promise((r) => setTimeout(r, 500));
      }
    }

    console.log('Capturing full_candlestick_modal_1m.png...');
    await page.screenshot({
      path: path.join(artifactDir, 'full_candlestick_modal_1m.png'),
    });

    console.log('ALL 6 SCREENSHOTS CAPTURED SUCCESSFULLY!');
  } catch (err) {
    console.error('Error during verification:', err);
  } finally {
    await browser.close();
  }
}

run();
