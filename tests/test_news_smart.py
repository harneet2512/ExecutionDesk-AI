from backend.services.news_smart import (
    build_adaptive_queries,
    classify_asset,
    select_fallback_queries,
)


def test_classify_asset_btc():
    assert classify_asset("BTC") == "MAJOR"


def test_classify_asset_unknown_symbol():
    assert classify_asset("XYZ123") == "UNKNOWN"


def test_build_adaptive_queries_btc():
    result = build_adaptive_queries("BTC")
    assert "BTC" in result.queries
    assert "BTC-USD" in result.queries
    assert "Bitcoin" in result.queries


def test_build_adaptive_queries_unknown():
    result = build_adaptive_queries("ABC")
    assert result.queries[:2] == ["ABC", "ABC-USD"]


def test_select_fallback_btc():
    result = select_fallback_queries("BTC", "MAJOR")
    assert "crypto market" in result.queries
    assert "bitcoin ETF" in result.queries
    assert "Fed rates" in result.queries


def test_select_fallback_meme():
    result = select_fallback_queries("DOGE", "MEME_SMALLCAP")
    assert "meme coin market" in result.queries
    assert "altcoin market" in result.queries


def test_fallback_rationale_not_empty():
    result = select_fallback_queries("BTC", "MAJOR")
    assert result.rationale
    assert "BTC" in result.rationale
