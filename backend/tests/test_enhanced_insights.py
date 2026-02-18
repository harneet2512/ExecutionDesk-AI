"""Unit tests for enhanced insight generation."""
import pytest
from backend.services.pre_confirm_insight import (
    build_fact_pack,
    _analyze_headline_sentiment,
    _template_headline,
    _template_why_it_matters
)


def test_analyze_headline_sentiment_bullish():
    """Test sentiment analysis identifies bullish headlines."""
    headlines = [
        "Bitcoin surges to new all-time high",
        "BTC rally continues with strong gains",
        "Crypto market sees bullish breakout"
    ]

    for headline in headlines:
        result = _analyze_headline_sentiment(headline)
        assert result["sentiment"] == "bullish", f"Expected bullish for: {headline}"
        assert 0 < result["confidence"] <= 1.0
        assert result["driver"] != "none"
        # Rationale should quote 3-10 words from the headline
        assert result["rationale"], f"Missing rationale for: {headline}"
        assert len(result["rationale"].split()) >= 3, f"Rationale too short for: {headline}"
        assert len(result["rationale"].split()) <= 10, f"Rationale too long for: {headline}"
        # Rationale words should come from the headline
        for word in result["rationale"].split()[:3]:
            assert word.lower().rstrip(",.!?") in headline.lower(), \
                f"Rationale word '{word}' not in headline: {headline}"


def test_analyze_headline_sentiment_bearish():
    """Test sentiment analysis identifies bearish headlines."""
    headlines = [
        "Bitcoin crashes below key support",
        "Crypto market plunges amid fears",
        "BTC drops 10% in massive sell-off"
    ]

    for headline in headlines:
        result = _analyze_headline_sentiment(headline)
        assert result["sentiment"] == "bearish", f"Expected bearish for: {headline}"
        assert 0 < result["confidence"] <= 1.0
        assert result["driver"] != "none"
        # Rationale should quote from headline
        assert result["rationale"], f"Missing rationale for: {headline}"
        assert len(result["rationale"].split()) >= 3


def test_analyze_headline_sentiment_neutral():
    """Test sentiment analysis identifies neutral headlines."""
    headlines = [
        "Bitcoin trading sideways today",
        "Crypto market awaits Fed decision",
        "BTC holds steady at current levels"
    ]

    for headline in headlines:
        result = _analyze_headline_sentiment(headline)
        assert result["sentiment"] == "neutral", f"Expected neutral for: {headline}"
        assert result["confidence"] == 0.0
        assert result["driver"] in ("none", "mixed")
        # Even neutral headlines should have a rationale (full headline)
        assert result["rationale"], f"Missing rationale for: {headline}"


def test_build_fact_pack_with_range_context():
    """Test fact pack includes 7d range context."""
    price_data = {
        "price": 50000,
        "change_24h_pct": 2.5,
        "change_7d_pct": 5.0,
        "range_7d_high": 52000,
        "range_7d_low": 48000,
        "price_pct_of_range": 50.0,
        "volatility_7d_atr": 3.5,
        "price_source": "market_data_provider"
    }
    
    headlines = [
        {"title": "BTC surges", "sentiment": "bullish", "published_at": "2024-01-01", "source": "Test"}
    ]
    
    facts = build_fact_pack(
        asset="BTC",
        side="BUY",
        notional_usd=100,
        asset_class="CRYPTO",
        price_data=price_data,
        headlines=headlines
    )
    
    assert facts["range_7d_high"] == 52000
    assert facts["range_7d_low"] == 48000
    assert facts["price_pct_of_range"] == 50.0
    assert facts["range_position"] == "mid_range"
    assert facts["volatility"] == "MODERATE"  # Based on 7d ATR
    assert "7-day range" in " ".join(facts["key_facts"])


def test_build_fact_pack_range_position_near_high():
    """Test range position correctly identifies near high."""
    price_data = {
        "price": 51500,
        "change_24h_pct": 2.5,
        "range_7d_high": 52000,
        "range_7d_low": 48000,
        "price_pct_of_range": 87.5,  # (51500-48000)/(52000-48000) * 100
        "volatility_7d_atr": 2.0,
        "price_source": "market_data_provider"
    }
    
    facts = build_fact_pack(
        asset="BTC",
        side="SELL",
        notional_usd=100,
        asset_class="CRYPTO",
        price_data=price_data,
        headlines=[]
    )
    
    assert facts["range_position"] == "near_high"
    assert "near 7d high" in " ".join(facts["key_facts"])


