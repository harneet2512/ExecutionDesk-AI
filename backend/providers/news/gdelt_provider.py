import httpx
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from backend.core.logging import get_logger

logger = get_logger(__name__)

# Circuit breaker state
_consecutive_failures = 0
_circuit_open_until = 0.0
CIRCUIT_BREAKER_THRESHOLD = 3
CIRCUIT_BREAKER_COOLDOWN = 300  # 5 minutes


class GDELTProvider:
    """
    Provider to query GDELT DOC 2.0 API.
    FREE, strict rate limits apply.
    Includes circuit breaker: after 3 consecutive failures, skip for 5 minutes.
    """
    BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(self, timeout_seconds: int = 20):
        self.timeout = timeout_seconds

    async def search(self, source_id: str, query: str, window_hours: int = 24) -> List[Dict[str, Any]]:
        """
        Search GDELT for news items.
        query: 'bitcoin', 'ethereum', etc.
        Returns list of normalised items + sets structured error on failure.
        """
        global _consecutive_failures, _circuit_open_until

        # Circuit breaker check
        if _consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD and time.time() < _circuit_open_until:
            logger.info(
                "GDELT circuit breaker OPEN (failures=%d, reopens in %ds)",
                _consecutive_failures, int(_circuit_open_until - time.time()),
            )
            return []

        items = []
        try:
            params = {
                "query": f"{query} sourcecountry:US sourcelang:eng",
                "mode": "ArtList",
                "format": "json",
                "maxrecords": "50",
                "timespan": f"{window_hours}h"
            }
            
            url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                if response.status_code == 429:
                    _consecutive_failures += 1
                    _circuit_open_until = time.time() + CIRCUIT_BREAKER_COOLDOWN
                    logger.warning("GDELT 429 rate limited for '%s' (failures=%d)", query, _consecutive_failures)
                    return []
                response.raise_for_status()
                data = response.json()

            if "articles" in data:
                for article in data["articles"]:
                    normalized = self._normalize_article(source_id, article)
                    if normalized:
                        items.append(normalized)

            # Success — reset circuit breaker
            _consecutive_failures = 0

        except Exception as e:
            _consecutive_failures += 1
            if _consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
                _circuit_open_until = time.time() + CIRCUIT_BREAKER_COOLDOWN
            logger.error("GDELT query failed for '%s' (failures=%d): %s", query, _consecutive_failures, str(e)[:200])
        
        return items

    def _normalize_article(self, source_id: str, article: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normalize GDELT article."""
        try:
            title = article.get("title", "").strip()
            url = article.get("url", "")
            if not title or not url:
                return None

            # GDELT date format: "20240520T123000Z"
            seendate = article.get("seendate")
            published_at = datetime.utcnow().isoformat()
            if seendate:
                try:
                    dt = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ")
                    published_at = dt.isoformat()
                except ValueError:
                    pass

            # Content hash
            import hashlib
            hash_input = f"{title}|{url}".encode('utf-8')
            content_hash = hashlib.sha256(hash_input).hexdigest()

            return {
                "source_id": source_id,
                "title": title,
                "url": url,
                "canonical_url": url,
                "published_at": published_at,
                "summary": "", # GDELT list doesn't give summaries, strictly headers
                "content_hash": content_hash,
                "raw_payload_json": str(article),
                "lang": article.get("language", "English"),
                "domain": article.get("domain", "")
            }

        except Exception as e:
            logger.warning(f"Error normalizing GDELT article: {e}")
            return None
