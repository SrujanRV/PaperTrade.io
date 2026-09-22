const puppeteer = require('puppeteer-core');
const path = require('path');

const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const artifactDir = 'C:\\Users\\sruja\\.gemini\\antigravity\\brain\\5182a1a7-7298-4a93-b2df-7e0a8d19ae8d';

async function run() {
  console.log('Launching browser...');
  const browser = await puppeteer.launch({
    executablePath: edgePath,
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 1100 });

    await page.goto('http://localhost:5173', { waitUntil: 'networkidle2' });
    await new Promise((r) => setTimeout(r, 2000));

    // Handle initial setup modal if present
    const setupModalClose = await page.$('button[title="Close dialog"]');
    if (setupModalClose) {
      await setupModalClose.click();
      await new Promise((r) => setTimeout(r, 500));
    }

    console.log('Switching to US Market watchlist...');
    const buttons = await page.$$('button');
    for (const b of buttons) {
      const text = await page.evaluate((el) => el.textContent, b);
      if (text.includes('US Market')) {
        await b.click();
        break;
      }
    }
    await new Promise((r) => setTimeout(r, 1000));

    // Open AAPL order ticket by clicking the first row in watchlist
    console.log('Clicking AAPL row to open Order Ticket...');
    const firstRow = await page.$('tbody tr');
    if (firstRow) {
      await firstRow.click();
    }
    await new Promise((r) => setTimeout(r, 1500));

    // Select LIMIT order type
    console.log('Selecting LIMIT order type...');
    const allBtns = await page.$$('button');
    for (const b of allBtns) {
      const text = await page.evaluate((el) => el.textContent, b);
      if (text.trim() === 'LIMIT') {
        await b.click();
        break;
      }
    }
    await new Promise((r) => setTimeout(r, 800));

    // Enter limit price 100.00
    console.log('Entering Limit Price: 100.00...');
    await page.waitForSelector('input[step="any"]', { timeout: 5000 });
    await page.$eval('input[step="any"]', (el) => {
      el.focus();
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        'value'
      ).set;
      nativeInputValueSetter.call(el, '100.00');
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await new Promise((r) => setTimeout(r, 800));

    page.on('console', (msg) => console.log('PAGE LOG:', msg.text()));
    page.on('pageerror', (err) => console.log('PAGE ERROR:', err.message));

    const pageCheck = await page.evaluate(() => {
      const form = document.querySelector('form');
      if (!form) return { hasForm: false };
      return {
        hasForm: true,
        valid: form.checkValidity(),
        inputs: Array.from(form.querySelectorAll('input')).map((i) => ({
          name: i.name || i.placeholder,
          value: i.value,
          valid: i.checkValidity(),
          msg: i.validationMessage,
        })),
      };
    });
    console.log('Form validity before click:', JSON.stringify(pageCheck));

    // Submit Limit Buy Order
    console.log('Submitting Limit Buy Order...');
    await page.evaluate(() => {
      const forms = document.querySelectorAll('form');
      const ticketForm = forms[forms.length - 1];
      if (ticketForm) {
        ticketForm.requestSubmit();
      }
    });
    await new Promise((r) => setTimeout(r, 2500));

    // Screenshot 1: Order Ticket showing Pending Order Created
    const ticketShotPath = path.join(artifactDir, 'order_ticket_limit_pending.png');
    await page.screenshot({ path: ticketShotPath });
    console.log('Saved:', ticketShotPath);

    // Navigate to Order History tab
    console.log('Navigating to Order History...');
    for (const b of await page.$$('button')) {
      const text = await page.evaluate((el) => el.textContent, b);
      if (text.includes('Order History')) {
        await b.click();
        break;
      }
    }
    await new Promise((r) => setTimeout(r, 1500));

    // Select US Market in Order History
    for (const b of await page.$$('button')) {
      const text = await page.evaluate((el) => el.textContent, b);
      if (text.includes('US Market (USD)')) {
        await b.click();
        break;
      }
    }
    await new Promise((r) => setTimeout(r, 1500));

    // Click PENDING filter sub-tab
    for (const b of await page.$$('button')) {
      const text = await page.evaluate((el) => el.textContent, b);
      if (text.includes('PENDING (')) {
        await b.click();
        break;
      }
    }
    await new Promise((r) => setTimeout(r, 1000));

    // Screenshot 2: Order History Pending tab
    const histShotPath = path.join(artifactDir, 'order_history_pending.png');
    await page.screenshot({ path: histShotPath });
    console.log('Saved:', histShotPath);

    // Cancel the pending order
    console.log('Clicking CANCEL button on pending order...');
    await page.evaluate(() => {
      const cancelBtn = Array.from(document.querySelectorAll('button')).find(
        (b) => b.textContent.trim() === 'CANCEL'
      );
      if (cancelBtn) cancelBtn.click();
    });
    await new Promise((r) => setTimeout(r, 2000));

    // Click ALL or REJECTED / CANCELLED filter
    for (const b of await page.$$('button')) {
      const text = await page.evaluate((el) => el.textContent, b);
      if (text.includes('REJECTED / CANCELLED')) {
        await b.click();
        break;
      }
    }
    await new Promise((r) => setTimeout(r, 1000));

    // Screenshot 3: Order History with Cancelled Order
    const cancelledShotPath = path.join(artifactDir, 'order_history_cancelled.png');
    await page.screenshot({ path: cancelledShotPath });
    console.log('Saved:', cancelledShotPath);

    // Click PLACE ANOTHER ORDER to return to ticket form
    console.log('Clicking PLACE ANOTHER ORDER to reset form...');
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('button')).find(
        (b) => b.textContent.trim() === 'PLACE ANOTHER ORDER'
      );
      if (btn) btn.click();
    });
    await new Promise((r) => setTimeout(r, 1000));

    // Select STOP-LOSS
    console.log('Selecting STOP-LOSS...');
    for (const b of await page.$$('button')) {
      const text = await page.evaluate((el) => el.textContent, b);
      if (text.trim() === 'STOP-LOSS') {
        await b.click();
        break;
      }
    }
    await new Promise((r) => setTimeout(r, 1200));

    // Screenshot 4: Stop Loss Order Ticket
    const stopLossShotPath = path.join(artifactDir, 'order_ticket_stop_loss.png');
    await page.screenshot({ path: stopLossShotPath });
    console.log('Saved:', stopLossShotPath);

    console.log('\nAll browser verification steps completed successfully!');
  } finally {
    await browser.close();
  }
}

run().catch((err) => {
  console.error('Verification failed:', err);
  process.exit(1);
});
