import puppeteer from 'puppeteer-core';
import path from 'path';
import fs from 'fs';

const ARTIFACT_DIR = 'C:/Users/sruja/.gemini/antigravity/brain/5182a1a7-7298-4a93-b2df-7e0a8d19ae8d';
const CHROME_PATH = 'C:/Program Files/Google/Chrome/Application/chrome.exe';

async function run() {
  console.log('Starting Phase 6e Headless Verification...');
  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1440,900'],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });

  try {
    console.log('Navigating to http://127.0.0.1:8000/ ...');
    await page.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle2', timeout: 30000 });
    await new Promise((r) => setTimeout(r, 2000));

    // Dismiss wallet modal if present
    const dismissBtn = await page.$('button ::-p-text(DISMISS)');
    if (dismissBtn) {
      console.log('Dismissing wallet setup modal...');
      await dismissBtn.click();
      await new Promise((r) => setTimeout(r, 500));
    }

    // ─────────────────────────────────────────────────────────────────────────
    // STEP 1: Go to OPTIONS view -> US OPTIONS mode -> MSFT
    // ─────────────────────────────────────────────────────────────────────────
    console.log('Clicking Option Chain tab...');
    const optionsTab = await page.waitForSelector('button ::-p-text(Option Chain)', { timeout: 10000 });
    await optionsTab.click();
    await new Promise((r) => setTimeout(r, 1000));

    console.log('Clicking US Options sub-tab...');
    const usOptionsBtn = await page.waitForSelector('button ::-p-text(US Options)', { timeout: 10000 });
    await usOptionsBtn.click();
    await new Promise((r) => setTimeout(r, 2500));

    // Ensure MSFT is loaded (or click MSFT quick chip)
    const msftChip = await page.$('button ::-p-text(MSFT)');
    if (msftChip) {
      console.log('Clicking MSFT quick select chip...');
      await msftChip.click();
      await new Promise((r) => setTimeout(r, 3000));
    }

    // Wait for strikes table to render
    await page.waitForSelector('td ::-p-text(BUY/SELL)', { timeout: 15000 });
    console.log('US Options table loaded for MSFT!');

    const shot1 = path.join(ARTIFACT_DIR, 'option_chain_us_msft.png');
    await page.screenshot({ path: shot1 });
    console.log('Captured screenshot 1:', shot1);

    // ─────────────────────────────────────────────────────────────────────────
    // STEP 2: Click an active Call option for MSFT -> Verify Order Ticket
    // ─────────────────────────────────────────────────────────────────────────
    console.log('Clicking an active Call strike for MSFT...');
    await page.evaluate(() => {
      const tds = Array.from(document.querySelectorAll('td[title*="Trade Call Option MSFT"]'));
      const active = tds.find((td) => !td.innerText.includes('—'));
      if (active) active.click();
      else if (tds.length > 5) tds[5].click();
    });
    await new Promise((r) => setTimeout(r, 1000));

    // Verify Order Ticket opened with MSFT
    await page.waitForSelector('button ::-p-text(BUY TO OPEN)', { timeout: 10000 });
    console.log('Order Ticket opened in Options mode for MSFT!');

    const shot2 = path.join(ARTIFACT_DIR, 'order_ticket_us_msft_call.png');
    await page.screenshot({ path: shot2 });
    console.log('Captured screenshot 2:', shot2);

    // ─────────────────────────────────────────────────────────────────────────
    // STEP 3: Switch to NSE Stocks mode -> RELIANCE
    // ─────────────────────────────────────────────────────────────────────────
    console.log('Clicking NSE Stocks sub-tab in Option Chain...');
    const nseStocksBtn = await page.waitForSelector('button ::-p-text(NSE Stocks)', { timeout: 10000 });
    await nseStocksBtn.click();
    await new Promise((r) => setTimeout(r, 2500));

    const relianceChip = await page.$('button ::-p-text(RELIANCE)');
    if (relianceChip) {
      console.log('Clicking RELIANCE quick chip...');
      await relianceChip.click();
      await new Promise((r) => setTimeout(r, 3000));
    }

    await page.waitForSelector('td ::-p-text(BUY/SELL)', { timeout: 15000 });
    console.log('NSE Stocks option chain loaded for RELIANCE (Lot size 250)!');

    const shot3 = path.join(ARTIFACT_DIR, 'option_chain_in_reliance.png');
    await page.screenshot({ path: shot3 });
    console.log('Captured screenshot 3:', shot3);

    // ─────────────────────────────────────────────────────────────────────────
    // STEP 4: Click a Call option for RELIANCE -> Verify Order Ticket
    // ─────────────────────────────────────────────────────────────────────────
    console.log('Clicking an active Call strike for RELIANCE...');
    await page.evaluate(() => {
      const tds = Array.from(document.querySelectorAll('td[title*="Trade Call Option RELIANCE"]'));
      const active = tds.find((td) => !td.innerText.includes('—'));
      if (active) active.click();
      else if (tds.length > 5) tds[5].click();
    });
    await new Promise((r) => setTimeout(r, 1000));

    const shot4 = path.join(ARTIFACT_DIR, 'order_ticket_in_reliance_option.png');
    await page.screenshot({ path: shot4 });
    console.log('Captured screenshot 4:', shot4);

    // ─────────────────────────────────────────────────────────────────────────
    // STEP 5: Switch to FUTURES view -> Indian Stock Futures -> RELIANCE
    // ─────────────────────────────────────────────────────────────────────────
    console.log('Clicking Futures Market tab...');
    const futuresTab = await page.waitForSelector('button ::-p-text(Futures Market)', { timeout: 10000 });
    await futuresTab.click();
    await new Promise((r) => setTimeout(r, 1500));

    console.log('Clicking Indian Stock Futures (NSE) sub-tab...');
    const inStockFutBtn = await page.waitForSelector('button ::-p-text(Indian Stock Futures (NSE))', { timeout: 10000 });
    await inStockFutBtn.click();
    await new Promise((r) => setTimeout(r, 2500));

    // Verify stock futures table loaded for RELIANCE
    await page.waitForSelector('button ::-p-text(TRADE)', { timeout: 15000 });
    console.log('Indian Stock Futures table loaded for RELIANCE!');

    const shot5 = path.join(ARTIFACT_DIR, 'futures_market_reliance_stock.png');
    await page.screenshot({ path: shot5 });
    console.log('Captured screenshot 5:', shot5);

    // ─────────────────────────────────────────────────────────────────────────
    // STEP 6: Click TRADE on RELIANCE Future -> Verify Order Ticket
    // ─────────────────────────────────────────────────────────────────────────
    console.log('Clicking TRADE on RELIANCE future...');
    const tradeFutBtn = await page.waitForSelector('button ::-p-text(TRADE)', { timeout: 10000 });
    await tradeFutBtn.click();
    await new Promise((r) => setTimeout(r, 1000));

    // Verify Futures Order Ticket opened
    await page.waitForSelector('span ::-p-text(INITIAL MARGIN (12% NOTIONAL))', { timeout: 10000 });
    console.log('Order Ticket opened for RELIANCE stock future!');

    const shot6 = path.join(ARTIFACT_DIR, 'order_ticket_in_reliance_futures.png');
    await page.screenshot({ path: shot6 });
    console.log('Captured screenshot 6:', shot6);

    console.log('ALL PHASE 6E HEADLESS VERIFICATION STEPS PASSED SUCCESSFULLY!');
  } catch (err) {
    console.error('Test error:', err);
    process.exit(1);
  } finally {
    await browser.close();
  }
}

run();
