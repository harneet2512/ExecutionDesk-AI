"""Prediction signals node - analyzes Polymarket data for trading signals."""
import json
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


async def execute(run_id: str, node_id: str, tenant_id: str) -> dict:
    """Execute prediction signals node - analyze market data from prediction_research."""

    # ------------------------------------------------------------------
    # 1. Read prediction_research node output from dag_nodes
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
        row = cursor.fetchone()

        if not row or "outputs_json" not in row.keys() or not row["outputs_json"]:
            raise ValueError("prediction_research node outputs not found")

        research_output = json.loads(row["outputs_json"])

    yes_price = float(research_output.get("yes_price", 0))
    no_price = float(research_output.get("no_price", 0))
    volume = float(research_output.get("volume", 0))
    liquidity = float(research_output.get("liquidity", 0))
    token_id = research_output.get("token_id", "")

    # ------------------------------------------------------------------
    # 2. Compute liquidity score (0-1)
    #    Blend volume and liquidity with reasonable scaling factors.
    #    - Volume component: tanh-like saturation at $1M
    #    - Liquidity component: tanh-like saturation at $500K
    # ------------------------------------------------------------------
    volume_component = min(1.0, volume / 1_000_000) if volume > 0 else 0.0
    liquidity_component = min(1.0, liquidity / 500_000) if liquidity > 0 else 0.0
    liquidity_score = round(0.6 * volume_component + 0.4 * liquidity_component, 4)

    # ------------------------------------------------------------------
    # 3. Market sentiment
    # ------------------------------------------------------------------
    market_sentiment = "bullish" if yes_price > 0.5 else "bearish"

    # ------------------------------------------------------------------
    # 4. Signal strength (0-1)
    #    Stronger when price is far from 0.50 (high conviction) and
    #    liquidity is adequate.
    # ------------------------------------------------------------------
    price_conviction = abs(yes_price - 0.5) * 2  # 0 at 0.50, 1 at 0.00/1.00
    signal_strength = round(min(1.0, price_conviction * 0.7 + liquidity_score * 0.3), 4)

    logger.info(
        "Prediction signals: sentiment=%s, yes=%.4f, no=%.4f, "
        "liquidity_score=%.4f, signal_strength=%.4f",
        market_sentiment,
        yes_price,
        no_price,
        liquidity_score,
        signal_strength,
    )

    # ------------------------------------------------------------------
    # 5. Build output and store in dag_nodes
    # ------------------------------------------------------------------
    signals_output = {
        "market_sentiment": market_sentiment,
        "yes_price": yes_price,
        "no_price": no_price,
        "liquidity_score": liquidity_score,
        "signal_strength": signal_strength,
        "volume": volume,
        "token_id": token_id,
    }

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE dag_nodes SET outputs_json = ? WHERE node_id = ?",
            (json.dumps(signals_output), node_id),
        )
        conn.commit()

    return signals_output
