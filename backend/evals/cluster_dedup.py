"""Cluster Dedup Score Evaluation - Penalize near-duplicate news clusters.

Checks that the news evidence linked to a run does not contain excessive
near-duplicate items within the same cluster.  Ideal state is at most one
item per cluster.

Score:
  1.0  – no news dependency OR max 1 item per cluster
  Penalized proportionally to the ratio of duplicate items
"""
import json
from typing import Tuple
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def evaluate_cluster_dedup(run_id: str, tenant_id: str) -> dict:
    """Evaluate cluster deduplication quality of news evidence."""
    with get_conn() as conn:
        cursor = conn.cursor()

        reasons = []

        # Get news evidence items with cluster info
        cursor.execute(
            """
            SELECT rne.item_id, rne.cluster_id
            FROM run_news_evidence rne
            WHERE rne.run_id = ?
            """,
            (run_id,),
        )
        rows = cursor.fetchall()

        if not rows:
            return {
                "score": 1.0,
                "reasons": ["No news evidence used; dedup not applicable"],
                "thresholds": {"max_items_per_cluster": 1},
            }

        # Group by cluster_id
        cluster_counts: dict = {}
        unclustered = 0
        for row in rows:
            cid = row["cluster_id"]
            if cid:
                cluster_counts[cid] = cluster_counts.get(cid, 0) + 1
            else:
                unclustered += 1

        if not cluster_counts:
            # All unclustered – no dedup assessment possible
            return {
                "score": 1.0,
                "reasons": [
                    f"{unclustered} unclustered news items; dedup not assessable"
                ],
                "thresholds": {"max_items_per_cluster": 1},
            }

        max_per_cluster = max(cluster_counts.values())
        total_items = sum(cluster_counts.values()) + unclustered
        unique_clusters = len(cluster_counts)
        duplicate_items = sum(max(0, c - 1) for c in cluster_counts.values())

        if max_per_cluster <= 1:
            score = 1.0
            reasons.append(
                f"Clean dedup: {unique_clusters} clusters, "
                f"max 1 item per cluster"
            )
        else:
            # Penalize: each duplicate reduces score proportionally
            dedup_ratio = 1.0 - (duplicate_items / total_items)
            score = max(0.0, round(dedup_ratio, 4))
            reasons.append(
                f"Duplicate items detected: {duplicate_items} duplicates "
                f"across {unique_clusters} clusters (max {max_per_cluster} "
                f"items in one cluster)"
            )

        return {
            "score": score,
            "reasons": reasons,
            "thresholds": {"max_items_per_cluster": 1},
            "metrics": {
                "total_items": total_items,
                "unique_clusters": unique_clusters,
                "max_per_cluster": max_per_cluster,
                "duplicate_items": duplicate_items,
                "unclustered": unclustered,
            },
        }
