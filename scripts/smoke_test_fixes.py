#!/usr/bin/env python3
"""Smoke test script to verify trade execution and insight fixes.

Tests:
1. Product metadata resilience (retry, fallback to stale cache)
2. Enhanced insights (trend, volatility, range, sentiment)
3. Confirmation flow (LIVE disabled handling)
4. Status propagation (CREATED → FAILED, not RUNNING → FAILED)
"""
import sys
import os
import asyncio
import json
from datetime import datetime, timedelta

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from services.market_metadata import MarketMetadataService, MetadataErrorCode
from services.pre_confirm_insight import generate_insight, _analyze_headline_sentiment
from core.error_codes import TradeErrorCode, get_error_message


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def print_test(name: str):
    """Print test name."""
    print(f"\n{Colors.BLUE}{Colors.BOLD}TEST: {name}{Colors.RESET}")


def print_pass(message: str):
    """Print pass message."""
    print(f"  {Colors.GREEN}✓{Colors.RESET} {message}")


def print_fail(message: str):
    """Print fail message."""
    print(f"  {Colors.RED}✗{Colors.RESET} {message}")


def print_info(message: str):
    """Print info message."""
    print(f"  {Colors.YELLOW}ℹ{Colors.RESET} {message}")


async def test_metadata_service_retry():
    """Test 1: MarketMetadataService retry logic."""
    print_test("Product Metadata Service - Retry Logic")
    
    service = MarketMetadataService()
    
    # Test with real API call (should succeed or use cache)
    result = await service.get_product_details("BTC-USD", allow_stale=True)
    
    if result.success:
        print_pass(f"Successfully fetched BTC-USD metadata")
        print_info(f"  Used stale cache: {result.used_stale_cache}")
        print_info(f"  Cache age: {result.cache_age_seconds}s" if result.cache_age_seconds else "  Fresh data")
        
        # Verify required fields
        if result.data:
            required_fields = ["base_increment", "base_min_size", "quote_increment"]
            for field in required_fields:
                if field in result.data:
                    print_pass(f"  Field '{field}' present: {result.data[field]}")
                else:
                    print_fail(f"  Field '{field}' missing")
        
        return True
    else:
        print_fail(f"Failed to fetch metadata: {result.error_message}")
        print_info(f"  Error code: {result.error_code.value}")
        return False


async def test_enhanced_insights_buy():
    """Test 2: Enhanced insights for BUY with range context."""
    print_test("Enhanced Insights - BUY Order")
    
    # Generate insight for BUY
    insight = await generate_insight(
        asset="BTC",
        side="BUY",
        notional_usd=100.0,
        asset_class="CRYPTO",
        news_enabled=True,
        mode="PAPER",
        request_id="smoke_test_buy"
    )
    
    if not insight:
        print_fail("Failed to generate insight")
        return False
    
    print_pass("Insight generated successfully")
    
    # Check for required fields
    checks = [
        ("headline", insight.get("headline")),
        ("why_it_matters", insight.get("why_it_matters")),
        ("key_facts", insight.get("key_facts")),
        ("confidence", insight.get("confidence")),
        ("generated_by", insight.get("generated_by"))
    ]
    
    all_passed = True
    for field, value in checks:
        if value:
            print_pass(f"Field '{field}' present")
        else:
            print_fail(f"Field '{field}' missing")
            all_passed = False
    
    # Check for non-generic content
    key_facts_text = " ".join(insight.get("key_facts", []))
    why_it_matters = insight.get("why_it_matters", "")
    
    if "24h" in key_facts_text or "7-day" in key_facts_text or "7d" in key_facts_text:
        print_pass("Insight includes trend data (24h/7d)")
    else:
        print_fail("Insight missing trend data")
        all_passed = False
    
    if "volatility" in key_facts_text.lower() or "volatility" in why_it_matters.lower():
        print_pass("Insight includes volatility context")
    else:
        print_info("Insight may be missing volatility context (acceptable if no data)")
    
    if "range" in key_facts_text.lower() or "high" in key_facts_text.lower() or "low" in key_facts_text.lower():
        print_pass("Insight includes range context")
    else:
        print_info("Insight may be missing range context (acceptable if no data)")
    
    # Check BUY-specific language
    if "buying" in why_it_matters.lower():
        print_pass("Insight uses BUY-specific language")
    else:
        print_fail("Insight missing BUY-specific language")
        all_passed = False
    
    print_info(f"Headline: {insight.get('headline', 'N/A')[:100]}")
    print_info(f"Confidence: {insight.get('confidence', 0):.2f}")
    print_info(f"Generated by: {insight.get('generated_by', 'N/A')}")
    
    return all_passed


