/**
 * Quick test: Sell $2 of BTC
 */
import { test } from '@playwright/test';

test.use({ baseURL: 'http://localhost:3001' });

test('Sell $2 BTC - Quick test', async ({ page }) => {
  console.log('=== QUICK SELL TEST ===\n');
  
  // 1. New chat
  await page.goto('/chat');
  const newChatBtn = page.locator('button:has-text("New Chat")').first();
  if (await newChatBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
    await newChatBtn.click();
    await page.waitForTimeout(1000);
  }
  console.log('✓ New chat started');
  
  // 2. Send "Sell $2 of BTC"
  const input = page.locator('input[type="text"], textarea').first();
  await input.fill('Sell $2 of BTC');
  await input.press('Enter');
  console.log('✓ Sent: "Sell $2 of BTC"');
  
  // 3. Click Confirm
  const confirmBtn = page.locator('button:has-text("Confirm Trade"), button:has-text("Confirm")').first();
  await confirmBtn.waitFor({ state: 'visible', timeout: 60_000 });
  console.log('✓ Confirmation appeared');
  await confirmBtn.click();
  console.log('✓ Clicked Confirm Trade');
  
  // 4. Wait for result (check every 5s)
  console.log('\nWaiting for result...');
  for (let i = 0; i < 6; i++) {
    await page.waitForTimeout(5000);
    const text = await page.locator('body').textContent() || '';
    
    if (text.includes('COMPLETED') || text.includes('executed successfully')) {
      console.log(`\n✅ SUCCESS at ${(i+1)*5}s`);
      await page.screenshot({ path: 'test-results/sell-success.png', fullPage: true });
      
      const successCard = page.locator('text=/executed successfully|COMPLETED/i').first();
      if (await successCard.isVisible({ timeout: 2000 }).catch(() => false)) {
        const context = await successCard.locator('..').textContent();
        console.log(`Details: ${context?.substring(0, 150)}`);
      }
      return;
    }
    
    if (text.includes('FAILED') || text.includes('Trade execution failed')) {
      console.log(`\n❌ FAILED at ${(i+1)*5}s`);
      await page.screenshot({ path: 'test-results/sell-failed.png', fullPage: true });
      
      // Get error details
      const errorCard = page.locator('text=/FAILED|failed/i').first();
      if (await errorCard.isVisible({ timeout: 2000 }).catch(() => false)) {
        const errorText = await errorCard.locator('..').textContent();
        console.log(`Error: ${errorText?.substring(0, 200)}`);
      }
      
      // Check for specific error messages
      const errors = await page.locator('text=/execution failed|error/i').allTextContents();
      if (errors.length > 0) {
        console.log('Error messages:', errors.slice(0, 3));
      }
      return;
    }
    
    console.log(`[${(i+1)*5}s] Still processing...`);
  }
  
  console.log('\n⏳ 30s elapsed - taking final screenshot');
  await page.screenshot({ path: 'test-results/sell-timeout.png', fullPage: true });
  
  const finalText = await page.locator('body').textContent() || '';
  if (finalText.includes('LIVE ORDER CONFIRMATION')) {
    console.log('⚠️ Still showing confirmation - may need manual CONFIRM input');
  } else {
    console.log('⏳ Status unclear after 30s');
  }
});
