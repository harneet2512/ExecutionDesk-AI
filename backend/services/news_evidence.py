from __future__ import annotations

from typing import Any, Dict, List

from backend.services.news_smart import build_adaptive_queries


def build_news_query_terms(asset_symbol: str) -> List[str]:
    return build_adaptive_queries(asset_symbol, lookback_hours=24).queries


def build_news_evidence_from_insight(
    asset_symbol: str,
    insight: Dict[str, Any] | None,
    *,
    lookback: str = "24h",
    sources: List[str] | None = None,
    provider_error: str | None = None,
) -> Dict[str, Any]:
    srcs = sources or ["RSS", "GDELT"]
    queries = build_news_query_terms(asset_symbol)
    raw_items = ((insight or {}).get("sources") or {}).get("headlines") or []
    items: List[Dict[str, Any]] = []
    for h in raw_items:
        if isinstance(h, dict):
            items.append(
                {
                    "title": h.get("title"),
                    "source": h.get("source"),
                    "published_at": h.get("published_at"),
                    "url": h.get("url"),
                    "snippet": h.get("rationale"),
                }
            )
    if provider_error:
        status = "error"
        reason = provider_error
    elif len(items) == 0:
        status = "empty"
        reason = "No relevant news found for requested asset in lookback window"
    else:
        status = "ok"
        reason = ""
    return {
        "assets": [asset_symbol],
        "queries": queries,
        "lookback": lookback,
        "sources": srcs,
        "items": items[:5],
        "status": status,
        "reason_if_empty_or_error": reason,
    }


def build_market_news_evidence(
    *,
    queries: List[str],
    lookback: str = "24h",
    sources: List[str] | None = None,
    status: str = "ok",
    reason_if_empty_or_error: str = "",
    rationale: str = "",
    items: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    payload_items = (items or [])[:5]
    return {
        "queries": queries,
        "lookback": lookback,
        "sources": sources or ["RSS", "GDELT"],
        "status": status,
        "items": payload_items,
        "reason_if_empty_or_error": reason_if_empty_or_error,
        "rationale": rationale,
    }