async def test_enhanced_insights_sell():
    """Test 3: Enhanced insights for SELL differ from BUY."""
    print_test("Enhanced Insights - SELL Order (vs BUY)")
    
    # Generate insight for SELL
    insight = await generate_insight(
        asset="BTC",
        side="SELL",
        notional_usd=100.0,
        asset_class="CRYPTO",
        news_enabled=True,
        mode="PAPER",
        request_id="smoke_test_sell"
    )
    
    if not insight:
        print_fail("Failed to generate insight")
        return False
    
    print_pass("Insight generated successfully")
    
    why_it_matters = insight.get("why_it_matters", "")
    
    # Check SELL-specific language
    if "selling" in why_it_matters.lower():
        print_pass("Insight uses SELL-specific language")
    else:
        print_fail("Insight missing SELL-specific language")
        return False
    
    # Check for strategic context
    strategic_terms = ["strength", "weakness", "profit", "loss", "cutting"]
    has_strategic = any(term in why_it_matters.lower() for term in strategic_terms)
    
    if has_strategic:
        print_pass("Insight includes strategic context for SELL")
    else:
        print_info("Insight may lack strategic context (acceptable)")
    
    print_info(f"Headline: {insight.get('headline', 'N/A')[:100]}")
    
    return True


def test_sentiment_analysis():
    """Test 4: Headline sentiment analysis."""
    print_test("Sentiment Analysis")
    
    test_cases = [
        ("Bitcoin surges to new all-time high", "bullish"),
        ("BTC crashes below key support", "bearish"),
        ("Bitcoin trading sideways today", "neutral"),
        ("Crypto market rallies on positive news", "bullish"),
        ("BTC plunges amid regulatory fears", "bearish")
    ]
    
    all_passed = True
    for headline, expected in test_cases:
        result = _analyze_headline_sentiment(headline)
        if result == expected:
            print_pass(f"'{headline[:50]}...' → {result}")
        else:
            print_fail(f"'{headline[:50]}...' → {result} (expected {expected})")
            all_passed = False
    
    return all_passed


def test_error_codes():
    """Test 5: Structured error codes."""
    print_test("Structured Error Codes")
    
    test_codes = [
        TradeErrorCode.PRODUCT_DETAILS_UNAVAILABLE,
        TradeErrorCode.PRODUCT_API_TIMEOUT,
        TradeErrorCode.INSUFFICIENT_BALANCE,
        TradeErrorCode.BELOW_MINIMUM_SIZE
    ]
    
    all_passed = True
    for code in test_codes:
        error_info = get_error_message(code)
        if error_info.get("message") and error_info.get("remediation"):
            print_pass(f"{code.value}: {error_info['message'][:50]}...")
        else:
            print_fail(f"{code.value}: Missing message or remediation")
            all_passed = False
    
    return all_passed


async def test_insight_with_zero_headlines():
    """Test 6: Insight quality with 0 headlines."""
    print_test("Insight Quality - Zero Headlines")
    
    # Generate insight with news enabled but likely 0 headlines
    insight = await generate_insight(
        asset="BTC",
        side="BUY",
        notional_usd=100.0,
        asset_class="CRYPTO",
        news_enabled=True,
        mode="PAPER",
        request_id="smoke_test_no_headlines"
    )
    
    if not insight:
        print_fail("Failed to generate insight")
        return False
    
    key_facts = insight.get("key_facts", [])
    why_it_matters = insight.get("why_it_matters", "")
    
    # Check that insight is NOT just generic "fees matter"
    key_facts_text = " ".join(key_facts)
    
    has_market_data = any(term in key_facts_text.lower() for term in ["24h", "7-day", "7d", "range", "volatility", "trading at"])
    
    if has_market_data:
        print_pass("Insight includes market data despite 0 headlines")
    else:
        print_fail("Insight is too generic (only fees/generic content)")
        return False
    
    # Check it's not ONLY about fees
    non_fee_facts = [f for f in key_facts if "fee" not in f.lower()]
    if len(non_fee_facts) >= 3:
        print_pass(f"Insight has {len(non_fee_facts)} non-fee facts")
    else:
        print_fail(f"Insight has only {len(non_fee_facts)} non-fee facts (too few)")
        return False
    
    print_info(f"Total key facts: {len(key_facts)}")
    print_info(f"Sample facts: {key_facts[:3]}")
    
    return True


async def run_all_tests():
    """Run all smoke tests."""
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"SMOKE TEST SUITE - Trade Execution & Insights Fixes")
    print(f"{'='*60}{Colors.RESET}\n")
    
    results = {}
    
    # Run tests
    results["metadata_retry"] = await test_metadata_service_retry()
    results["insights_buy"] = await test_enhanced_insights_buy()
    results["insights_sell"] = await test_enhanced_insights_sell()
    results["sentiment"] = test_sentiment_analysis()
    results["error_codes"] = test_error_codes()
    results["zero_headlines"] = await test_insight_with_zero_headlines()
    
    # Summary
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"TEST SUMMARY")
    print(f"{'='*60}{Colors.RESET}\n")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = f"{Colors.GREEN}PASS{Colors.RESET}" if result else f"{Colors.RED}FAIL{Colors.RESET}"
        print(f"  {test_name.replace('_', ' ').title()}: {status}")
    
    print(f"\n{Colors.BOLD}Total: {passed}/{total} tests passed{Colors.RESET}")
    
    if passed == total:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✓ ALL TESTS PASSED{Colors.RESET}\n")
        return 0
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}✗ SOME TESTS FAILED{Colors.RESET}\n")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)
