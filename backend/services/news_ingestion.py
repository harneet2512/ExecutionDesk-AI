import asyncio
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any
from backend.db.connect import get_conn
from backend.core.logging import get_logger
from backend.core.ids import new_id
from backend.providers.news import RSSProvider, GDELTProvider
from backend.services.news_mapping import NewsMappingService

logger = get_logger(__name__)

class NewsIngestionService:
    def __init__(self):
        self.rss_provider = RSSProvider()
        self.gdelt_provider = GDELTProvider()
        self.mapper = NewsMappingService()

    async def ingest_all(self, run_id: str = None):
        """Run ingestion for all enabled sources.

        Returns structured diagnostics dict including per-provider status.
        """
        sources = self._get_enabled_sources()
        if not sources:
            logger.info("No enabled news sources found.")
            return {"total_new": 0, "provider_statuses": [], "sources_checked": 0}

        logger.info(f"Starting news ingestion for {len(sources)} sources.")
        
        tasks = []
        for source in sources:
            tasks.append(self._ingest_source_with_status(source, run_id))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Collect provider statuses
        total_new = 0
        provider_statuses = []
        for res in results:
            if isinstance(res, dict):
                total_new += res.get("items_count", 0)
                provider_statuses.append(res)
            elif isinstance(res, int):
                total_new += res
            elif isinstance(res, Exception):
                logger.error(f"Ingestion error: {res}")
                provider_statuses.append({
                    "provider": "unknown",
                    "status": "error",
                    "items_count": 0,
                    "error": str(res)[:200],
                })
        
        logger.info(f"Ingestion complete. Added {total_new} new items from {len(sources)} sources.")
        
        # After ingestion, run clustering (basic)
        self._cluster_recent_items()

        return {
            "total_new": total_new,
            "provider_statuses": provider_statuses,
            "sources_checked": len(sources),
        }

    async def _ingest_source(self, source: Dict[str, Any]) -> int:
        """Fetch and save items for a single source. Returns count of new items."""
        result = await self._ingest_source_with_status(source)
        return result.get("items_count", 0) if isinstance(result, dict) else 0

    async def _ingest_source_with_status(self, source: Dict[str, Any], run_id: str = None) -> Dict[str, Any]:
        """Fetch and save items with provider status tracking."""
        import time as _time
        source_id = source["id"]
        source_type = source["type"]
        source_name = source.get("name", source_id)
        url = source["url"]

        t0 = _time.time()
        status_record = {
            "provider": f"{source_type}:{source_name}",
            "source_id": source_id,
            "status": "pending",
            "items_count": 0,
            "latency_ms": 0,
            "error": None,
        }

        try:
            items = []
            if source_type == "rss":
                items = await self.rss_provider.fetch(source_id, url)
            elif source_type == "gdelt":
                items = await self.gdelt_provider.search(source_id, query=url)

            status_record["latency_ms"] = int((_time.time() - t0) * 1000)

            if not items:
                status_record["status"] = "empty"
                status_record["items_count"] = 0
            else:
                saved = self._save_items(items)
                status_record["status"] = "ok"
                status_record["items_count"] = saved

        except Exception as e:
            status_record["latency_ms"] = int((_time.time() - t0) * 1000)
            status_record["status"] = "error"
            status_record["error"] = str(e)[:200]
            logger.error("Ingestion error for %s: %s", source_name, str(e)[:200])

        # Log to news_fetch_log table
        try:
            from backend.core.time import now_iso
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO news_fetch_log
                       (fetch_id, run_id, provider, status, items_count, latency_ms, error, ts)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        new_id("nfl"), run_id, status_record["provider"],
                        status_record["status"], status_record["items_count"],
                        status_record["latency_ms"], status_record["error"], now_iso(),
                    ),
                )
                conn.commit()
        except Exception:
            pass  # Non-critical logging

        return status_record

    def _save_items(self, items: List[Dict[str, Any]]) -> int:
        """Save items to DB with dedup logic. Returns count of new items."""
        new_count = 0
        with get_conn() as conn:
            cursor = conn.cursor()
            
            for item in items:
                # content_hash check
                cursor.execute("SELECT id FROM news_items WHERE content_hash = ?", (item["content_hash"],))
                if cursor.fetchone():
                    continue

                # canonical_url check
                cursor.execute("SELECT id FROM news_items WHERE canonical_url = ?", (item["canonical_url"],))
                if cursor.fetchone():
                    continue

                # Insert
                item_id = new_id("news_")
                cursor.execute(
                    """
                    INSERT INTO news_items (
                        id, source_id, published_at, url, canonical_url, title, summary, 
                        raw_payload_json, content_hash, lang, domain
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id, item["source_id"], item["published_at"], item["url"], 
                        item["canonical_url"], item["title"], item["summary"], 
                        item["raw_payload_json"], item["content_hash"], item["lang"], 
                        item.get("domain", "")
                    )
                )

                # Extract and Save Asset Mentions
                mentions = self.mapper.extract_assets(item["title"] + " " + item["summary"])
                for mention in mentions:
                    cursor.execute(
                        """
                        INSERT INTO news_asset_mentions (item_id, asset_symbol, confidence, method)
                        VALUES (?, ?, ?, ?)
                        """,
                        (item_id, mention["asset_symbol"], mention["confidence"], mention["method"])
                    )

                new_count += 1
            
            conn.commit()
        return new_count

    def _get_enabled_sources(self) -> List[Dict[str, Any]]:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM news_sources WHERE is_enabled = 1")
            return [dict(row) for row in cursor.fetchall()]

    def _cluster_recent_items(self):
        """
        Simple clustering: Group items with similar titles in the last 24h.
        Uses Jaccard similarity on token-normalized title sets.
        Stores clusters in news_clusters + news_cluster_items tables.
        """
        from datetime import datetime, timedelta
        import hashlib
        since = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        now_iso = datetime.utcnow().isoformat()

        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                # Get items not yet assigned to a cluster
                cursor.execute(
                    """SELECT ni.id, ni.title FROM news_items ni
                       LEFT JOIN news_cluster_items nci ON ni.id = nci.item_id
                       WHERE ni.published_at > ? AND nci.item_id IS NULL
                       ORDER BY ni.published_at DESC LIMIT 200""",
                    (since,)
                )
                items = cursor.fetchall()

                if len(items) < 2:
                    return

                # Normalize titles into token sets
                import re
                def tokenize(title):
                    return set(re.findall(r'\b[a-z]{3,}\b', title.lower()))

                item_tokens = [(dict(row)["id"], dict(row)["title"], tokenize(dict(row)["title"])) for row in items]

                # Greedy clustering with Jaccard threshold
                JACCARD_THRESHOLD = 0.4
                clusters = []  # list of lists of item_ids
                assigned = set()

                for i, (id_i, title_i, tokens_i) in enumerate(item_tokens):
                    if id_i in assigned:
                        continue
                    cluster = [id_i]
                    assigned.add(id_i)

                    for j in range(i + 1, len(item_tokens)):
                        id_j, title_j, tokens_j = item_tokens[j]
                        if id_j in assigned:
                            continue
                        if not tokens_i or not tokens_j:
                            continue
                        intersection = tokens_i & tokens_j
                        union = tokens_i | tokens_j
                        jaccard = len(intersection) / len(union)
                        if jaccard >= JACCARD_THRESHOLD:
                            cluster.append(id_j)
                            assigned.add(id_j)

                    if len(cluster) > 1:
                        clusters.append(cluster)

                # Persist clusters using actual table schema
                for cluster_item_ids in clusters:
                    cluster_id = new_id("clus_")
                    cluster_hash = hashlib.sha256("|".join(sorted(cluster_item_ids)).encode()).hexdigest()[:16]
                    cursor.execute(
                        """INSERT INTO news_clusters
                           (id, cluster_hash, first_seen_at, last_seen_at, top_item_id, size, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (cluster_id, cluster_hash, now_iso, now_iso, cluster_item_ids[0], len(cluster_item_ids), now_iso)
                    )
                    for item_id in cluster_item_ids:
                        cursor.execute(
                            "INSERT OR IGNORE INTO news_cluster_items (cluster_id, item_id) VALUES (?, ?)",
                            (cluster_id, item_id)
                        )

                conn.commit()
                if clusters:
                    logger.info(f"Created {len(clusters)} news clusters from {len(items)} items.")
        except Exception as e:
            logger.warning("Clustering failed (non-fatal): %s", str(e)[:200])

    def seed_default_sources(self):
        """Seed default free RSS sources if none exist."""
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) as count FROM news_sources")
            if cursor.fetchone()["count"] > 0:
                return

            defaults = [
                ("Coindesk", "rss", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
                ("Cointelegraph", "rss", "https://cointelegraph.com/rss"),
                ("Decrypt", "rss", "https://decrypt.co/feed"),
                ("Bitcoin Magazine", "rss", "https://bitcoinmagazine.com/.rss/full/"),
                # GDELT Queries
                ("GDELT-Bitcoin", "gdelt", "bitcoin"),
                ("GDELT-Ethereum", "gdelt", "ethereum"),
            ]

            for name, type_, url in defaults:
                cursor.execute(
                    "INSERT INTO news_sources (id, name, type, url) VALUES (?, ?, ?, ?)",
                    (new_id("src_"), name, type_, url)
                )
            conn.commit()
            logger.info("Seeded default news sources.")
