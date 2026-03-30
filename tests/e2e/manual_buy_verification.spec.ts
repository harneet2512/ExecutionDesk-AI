/**
 * Quick manual verification: Buy trade execution
 */
import { test, expect, type Page } from '@playwright/test';

test.use({ baseURL: 'http://localhost:3001' });

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

async function clickConfirm(page: Page) {
  const confirmBtn = page.locator('button:has-text("Confirm Trade"), button:has-text("Confirm")').first();
  await confirmBtn.waitFor({ state: 'visible', timeout: 30_000 });
  await confirmBtn.click();
}

test('Buy $2 of BTC and observe result', async ({ page }) => {
  console.log('\n=== MANUAL VERIFICATION: BUY TRADE ===');
  
  // Step 1: Navigate and start new chat
  console.log('\nStep 1: Navigating to /chat');
  await page.goto('/chat');
  await page.waitForLoadState('networkidle');
  
  const newChatBtn = page.locator('button:has-text("New Chat")').first();
  if (await newChatBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
    console.log('Clicking New Chat');
    await newChatBtn.click();
    await page.waitForTimeout(1000);
  }
  
  await page.screenshot({ path: 'test-results/manual-01-start.png', fullPage: true });
  
  // Step 2: Send "Buy $2 of BTC"
  console.log('\nStep 2: Sending "Buy $2 of BTC"');
  await sendChatCommand(page, 'Buy $2 of BTC');
  
  // Wait for confirmation card
  console.log('Waiting for confirmation card...');
  await page.locator('button:has-text("Confirm Trade"), button:has-text("Confirm")').first()
    .waitFor({ state: 'visible', timeout: 60_000 });
  
  await page.screenshot({ path: 'test-results/manual-02-confirmation.png', fullPage: true });
  console.log('✓ Confirmation card appeared');
  
  // Step 3: Click Confirm Trade
  console.log('\nStep 3: Clicking "Confirm Trade"');
  await clickConfirm(page);
  console.log('✓ Clicked Confirm Trade button');
  
  // Step 4-5: Wait for result (15 seconds)
  console.log('\nStep 4-5: Waiting 15 seconds for trade execution result...');
  await page.waitForTimeout(15_000);
  
  await page.screenshot({ path: 'test-results/manual-03-result.png', fullPage: true });
  
  // Check for success or failure
  console.log('\n=== RESULT ANALYSIS ===');
  
  const pageText = await page.locator('body').textContent() || '';
  
  // Check for success indicators
  const hasSuccess = pageText.includes('executed successfully') || 
                     pageText.includes('COMPLETED') ||
                     pageText.includes('Success');
  
  // Check for failure indicators
  const hasFailed = pageText.includes('FAILED') || 
                    pageText.includes('failed') ||
                    pageText.includes('Trade execution failed');
  
  // Look for error messages
  const errorMessages: string[] = [];
  
  const errorLocators = [
    page.locator('text=/execution failed/i'),
    page.locator('text=/trade failed/i'),
    page.locator('text=/error/i'),
    page.locator('[class*="error"]'),
    page.locator('[class*="failed"]')
  ];
  
  for (const locator of errorLocators) {
    const count = await locator.count();
    for (let i = 0; i < count; i++) {
      const text = await locator.nth(i).textContent();
      if (text && text.length < 200) {
        errorMessages.push(text.trim());
      }
    }
  }
  
  // Look for status cards
  const statusCards = page.locator('[class*="border"][class*="rounded"]').filter({
    hasText: /BUY|SELL|BTC/
  });
  const cardCount = await statusCards.count();
  
  console.log(`\nTrade Status Cards Found: ${cardCount}`);
  
  for (let i = 0; i < cardCount; i++) {
    const cardText = await statusCards.nth(i).textContent();
    console.log(`\nCard ${i + 1}:`);
    console.log(cardText?.substring(0, 300));
  }
  
  // Final status
  console.log('\n=== FINAL STATUS ===');
  
  if (hasSuccess) {
    console.log('✅ TRADE SUCCESSFUL');
  } else if (hasFailed) {
    console.log('❌ TRADE FAILED');
    
    if (errorMessages.length > 0) {
      console.log('\nError Messages:');
      const uniqueErrors = [...new Set(errorMessages)];
      uniqueErrors.slice(0, 5).forEach((msg, idx) => {
        console.log(`  ${idx + 1}. ${msg}`);
      });
    }
  } else {
    console.log('⏳ TRADE PENDING or STATUS UNCLEAR');
  }
  
  // Look for specific error details
  const failedCard = page.locator('text=/Trade Failed/i').first();
  if (await failedCard.isVisible({ timeout: 2000 }).catch(() => false)) {
    console.log('\n📋 Failed Trade Card Details:');
    
    const sideLocator = page.locator('text=/Side/i').first();
    const symbolLocator = page.locator('text=/Symbol/i').first();
    const notionalLocator = page.locator('text=/Notional/i').first();
    const statusLocator = page.locator('text=/Status.*FAILED/i').first();
    
    if (await sideLocator.isVisible({ timeout: 1000 }).catch(() => false)) {
      const sideText = await sideLocator.textContent();
      console.log(`  Side: ${sideText}`);
    }
    
    if (await symbolLocator.isVisible({ timeout: 1000 }).catch(() => false)) {
      const symbolText = await symbolLocator.textContent();
      console.log(`  Symbol: ${symbolText}`);
    }
    
    if (await notionalLocator.isVisible({ timeout: 1000 }).catch(() => false)) {
      const notionalText = await notionalLocator.textContent();
      console.log(`  Notional: ${notionalText}`);
    }
    
    if (await statusLocator.isVisible({ timeout: 1000 }).catch(() => false)) {
      const statusText = await statusLocator.textContent();
      console.log(`  Status: ${statusText}`);
    }
  }
  
  console.log('\n=== VERIFICATION COMPLETE ===');
});