def test_build_fact_pack_range_position_near_low():
    """Test range position correctly identifies near low."""
    price_data = {
        "price": 48200,
        "change_24h_pct": -2.5,
        "range_7d_high": 52000,
        "range_7d_low": 48000,
        "price_pct_of_range": 5.0,  # (48200-48000)/(52000-48000) * 100
        "volatility_7d_atr": 2.0,
        "price_source": "market_data_provider"
    }
    
    facts = build_fact_pack(
        asset="BTC",
        side="BUY",
        notional_usd=100,
        asset_class="CRYPTO",
        price_data=price_data,
        headlines=[]
    )
    
    assert facts["range_position"] == "near_low"
    assert "near 7d low" in " ".join(facts["key_facts"])


def test_build_fact_pack_sentiment_distribution():
    """Test sentiment distribution calculation."""
    headlines = [
        {"title": "BTC surges", "sentiment": "bullish", "published_at": "2024-01-01", "source": "Test"},
        {"title": "BTC rallies", "sentiment": "bullish", "published_at": "2024-01-01", "source": "Test"},
        {"title": "BTC drops", "sentiment": "bearish", "published_at": "2024-01-01", "source": "Test"},
        {"title": "BTC stable", "sentiment": "neutral", "published_at": "2024-01-01", "source": "Test"}
    ]
    
    price_data = {
        "price": 50000,
        "change_24h_pct": 2.5,
        "price_source": "market_data_provider"
    }
    
    facts = build_fact_pack(
        asset="BTC",
        side="BUY",
        notional_usd=100,
        asset_class="CRYPTO",
        price_data=price_data,
        headlines=headlines,
        news_enabled=True
    )
    
    assert facts["sentiment_counts"]["bullish"] == 2
    assert facts["sentiment_counts"]["bearish"] == 1
    assert facts["sentiment_counts"]["neutral"] == 1
    assert "2 bullish" in facts["headline_sentiment_summary"]
    assert "1 bearish" in facts["headline_sentiment_summary"]


def test_template_headline_with_range_context():
    """Test headline template includes range context."""
    facts = {
        "asset": "BTC",
        "change_24h_pct": 3.5,
        "price": 50000,
        "range_position": "near_high",
        "headlines": [],
        "top_headlines": [],
        "live_allowed": True,
        "mode": "PAPER",
        "news_enabled": False
    }
    
    headline = _template_headline(facts)
    
    assert "BTC up 3.5% in 24h, near 7d high" in headline


def test_template_why_it_matters_buy_near_low():
    """Test BUY insight near 7d low mentions dip buying."""
    facts = {
        "asset": "BTC",
        "side": "BUY",
        "notional_usd": 100,
        "change_24h_pct": -3.0,
        "range_position": "near_low",
        "price_pct_of_range": 10.0,
        "volatility": "MODERATE",
        "estimated_fees_usd": 0.60,
        "fee_impact_pct": 0.6,
        "headlines": [],
        "top_headlines": [],
        "news_enabled": False,
        "live_allowed": True,
        "mode": "PAPER"
    }
    
    why_it_matters = _template_why_it_matters(facts)
    
    assert "near its 7-day low" in why_it_matters
    assert "dip" in why_it_matters.lower() or "falling knife" in why_it_matters.lower()


def test_template_why_it_matters_sell_near_high():
    """Test SELL insight near 7d high mentions profit taking."""
    facts = {
        "asset": "BTC",
        "side": "SELL",
        "notional_usd": 100,
        "change_24h_pct": 4.0,
        "range_position": "near_high",
        "price_pct_of_range": 90.0,
        "volatility": "MODERATE",
        "estimated_fees_usd": 0.60,
        "fee_impact_pct": 0.6,
        "headlines": [],
        "top_headlines": [],
        "news_enabled": False,
        "live_allowed": True,
        "mode": "PAPER"
    }
    
    why_it_matters = _template_why_it_matters(facts)
    
    assert "near its 7-day high" in why_it_matters
    assert "profit" in why_it_matters.lower() or "strength" in why_it_matters.lower()


