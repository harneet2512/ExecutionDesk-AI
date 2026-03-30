import json
import re
from datetime import datetime
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.logging import get_logger
from backend.services.news_brief import NewsBriefService
from backend.services.visible_reasoning import VisibleReasoningService

logger = get_logger(__name__)
news_service = NewsBriefService()
reasoning_service = VisibleReasoningService()

# Critical security keywords that ALWAYS block (severe operational risk)
CRITICAL_BLOCKER_KEYWORDS = [
    "hack", "hacked", "exploit", "exploited",
    "delist", "delisted", "delisting",
    "rug pull", "rugpull",
    "bridge attack", "flash loan attack",
]

# Sentiment gate thresholds
SENTIMENT_GATE_THRESHOLD = -0.3  # net_sentiment must be below this
SENTIMENT_CONFIDENCE_THRESHOLD = 0.65  # aggregate confidence must exceed this
MIN_BEARISH_HEADLINES = 2  # Need at least 2 bearish headlines to gate


def _compute_sentiment_gate(brief: dict, candidates: list) -> dict:
    """Compute aggregate sentiment from news headlines and determine gating.

    Returns a SentimentGateResult dict:
      - gated: bool (True = BUY should be blocked/warned)
      - net_sentiment: float (-1.0 to 1.0)
      - confidence: float (0.0 to 1.0)
      - bearish_headlines: list of {title, source, timestamp}
      - bullish_count / bearish_count / neutral_count
      - explanation: str (grounded in headline evidence)
      - critical_blockers: list (severe security/delist events)
      - risk_override_allowed: bool
    """
    from backend.services.pre_confirm_insight import _analyze_headline_sentiment

    all_sentiments = []
    bearish_headlines = []
    critical_blockers = []
    bullish_count = 0
    bearish_count = 0
    neutral_count = 0

    for asset_data in brief.get("assets", []):
        symbol = asset_data.get("symbol", "")
        if symbol not in candidates:
            continue
        for cluster in asset_data.get("clusters", []):
            for item in cluster.get("items", []):
                title = item.get("title", "") or ""
                if not title.strip():
                    continue

                # Check for critical security blockers (always block)
                title_lower = title.lower()
                for kw in CRITICAL_BLOCKER_KEYWORDS:
                    if kw in title_lower:
                        critical_blockers.append({
                            "asset": symbol,
                            "keyword": kw,
                            "title": title,
                            "url": item.get("url", ""),
                            "item_id": item.get("item_id", ""),
                        })
                        break

                # Analyse sentiment
                sa = _analyze_headline_sentiment(title)
                sentiment = sa.get("sentiment", "neutral")
                conf = sa.get("confidence", 0.0)
                all_sentiments.append(sa)

                if sentiment == "bearish":
                    bearish_count += 1
                    bearish_headlines.append({
                        "title": title,
                        "source": item.get("source_name", "Unknown"),
                        "timestamp": item.get("published_at", ""),
                        "url": item.get("url", ""),
                        "confidence": conf,
                        "driver": sa.get("driver", ""),
                    })
                elif sentiment == "bullish":
                    bullish_count += 1
                else:
                    neutral_count += 1

    total = bullish_count + bearish_count + neutral_count
    if total == 0:
        return {
            "gated": False,
            "net_sentiment": 0.0,
            "confidence": 0.0,
            "bearish_headlines": [],
            "critical_blockers": [],
            "bullish_count": 0, "bearish_count": 0, "neutral_count": 0,
            "explanation": "No news headlines available for sentiment analysis.",
            "risk_override_allowed": False,
        }

    # Net sentiment: range -1.0 (all bearish) to +1.0 (all bullish)
    net_sentiment = (bullish_count - bearish_count) / total

    # Aggregate confidence: average of bearish headline confidences (if any)
    avg_confidence = 0.0
    if bearish_headlines:
        avg_confidence = sum(h["confidence"] for h in bearish_headlines) / len(bearish_headlines)

    # Determine gating
    gated = False
    explanation = ""

    # Critical blockers always gate
    if critical_blockers:
        gated = True
        crit = critical_blockers[0]
        explanation = (
            f"CRITICAL: {crit['keyword'].upper()} detected — "
            f"\"{crit['title']}\" ({crit['asset']}). Trade gated for safety."
        )
    # Sentiment-based gating: only when strongly bearish with confidence
    elif (net_sentiment < SENTIMENT_GATE_THRESHOLD
          and avg_confidence > SENTIMENT_CONFIDENCE_THRESHOLD
          and bearish_count >= MIN_BEARISH_HEADLINES):
        gated = True
        top_bearish = bearish_headlines[:2]
        headlines_text = "; ".join(f'"{h["title"]}" ({h["source"]})' for h in top_bearish)
        explanation = (
            f"Bearish sentiment detected (score: {net_sentiment:.2f}, "
            f"confidence: {avg_confidence:.2f}, {bearish_count} bearish headlines). "
            f"Evidence: {headlines_text}"
        )

    return {
        "gated": gated,
        "net_sentiment": round(net_sentiment, 3),
        "confidence": round(avg_confidence, 3),
        "bearish_headlines": bearish_headlines[:5],  # Top 5
        "critical_blockers": critical_blockers,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "neutral_count": neutral_count,
        "explanation": explanation,
        "risk_override_allowed": gated and not critical_blockers,
    }


