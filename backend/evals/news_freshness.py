"""News Freshness Evaluation - Verify news evidence is timely.

If a run uses news evidence, the median age of those news items should be
below a configurable threshold.  Stale news must trigger a ``news_stale``
flag in the news_brief artifact.

Score:
  1.0  – no news dependency OR all items < MAX_AGE_HOURS
  0.5  – max age < 2 * MAX_AGE_HOURS (warn)
  0.0  – older items present without stale flag
"""
import json
from datetime import datetime, timedelta
from typing import Tuple
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)

MAX_AGE_HOURS = 24


def evaluate_news_freshness(run_id: str, tenant_id: str) -> dict:
    """Evaluate freshness of news evidence used in a run."""
    with get_conn() as conn:
        cursor = conn.cursor()

        reasons = []

        # Get run start time
        cursor.execute(
            "SELECT started_at FROM runs WHERE run_id = ?", (run_id,)
        )
        run_row = cursor.fetchone()
        if not run_row or not run_row["started_at"]:
            return {
                "score": 1.0,
                "reasons": ["No run start time; skipping news freshness check"],
                "thresholds": {"max_age_hours": MAX_AGE_HOURS},
            }

        try:
            run_start = datetime.fromisoformat(
                run_row["started_at"].replace("Z", "+00:00")
            )
        except Exception:
            run_start = datetime.utcnow()

        # Get news items linked to this run
        cursor.execute(
            """
            SELECT ni.published_at
            FROM run_news_evidence rne
            JOIN news_items ni ON ni.id = rne.item_id
            WHERE rne.run_id = ?
            """,
            (run_id,),
        )
        rows = cursor.fetchall()

        if not rows:
            return {
                "score": 1.0,
                "reasons": ["No news evidence used; freshness not applicable"],
                "thresholds": {"max_age_hours": MAX_AGE_HOURS},
            }

        # Compute ages
        ages_hours = []
        for row in rows:
            try:
                pub = datetime.fromisoformat(
                    row["published_at"].replace("Z", "+00:00")
                )
                age_h = (run_start - pub).total_seconds() / 3600
                ages_hours.append(max(age_h, 0))
            except Exception:
                ages_hours.append(999)  # treat parse failures as very old

        max_age = max(ages_hours)
        median_age = sorted(ages_hours)[len(ages_hours) // 2]

        # Check for news_stale flag in news_brief artifact
        cursor.execute(
            """
            SELECT artifact_json FROM run_artifacts
            WHERE run_id = ? AND artifact_type = 'news_brief'
            """,
            (run_id,),
        )
        brief_row = cursor.fetchone()
        has_stale_flag = False
        if brief_row:
            try:
                brief = json.loads(brief_row["artifact_json"])
                has_stale_flag = brief.get("news_stale", False)
            except Exception:
                pass

        if max_age <= MAX_AGE_HOURS:
            score = 1.0
            reasons.append(
                f"All {len(ages_hours)} news items within {MAX_AGE_HOURS}h "
                f"(max age {max_age:.1f}h, median {median_age:.1f}h)"
            )
        elif max_age <= MAX_AGE_HOURS * 2:
            score = 0.5
            reasons.append(
                f"Some news items moderately stale (max {max_age:.1f}h, "
                f"median {median_age:.1f}h)"
            )
            if not has_stale_flag:
                score = 0.25
                reasons.append("news_stale flag missing in news_brief")
        else:
            if has_stale_flag:
                score = 0.5
                reasons.append(
                    f"Very stale news (max {max_age:.1f}h) but news_stale=true set"
                )
            else:
                score = 0.0
                reasons.append(
                    f"Very stale news (max {max_age:.1f}h) with no stale flag"
                )

        return {
            "score": score,
            "reasons": reasons,
            "thresholds": {"max_age_hours": MAX_AGE_HOURS},
            "metrics": {
                "items_count": len(ages_hours),
                "max_age_hours": round(max_age, 2),
                "median_age_hours": round(median_age, 2),
                "has_stale_flag": has_stale_flag,
            },
        }
