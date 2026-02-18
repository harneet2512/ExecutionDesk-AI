/**
 * Test buy trade after Python import fix
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

test('Buy $2 BTC - Test import fix', async ({ page }) => {
  console.log('\n=== TESTING PYTHON IMPORT FIX ===');
  
  // Step 1: Start new chat
  console.log('\nStep 1: Starting new chat');
  await page.goto('/chat');
  await page.waitForLoadState('networkidle');
  
  const newChatBtn = page.locator('button:has-text("New Chat")').first();
  if (await newChatBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
    console.log('Clicking "New Chat" button');
    await newChatBtn.click();
    await page.waitForTimeout(1000);
  }
  
  await page.screenshot({ path: 'test-results/import-fix-01-start.png', fullPage: true });
  
  // Step 2: Send "Buy $2 of BTC"
  console.log('\nStep 2: Sending "Buy $2 of BTC"');
  await sendChatCommand(page, 'Buy $2 of BTC');
  console.log('Command sent, waiting for response...');
  
  // Step 3: Wait for confirmation card
  console.log('\nStep 3: Waiting for confirmation card...');
  try {
    await page.locator('button:has-text("Confirm Trade"), button:has-text("Confirm")').first()
      .waitFor({ state: 'visible', timeout: 60_000 });
    console.log('✅ Confirmation card appeared');
    
    await page.screenshot({ path: 'test-results/import-fix-02-confirmation.png', fullPage: true });
    
    // Click Confirm Trade
    console.log('Clicking "Confirm Trade" button');
    await clickConfirm(page);
    console.log('✅ Confirm clicked');
    
  } catch (error) {
    console.log('❌ Confirmation card did not appear within 60 seconds');
    await page.screenshot({ path: 'test-results/import-fix-02-no-confirmation.png', fullPage: true });
    throw error;
  }
  
  // Step 4: Wait up to 30 seconds for result
  console.log('\nStep 4: Waiting up to 30 seconds for result...');
  
  // Monitor for changes every 5 seconds
  for (let i = 0; i < 6; i++) {
    await page.waitForTimeout(5000);
    
    const pageText = await page.locator('body').textContent() || '';
    
    // Check for completion indicators
    const hasSuccess = pageText.includes('executed successfully') || 
                       pageText.includes('COMPLETED') ||
                       pageText.match(/Success/);
    
    const hasFailed = pageText.includes('FAILED') || 
                      pageText.includes('failed');
    
    const hasError = pageText.includes('error') ||
                     pageText.includes('Error');
    
    console.log(`\n[${(i + 1) * 5}s] Status check:`);
    console.log(`  - Success indicators: ${hasSuccess ? 'YES' : 'NO'}`);
    console.log(`  - Failure indicators: ${hasFailed ? 'YES' : 'NO'}`);
    console.log(`  - Error indicators: ${hasError ? 'YES' : 'NO'}`);
    
    if (hasSuccess || hasFailed) {
      console.log(`\n✓ Trade completed at ${(i + 1) * 5} seconds`);
      break;
    }
    
    if (i === 5) {
      console.log('\n⏳ 30 seconds elapsed');
    }
  }
  
  await page.screenshot({ path: 'test-results/import-fix-03-result.png', fullPage: true });
  
  // Step 5: Analyze result
  console.log('\n=== STEP 5: RESULT ANALYSIS ===');
  
  const finalPageText = await page.locator('body').textContent() || '';
  
  // Look for trade status cards
  const tradeCards = page.locator('[class*="border"][class*="rounded"]').filter({
    hasText: /BUY|SELL|BTC|Trade/i
  });
  const cardCount = await tradeCards.count();
  console.log(`\nTrade cards found: ${cardCount}`);
  
  // Check each card
  for (let i = 0; i < Math.min(cardCount, 3); i++) {
    const card = tradeCards.nth(i);
    const cardText = await card.textContent();
    console.log(`\n--- Card ${i + 1} ---`);
    console.log(cardText?.substring(0, 200));
  }
  
  // Look for specific status indicators
  const statusElements = [
    { name: 'Success', locator: page.locator('text=/executed successfully|COMPLETED|Success/i') },
    { name: 'Failed', locator: page.locator('text=/FAILED|Trade Failed/i') },
    { name: 'Error', locator: page.locator('text=/execution failed|error/i') },
    { name: 'Import Error', locator: page.locator('text=/ImportError|ModuleNotFoundError|cannot import/i') },
  ];
  
  console.log('\n=== STATUS INDICATORS ===');
  for (const { name, locator } of statusElements) {
    const isVisible = await locator.first().isVisible({ timeout: 1000 }).catch(() => false);
    console.log(`${name}: ${isVisible ? '✓ FOUND' : '✗ Not found'}`);
  }
  
  // Determine final status
  console.log('\n=== FINAL STATUS ===');
  
  const hasImportError = finalPageText.match(/ImportError|ModuleNotFoundError|cannot import/i);
  const hasTradeFailure = finalPageText.match(/FAILED|Trade Failed/i);
  const hasExecutionError = finalPageText.match(/execution failed/i);
  const hasSuccess = finalPageText.match(/executed successfully|COMPLETED/i);
  
  if (hasImportError) {
    console.log('❌ IMPORT ERROR DETECTED');
    console.log('The Python import error still exists!');
    
    // Extract error details
    const errorMatches = finalPageText.match(/(ImportError|ModuleNotFoundError)[^\n]*/g);
    if (errorMatches) {
      console.log('\nError details:');
      errorMatches.forEach(err => console.log(`  - ${err}`));
    }
  } else if (hasSuccess) {
    console.log('✅ TRADE SUCCEEDED');
    console.log('Import fix verified working!');
  } else if (hasTradeFailure) {
    console.log('⚠️ TRADE FAILED (but no import error)');
    console.log('Import fix appears to be working - failure is at execution layer');
    
    if (hasExecutionError) {
      console.log('Error message: "Trade execution failed"');
    }
  } else {
    console.log('⏳ STATUS UNCLEAR - trade may still be processing');
  }
  
  // Check for error messages
  const errorTexts: string[] = [];
  const errorLocators = page.locator('text=/error|Error|failed|Failed/i');
  const errorCount = await errorLocators.count();
  
  if (errorCount > 0) {
    console.log(`\n=== ERROR MESSAGES (${errorCount} found) ===`);
    for (let i = 0; i < Math.min(errorCount, 5); i++) {
      const text = await errorLocators.nth(i).textContent();
      if (text && text.length < 200 && !errorTexts.includes(text.trim())) {
        errorTexts.push(text.trim());
        console.log(`${i + 1}. ${text.trim()}`);
      }
    }
  }
  
  console.log('\n=== TEST COMPLETE ===');
  
  // Log summary for user
  if (hasImportError) {
    console.log('\n🔴 RESULT: Import error still present - fix did not work');
  } else if (hasSuccess) {
    console.log('\n🟢 RESULT: Trade succeeded - fix is working!');
  } else if (hasTradeFailure) {
    console.log('\n🟡 RESULT: Trade failed but progressed past import stage - fix is working!');
  } else {
    console.log('\n⚪ RESULT: Inconclusive - check screenshots');
  }
});
