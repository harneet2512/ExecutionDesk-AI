import feedparser
import httpx
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import List, Optional, Dict, Any
from backend.core.logging import get_logger

logger = get_logger(__name__)

class RSSProvider:
    """
    Provider to fetch and normalize news from RSS/Atom feeds.
    Strictly free, no API keys required.
    """

    def __init__(self, timeout_seconds: int = 10):
        self.timeout = timeout_seconds
        # Common user agent to avoid strict blocking
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; AgenticTradingPlatform/1.0; +http://localhost)"
        }

    async def fetch(self, source_id: str, url: str) -> List[Dict[str, Any]]:
        """
        Fetch feed items from a URL.
        Returns a list of normalized news items.
        Per-source error handling: one bad feed won't break all.
        """
        items = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(url, headers=self.headers)
                response.raise_for_status()
                content = response.text

            feed = feedparser.parse(content)
            
            if feed.bozo:
                logger.warning(f"RSS Parse warning for {url}: {feed.bozo_exception}")

            for entry in feed.entries:
                try:
                    normalized = self._normalize_entry(source_id, entry, url)
                    if normalized:
                        items.append(normalized)
                except Exception as entry_err:
                    logger.debug("Skipping RSS entry from %s: %s", url, str(entry_err)[:100])

        except httpx.TimeoutException:
            logger.warning("RSS feed timeout for %s (non-fatal, skipping)", url)
        except httpx.HTTPStatusError as e:
            logger.warning("RSS feed HTTP %d for %s (non-fatal)", e.response.status_code, url)
        except Exception as e:
            logger.error("RSS feed failed for %s: %s", url, str(e)[:200])
        
        return items

    def _normalize_entry(self, source_id: str, entry: Any, feed_url: str) -> Optional[Dict[str, Any]]:
        """Normalize a feedparser entry into our internal Dict format."""
        try:
            # Title
            title = getattr(entry, "title", "").strip()
            if not title:
                return None

            # Link
            link = getattr(entry, "link", "")
            if not link:
                return None

            # Published Date
            published_at = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published_at = datetime(*entry.published_parsed[:6]).isoformat()
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                published_at = datetime(*entry.updated_parsed[:6]).isoformat()
            else:
                # Fallback to now if missing, though ideally we skip or use retrieved_at
                published_at = datetime.utcnow().isoformat()

            # Summary (prefer summary, then description)
            summary = getattr(entry, "summary", "")
            if not summary:
                summary = getattr(entry, "description", "")

            # Content hash (simple dedup key)
            import hashlib
            hash_input = f"{title}|{link}".encode('utf-8')
            content_hash = hashlib.sha256(hash_input).hexdigest()

            return {
                "source_id": source_id,
                "title": title,
                "url": link,
                "canonical_url": link, # RSS usually gives the direct link
                "published_at": published_at,
                "summary": summary,
                "content_hash": content_hash,
                "raw_payload_json": str(entry), # Store full entry for debugging
                "lang": "en", # Assumption, logic can be improved
            }

        except Exception as e:
            logger.warning(f"Error normalizing RSS entry from {feed_url}: {e}")
            return None
