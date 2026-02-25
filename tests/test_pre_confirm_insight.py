"""Tests for pre-confirm financial insight generation."""
import pytest
import json
import asyncio
from unittest.mock import patch, MagicMock


def run_async(coro):
    """Helper to run async functions in sync tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestBuildFactPack:
    """build_fact_pack returns valid structure from deterministic inputs."""

    def test_returns_all_required_keys(self):
        from backend.services.pre_confirm_insight import build_fact_pack
        facts = build_fact_pack(
            asset="BTC",
            side="BUY",
            notional_usd=10.0,
            asset_class="CRYPTO",
            price_data={"price": 50000.0, "change_24h_pct": -2.5, "price_source": "test"},
            headlines=[{"title": "BTC rallies", "published_at": "2024-01-01", "source": "Test"}]
        )
        required_keys = ["asset", "side", "notional_usd", "price", "change_24h_pct",
                         "volatility", "headlines", "risk_flags", "confidence", "key_facts"]
        for key in required_keys:
            assert key in facts, f"Missing key: {key}"

    def test_volatility_high_above_5pct(self):
        from backend.services.pre_confirm_insight import build_fact_pack
        facts = build_fact_pack("BTC", "BUY", 100.0, "CRYPTO",
                                {"price": 50000.0, "change_24h_pct": 7.0, "price_source": "test"}, [])
        assert facts["volatility"] == "HIGH"
        assert "high_volatility" in facts["risk_flags"]

    def test_volatility_moderate_2_to_5(self):
        from backend.services.pre_confirm_insight import build_fact_pack
        facts = build_fact_pack("BTC", "BUY", 100.0, "CRYPTO",
                                {"price": 50000.0, "change_24h_pct": 3.0, "price_source": "test"}, [])
        assert facts["volatility"] == "MODERATE"

    def test_volatility_low_below_2(self):
        from backend.services.pre_confirm_insight import build_fact_pack
        facts = build_fact_pack("BTC", "BUY", 100.0, "CRYPTO",
                                {"price": 50000.0, "change_24h_pct": 0.5, "price_source": "test"}, [])
        assert facts["volatility"] == "LOW"

    def test_thin_notional_flag(self):
        from backend.services.pre_confirm_insight import build_fact_pack
        facts = build_fact_pack("BTC", "BUY", 5.0, "CRYPTO",
                                {"price": 50000.0, "change_24h_pct": 0.5, "price_source": "test"}, [])
        assert "thin_notional" in facts["risk_flags"]

    def test_news_empty_flag(self):
        from backend.services.pre_confirm_insight import build_fact_pack
        facts = build_fact_pack("BTC", "BUY", 100.0, "CRYPTO",
                                {"price": 50000.0, "change_24h_pct": 0.5, "price_source": "test"}, [])
        assert "news_empty" in facts["risk_flags"]

    def test_price_unavailable_flag(self):
        from backend.services.pre_confirm_insight import build_fact_pack
        facts = build_fact_pack("BTC", "BUY", 100.0, "CRYPTO",
                                {"price": None, "change_24h_pct": None, "price_source": "none"}, [])
        assert "price_unavailable" in facts["risk_flags"]

    def test_confidence_with_all_data(self):
        from backend.services.pre_confirm_insight import build_fact_pack
        facts = build_fact_pack("BTC", "BUY", 100.0, "CRYPTO",
                                {"price": 50000.0, "change_24h_pct": 1.0, "price_source": "test"},
                                [{"title": "a", "published_at": "t", "source": "s"},
                                 {"title": "b", "published_at": "t", "source": "s"}])
        # 0.35 + 0.15 (price+change) + 0.10 (volatility) + 0.10 (2+ headlines) = 0.70
        assert facts["confidence"] == pytest.approx(0.70)

    def test_confidence_no_data(self):
        from backend.services.pre_confirm_insight import build_fact_pack
        facts = build_fact_pack("BTC", "BUY", 100.0, "CRYPTO",
                                {"price": None, "change_24h_pct": None, "price_source": "none"}, [])
        # 0.35 - 0.20 (news_empty) - 0.20 (price_unavailable) = max(0, -0.05) = 0.0
        assert facts["confidence"] == pytest.approx(0.0)


class TestTemplateInsight:
    """Template insight always returns valid InsightSchema."""

    def test_template_insight_valid_schema(self):
        from backend.services.pre_confirm_insight import _build_template_insight, InsightSchema
        facts = {
            "asset": "BTC",
            "side": "BUY",
            "notional_usd": 10.0,
            "change_24h_pct": -2.5,
            "volatility": "MODERATE",
            "price": 50000.0,
            "headlines": [{"title": "BTC rallies", "published_at": "t", "source": "s"}],
            "risk_flags": [],
            "confidence": 0.60,
            "key_facts": ["BTC at $50,000"],
            "price_source": "test",
        }
        result = _build_template_insight(facts, "req_123")
        # Validate it matches schema
        validated = InsightSchema(**result)
        assert validated.request_id == "req_123"
        assert validated.generated_by == "template"

    def test_headline_contains_asset(self):
        from backend.services.pre_confirm_insight import _template_headline
        headline = _template_headline({
            "asset": "ETH",
            "change_24h_pct": 3.2,
            "price": 3000.0,
            "headlines": [{"title": "a"}]
        })
        assert "ETH" in headline

    def test_why_it_matters_mentions_side_and_asset(self):
        from backend.services.pre_confirm_insight import _template_why_it_matters
        text = _template_why_it_matters({
            "asset": "BTC",
            "side": "SELL",
            "notional_usd": 2.0,
            "change_24h_pct": 6.0,
            "volatility": "HIGH",
            "price": 50000.0,
        })
        assert "BTC" in text
        assert "selling" in text.lower() or "sell" in text.lower()

    def test_buy_why_it_matters_specific(self):
        from backend.services.pre_confirm_insight import _template_why_it_matters
        text = _template_why_it_matters({
            "asset": "BTC",
            "side": "BUY",
            "notional_usd": 2.0,
            "change_24h_pct": -2.3,
            "volatility": "MODERATE",
            "price": 50000.0,
        })
        assert "buying" in text.lower()
        assert "2.3%" in text or "2.30%" in text


class TestGenerateInsight:
    """generate_insight always returns valid dict, never raises."""

    def test_returns_valid_dict_on_success(self):
        from backend.services.pre_confirm_insight import generate_insight, InsightSchema

        with patch("backend.services.pre_confirm_insight._fetch_price_data") as mock_price, \
             patch("backend.services.pre_confirm_insight._fetch_headlines") as mock_news:
            mock_price.return_value = {"price": 50000.0, "change_24h_pct": -1.5, "price_source": "test"}
            mock_news.return_value = (
                [{"title": "BTC dips", "published_at": "t", "source": "Reuters"}],
                [],
                False,
                {
                    "asset_queries": ["BTC", "BTC-USD", "Bitcoin"],
                    "asset_status": "ok",
                    "asset_reason": "",
                    "fallback_queries": [],
                    "fallback_status": "",
                    "fallback_reason": "",
                    "fallback_rationale": "",
                    "asset_category": "MAJOR",
                },
            )

            result = run_async(generate_insight("BTC", "BUY", 10.0, request_id="req_test"))

        # Must be valid InsightSchema
        validated = InsightSchema(**result)
        assert validated.headline
        assert validated.why_it_matters
        assert "BTC" in validated.headline

    def test_returns_fallback_on_total_failure(self):
        from backend.services.pre_confirm_insight import generate_insight, InsightSchema, _insight_cache
        # Clear cache to avoid stale hits from previous tests
        _insight_cache.clear()

        with patch("backend.services.pre_confirm_insight._fetch_price_data", side_effect=Exception("boom")), \
             patch("backend.services.pre_confirm_insight._fetch_headlines", side_effect=Exception("boom")):
            result = run_async(generate_insight("UNKNOWN_ASSET", "BUY", 999.0, request_id="req_fail"))

        validated = InsightSchema(**result)
        assert validated.headline == "Market insight unavailable"
        assert "insight_unavailable" in validated.risk_flags

    def test_news_disabled_skips_headlines(self):
        from backend.services.pre_confirm_insight import generate_insight

        with patch("backend.services.pre_confirm_insight._fetch_price_data") as mock_price, \
             patch("backend.services.pre_confirm_insight._fetch_headlines") as mock_news:
            mock_price.return_value = {"price": 50000.0, "change_24h_pct": 1.0, "price_source": "test"}

            result = run_async(generate_insight("BTC", "BUY", 10.0, news_enabled=False, request_id="req_no_news"))

        # Headlines fetcher should not be called when news is disabled
        mock_news.assert_not_called()
        # When news is disabled, news_empty flag is not set (it's intentional, not a data gap)
        assert "news_empty" not in result["risk_flags"]

    def test_empty_asset_news_triggers_market_fallback_and_rationale(self):
        from backend.services.pre_confirm_insight import generate_insight

        with patch("backend.services.pre_confirm_insight._fetch_price_data") as mock_price, \
             patch("backend.services.pre_confirm_insight._fetch_headlines") as mock_news:
            mock_price.return_value = {"price": 50000.0, "change_24h_pct": -1.0, "price_source": "test"}
            mock_news.return_value = (
                [],
                [{"title": "Crypto market sentiment turns risk-on", "published_at": "t", "source": "Reuters"}],
                False,
                {
                    "asset_queries": ["BTC", "BTC-USD", "Bitcoin"],
                    "asset_status": "empty",
                    "asset_reason": "No relevant news found for BTC in the last 24h.",
                    "fallback_queries": ["crypto market", "bitcoin ETF"],
                    "fallback_status": "ok",
                    "fallback_reason": "",
                    "fallback_rationale": "No asset-specific headlines returned, so showing broader market headlines most likely to impact BTC.",
                    "asset_category": "MAJOR",
                },
            )
            result = run_async(generate_insight("BTC", "BUY", 10.0, request_id="req_market_fb"))

        assert result.get("market_news_evidence") is not None
        assert result["market_news_evidence"]["rationale"]
        assert result["market_news_evidence"]["queries"]

    def test_evidence_payload_includes_required_fields(self):
        from backend.services.pre_confirm_insight import generate_insight

        with patch("backend.services.pre_confirm_insight._fetch_price_data") as mock_price, \
             patch("backend.services.pre_confirm_insight._fetch_headlines") as mock_news:
            mock_price.return_value = {"price": 50000.0, "change_24h_pct": 1.0, "price_source": "test"}
            mock_news.return_value = (
                [{"title": "Bitcoin ETF inflows rise", "published_at": "t", "source": "Reuters"}],
                [],
                False,
                {
                    "asset_queries": ["BTC", "BTC-USD", "Bitcoin"],
                    "asset_status": "ok",
                    "asset_reason": "",
                    "fallback_queries": [],
                    "fallback_status": "",
                    "fallback_reason": "",
                    "fallback_rationale": "",
                    "asset_category": "MAJOR",
                },
            )
            result = run_async(generate_insight("BTC", "BUY", 10.0, request_id="req_evidence"))

        asset_evidence = result.get("asset_news_evidence") or {}
        for key in ["queries", "lookback", "sources", "items", "status"]:
            assert key in asset_evidence
        assert result.get("impact_summary")

    def test_pre_confirm_news_shape_contract(self):
        from backend.services.pre_confirm_insight import generate_insight

        with patch("backend.services.pre_confirm_insight._fetch_price_data") as mock_price, \
             patch("backend.services.pre_confirm_insight._fetch_headlines") as mock_news:
            mock_price.return_value = {"price": 50000.0, "change_24h_pct": 0.2, "price_source": "test"}
            mock_news.return_value = (
                [],
                [{"title": "Crypto market sentiment improves", "published_at": "t", "source": "Reuters"}],
                False,
                {
                    "asset_queries": ["BTC", "BTC-USD", "Bitcoin"],
                    "asset_status": "empty",
                    "asset_reason": "No relevant news found for BTC in the last 24h.",
                    "fallback_queries": ["crypto market"],
                    "fallback_status": "ok",
                    "fallback_reason": "",
                    "fallback_rationale": "No asset-specific headlines returned, so I'm showing broader market headlines most likely to impact BTC.",
                    "asset_category": "MAJOR",
                },
            )
            result = run_async(generate_insight("BTC", "BUY", 10.0, news_enabled=True, request_id="req_contract"))

        assert "news_outcome" in result
        assert "asset_news_evidence" in result
        assert "impact_summary" in result
        ae = result["asset_news_evidence"]
        for key in ["status", "queries", "lookback", "sources", "items"]:
            assert key in ae
        assert result.get("market_news_evidence") is not None


class TestInsightDataQuality:
    """Insight data quality: no UNKNOWN strings, descriptive reasons."""

    def test_no_unknown_strings_in_fact_pack(self):
        """build_fact_pack never contains the string 'UNKNOWN' in any value."""
        from backend.services.pre_confirm_insight import build_fact_pack

        # Test with missing price and no headlines (worst case)
        facts = build_fact_pack(
            "BTC", "BUY", 10.0, "CRYPTO",
            {"price": None, "change_24h_pct": None, "price_source": "none"},
            [], news_enabled=True, headlines_fetch_failed=True,
        )

        # Recursively check all string values
        def check_no_unknown(obj, path=""):
            if isinstance(obj, str):
                assert "UNKNOWN" not in obj.upper() or "unknown reason" in obj.lower(), \
                    f"Found UNKNOWN at {path}: {obj}"
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    check_no_unknown(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    check_no_unknown(v, f"{path}[{i}]")

        check_no_unknown(facts)

    def test_no_unknown_in_template_insight(self):
        """Template insight never says 'UNKNOWN' or 'Volatility UNKNOWN'."""
        from backend.services.pre_confirm_insight import _build_template_insight

        facts = {
            "asset": "BTC", "side": "BUY", "notional_usd": 10.0,
            "change_24h_pct": None, "volatility": None, "price": None,
            "headlines": [], "risk_flags": ["price_unavailable"],
            "confidence": 0.0, "key_facts": ["Price not available"],
            "price_source": "none", "news_enabled": True,
            "live_allowed": True, "mode": "PAPER",
            "data_quality": {
                "missing_price": True,
                "missing_price_reason": "Market data provider returned no data for BTC",
                "missing_change": True,
                "missing_change_reason": "No candle data in market_candles table for BTC",
                "missing_headlines": True,
                "missing_headlines_reason": "News feed returned 0 results for BTC in 48h window",
                "stale_data": True,
                "headlines_fetch_failed": False,
            },
            "estimated_fees_usd": 0.06, "fee_impact_pct": 0.6,
        }
        result = _build_template_insight(facts, "req_test")
        assert "UNKNOWN" not in result["headline"]
        assert "UNKNOWN" not in result["why_it_matters"]
        for fact in result["key_facts"]:
            assert "UNKNOWN" not in fact

    def test_data_quality_keys_present(self):
        """data_quality dict has all required boolean keys."""
        from backend.services.pre_confirm_insight import build_fact_pack

        facts = build_fact_pack(
            "ETH", "SELL", 50.0, "CRYPTO",
            {"price": 3000.0, "change_24h_pct": 1.5, "price_source": "test"},
            [{"title": "ETH update", "published_at": "t", "source": "s"}],
        )

        dq = facts["data_quality"]
        required_bool_keys = ["missing_price", "missing_change", "missing_headlines",
                              "stale_data", "headlines_fetch_failed"]
        for key in required_bool_keys:
            assert key in dq, f"Missing data_quality key: {key}"
            assert isinstance(dq[key], bool), f"data_quality[{key}] should be bool"

    def test_data_quality_reasons_present_when_missing(self):
        """data_quality includes descriptive reasons when data is missing."""
        from backend.services.pre_confirm_insight import build_fact_pack

        facts = build_fact_pack(
            "BTC", "BUY", 10.0, "CRYPTO",
            {"price": None, "change_24h_pct": None, "price_source": "none"},
            [], news_enabled=True,
        )

        dq = facts["data_quality"]
        assert dq["missing_price"] is True
        assert dq["missing_price_reason"] is not None
        assert "BTC" in dq["missing_price_reason"]

        assert dq["missing_change"] is True
        assert dq["missing_change_reason"] is not None

        assert dq["missing_headlines"] is True
        assert dq["missing_headlines_reason"] is not None

    def test_headlines_fetch_failed_descriptive(self):
        """When headlines fetch fails, reason mentions tables/configuration."""
        from backend.services.pre_confirm_insight import build_fact_pack

        facts = build_fact_pack(
            "BTC", "BUY", 10.0, "CRYPTO",
            {"price": 50000.0, "change_24h_pct": 1.0, "price_source": "test"},
            [], news_enabled=True, headlines_fetch_failed=True,
        )

        dq = facts["data_quality"]
        assert dq["headlines_fetch_failed"] is True
        assert "fetch failed" in dq["missing_headlines_reason"].lower() or \
               "tables" in dq["missing_headlines_reason"].lower()


class TestInsightCache:
    """Insight cache: 60s TTL, returns cached result within window."""

    def test_cache_hit_within_ttl(self):
        from backend.services.pre_confirm_insight import _cache_set, _cache_get

        _cache_set("test_key", {"headline": "cached"})
        result = _cache_get("test_key")
        assert result is not None
        assert result["headline"] == "cached"

    def test_cache_miss_after_eviction(self):
        import time
        from backend.services.pre_confirm_insight import _cache_set, _cache_get, _insight_cache

        _cache_set("old_key", {"headline": "old"})
        # Manually expire
        _insight_cache["old_key"] = ({"headline": "old"}, time.time() - 999)

        result = _cache_get("old_key")
        assert result is None