async def execute(run_id: str, node_id: str, tenant_id: str) -> dict:
    """
    Execute news node: fetch news brief for candidate assets.
    Detects blockers (hack/exploit/delist/outage) as conservative constraints.
    """
    with get_conn() as conn:
        cursor = conn.cursor()

        # Belt-and-suspenders: Check if news is enabled for this run
        cursor.execute("SELECT news_enabled FROM runs WHERE run_id = ?", (run_id,))
        news_check = cursor.fetchone()
        news_enabled = True  # Default
        if news_check and "news_enabled" in news_check.keys() and news_check["news_enabled"] is not None:
            news_enabled = bool(news_check["news_enabled"])

        if not news_enabled:
            logger.info(f"NewsNode: Skipping news analysis for run {run_id} (news_enabled=False)")
            # Store news_skipped artifact
            cursor.execute(
                """
                INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
                VALUES (?, 'news', 'news_skipped', ?)
                """,
                (run_id, json.dumps({"reason": "news_enabled=False", "skipped_at": datetime.utcnow().isoformat() + "Z"}))
            )
            conn.commit()
            return {
                "news_skipped": True,
                "brief": {},
                "blockers": [],
                "evidence_refs": [],
                "safe_summary": "News analysis skipped (disabled by user toggle)"
            }

        # Get run details for determinism
        cursor.execute("SELECT execution_mode, source_run_id, created_at FROM runs WHERE run_id = ?", (run_id,))
        run_row = cursor.fetchone()
        execution_mode = run_row["execution_mode"]
        source_run_id = run_row["source_run_id"]
        run_created_at_iso = run_row["created_at"]

        # Get signals output for candidate assets
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes
            WHERE run_id = ? AND name = 'signals'
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,)
        )
        signals_row = cursor.fetchone()

        candidates = []
        if signals_row:
            signals_output = json.loads(signals_row["outputs_json"])
            top_symbol = signals_output.get("top_symbol")
            if top_symbol:
                candidates.append(top_symbol)
            # Also check a few runner-ups for broader news coverage
            rankings = signals_output.get("rankings", [])
            for r in rankings[:3]:
                sym = r.get("symbol", "")
                if sym and sym not in candidates:
                    # Extract base asset from "BTC-USD" -> "BTC"
                    candidates.append(sym)

        # Convert product_ids to base symbols for news lookup
        base_symbols = []
        for c in candidates:
            base = c.split("-")[0] if "-" in c else c
            if base not in base_symbols:
                base_symbols.append(base)

        # 1. Create News Brief
        brief = {}
        if execution_mode == "REPLAY" and source_run_id:
            logger.info(f"NewsNode: Replaying artifacts from source run {source_run_id}")
            brief = news_service.create_brief_from_source(run_id, source_run_id)
        else:
            ref_time = datetime.fromisoformat(run_created_at_iso.replace('Z', '+00:00')) if run_created_at_iso else datetime.utcnow()
            brief = news_service.create_brief(run_id, base_symbols, reference_time=ref_time)

        # 2. Compute sentiment gate (replaces keyword-only blocker)
        sentiment_gate = _compute_sentiment_gate(brief, base_symbols)
        brief["sentiment_gate"] = sentiment_gate
        # Backwards-compatible: build blockers list from critical blockers
        blockers = sentiment_gate.get("critical_blockers", [])
        brief["blockers"] = blockers

        if sentiment_gate.get("gated"):
            logger.warning(
                "NewsNode: Sentiment gate TRIGGERED for run %s — net=%.2f conf=%.2f bearish=%d critical=%d",
                run_id, sentiment_gate.get("net_sentiment", 0),
                sentiment_gate.get("confidence", 0),
                sentiment_gate.get("bearish_count", 0),
                len(blockers),
            )

        # 3. Store News Brief Artifact
        cursor.execute(
            """
            INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
            VALUES (?, 'news', 'news_brief', ?)
            """,
            (run_id, json.dumps(brief))
        )

        conn.commit()

    return {
        "brief": brief,
        "checked_assets": candidates,
        "blockers": blockers,
        "sentiment_gate": sentiment_gate,
        "evidence_refs": [{"news_brief": True, "blocker_count": len(blockers), "sentiment_gated": sentiment_gate.get("gated", False)}],
        "safe_summary": (
            f"Analyzed news for {', '.join(base_symbols)}. "
            f"Sentiment: {sentiment_gate.get('net_sentiment', 0):.2f} "
            f"({sentiment_gate.get('bullish_count', 0)}B/{sentiment_gate.get('bearish_count', 0)}b/{sentiment_gate.get('neutral_count', 0)}N). "
            + (f"GATED: {sentiment_gate.get('explanation', '')}" if sentiment_gate.get("gated") else "No gate triggered.")
        )
    }
