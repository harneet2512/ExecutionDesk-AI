from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal

from backend.db.connect import get_conn

AssetCategory = Literal["MAJOR", "L1_ALT", "L2_ECOSYSTEM", "MEME_SMALLCAP", "UNKNOWN"]


@dataclass(frozen=True)
class AdaptiveQueryResult:
    symbol: str
    queries: List[str]
    lookback_hours: int


@dataclass(frozen=True)
class FallbackQuerySet:
    category: AssetCategory
    queries: List[str]
    rationale: str


CANONICAL_NAME_MAP: Dict[str, str] = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
    "ADA": "Cardano",
    "XRP": "XRP",
    "DOGE": "Dogecoin",
    "SHIB": "Shiba Inu",
    "PEPE": "Pepe",
    "MATIC": "Polygon",
    "ARB": "Arbitrum",
    "OP": "Optimism",
    "AVAX": "Avalanche",
    "DOT": "Polkadot",
    "LINK": "Chainlink",
    "UNI": "Uniswap",
    "ATOM": "Cosmos",
    "LTC": "Litecoin",
    "BCH": "Bitcoin Cash",
    "SUI": "Sui",
    "TRX": "TRON",
}

COMMON_SYNONYMS: Dict[str, List[str]] = {
    "BTC": ["Bitcoin", "bitcoin"],
    "ETH": ["Ethereum", "Ether", "ethereum"],
    "SOL": ["Solana", "solana"],
    "DOGE": ["Dogecoin", "doge"],
    "SHIB": ["Shiba Inu", "shib"],
}

L1_ALT_SYMBOLS = {"SOL", "ADA", "DOT", "AVAX", "ATOM", "TRX", "SUI", "LTC", "BCH", "XRP", "LINK"}
L2_ECOSYSTEM_SYMBOLS = {"ARB", "OP", "MATIC", "IMX", "STRK"}
MEME_SYMBOLS = {"DOGE", "SHIB", "PEPE", "BONK", "WIF", "FLOKI"}


def _normalize_symbol(symbol: str) -> str:
    return (symbol or "").upper().replace("-USD", "").strip()


def classify_asset(symbol: str) -> AssetCategory:
    normalized = _normalize_symbol(symbol)
    if normalized in {"BTC", "ETH"}:
        return "MAJOR"
    if normalized in MEME_SYMBOLS:
        return "MEME_SMALLCAP"
    if normalized in L2_ECOSYSTEM_SYMBOLS:
        return "L2_ECOSYSTEM"
    if normalized in L1_ALT_SYMBOLS:
        return "L1_ALT"
    return "UNKNOWN"


def build_adaptive_queries(symbol: str, lookback_hours: int = 24) -> AdaptiveQueryResult:
    normalized = _normalize_symbol(symbol)
    query_candidates: List[str] = [normalized, f"{normalized}-USD"] if normalized else []

    canonical = CANONICAL_NAME_MAP.get(normalized)
    if canonical:
        query_candidates.append(canonical)

    for synonym in COMMON_SYNONYMS.get(normalized, []):
        query_candidates.append(synonym)

    # Keep order deterministic while removing duplicates and empties.
    seen = set()
    queries: List[str] = []
    for item in query_candidates:
        key = (item or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        queries.append(item.strip())

    return AdaptiveQueryResult(symbol=normalized, queries=queries, lookback_hours=lookback_hours)


def select_fallback_queries(symbol: str, category: AssetCategory) -> FallbackQuerySet:
    normalized = _normalize_symbol(symbol)
    if category == "MAJOR":
        queries = [
            "crypto market",
            "bitcoin ETF",
            "Fed rates",
            "risk-on assets",
            "US CPI",
            "liquidity",
            "exchange flows",
        ]
    elif category == "MEME_SMALLCAP":
        queries = [
            "altcoin market",
            "meme coin market",
            "Solana ecosystem",
            "on-chain activity",
            "crypto market sentiment",
        ]
    elif category == "L2_ECOSYSTEM":
        queries = [
            "layer 2 scaling",
            "Ethereum ecosystem",
            "L2 fees",
            "crypto market",
        ]
    else:
        queries = [
            "altcoin market",
            "crypto market",
            "DeFi",
            "market sentiment",
        ]

    rationale = (
        f"No asset-specific headlines returned, so I'm showing broader market headlines most likely "
        f"to impact {normalized or symbol}."
    )
    return FallbackQuerySet(category=category, queries=queries, rationale=rationale)


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def rank_headlines(items: List[Dict[str, Any]], query_terms: List[str], limit: int = 5) -> List[Dict[str, Any]]:
    query_tokens = [q.lower() for q in query_terms if q]
    now = datetime.utcnow()
    ranked: List[tuple[float, Dict[str, Any]]] = []
    for item in items:
        title = str(item.get("title") or "")
        published_at = str(item.get("published_at") or "")
        relevance_hits = sum(1 for token in query_tokens if token in title.lower())
        recency_boost = 0.0
        try:
            dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            age_hours = max((now - dt.replace(tzinfo=None)).total_seconds() / 3600.0, 0.0)
            recency_boost = max(0.0, 24.0 - age_hours) / 24.0
        except Exception:
            recency_boost = 0.0
        score = (relevance_hits * 2.0) + recency_boost
        ranked.append((score, item))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in ranked[:limit]]


def fetch_market_fallback(queries: List[str], lookback_hours: int = 24, limit: int = 5) -> List[Dict[str, Any]]:
    if not queries:
        return []
    cutoff = (datetime.utcnow() - timedelta(hours=lookback_hours)).isoformat()
    sql_like = " OR ".join(["LOWER(ni.title) LIKE ?"] * len(queries))
    params = [f"%{q.lower()}%" for q in queries] + [cutoff]
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT ni.title, ni.url, ni.published_at, COALESCE(ns.name, 'Unknown') AS source_name
            FROM news_items ni
            LEFT JOIN news_sources ns ON ns.id = ni.source_id
            WHERE ({sql_like})
              AND ni.published_at >= ?
            ORDER BY ni.published_at DESC
            LIMIT 100
            """,
            params,
        )
        rows = cursor.fetchall()

    deduped: List[Dict[str, Any]] = []
    seen_titles = set()
    for row in rows:
        normalized = _normalize_title(row["title"] if "title" in row.keys() else "")
        if not normalized or normalized in seen_titles:
            continue
        seen_titles.add(normalized)
        deduped.append(
            {
                "title": row["title"],
                "url": row["url"] if "url" in row.keys() else None,
                "published_at": row["published_at"] if "published_at" in row.keys() else "",
                "source": row["source_name"] if "source_name" in row.keys() else "Unknown",
            }
        )
    return rank_headlines(deduped, queries, limit=limit)
