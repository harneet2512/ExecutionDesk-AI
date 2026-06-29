"""Prediction research node - searches Polymarket for matching events."""
import json
import httpx
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)

# Polymarket Gamma API base URL
GAMMA_API_BASE = "https://gamma-api.polymarket.com"


async def execute(run_id: str, node_id: str, tenant_id: str) -> dict:
    """Execute prediction research node - search Polymarket for matching markets."""

    # ------------------------------------------------------------------
    # 1. Read intent from the runs table
    # ------------------------------------------------------------------
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT intent_json, asset_class FROM runs WHERE run_id = ?",
            (run_id,),
        )
        row = cursor.fetchone()

        if not row or "intent_json" not in row.keys() or not row["intent_json"]:
            raise ValueError("No intent found for run %s" % run_id)

        intent = json.loads(row["intent_json"])
        asset_class = (
            row["asset_class"]
            if "asset_class" in row.keys() and row["asset_class"]
            else "PREDICTION_MARKET"
        )

    if asset_class != "PREDICTION_MARKET":
        logger.warning(
            "prediction_research called on non-PREDICTION_MARKET run %s (asset_class=%s)",
            run_id,
            asset_class,
        )

    market_query = intent.get("market_query", "")
    if not market_query:
        raise ValueError("Intent missing 'market_query' for prediction research")

    logger.info("Searching Polymarket for query=%s", market_query)

    # ------------------------------------------------------------------
    # 2. Query Polymarket Gamma API for matching events
    # ------------------------------------------------------------------
    url = f"{GAMMA_API_BASE}/events"
    params = {
        "slug_contains": market_query,
        "active": "true",
        "closed": "false",
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            events = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error("Polymarket API HTTP error: %s", exc)
        raise ValueError(
            "Polymarket API returned status %d for query '%s'"
            % (exc.response.status_code, market_query)
        )
    except Exception as exc:
        logger.error("Polymarket API request failed: %s", exc)
        raise ValueError("Polymarket API request failed: %s" % exc)

    if not events:
        raise ValueError(
            "No active Polymarket events found for query '%s'" % market_query
        )

    # ------------------------------------------------------------------
    # 3. Pick the best matching market (highest volume)
    # ------------------------------------------------------------------
    best_market = None
    best_volume = -1.0

    for event in events:
        markets = event.get("markets", [])
        for mkt in markets:
            if not mkt.get("active", False):
                continue
            vol = float(mkt.get("volume", 0) or 0)
            if vol > best_volume:
                best_volume = vol
                best_market = mkt

    if best_market is None:
        raise ValueError(
            "No active markets with volume found for query '%s'" % market_query
        )

    # ------------------------------------------------------------------
    # 4. Extract token IDs and prices
    # ------------------------------------------------------------------
    question = best_market.get("question", "")
    condition_id = best_market.get("conditionId", best_market.get("condition_id", ""))
    liquidity = float(best_market.get("liquidity", 0) or 0)
    volume = float(best_market.get("volume", 0) or 0)

    # Outcome prices -- Polymarket stores YES at outcomePrices[0], NO at [1]
    outcome_prices_raw = best_market.get("outcomePrices", "[]")
    if isinstance(outcome_prices_raw, str):
        try:
            outcome_prices = json.loads(outcome_prices_raw)
        except (json.JSONDecodeError, TypeError):
            outcome_prices = []
    else:
        outcome_prices = outcome_prices_raw

    yes_price = float(outcome_prices[0]) if len(outcome_prices) > 0 else 0.0
    no_price = float(outcome_prices[1]) if len(outcome_prices) > 1 else 1.0 - yes_price

    # Token IDs -- clobTokenIds stores [yes_token, no_token]
    clob_token_ids_raw = best_market.get("clobTokenIds", "[]")
    if isinstance(clob_token_ids_raw, str):
        try:
            clob_token_ids = json.loads(clob_token_ids_raw)
        except (json.JSONDecodeError, TypeError):
            clob_token_ids = []
    else:
        clob_token_ids = clob_token_ids_raw

    yes_token_id = clob_token_ids[0] if len(clob_token_ids) > 0 else ""
    no_token_id = clob_token_ids[1] if len(clob_token_ids) > 1 else ""

    # Default: select the YES outcome token
    selected_outcome = intent.get("outcome", "YES").upper()
    token_id = yes_token_id if selected_outcome == "YES" else no_token_id

    logger.info(
        "Selected market: question=%s, yes=%.4f, no=%.4f, volume=%.2f, liquidity=%.2f",
        question,
        yes_price,
        no_price,
        volume,
        liquidity,
    )

    # ------------------------------------------------------------------
    # 5. Persist research artifact in run_artifacts
    # ------------------------------------------------------------------
    market_data = {
        "question": question,
        "condition_id": condition_id,
        "yes_token_id": yes_token_id,
        "no_token_id": no_token_id,
        "yes_price": yes_price,
        "no_price": no_price,
        "volume": volume,
        "liquidity": liquidity,
        "selected_outcome": selected_outcome,
        "token_id": token_id,
        "slug": best_market.get("slug", ""),
        "end_date": best_market.get("endDate", ""),
    }

    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json)
                   VALUES (?, 'prediction_research', 'polymarket_event', ?)""",
                (run_id, json.dumps(market_data)),
            )
            conn.commit()
    except Exception:
        logger.warning("Failed to persist prediction_research artifact (non-critical)")

    # ------------------------------------------------------------------
    # 6. Build output and store in dag_nodes
    # ------------------------------------------------------------------
    research_output = {
        "market": market_data,
        "yes_price": yes_price,
        "no_price": no_price,
        "token_id": token_id,
        "volume": volume,
        "question": question,
        "condition_id": condition_id,
        "liquidity": liquidity,
    }

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE dag_nodes SET outputs_json = ? WHERE node_id = ?",
            (json.dumps(research_output), node_id),
        )
        conn.commit()

    return research_output
