/**
 * Automated test for "top performer" feature using Puppeteer
 * 
 * Installation:
 *   npm install puppeteer
 * 
 * Run:
 *   node tests/browser/test_top_performer_puppeteer.js
 */

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'http://localhost:3000';
const RESULTS_DIR = path.join(__dirname, '../../test_results');

// Ensure results directory exists
if (!fs.existsSync(RESULTS_DIR)) {
  fs.mkdirSync(RESULTS_DIR, { recursive: true });
}

/**
 * Wait for assistant response after sending a message
 */
async function waitForAssistantResponse(page, timeout = 60000) {
  try {
    // Wait for loading to complete or assistant message to appear
    // Check for either: loading indicator disappearing OR action required card OR insight card
    const startTime = Date.now();
    while (Date.now() - startTime < timeout) {
      // Check if loading is still active (spinner or loading text)
      const isLoading = await page.evaluate(() => {
        const loadingText = document.body.textContent || '';
        return loadingText.includes('Analyzing') || 
               loadingText.includes('Processing') ||
               document.querySelector('.animate-spin') !== null;
      });
      
      // Check if response arrived (confirmation card, insight, or selection panel)
      const hasResponse = await page.evaluate(() => {
        const content = document.body.textContent || '';
        return content.includes('Action Required') ||
               content.includes('Asset Selection') ||
               content.includes('Confirm') ||
               content.includes('CONFIRM') ||
               content.includes('Cancel');
      });
      
      if (hasResponse && !isLoading) {
        // Give extra time for UI to stabilize
        await new Promise(resolve => setTimeout(resolve, 3000));
        return;
      }
      
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    throw new Error('Timeout waiting for assistant response');
  } catch (error) {
    console.error('Timeout waiting for assistant response:', error.message);
    throw error;
  }
}

/**
 * Send a message in the chat
 */
async function sendMessage(page, message) {
  // Wait for page to be fully loaded
  await new Promise(resolve => setTimeout(resolve, 2000));
  
  // Find textarea - placeholder is "Ask me anything about trading..."
  const textarea = await page.waitForSelector('textarea', { timeout: 10000 });
  await textarea.click();
  await textarea.type(message, { delay: 30 }); // Type slowly to ensure all chars are captured
  
  // Find and click the Send button by XPath (contains "Send" text)
  await page.evaluate(() => {
    const buttons = document.querySelectorAll('button');
    for (const btn of buttons) {
      if (btn.textContent?.trim() === 'Send') {
        btn.click();
        return;
      }
    }
    // Try any button with send-like class
    const sendBtn = document.querySelector('button[type="submit"], .send-button');
    if (sendBtn) sendBtn.click();
  });
  
  // Wait for response
  await waitForAssistantResponse(page);
}

/**
 * Check for console errors
 */
function setupConsoleMonitor(page) {
  const errors = [];
  
  page.on('console', msg => {
    if (msg.type() === 'error') {
      errors.push(msg.text());
    }
  });
  
  page.on('pageerror', error => {
    errors.push(error.message);
  });
  
  return errors;
}

/**
 * Test Case 1: 10 minutes window
 */
async function test10Minutes(browser) {
  console.log('\n=== Test Case 1: 10 minutes window ===');
  
  const page = await browser.newPage();
  const consoleErrors = setupConsoleMonitor(page);
  
  try {
    // Navigate to chat
    await page.goto(`${BASE_URL}/chat`, { waitUntil: 'networkidle2' });
    
    // Send message
    console.log('Sending: "Buy $2 of highest performing crypto in last 10 minutes"');
    await sendMessage(page, 'Buy $2 of highest performing crypto in last 10 minutes');
    
    // Get page content
    const content = await page.content();
    
    // Verify: NO "which crypto?" prompt
    if (content.toLowerCase().includes('which crypto')) {
      throw new Error('❌ FAIL: System asked for crypto clarification');
    }
    console.log('✅ No clarification prompt');
    
    // Verify: Selection Panel appears
    const selectionPanel = await page.$('text/Asset Selection') || 
                          await page.$('[class*="selection"]');
    if (!selectionPanel) {
      throw new Error('❌ FAIL: Selection Panel not found');
    }
    console.log('✅ Selection Panel found');
    
    // Verify: Window description mentions 10 minutes
    const bodyText = await page.evaluate(() => document.body.textContent);
    if (!(/10m|10 min|last 10 minutes/i.test(bodyText))) {
      console.warn('⚠️  Warning: Window description may not mention "10 minutes"');
    } else {
      console.log('✅ Window description found');
    }
    
    // Verify: Return percentage shown
    if (!(/[+-]?\d+\.\d+%/.test(bodyText))) {
      console.warn('⚠️  Warning: Return percentage not found');
    } else {
      console.log('✅ Return percentage displayed');
    }
    
    // Verify: Financial Insight Card renders (NOT JSON)
    const hasInsightCard = bodyText.includes('Why it matters for this trade');
    const hasRawJson = bodyText.includes('"headline":');
    
    if (!hasInsightCard) {
      throw new Error('❌ FAIL: Financial Insight Card not rendered');
    }
    if (hasRawJson) {
      throw new Error('❌ FAIL: Raw JSON displayed instead of formatted card');
    }
    console.log('✅ Financial Insight Card rendered properly');
    
    // Verify: Confirm/Cancel buttons
    const confirmBtn = await page.$('button::-p-text(Confirm)');
    const cancelBtn = await page.$('button::-p-text(Cancel)');
    
    if (!confirmBtn || !cancelBtn) {
      throw new Error('❌ FAIL: Confirm/Cancel buttons not found');
    }
    console.log('✅ Confirm/Cancel buttons present');
    
    // Take screenshot
    const screenshotPath = path.join(RESULTS_DIR, 'test_10_minutes.png');
    await page.screenshot({ path: screenshotPath, fullPage: true });
    console.log(`📸 Screenshot saved: ${screenshotPath}`);
    
    // Check console errors
    if (consoleErrors.length > 0) {
      console.error('❌ Console errors found:', consoleErrors);
      throw new Error(`Console errors: ${consoleErrors.join(', ')}`);
    }
    console.log('✅ No console errors');
    
    console.log('✅ Test Case 1: PASSED');
    return true;
    
  } catch (error) {
    console.error('❌ Test Case 1: FAILED');
    console.error(error.message);
    
    // Take error screenshot
    const errorPath = path.join(RESULTS_DIR, 'test_10_minutes_error.png');
    await page.screenshot({ path: errorPath, fullPage: true });
    console.log(`📸 Error screenshot: ${errorPath}`);
    
    return false;
  } finally {
    await page.close();
  }
}

/**
 * Test Case 2: 1 week window
 */
async function test1Week(browser) {
  console.log('\n=== Test Case 2: 1 week window ===');
  
  const page = await browser.newPage();
  const consoleErrors = setupConsoleMonitor(page);
  
  try {
    await page.goto(`${BASE_URL}/chat`, { waitUntil: 'networkidle2' });
    
    console.log('Sending: "Buy $2 of highest performing crypto in last week"');
    await sendMessage(page, 'Buy $2 of highest performing crypto in last week');
    
    const bodyText = await page.evaluate(() => document.body.textContent);
    
    // Verify: Selection Panel
    const hasSelectionPanel = bodyText.includes('Asset Selection');
    if (!hasSelectionPanel) {
      throw new Error('❌ FAIL: Selection Panel not found');
    }
    console.log('✅ Selection Panel found');
    
    // Verify: Window description
    if (!(/1w|7d|7 day|last week|week/i.test(bodyText))) {
      console.warn('⚠️  Warning: Window description may not mention "week"');
    } else {
      console.log('✅ Window description found');
    }
    
    // Verify: Financial Insight Card
    const hasInsightCard = bodyText.includes('Why it matters for this trade');
    if (!hasInsightCard) {
      throw new Error('❌ FAIL: Financial Insight Card not rendered');
    }
    console.log('✅ Financial Insight Card rendered');
    
    // Screenshot
    const screenshotPath = path.join(RESULTS_DIR, 'test_1_week.png');
    await page.screenshot({ path: screenshotPath, fullPage: true });
    console.log(`📸 Screenshot saved: ${screenshotPath}`);
    
    if (consoleErrors.length > 0) {
      console.error('❌ Console errors:', consoleErrors);
      throw new Error('Console errors found');
    }
    console.log('✅ No console errors');
    
    console.log('✅ Test Case 2: PASSED');
    return true;
    
  } catch (error) {
    console.error('❌ Test Case 2: FAILED');
    console.error(error.message);
    
    const errorPath = path.join(RESULTS_DIR, 'test_1_week_error.png');
    await page.screenshot({ path: errorPath, fullPage: true });
    
    return false;
  } finally {
    await page.close();
  }
}

/**
 * Test Case 3: 7 weeks window
 */
async function test7Weeks(browser) {
  console.log('\n=== Test Case 3: 7 weeks window ===');
  
  const page = await browser.newPage();
  const consoleErrors = setupConsoleMonitor(page);
  
  try {
    await page.goto(`${BASE_URL}/chat`, { waitUntil: 'networkidle2' });
    
    console.log('Sending: "Buy $2 of highest performing crypto in last 7 weeks"');
    await sendMessage(page, 'Buy $2 of highest performing crypto in last 7 weeks');
    
    const bodyText = await page.evaluate(() => document.body.textContent);
    
    // Verify: Selection Panel
    const hasSelectionPanel = bodyText.includes('Asset Selection');
    if (!hasSelectionPanel) {
      throw new Error('❌ FAIL: Selection Panel not found');
    }
    console.log('✅ Selection Panel found');
    
    // Verify: Window description
    if (!(/7w|49d|7 week|weeks/i.test(bodyText))) {
      console.warn('⚠️  Warning: Window description may not mention "7 weeks"');
    } else {
      console.log('✅ Window description found');
    }
    
    // Verify: Financial Insight Card
    const hasInsightCard = bodyText.includes('Why it matters for this trade');
    if (!hasInsightCard) {
      throw new Error('❌ FAIL: Financial Insight Card not rendered');
    }
    console.log('✅ Financial Insight Card rendered');
    
    // Screenshot
    const screenshotPath = path.join(RESULTS_DIR, 'test_7_weeks.png');
    await page.screenshot({ path: screenshotPath, fullPage: true });
    console.log(`📸 Screenshot saved: ${screenshotPath}`);
    
    if (consoleErrors.length > 0) {
      console.error('❌ Console errors:', consoleErrors);
      throw new Error('Console errors found');
    }
    console.log('✅ No console errors');
    
    console.log('✅ Test Case 3: PASSED');
    return true;
    
  } catch (error) {
    console.error('❌ Test Case 3: FAILED');
    console.error(error.message);
    
    const errorPath = path.join(RESULTS_DIR, 'test_7_weeks_error.png');
    await page.screenshot({ path: errorPath, fullPage: true });
    
    return false;
  } finally {
    await page.close();
  }
}

/**
 * Main test runner
 */
async function runTests() {
  console.log('🚀 Starting Top Performer Feature Tests');
  console.log(`Target: ${BASE_URL}/chat`);
  console.log(`Results directory: ${RESULTS_DIR}`);
  
  const browser = await puppeteer.launch({
    headless: false, // Set to true for CI/CD
    args: ['--start-maximized'],
    defaultViewport: { width: 1920, height: 1080 }
  });
  
  const results = {
    test1: false,
    test2: false,
    test3: false,
  };
  
  try {
    results.test1 = await test10Minutes(browser);
    results.test2 = await test1Week(browser);
    results.test3 = await test7Weeks(browser);
    
  } catch (error) {
    console.error('Fatal error during test execution:', error);
  } finally {
    await browser.close();
  }
  
  // Summary
  console.log('\n' + '='.repeat(50));
  console.log('📊 TEST SUMMARY');
  console.log('='.repeat(50));
  console.log(`Test 1 (10 minutes): ${results.test1 ? '✅ PASSED' : '❌ FAILED'}`);
  console.log(`Test 2 (1 week):     ${results.test2 ? '✅ PASSED' : '❌ FAILED'}`);
  console.log(`Test 3 (7 weeks):    ${results.test3 ? '✅ PASSED' : '❌ FAILED'}`);
  
  const passCount = Object.values(results).filter(r => r).length;
  const totalCount = Object.keys(results).length;
  
  console.log('='.repeat(50));
  console.log(`Overall: ${passCount}/${totalCount} tests passed`);
  
  if (passCount === totalCount) {
    console.log('🎉 All tests passed!');
    process.exit(0);
  } else {
    console.log('❌ Some tests failed. Check screenshots in test_results/');
    process.exit(1);
  }
}

// Run tests
runTests().catch(error => {
  console.error('Unhandled error:', error);
  process.exit(1);
});
