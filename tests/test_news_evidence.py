import pytest

from backend.services.news_evidence import build_news_evidence_from_insight


def test_news_evidence_status_ok():
    insight = {
        "sources": {
            "headlines": [
                {"title": "Bitcoin rises", "source": "CoinDesk", "published_at": "2026-01-01T00:00:00Z", "url": "https://x", "rationale": "market momentum"}
            ]
        }
    }
    out = build_news_evidence_from_insight("BTC", insight)
    assert out["status"] == "ok"
    assert len(out["items"]) == 1
    assert out["queries"][:2] == ["Bitcoin", "BTC"]


def test_news_evidence_status_empty():
    out = build_news_evidence_from_insight("BTC", {"sources": {"headlines": []}})
    assert out["status"] == "empty"
    assert out["reason_if_empty_or_error"]


def test_news_evidence_status_error():
    out = build_news_evidence_from_insight("BTC", {"sources": {"headlines": []}}, provider_error="provider timeout")
    assert out["status"] == "error"
    assert "timeout" in out["reason_if_empty_or_error"]
