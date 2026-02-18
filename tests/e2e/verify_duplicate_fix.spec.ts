/**
 * Re-verification test for duplicate portfolio messages fix.
 * 
 * This test specifically checks if the duplicate message bug has been fixed.
 */
import { test, expect, type Page } from '@playwright/test';

// Override base URL for this test
test.use({ baseURL: 'http://localhost:3001' });

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

/** Count assistant message bubbles */
async function countAssistantMessages(page: Page): Promise<number> {
  // Wait a bit for messages to fully render
  await page.waitForTimeout(2000);
  
  // Assistant messages are typically on the left side with specific styling
  // Try multiple selectors to catch all possible message formats
  const messages = page.locator('.justify-start').filter({ 
    has: page.locator('[class*="rounded"]') 
  });
  
  const count = await messages.count();
  console.log(`Found ${count} assistant message containers`);
  
  // Also log the actual messages for debugging
  for (let i = 0; i < count; i++) {
    const text = await messages.nth(i).textContent();
    console.log(`Message ${i + 1}: ${text?.substring(0, 100)}...`);
  }
  
  return count;
}

test.describe('Duplicate Portfolio Message Fix Verification', () => {
  test('Portfolio analysis should create only ONE assistant message', async ({ page }) => {
    console.log('\n=== VERIFYING DUPLICATE MESSAGE FIX ===');
    
    // Step 1: Navigate and start fresh
    console.log('Step 1: Navigating to /chat');
    await page.goto('/chat');
    
    // Click "New Chat" to ensure clean slate
    const newChatBtn = page.locator('button:has-text("New Chat"), a:has-text("New Chat")').first();
    if (await newChatBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      console.log('Clicking New Chat button to start fresh');
      await newChatBtn.click();
      await page.waitForTimeout(1000);
    }
    
    await page.waitForLoadState('networkidle');
    
    // Step 2: Ensure News is ON
    console.log('Step 2: Ensuring News is ON');
    await page.evaluate(() => localStorage.setItem('newsEnabled', 'true'));
    
    const newsToggle = page.locator('button[aria-pressed]').first();
    if (await newsToggle.isVisible({ timeout: 3_000 }).catch(() => false)) {
      const isPressed = await newsToggle.getAttribute('aria-pressed');
      console.log(`News toggle state: ${isPressed}`);
      if (isPressed === 'false') {
        console.log('Toggling News ON');
        await newsToggle.click();
        await page.waitForTimeout(1000);
      }
    }
    
    // Take screenshot of initial state
    await page.screenshot({ path: 'test-results/recheck-01-initial.png', fullPage: true });
    
    // Count messages before command
    const messagesBefore = await countAssistantMessages(page);
    console.log(`Assistant messages before command: ${messagesBefore}`);
    
    // Step 3: Send "Analyze my portfolio"
    console.log('Step 3: Sending "Analyze my portfolio"');
    await sendChatCommand(page, 'Analyze my portfolio');
    
    // Wait for response to appear
    console.log('Waiting for portfolio response...');
    await page.locator('.justify-start').first().waitFor({ state: 'visible', timeout: 60_000 });
    
    // Wait a bit longer to ensure all messages have rendered
    await page.waitForTimeout(8000);
    
    // Take screenshot of response
    await page.screenshot({ path: 'test-results/recheck-02-portfolio-response.png', fullPage: true });
    
    // Step 4: Count assistant messages after command
    const messagesAfter = await countAssistantMessages(page);
    console.log(`Assistant messages after command: ${messagesAfter}`);
    
    const newMessages = messagesAfter - messagesBefore;
    console.log(`New messages created: ${newMessages}`);
    
    // Check for PortfolioCard structure
    console.log('Checking for PortfolioCard structure...');
    const portfolioHeader = page.locator('text=/Portfolio Snapshot|Portfolio Analysis/i');
    const hasPortfolioHeader = await portfolioHeader.isVisible({ timeout: 5_000 }).catch(() => false);
    console.log(`Portfolio header visible: ${hasPortfolioHeader}`);
    
    const tableHeaders = page.locator('th, [class*="font-bold"]:has-text("Asset"), [class*="font-bold"]:has-text("QTY")');
    const headerCount = await tableHeaders.count();
    console.log(`Table headers found: ${headerCount}`);
    
    // Get all visible text for inspection
    const pageText = await page.locator('body').textContent();
    const portfolioOccurrences = (pageText?.match(/Portfolio Snapshot/gi) || []).length;
    console.log(`"Portfolio Snapshot" appears ${portfolioOccurrences} times in page`);
    
    // ASSERTIONS
    console.log('\n=== VERIFICATION RESULTS ===');
    
    if (newMessages === 1) {
      console.log('✅ SUCCESS: Only ONE new assistant message created');
    } else {
      console.log(`❌ FAILURE: ${newMessages} new messages created (expected 1)`);
    }
    
    if (hasPortfolioHeader && headerCount > 0) {
      console.log('✅ PortfolioCard displays properly with table format');
    } else {
      console.log('❌ PortfolioCard structure issue detected');
    }
    
    // Main assertion
    expect(newMessages).toBe(1);
    expect(hasPortfolioHeader).toBeTruthy();
    expect(headerCount).toBeGreaterThan(0);
    
    console.log('\n=== TEST COMPLETE ===');
  });
});
