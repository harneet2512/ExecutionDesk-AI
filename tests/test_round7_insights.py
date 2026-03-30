"""Tests for Round 7: Non-generic insights.

Covers:
- Insight never says 'UNKNOWN' in key_facts
- Insight includes fee estimate fields
- Insight data quality flags when price missing
- Template with 0 headlines explains why
- Insight always generated even when news_enabled=False
- Headlines referenced in why_it_matters when present
"""
import pytest
import os
from unittest.mock import patch, AsyncMock

os.environ["TEST_AUTH_BYPASS"] = "true"
os.environ["PYTEST_CURRENT_TEST"] = "test"


class TestBuildFactPack:
    """build_fact_pack produces enhanced, non-generic facts."""

    def test_insight_never_says_unknown(self):
        """build_fact_pack with change_24h_pct=None produces no 'UNKNOWN' in key_facts."""
        from backend.services.pre_confirm_insight import build_fact_pack

        price_data = {"price": 71000.0, "change_24h_pct": None, "price_source": "market_data_provider"}
        facts = build_fact_pack(
            asset="BTC", side="buy", notional_usd=5.0,
            asset_class="CRYPTO", price_data=price_data, headlines=[],
            mode="PAPER", news_enabled=False
        )

        for fact in facts["key_facts"]:
            assert "UNKNOWN" not in fact, f"Found 'UNKNOWN' in key_fact: {fact}"
        # volatility should be None, not "UNKNOWN"
        assert facts["volatility"] is None or facts["volatility"] in ("LOW", "MODERATE", "HIGH")

    def test_insight_includes_fee_estimate(self):
        """build_fact_pack returns estimated_fees_usd and fee_impact_pct."""
        from backend.services.pre_confirm_insight import build_fact_pack

        price_data = {"price": 71000.0, "change_24h_pct": 2.5, "price_source": "market_data_provider"}
        facts = build_fact_pack(
            asset="BTC", side="buy", notional_usd=10.0,
            asset_class="CRYPTO", price_data=price_data, headlines=[],
            mode="PAPER", news_enabled=False
        )

        assert "estimated_fees_usd" in facts
        assert "fee_impact_pct" in facts
        assert facts["estimated_fees_usd"] == pytest.approx(0.06, abs=0.01)
        assert facts["fee_impact_pct"] == pytest.approx(0.6, abs=0.1)

    def test_insight_data_quality_flags(self):
        """build_fact_pack with missing price returns data_quality.missing_price=True."""
        from backend.services.pre_confirm_insight import build_fact_pack

        price_data = {"price": None, "change_24h_pct": None, "price_source": "none"}
        facts = build_fact_pack(
            asset="BTC", side="buy", notional_usd=5.0,
            asset_class="CRYPTO", price_data=price_data, headlines=[],
            mode="PAPER", news_enabled=True
        )

        assert "data_quality" in facts
        assert facts["data_quality"]["missing_price"] is True
        assert facts["data_quality"]["missing_change"] is True
        assert facts["data_quality"]["stale_data"] is True


class TestTemplateInsight:
    """Template-based insight is context-aware."""

    def test_insight_no_headlines_explanation(self):
        """Template with 0 headlines says 'No headlines pulled' not just '0 headlines'."""
        from backend.services.pre_confirm_insight import _template_why_it_matters

        facts = {
            "asset": "BTC", "side": "buy", "notional_usd": 5.0,
            "change_24h_pct": None, "volatility": None,
            "headlines": [], "top_headlines": [],
            "news_enabled": True, "live_allowed": True,
            "mode": "PAPER", "estimated_fees_usd": 0.03,
            "fee_impact_pct": 0.6, "data_quality": {
                "headlines_fetch_failed": False,
            },
        }
        result = _template_why_it_matters(facts)
        assert "No headlines pulled" in result or "no results" in result, \
            f"Expected explanation for missing headlines, got: {result}"
        assert "0 headlines" not in result, \
            f"Should not use bare '0 headlines' format, got: {result}"

    def test_insight_headline_no_unknown(self):
        """_template_headline never outputs 'UNKNOWN'."""
        from backend.services.pre_confirm_insight import _template_headline

        facts = {
            "asset": "BTC", "change_24h_pct": None, "price": 71000.0,
            "headlines": [], "top_headlines": [],
            "live_allowed": True, "mode": "PAPER",
            "news_enabled": True,
        }
        result = _template_headline(facts)
        assert "UNKNOWN" not in result, f"Found 'UNKNOWN' in headline: {result}"


class TestInsightGeneration:
    """Insight generation always produces output."""

    @pytest.mark.asyncio
    async def test_insight_always_generated(self):
        """Insight is produced even when news_enabled=False."""
        from backend.services.pre_confirm_insight import generate_insight

        # Mock price fetch to avoid network call
        with patch("backend.services.pre_confirm_insight._fetch_price_data", new_callable=AsyncMock) as mock_price:
            mock_price.return_value = {
                "price": 71000.0,
                "change_24h_pct": 1.5,
                "price_source": "mock"
            }
            result = await generate_insight(
                asset="BTC", side="buy", notional_usd=5.0,
                asset_class="CRYPTO", news_enabled=False,
                mode="PAPER", request_id="test_123"
            )

        assert result is not None
        assert "headline" in result
        assert "why_it_matters" in result
        assert "key_facts" in result
        assert len(result["key_facts"]) > 0

    @pytest.mark.asyncio
    async def test_insight_headlines_in_why_it_matters(self):
        """When headlines exist, why_it_matters references headline theme."""
        from backend.services.pre_confirm_insight import generate_insight

        mock_headlines = [
            {"title": "Bitcoin ETF inflows hit record high", "published_at": "2024-01-01T00:00:00", "source": "CoinDesk"},
            {"title": "Crypto market rally continues", "published_at": "2024-01-01T00:00:00", "source": "Reuters"},
        ]

        with patch("backend.services.pre_confirm_insight._fetch_price_data", new_callable=AsyncMock) as mock_price, \
             patch("backend.services.pre_confirm_insight._fetch_headlines", return_value=(mock_headlines, False, "")):
            mock_price.return_value = {
                "price": 71000.0,
                "change_24h_pct": 3.2,
                "price_source": "mock"
            }
            result = await generate_insight(
                asset="BTC", side="buy", notional_usd=10.0,
                asset_class="CRYPTO", news_enabled=True,
                mode="PAPER", request_id="test_456"
            )

        assert result is not None
        wim = result["why_it_matters"]
        # Should reference headline content (may be paraphrased by LLM)
        assert "headlines" in wim.lower() or "Bitcoin ETF" in wim or "ETF" in wim or "inflow" in wim.lower(), \
            f"Expected headline reference in why_it_matters: {wim}"