def test_template_why_it_matters_buy_vs_sell_different():
    """Test BUY and SELL insights are different for same conditions."""
    base_facts = {
        "asset": "BTC",
        "notional_usd": 100,
        "change_24h_pct": 3.0,
        "range_position": "mid_range",
        "price_pct_of_range": 50.0,
        "volatility": "MODERATE",
        "estimated_fees_usd": 0.60,
        "fee_impact_pct": 0.6,
        "headlines": [],
        "top_headlines": [],
        "news_enabled": False,
        "live_allowed": True,
        "mode": "PAPER"
    }
    
    buy_facts = {**base_facts, "side": "BUY"}
    sell_facts = {**base_facts, "side": "SELL"}
    
    buy_insight = _template_why_it_matters(buy_facts)
    sell_insight = _template_why_it_matters(sell_facts)
    
    assert buy_insight != sell_insight
    assert "buying" in buy_insight.lower()
    assert "selling" in sell_insight.lower()


def test_template_why_it_matters_with_sentiment():
    """Test insight includes sentiment context."""
    facts = {
        "asset": "BTC",
        "side": "BUY",
        "notional_usd": 100,
        "change_24h_pct": 2.0,
        "volatility": "MODERATE",
        "estimated_fees_usd": 0.60,
        "fee_impact_pct": 0.6,
        "headlines": [
            {"title": "BTC crashes", "sentiment": "bearish"},
            {"title": "BTC drops", "sentiment": "bearish"}
        ],
        "top_headlines": ["BTC crashes"],
        "headline_sentiment_summary": "2 bearish",
        "sentiment_counts": {"bullish": 0, "bearish": 2, "neutral": 0},
        "news_enabled": True,
        "live_allowed": True,
        "mode": "PAPER"
    }
    
    why_it_matters = _template_why_it_matters(facts)
    
    assert "2 bearish" in why_it_matters
    assert "bearish sentiment" in why_it_matters.lower()
    assert "contrarian" in why_it_matters.lower() or "risky" in why_it_matters.lower()


def test_volatility_calculation_uses_7d_atr():
    """Test volatility uses 7d ATR when available."""
    price_data = {
        "price": 50000,
        "change_24h_pct": 1.0,  # Would be LOW
        "volatility_7d_atr": 6.0,  # Should be HIGH
        "price_source": "market_data_provider"
    }
    
    facts = build_fact_pack(
        asset="BTC",
        side="BUY",
        notional_usd=100,
        asset_class="CRYPTO",
        price_data=price_data,
        headlines=[]
    )
    
    # Should use 7d ATR (6.0) which is HIGH, not 24h change (1.0) which would be LOW
    assert facts["volatility"] == "HIGH"


def test_volatility_fallback_to_24h_change():
    """Test volatility falls back to 24h change when 7d ATR unavailable."""
    price_data = {
        "price": 50000,
        "change_24h_pct": 3.0,  # MODERATE
        "volatility_7d_atr": None,  # Not available
        "price_source": "market_data_provider"
    }
    
    facts = build_fact_pack(
        asset="BTC",
        side="BUY",
        notional_usd=100,
        asset_class="CRYPTO",
        price_data=price_data,
        headlines=[]
    )
    
    # Should fall back to 24h change
    assert facts["volatility"] == "MODERATE"


def test_insight_with_zero_headlines_non_generic():
    """Test insight with 0 headlines still provides strong market context."""
    price_data = {
        "price": 50000,
        "change_24h_pct": 3.5,
        "change_7d_pct": 8.0,
        "range_7d_high": 52000,
        "range_7d_low": 48000,
        "price_pct_of_range": 50.0,
        "volatility_7d_atr": 4.0,
        "price_source": "market_data_provider"
    }
    
    facts = build_fact_pack(
        asset="BTC",
        side="BUY",
        notional_usd=100,
        asset_class="CRYPTO",
        price_data=price_data,
        headlines=[],  # No headlines
        news_enabled=True
    )
    
    # Should have strong insights despite no headlines
    assert facts["change_24h_pct"] == 3.5
    assert facts["change_7d_pct"] == 8.0
    assert facts["range_7d_high"] is not None
    assert facts["volatility"] is not None
    assert len(facts["key_facts"]) >= 4  # Should have multiple facts
    
    # Key facts should NOT be generic "fees matter" only
    key_facts_text = " ".join(facts["key_facts"])
    assert "24h" in key_facts_text or "7-day" in key_facts_text
    assert "range" in key_facts_text.lower() or "volatility" in key_facts_text.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
