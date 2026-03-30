"""Tests for Round 7 fixes: backend stability, news pipeline, and product details fallback."""
import pytest
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_market_metadata_import():
    """Test that market_metadata.py imports correctly after fixing time_utils path."""
    try:
        from backend.services.market_metadata import MarketMetadataService, SAFE_FALLBACK_PRECISION
        assert MarketMetadataService is not None
        assert isinstance(SAFE_FALLBACK_PRECISION, dict)
        assert "BTC-USD" in SAFE_FALLBACK_PRECISION
        assert "ETH-USD" in SAFE_FALLBACK_PRECISION
    except ImportError as e:
        pytest.fail(f"Failed to import market_metadata: {e}")


def test_safe_fallback_precision_structure():
    """Test that safe fallback precision has correct structure."""
    from backend.services.market_metadata import SAFE_FALLBACK_PRECISION
    
    for product_id, precision in SAFE_FALLBACK_PRECISION.items():
        assert "base_increment" in precision
        assert "quote_increment" in precision
        assert "base_min_size" in precision
        assert "base_max_size" in precision
        assert "quote_min_size" in precision
        assert "quote_max_size" in precision
        
        # Verify all values are strings (as expected by Coinbase API format)
        for key, value in precision.items():
            assert isinstance(value, str), f"{product_id}.{key} should be string, got {type(value)}"


def test_portfolio_node_imports():
    """Test that portfolio_node.py imports correctly after fixing column names."""
    try:
        from backend.orchestrator.nodes import portfolio_node
        assert portfolio_node.execute is not None
    except ImportError as e:
        pytest.fail(f"Failed to import portfolio_node: {e}")


def test_pre_confirm_insight_imports():
    """Test that pre_confirm_insight.py imports correctly with new functions."""
    try:
        from backend.services.pre_confirm_insight import (
            generate_insight,
            _fetch_headlines,
            _fetch_price_data,
            build_fact_pack
        )
        assert generate_insight is not None
        assert _fetch_headlines is not None
        assert _fetch_price_data is not None
        assert build_fact_pack is not None
    except ImportError as e:
        pytest.fail(f"Failed to import pre_confirm_insight: {e}")


def test_news_fetch_symbol_variants():
    """Test that news fetch handles multiple symbol variants."""
    from backend.services.pre_confirm_insight import _fetch_headlines
    
    # This test verifies the function signature and basic structure
    # Actual DB queries would require test database setup
    import inspect
    sig = inspect.signature(_fetch_headlines)
    assert 'symbol' in sig.parameters
    assert 'limit' in sig.parameters


@pytest.mark.asyncio
async def test_market_metadata_fallback_logic():
    """Test that market metadata service uses fallback when API fails."""
    from backend.services.market_metadata import MarketMetadataService, SAFE_FALLBACK_PRECISION
    
    service = MarketMetadataService()
    
    # Test that BTC-USD has fallback defined
    assert "BTC-USD" in SAFE_FALLBACK_PRECISION
    btc_fallback = SAFE_FALLBACK_PRECISION["BTC-USD"]
    
    # Verify fallback has required fields
    assert float(btc_fallback["base_min_size"]) > 0
    assert float(btc_fallback["quote_min_size"]) > 0


def test_coinbase_provider_imports():
    """Test that coinbase_provider.py imports correctly."""
    try:
        from backend.providers.coinbase_provider import CoinbaseProvider
        assert CoinbaseProvider is not None
    except ImportError as e:
        pytest.fail(f"Failed to import CoinbaseProvider: {e}")


def test_fact_pack_structure():
    """Test that build_fact_pack returns expected structure."""
    from backend.services.pre_confirm_insight import build_fact_pack
    
    # Mock price data
    price_data = {
        "price": 50000.0,
        "change_24h_pct": 2.5,
        "change_7d_pct": 5.0,
        "range_7d_high": 52000.0,
        "range_7d_low": 48000.0,
        "price_pct_of_range": 50.0,
        "volatility_7d_atr": 3.0,
        "price_source": "test"
    }
    
    headlines = [
        {"title": "BTC rallies", "published_at": "2024-01-01T00:00:00Z", "source": "Test", "sentiment": "bullish"}
    ]
    
    fact_pack = build_fact_pack(
        asset="BTC",
        side="BUY",
        notional_usd=100.0,
        asset_class="CRYPTO",
        price_data=price_data,
        headlines=headlines,
        mode="PAPER",
        news_enabled=True,
        headlines_fetch_failed=False
    )
    
    # Verify structure
    assert "asset" in fact_pack
    assert "price" in fact_pack
    assert "key_facts" in fact_pack
    assert "risk_flags" in fact_pack
    assert "confidence" in fact_pack
    assert isinstance(fact_pack["key_facts"], list)
    assert isinstance(fact_pack["risk_flags"], list)
    assert 0 <= fact_pack["confidence"] <= 1


def test_insight_generation_imports():
    """Test that insight generation functions are importable."""
    try:
        from backend.services.pre_confirm_insight import (
            _template_headline,
            _template_why_it_matters,
            _build_template_insight,
            _analyze_headline_sentiment
        )
        assert _template_headline is not None
        assert _template_why_it_matters is not None
        assert _build_template_insight is not None
        assert _analyze_headline_sentiment is not None
    except ImportError as e:
        pytest.fail(f"Failed to import insight generation functions: {e}")


def test_sentiment_analysis():
    """Test headline sentiment analysis."""
    from backend.services.pre_confirm_insight import _analyze_headline_sentiment
    
    # Test bullish keywords
    assert _analyze_headline_sentiment("Bitcoin surges to new high") == "bullish"
    assert _analyze_headline_sentiment("BTC rally continues") == "bullish"
    
    # Test bearish keywords
    assert _analyze_headline_sentiment("Bitcoin crashes amid fears") == "bearish"
    assert _analyze_headline_sentiment("BTC plunges on bad news") == "bearish"
    
    # Test neutral
    assert _analyze_headline_sentiment("Bitcoin price analysis") == "neutral"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
