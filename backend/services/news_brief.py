import json
from datetime import datetime, timedelta
from typing import List, Dict, Any
from backend.db.connect import get_conn
from backend.core.logging import get_logger
from backend.core.ids import new_id

logger = get_logger(__name__)

class NewsBriefService:
    """
    Generates a NewsBrief for a run.
    """

    def create_brief(self, run_id: str, assets: List[str], window_hours: int = 24, reference_time: datetime = None) -> Dict[str, Any]:
        """
        Create a NewsBrief for the given assets + time window.
        Persists evidence links to run_news_evidence.
        """
        # Time window
        ref_time = reference_time or datetime.utcnow()
        since = (ref_time - timedelta(hours=window_hours)).isoformat()
        
        brief = {
            "window_hours": window_hours,
            "assets": [],
            "blockers": [],
            "generated_at": datetime.utcnow().isoformat()
        }

        with get_conn() as conn:
            cursor = conn.cursor()
            
            for asset in assets:
                # Get relevant items
                cursor.execute(
                    """
                    SELECT i.*, m.confidence 
                    FROM news_items i
                    JOIN news_asset_mentions m ON i.id = m.item_id
                    WHERE m.asset_symbol = ? 
                      AND i.published_at <= ?
                      AND i.published_at > ?
                    ORDER BY i.published_at DESC
                    LIMIT 10
                    """,
                    (asset, ref_time.isoformat(), since)
                )
                rows = cursor.fetchall()
                
                self._process_rows_into_brief(cursor, run_id, asset, rows, brief)

            conn.commit()
            
        return brief

    def create_brief_from_source(self, run_id: str, source_run_id: str) -> Dict[str, Any]:
        """
        Recreate a news brief using EXACTLY the evidence from a source run.
        """
        brief = {
            "window_hours": 0, # N/A
            "assets": [],
            "blockers": [],
            "generated_at": datetime.utcnow().isoformat(),
            "source_run_id": source_run_id
        }
        
        with get_conn() as conn:
            cursor = conn.cursor()
            
            # Get evidence items from source run
            cursor.execute(
                """
                SELECT i.*, m.confidence, m.asset_symbol
                FROM run_news_evidence e
                JOIN news_items i ON e.item_id = i.id
                LEFT JOIN news_asset_mentions m ON i.id = m.item_id
                WHERE e.run_id = ?
                """,
                (source_run_id,)
            )
            rows = cursor.fetchall()
            
            # Group by asset
            asset_map = {}
            for row in rows:
                asset = row["asset_symbol"]
                if not asset: continue # Should not happen if strictly mapped
                if asset not in asset_map:
                    asset_map[asset] = []
                asset_map[asset].append(row)
            
            for asset, asset_rows in asset_map.items():
                self._process_rows_into_brief(cursor, run_id, asset, asset_rows, brief)
                
            conn.commit()
        return brief

    def _process_rows_into_brief(self, cursor: Any, run_id: str, asset: str, rows: List[Any], brief: Dict[str, Any]):
        """Helper to process rows into brief structure."""
        asset_data = {
            "symbol": asset,
            "clusters": []
        }
        
        items_refs = []
        for row in rows:
            item_ref = {
                "item_id": row["id"],
                "source_id": row["source_id"],
                "published_at": row["published_at"],
                "url": row["url"],
                "title": row["title"]
            }
            # Avoid dupes
            if not any(x["item_id"] == row["id"] for x in items_refs):
                   items_refs.append(item_ref)
            
            # Record Evidence for this NEW run (if not already exists)
            cursor.execute(
                """
                INSERT OR IGNORE INTO run_news_evidence (run_id, item_id, role)
                VALUES (?, ?, 'context')
                """,
                (run_id, row["id"])
            )

        if items_refs:
            asset_data["clusters"].append({
                "cluster_id": new_id("clus_"),
                "headline": f"Recent news for {asset}",
                "items": items_refs,
                "tags": []
            })
            brief["assets"].append(asset_data)
