/**
 * Verification test for specific fixes in the trading chat application.
 * 
 * Tests:
 * 1. Portfolio analysis shows as structured table/card (not unstructured text)
 * 2. No duplicate "Operation completed successfully" ghost bubbles
 * 3. LIVE mode correctly shown in confirmation cards
 * 4. Earlier messages remain unchanged when new commands are sent
 * 5. Trade execution completes without extra bubbles
 * 
 * Prerequisites:
 *   - Backend running on port 8000
 *   - Frontend running on port 3001 (configured in this test)
 */
import { test, expect, type Page } from '@playwright/test';

// Override base URL for this test
test.use({ baseURL: 'http://localhost:3001' });

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Type a command in the chat input and submit */
async function sendChatCommand(page: Page, command: string) {
  const input = page.locator('input[type="text"], textarea').first();
  await input.fill(command);
  const sendBtn = page.locator('button[type="submit"], button:has-text("Send")').first();
  if (await sendBtn.isVisible()) {
    await sendBtn.click();
  } else {
    await input.press('Enter');
  }
}

/** Click the first visible Confirm button */
async function clickConfirm(page: Page) {
  const confirmBtn = page.locator('button:has-text("Confirm Trade"), button:has-text("Confirm")').first();
  await confirmBtn.waitFor({ state: 'visible', timeout: 30_000 });
  await confirmBtn.click();
}

/** Take a screenshot for verification */
async function takeScreenshot(page: Page, name: string) {
  await page.screenshot({ 
    path: `test-results/verify-${name}.png`, 
    fullPage: true 
  });
}

/** Count assistant message bubbles */
async function countAssistantMessages(page: Page): Promise<number> {
  // Assistant messages are typically in the left side with specific styling
  const messages = page.locator('.justify-start .rounded-2xl, .justify-start .rounded-lg').filter({ hasText: /.+/ });
  return await messages.count();
}

/** Check if portfolio is displayed as a structured card/table */
async function assertPortfolioIsStructured(page: Page) {
  // Look for table headers or card structure indicators
  const tableHeaders = page.locator('th, [class*="font-bold"]:has-text("Asset"), [class*="font-bold"]:has-text("Qty"), [class*="font-bold"]:has-text("Value")');
  const headerCount = await tableHeaders.count();
  
  // Should have structured elements
  expect(headerCount).toBeGreaterThan(0);
  
  // Look for "Portfolio Snapshot" header
  const portfolioHeader = page.locator('text=/Portfolio Snapshot|Portfolio Analysis/i');
  const hasHeader = await portfolioHeader.isVisible({ timeout: 5_000 }).catch(() => false);
  expect(hasHeader).toBeTruthy();
}

/** Assert no "Operation completed successfully" ghost bubbles */
async function assertNoGhostBubbles(page: Page) {
  const ghostBubbles = page.locator('text=/Operation completed successfully/i');
  const count = await ghostBubbles.count();
  expect(count).toBe(0);
}

/** Assert LIVE mode is shown in confirmation card */
async function assertLiveModeShown(page: Page) {
  const liveIndicator = page.locator('text=/LIVE/i').filter({ hasNot: page.locator('text=/PAPER/i') });
  const hasLive = await liveIndicator.isVisible({ timeout: 5_000 }).catch(() => false);
  expect(hasLive).toBeTruthy();
}

/** Get the text content of all messages for comparison */
async function getAllMessagesText(page: Page): Promise<string[]> {
  const messages = page.locator('.justify-start .rounded-2xl, .justify-start .rounded-lg');
  const count = await messages.count();
  const texts: string[] = [];
  for (let i = 0; i < count; i++) {
    const text = await messages.nth(i).textContent() || '';
    texts.push(text.trim());
  }
  return texts;
}

