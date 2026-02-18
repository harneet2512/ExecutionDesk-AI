/**
 * Test buy trade after fix - expecting to see processing steps
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

test('Buy $2 BTC - Monitor processing steps', async ({ page }) => {
  console.log('\n=== TESTING TRADE PROCESSING STEPS ===');
  
  const processStepsObserved: string[] = [];
  const statusChanges: Array<{time: number, status: string}> = [];
  const startTime = Date.now();
  
  // Step 1: Start new chat
  console.log('\nStep 1: Starting new chat');
  await page.goto('/chat');
  await page.waitForLoadState('networkidle');
  
  const newChatBtn = page.locator('button:has-text("New Chat")').first();
  if (await newChatBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
    console.log('✅ Clicking "New Chat" button');
    await newChatBtn.click();
    await page.waitForTimeout(1000);
  }
  
  await page.screenshot({ path: 'test-results/steps-01-start.png', fullPage: true });
  
  // Step 2: Send "Buy $2 of BTC"
  console.log('\nStep 2: Sending "Buy $2 of BTC"');
  await sendChatCommand(page, 'Buy $2 of BTC');
  console.log('✅ Command sent');
  
  // Step 3: Wait for confirmation and click
  console.log('\nStep 3: Waiting for confirmation card...');
  await page.locator('button:has-text("Confirm Trade"), button:has-text("Confirm")').first()
    .waitFor({ state: 'visible', timeout: 60_000 });
  console.log('✅ Confirmation card appeared');
  
  await page.screenshot({ path: 'test-results/steps-02-confirmation.png', fullPage: true });
  
  console.log('Clicking "Confirm Trade"');
  await clickConfirm(page);
  console.log('✅ Confirmed - starting execution monitoring');
  
  // Step 4: Monitor for 45 seconds, checking every 3 seconds
  console.log('\nStep 4: Monitoring trade execution (up to 45 seconds)...');
  console.log('Looking for processing steps like:');
  console.log('  - Fetching market data');
  console.log('  - Executing order');
  console.log('  - Processing');
  console.log('  - Validating');
  console.log('  - Completed/Failed');
  
  let finalStatus = 'UNKNOWN';
  let errorMessage = '';
  
  for (let i = 0; i < 15; i++) {  // 15 checks x 3 seconds = 45 seconds
    await page.waitForTimeout(3000);
    
    const elapsed = Math.round((Date.now() - startTime) / 1000);
    const pageText = await page.locator('body').textContent() || '';
    
    // Look for processing steps
    const stepIndicators = [
      'Fetching market data',
      'fetching',
      'Executing order',
      'executing',
      'Processing',
      'processing',
      'Validating',
      'validating',
      'Analyzing',
      'analyzing',
      'Creating order',
      'Placing order',
      'Confirming',
      'Running',
      'RUNNING',
    ];
    
    // Check for completion
    const isComplete = pageText.match(/COMPLETED|executed successfully|Success/i);
    const isFailed = pageText.match(/FAILED|Trade Failed/i);
    
    // Detect new steps
    for (const step of stepIndicators) {
      if (pageText.toLowerCase().includes(step.toLowerCase()) && !processStepsObserved.includes(step)) {
        processStepsObserved.push(step);
        console.log(`\n[${elapsed}s] 🔄 Processing step detected: "${step}"`);
      }
    }
    
    // Detect status changes
    if (isComplete && finalStatus !== 'COMPLETED') {
      finalStatus = 'COMPLETED';
      statusChanges.push({ time: elapsed, status: 'COMPLETED' });
      console.log(`\n[${elapsed}s] ✅ Status: COMPLETED`);
      break;
    } else if (isFailed && finalStatus !== 'FAILED') {
      finalStatus = 'FAILED';
      statusChanges.push({ time: elapsed, status: 'FAILED' });
      console.log(`\n[${elapsed}s] ❌ Status: FAILED`);
      break;
    }
    
    // Progress indicator
    if ((i + 1) % 3 === 0) {
      console.log(`[${elapsed}s] ⏳ Still monitoring... (${elapsed}/45s)`);
    }
    
    // Take periodic screenshots
    if (i === 2) {
      await page.screenshot({ path: 'test-results/steps-03-mid-execution.png', fullPage: true });
    }
  }
  
  await page.screenshot({ path: 'test-results/steps-04-final.png', fullPage: true });
  
  // Step 5: Analyze results
  console.log('\n=== STEP 5: RESULTS ===');
  
  const finalPageText = await page.locator('body').textContent() || '';
  
  // Look for error messages
  const errorPatterns = [
    /execution failed/i,
    /trade failed/i,
    /error:.+/i,
    /Error:.+/i,
    /failed:.+/i,
  ];
  
  for (const pattern of errorPatterns) {
    const match = finalPageText.match(pattern);
    if (match) {
      errorMessage = match[0];
      break;
    }
  }
  
  // Look for specific error messages in UI
  const errorLocator = page.locator('text=/Trade execution failed|execution failed|error/i');
  const errorCount = await errorLocator.count();
  if (errorCount > 0 && !errorMessage) {
    errorMessage = await errorLocator.first().textContent() || 'Unknown error';
  }
  
  // Count trade status cards
  const tradeCards = page.locator('[class*="border"][class*="rounded"]').filter({
    hasText: /BUY|SELL|BTC|Trade/i
  });
  const cardCount = await tradeCards.count();
  
  console.log('\n📊 FINAL REPORT:');
  console.log('================');
  console.log(`\n1. Trade Status: ${finalStatus}`);
  
  if (finalStatus === 'COMPLETED') {
    console.log('   ✅ TRADE SUCCEEDED');
  } else if (finalStatus === 'FAILED') {
    console.log('   ❌ TRADE FAILED');
  } else {
    console.log('   ⏳ TRADE STATUS UNCLEAR');
  }
  
  console.log(`\n2. Error Message: ${errorMessage || 'None'}`);
  
  console.log(`\n3. Processing Steps Observed: ${processStepsObserved.length}`);
  if (processStepsObserved.length > 0) {
    processStepsObserved.forEach((step, idx) => {
      console.log(`   ${idx + 1}. ${step}`);
    });
  } else {
    console.log('   ⚠️ No explicit processing steps detected');
    console.log('   (Trade may have executed too quickly)');
  }
  
  console.log(`\n4. Status Changes: ${statusChanges.length}`);
  statusChanges.forEach(change => {
    console.log(`   - ${change.status} at ${change.time}s`);
  });
  
  console.log(`\n5. Trade Cards Found: ${cardCount}`);
  
  // Analyze trade cards
  console.log('\n📋 Trade Card Details:');
  for (let i = 0; i < Math.min(cardCount, 3); i++) {
    const card = tradeCards.nth(i);
    const cardText = await card.textContent();
    console.log(`\n--- Card ${i + 1} ---`);
    console.log(cardText?.substring(0, 250).replace(/\s+/g, ' '));
  }
  
  // Check for specific UI elements
  console.log('\n🔍 UI Elements Check:');
  
  const elements = [
    { name: 'Success indicator', locator: page.locator('text=/executed successfully|COMPLETED|Success/i') },
    { name: 'Failed indicator', locator: page.locator('text=/FAILED|Trade Failed/i') },
    { name: 'Retry button', locator: page.locator('button:has-text("Retry Trade")') },
    { name: 'Debug button', locator: page.locator('button:has-text("Copy Debug Info")') },
    { name: 'View details link', locator: page.locator('text=/View Run Details/i') },
  ];
  
  for (const { name, locator } of elements) {
    const isVisible = await locator.first().isVisible({ timeout: 1000 }).catch(() => false);
    console.log(`   ${isVisible ? '✅' : '❌'} ${name}`);
  }
  
  // Final verdict
  console.log('\n=== FINAL VERDICT ===');
  
  if (processStepsObserved.length > 0) {
    console.log('✅ Processing steps were visible during execution');
    console.log('   Fix appears to be working - trade progresses through stages');
  } else {
    console.log('⚠️ No explicit processing steps detected');
    console.log('   Trade may execute too quickly to show intermediate steps');
    console.log('   OR processing steps are not displayed in UI');
  }
  
  if (finalStatus === 'COMPLETED') {
    console.log('✅ Trade executed successfully');
  } else if (finalStatus === 'FAILED') {
    console.log('❌ Trade failed with error: ' + (errorMessage || 'Unknown'));
    console.log('   But it reached the execution stage (progress!)');
  }
  
  console.log('\n=== TEST COMPLETE ===');
});
