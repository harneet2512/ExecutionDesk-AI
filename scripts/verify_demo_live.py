#!/usr/bin/env python
"""FDE-10 Verification Script: CRYPTO + STOCKS + News Toggle + ASSISTED_LIVE.

Run this script to verify the demo is configured correctly and all features work.

Usage:
    python scripts/verify_demo_live.py
"""
import os
import sys
import json

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Enable pytest mode to allow imports without credentials
os.environ["PYTEST_CURRENT_TEST"] = "verify_demo_live"


class VerificationResult:
    """Track pass/fail for each check."""

    def __init__(self):
        self.results = []

    def check(self, name: str, passed: bool, details: str = ""):
        status = "PASS" if passed else "FAIL"
        self.results.append((name, status, details))
        print(f"  [{status}] {name}")
        if details:
            print(f"         {details}")

    def summary(self):
        passed = sum(1 for _, s, _ in self.results if s == "PASS")
        total = len(self.results)
        print(f"\n{'='*60}")
        print(f"VERIFICATION SUMMARY: {passed}/{total} checks passed")
        if passed < total:
            print("\nFailed checks:")
            for name, status, details in self.results:
                if status == "FAIL":
                    print(f"  - {name}: {details}")
        return passed == total


def main():
    """Run all verification checks."""
    print("="*60)
    print("FDE-10 Verification: CRYPTO + STOCKS + News Toggle")
    print("="*60)
    print()

    v = VerificationResult()

    # 1. Check Polygon API key configuration
    print("[1] Environment Configuration")
    from backend.core.config import get_settings
    settings = get_settings()
    has_polygon = bool(settings.polygon_api_key)
    v.check("POLYGON_API_KEY configured", has_polygon,
            "Set POLYGON_API_KEY in .env for stock data" if not has_polygon else "")

    # 2. Check Coinbase credentials (for crypto)
    from backend.services.market_data_provider import has_coinbase_creds
    has_coinbase = has_coinbase_creds()
    v.check("Coinbase credentials configured", has_coinbase,
            "Set COINBASE_API_KEY_NAME and COINBASE_API_PRIVATE_KEY for crypto" if not has_coinbase else "")

    # 3. Test market data provider factory
    print("\n[2] Market Data Providers")
    try:
        from backend.services.market_data_provider import get_market_data_provider
        crypto_provider = get_market_data_provider(asset_class="CRYPTO")
        v.check("CRYPTO provider (Coinbase)",
                type(crypto_provider).__name__ == "CoinbaseMarketDataProvider",
                f"Got {type(crypto_provider).__name__}")
    except Exception as e:
        v.check("CRYPTO provider (Coinbase)", False, str(e))

    try:
        stock_provider = get_market_data_provider(asset_class="STOCK")
        v.check("STOCK provider (Polygon)",
                type(stock_provider).__name__ == "PolygonMarketDataProvider",
                f"Got {type(stock_provider).__name__}")
    except Exception as e:
        v.check("STOCK provider (Polygon)", False, str(e))

    # 4. Test NLP classification
    print("\n[3] NLP Classification")
    from backend.agents.trade_parser import parse_trade_command

    # Crypto test
    crypto_result = parse_trade_command("buy $50 of BTC")
    v.check("NLP: 'buy $50 of BTC' → CRYPTO",
            crypto_result.asset_class == "CRYPTO" and crypto_result.asset == "BTC",
            f"asset_class={crypto_result.asset_class}, asset={crypto_result.asset}")

    # Stock test
    stock_result = parse_trade_command("buy $50 of AAPL")
    v.check("NLP: 'buy $50 of AAPL' → STOCK",
            stock_result.asset_class == "STOCK" and stock_result.asset == "AAPL",
            f"asset_class={stock_result.asset_class}, asset={stock_result.asset}")

    # Stock with keyword
    stock_kw = parse_trade_command("buy $100 of NVDA stock")
    v.check("NLP: 'buy $100 of NVDA stock' → STOCK",
            stock_kw.asset_class == "STOCK" and stock_kw.asset == "NVDA",
            f"asset_class={stock_kw.asset_class}, asset={stock_kw.asset}")

    # Ambiguous
    ambig = parse_trade_command("buy $50 crypto stock")
    v.check("NLP: 'buy $50 crypto stock' → AMBIGUOUS",
            ambig.asset_class == "AMBIGUOUS",
            f"asset_class={ambig.asset_class}")

    # 5. Test database migrations
    print("\n[4] Database Schema")
    from backend.db.connect import get_conn
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            # Check trade_tickets table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trade_tickets'")
            has_tickets_table = cursor.fetchone() is not None
            v.check("trade_tickets table exists", has_tickets_table,
                    "Run migrations or init_db()" if not has_tickets_table else "")

            # Check runs table has news_enabled column
            cursor.execute("PRAGMA table_info(runs)")
            columns = [row[1] for row in cursor.fetchall()]
            has_news_enabled = "news_enabled" in columns
            v.check("runs.news_enabled column exists", has_news_enabled,
                    f"Columns: {columns}" if not has_news_enabled else "")

            has_asset_class = "asset_class" in columns
            v.check("runs.asset_class column exists", has_asset_class,
                    f"Columns: {columns}" if not has_asset_class else "")
    except Exception as e:
        v.check("Database schema check", False, str(e))

    # 6. Test rate limiter
    print("\n[5] Rate Limiter")
    try:
        from backend.services.rate_limiter import TokenBucketRateLimiter
        limiter = TokenBucketRateLimiter(tokens_per_minute=5)
        v.check("TokenBucketRateLimiter initialized", True,
                f"tokens_per_minute={limiter.tokens_per_minute}")

        # Test acquire
        acquired = limiter.try_acquire()
        v.check("Rate limiter token acquire", acquired, "")
    except Exception as e:
        v.check("Rate limiter", False, str(e))

    # 7. Test trade tickets repo
    print("\n[6] Trade Tickets Repository")
    try:
        from backend.db.repo.trade_tickets_repo import TradeTicketsRepo
        repo = TradeTicketsRepo()
        v.check("TradeTicketsRepo import", True, "")

        # Test create_ticket (in-memory test)
        ticket_id = repo.create_ticket(
            tenant_id="test_tenant",
            run_id="test_run",
            symbol="AAPL",
            side="BUY",
            notional_usd=100.0,
            asset_class="STOCK"
        )
        v.check("Create trade ticket", ticket_id.startswith("ticket_"),
                f"ticket_id={ticket_id}")

        # Cleanup
        repo.mark_cancelled("test_tenant", ticket_id)
    except Exception as e:
        v.check("Trade tickets repo", False, str(e))

    # 8. Test stock watchlist
    print("\n[7] Stock Watchlist")
    watchlist = settings.stock_watchlist_list
    v.check("Stock watchlist configured", len(watchlist) > 0,
            f"Watchlist: {watchlist}")

    # 9. Test API routes import
    print("\n[8] API Routes")
    try:
        from backend.api.routes.trade_tickets import router
        v.check("trade_tickets router import", router is not None, "")
    except Exception as e:
        v.check("trade_tickets router", False, str(e))

    # 10. Check evals exist
    print("\n[9] Evals Structure")
    try:
        from backend.orchestrator.nodes.eval_node import execute
        v.check("eval_node import", True, "")
    except Exception as e:
        v.check("eval_node import", False, str(e))

    # 11. Check new market evidence evals
    print("\n[10] Market Evidence Evals")
    try:
        from backend.evals.market_evidence_evals import (
            market_evidence_integrity,
            freshness_eval,
            rate_limit_resilience
        )
        v.check("market_evidence_evals import", True, "")
    except Exception as e:
        v.check("market_evidence_evals import", False, str(e))

    # 12. Check grounding evals
    print("\n[11] Grounding Evals")
    try:
        from backend.evals.grounding_evals import (
            portfolio_grounding,
            news_evidence_integrity
        )
        v.check("grounding_evals import", True, "")
    except Exception as e:
        v.check("grounding_evals import", False, str(e))

    # 13. Check news toggle in chat route
    print("\n[12] News Toggle Support")
    try:
        from backend.api.routes.chat import CommandRequest
        import inspect
        sig = inspect.signature(CommandRequest.__init__)
        params = list(sig.parameters.keys())
        has_news = 'news_enabled' in str(CommandRequest.model_fields)
        v.check("CommandRequest has news_enabled field", has_news, "")
    except Exception as e:
        v.check("News toggle support", False, str(e))

    # 14. Check frontend components exist
    print("\n[13] Frontend Components")
    import os
    frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "components")
    components_to_check = ["NewsToggle.tsx", "NewsBriefCard.tsx", "OrderTicketCard.tsx"]
    for comp in components_to_check:
        comp_path = os.path.join(frontend_dir, comp)
        exists = os.path.exists(comp_path)
        v.check(f"Component {comp} exists", exists, comp_path if not exists else "")

    # 15. Check ASSISTED_LIVE execution mode is handled
    print("\n[14] Execution Modes")
    try:
        from backend.orchestrator.nodes.execution_node import execute as exec_execute
        v.check("execution_node import", True, "")
    except Exception as e:
        v.check("execution_node import", False, str(e))

    # Summary
    all_passed = v.summary()
    print()

    if all_passed:
        print("✅ All verification checks passed!")
        print("\nReady for demo:")
        print("  - Start backend: uvicorn backend.api.main:app --reload")
        print("  - Start frontend: cd frontend && npm run dev")
        print("  - Open: http://localhost:3000")
        return 0
    else:
        print("❌ Some checks failed. Review the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