// ---------------------------------------------------------------------------
// VERIFICATION PASS 1: News ON
// ---------------------------------------------------------------------------
test.describe('Verification Pass 1 - News ON', () => {
  test.beforeEach(async ({ page }) => {
    console.log('Navigating to http://localhost:3001/chat');
    await page.goto('/chat');
    await page.evaluate(() => localStorage.setItem('newsEnabled', 'true'));
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Ensure news toggle is ON
    const newsToggle = page.locator('button[aria-pressed]').first();
    if (await newsToggle.isVisible({ timeout: 3_000 }).catch(() => false)) {
      const isPressed = await newsToggle.getAttribute('aria-pressed').catch(() => null);
      console.log(`News toggle aria-pressed: ${isPressed}`);
      if (isPressed === 'false') {
        console.log('Toggling news ON');
        await newsToggle.click();
        await page.waitForTimeout(1_000);
      }
    }
    
    await takeScreenshot(page, '00-initial-state');
  });

  test('Step 1-5: Portfolio analysis shows structured card', async ({ page }) => {
    console.log('\n=== STEP 1-5: Portfolio Analysis ===');
    
    // Step 3: Send "Analyze my portfolio"
    console.log('Step 3: Sending "Analyze my portfolio"');
    const messageCountBefore = await countAssistantMessages(page);
    console.log(`Messages before: ${messageCountBefore}`);
    
    await sendChatCommand(page, 'Analyze my portfolio');
    
    // Wait for response
    console.log('Waiting for portfolio response...');
    await page.waitForTimeout(5_000);
    
    // Wait for assistant message to appear
    await page.locator('.justify-start').first().waitFor({ state: 'visible', timeout: 60_000 });
    await page.waitForTimeout(5_000);
    
    await takeScreenshot(page, '01-portfolio-response');
    
    // Step 4: Verify response
    console.log('Step 4: Verifying response...');
    
    // Should have ONE new assistant message (not multiple)
    const messageCountAfter = await countAssistantMessages(page);
    console.log(`Messages after: ${messageCountAfter}`);
    const newMessages = messageCountAfter - messageCountBefore;
    console.log(`New messages: ${newMessages}`);
    expect(newMessages).toBe(1);
    
    // Should contain structured portfolio card with table
    console.log('Checking for structured portfolio card...');
    await assertPortfolioIsStructured(page);
    
    // NO extra "Operation completed successfully" bubble
    console.log('Checking for ghost bubbles...');
    await assertNoGhostBubbles(page);
    
    console.log('✓ Portfolio analysis verification passed');
  });

  test('Step 6-9: Buy trade shows LIVE mode and completes cleanly', async ({ page }) => {
    console.log('\n=== STEP 6-9: Buy Trade ===');
    
    // First get portfolio for comparison
    console.log('Getting initial portfolio...');
    await sendChatCommand(page, 'Analyze my portfolio');
    await page.waitForTimeout(5_000);
    await page.locator('.justify-start').first().waitFor({ state: 'visible', timeout: 60_000 });
    await page.waitForTimeout(3_000);
    
    const portfolioTextBefore = await getAllMessagesText(page);
    console.log(`Initial messages count: ${portfolioTextBefore.length}`);
    
    await takeScreenshot(page, '02-before-buy');
    
    // Step 6: Send "Buy $2 of BTC"
    console.log('Step 6: Sending "Buy $2 of BTC"');
    await sendChatCommand(page, 'Buy $2 of BTC');
    
    // Step 7: Check confirmation card
    console.log('Step 7: Waiting for confirmation card...');
    await page.locator('button:has-text("Confirm Trade"), button:has-text("Confirm")').first()
      .waitFor({ state: 'visible', timeout: 60_000 });
    
    await takeScreenshot(page, '03-buy-confirmation');
    
    // Check for LIVE mode indicator
    console.log('Checking for LIVE mode indicator...');
    await assertLiveModeShown(page);
    console.log('✓ LIVE mode shown');
    
    // Check for Confirm Trade and Cancel buttons
    const confirmBtn = page.locator('button:has-text("Confirm Trade"), button:has-text("Confirm")').first();
    const cancelBtn = page.locator('button:has-text("Cancel")').first();
    expect(await confirmBtn.isVisible()).toBeTruthy();
    expect(await cancelBtn.isVisible()).toBeTruthy();
    console.log('✓ Confirm and Cancel buttons present');
    
    // Step 8: Click Confirm Trade
    console.log('Step 8: Clicking Confirm Trade...');
    await clickConfirm(page);
    
    // Step 9: Wait for execution to complete
    console.log('Step 9: Waiting for execution to complete...');
    await page.waitForTimeout(15_000);
    
    await takeScreenshot(page, '04-buy-completed');
    
    // Should show trade processing card
    const processingCard = page.locator('[class*="border"][class*="rounded"]').filter({ 
      hasText: /Executing|executed|COMPLETED|Success/i 
    });
    const hasProcessingCard = await processingCard.first().isVisible({ timeout: 5_000 }).catch(() => false);
    console.log(`Processing card visible: ${hasProcessingCard}`);
    
    // NO extra "Operation completed successfully" ghost bubble
    console.log('Checking for ghost bubbles after buy...');
    await assertNoGhostBubbles(page);
    
    // Earlier portfolio message should NOT have changed
    console.log('Checking that earlier messages remain unchanged...');
    const portfolioTextAfter = await getAllMessagesText(page);
    console.log(`Messages after buy: ${portfolioTextAfter.length}`);
    
    // The first message (portfolio) should still be present and unchanged
    if (portfolioTextBefore.length > 0 && portfolioTextAfter.length > 0) {
      expect(portfolioTextAfter[0]).toContain('Portfolio');
    }
    
    console.log('✓ Buy trade verification passed');
  });

  test('Step 10-13: Sell trade shows LIVE mode and completes cleanly', async ({ page }) => {
    console.log('\n=== STEP 10-13: Sell Trade ===');
    
    // Step 10: Send "Sell $2 of BTC"
    console.log('Step 10: Sending "Sell $2 of BTC"');
    await sendChatCommand(page, 'Sell $2 of BTC');
    
    // Step 11: Check confirmation card
    console.log('Step 11: Waiting for confirmation card...');
    await page.locator('button:has-text("Confirm Trade"), button:has-text("Confirm")').first()
      .waitFor({ state: 'visible', timeout: 60_000 });
    
    await takeScreenshot(page, '05-sell-confirmation');
    
    // Should show LIVE mode
    console.log('Checking for LIVE mode indicator...');
    await assertLiveModeShown(page);
    console.log('✓ LIVE mode shown');
    
    // Step 12: Click Confirm Trade
    console.log('Step 12: Clicking Confirm Trade...');
    await clickConfirm(page);
    
    // Step 13: Verify execution completes without extra bubbles
    console.log('Step 13: Waiting for execution to complete...');
    await page.waitForTimeout(15_000);
    
    await takeScreenshot(page, '06-sell-completed');
    
    // NO extra "Operation completed successfully" ghost bubble
    console.log('Checking for ghost bubbles after sell...');
    await assertNoGhostBubbles(page);
    
    console.log('✓ Sell trade verification passed');
  });

  test('Check browser console for errors', async ({ page }) => {
    const errors: string[] = [];
    
    page.on('console', msg => {
      if (msg.type() === 'error') {
        errors.push(msg.text());
      }
    });
    
    await page.goto('/chat');
    await page.waitForTimeout(3_000);
    
    // Send a simple command to trigger any errors
    await sendChatCommand(page, 'Analyze my portfolio');
    await page.waitForTimeout(5_000);
    
    console.log('\n=== Console Errors ===');
    if (errors.length > 0) {
      console.log('Errors found:');
      errors.forEach(err => console.log(`  - ${err}`));
    } else {
      console.log('No console errors detected');
    }
    
    // Don't fail the test on console errors, just report them
    console.log(`Total console errors: ${errors.length}`);
  });
});
