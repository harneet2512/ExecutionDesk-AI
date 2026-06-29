"""Prediction risk node - budget enforcement for prediction market orders."""
import json
from backend.db.connect import get_conn
from backend.core.config import get_settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


async def execute(run_id: str, node_id: str, tenant_id: str) -> dict:
    """Execute prediction risk node - enforce budget and exposure limits."""
    settings = get_settings()

    # ------------------------------------------------------------------
    # 1. Read intent from runs table
    # ------------------------------------------------------------------
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT intent_json FROM runs WHERE run_id = ?", (run_id,))
        intent_row = cursor.fetchone()

        if not intent_row or "intent_json" not in intent_row.keys() or not intent_row["intent_json"]:
            intent = {}
        else:
            intent = json.loads(intent_row["intent_json"])

    # Support both "budget_usd" and "amount_usd" (confirmation metadata fallback)
    budget_usd = intent.get("budget_usd") or intent.get("amount_usd") or 10.0
    budget_usd = float(budget_usd)

    # ------------------------------------------------------------------
    # 2. Read prediction_research node output from dag_nodes
    # ------------------------------------------------------------------
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes
            WHERE run_id = ? AND name = 'prediction_research'
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,),
        )
        research_row = cursor.fetchone()

        if not research_row or "outputs_json" not in research_row.keys() or not research_row["outputs_json"]:
            raise ValueError("prediction_research node outputs not found")

        research_output = json.loads(research_row["outputs_json"])

    token_id = research_output.get("token_id", "")
    yes_price = float(research_output.get("yes_price", 0))

    # ------------------------------------------------------------------
    # 3. Enforce max exposure: cap at settings.max_notional_per_order_usd
    # ------------------------------------------------------------------
    max_notional = min(budget_usd, settings.max_notional_per_order_usd)

    # ------------------------------------------------------------------
    # 4. Minimum order check: $1.00 minimum
    # ------------------------------------------------------------------
    min_order_usd = 1.0
    if max_notional < min_order_usd:
        raise ValueError(
            "Order notional $%.2f below minimum $%.2f" % (max_notional, min_order_usd)
        )

    # ------------------------------------------------------------------
    # 5. Build risk summary
    # ------------------------------------------------------------------
    if max_notional < budget_usd:
        risk_summary = (
            "Budget capped: requested $%.2f exceeds max notional $%.2f"
            % (budget_usd, settings.max_notional_per_order_usd)
        )
    else:
        risk_summary = "Within limits: $%.2f of $%.2f max" % (
            max_notional,
            settings.max_notional_per_order_usd,
        )

    logger.info(
        "Prediction risk: budget=$%.2f, max_notional=$%.2f, risk=%s",
        budget_usd,
        max_notional,
        risk_summary,
    )

    # ------------------------------------------------------------------
    # 6. Build output and store in dag_nodes
    # ------------------------------------------------------------------
    risk_output = {
        "budget_usd": budget_usd,
        "max_notional": max_notional,
        "risk_summary": risk_summary,
        "token_id": token_id,
        "yes_price": yes_price,
    }

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE dag_nodes SET outputs_json = ? WHERE node_id = ?",
            (json.dumps(risk_output), node_id),
        )
        conn.commit()

    return risk_output
