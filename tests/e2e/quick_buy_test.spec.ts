/**
 * Quick buy trade test
 */
import { test } from '@playwright/test';

test.use({ baseURL: 'http://localhost:3001' });

test('Quick buy test', async ({ page }) => {
  console.log('=== QUICK BUY TRADE TEST ===\n');
  
  // Navigate and start new chat
  console.log('1. Going to /chat...');
  await page.goto('/chat');
  await page.waitForLoadState('networkidle');
  
  const newChatBtn = page.locator('button:has-text("New Chat")').first();
  if (await newChatBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
    console.log('2. Clicking "New Chat"...');
    await newChatBtn.click();
    await page.waitForTimeout(1000);
  }
  
  // Send command
  console.log('3. Sending "Buy $2 of BTC"...');
  const input = page.locator('input[type="text"], textarea').first();
  await input.fill('Buy $2 of BTC');
  
  const sendBtn = page.locator('button[type="submit"], button:has-text("Send")').first();
  if (await sendBtn.isVisible()) {
    await sendBtn.click();
  } else {
    await input.press('Enter');
  }
  
  // Wait for confirmation
  console.log('4. Waiting for confirmation card...');
  await page.locator('button:has-text("Confirm Trade"), button:has-text("Confirm")').first()
    .waitFor({ state: 'visible', timeout: 60_000 });
  console.log('   ✓ Confirmation appeared');
  
  await page.screenshot({ path: 'test-results/quick-01-confirm.png', fullPage: true });
  
  // Click Confirm
  console.log('5. Clicking "Confirm Trade"...');
  const confirmBtn = page.locator('button:has-text("Confirm Trade"), button:has-text("Confirm")').first();
  await confirmBtn.click();
  console.log('   ✓ Clicked');
  
  // Wait 20 seconds
  console.log('6. Waiting 20 seconds for result...');
  await page.waitForTimeout(20_000);
  
  await page.screenshot({ path: 'test-results/quick-02-result.png', fullPage: true });
  
  // Check result
  console.log('\n=== RESULT ===');
  const pageText = await page.locator('body').textContent() || '';
  
  const succeeded = pageText.match(/executed successfully|COMPLETED|Success/i);
  const failed = pageText.match(/FAILED|Trade Failed/i);
  const error = pageText.match(/Trade execution failed|error/i);
  
  if (succeeded) {
    console.log('✅ TRADE SUCCEEDED');
  } else if (failed) {
    console.log('❌ TRADE FAILED');
    
    if (error) {
      // Extract error message
      const errorCard = page.locator('text=/Trade execution failed|execution failed/i').first();
      if (await errorCard.isVisible({ timeout: 1000 }).catch(() => false)) {
        const errorText = await errorCard.textContent();
        console.log(`   Error: ${errorText}`);
      }
      
      // Check for detailed status
      const statusCard = page.locator('text=/Trade Failed/i').first();
      if (await statusCard.isVisible({ timeout: 1000 }).catch(() => false)) {
        console.log('\n   Trade Details:');
        
        const details = await page.locator('body').textContent();
        const sideMatch = details?.match(/Side[\s:]+(\w+)/i);
        const symbolMatch = details?.match(/Symbol[\s:]+(\w+)/i);
        const notionalMatch = details?.match(/Notional[\s:]+\$?([\d.]+)/i);
        const statusMatch = details?.match(/Status[\s:]+(\w+)/i);
        
        if (sideMatch) console.log(`   - Side: ${sideMatch[1]}`);
        if (symbolMatch) console.log(`   - Symbol: ${symbolMatch[1]}`);
        if (notionalMatch) console.log(`   - Notional: $${notionalMatch[1]}`);
        if (statusMatch) console.log(`   - Status: ${statusMatch[1]}`);
      }
    }
  } else {
    console.log('⏳ STATUS UNCLEAR');
  }
  
  console.log('\n=== TEST COMPLETE ===');
});
