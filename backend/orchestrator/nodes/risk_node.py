"""Risk node - position sizing with budget enforcement."""
import json
from backend.db.connect import get_conn
from backend.core.config import get_settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


async def execute(run_id: str, node_id: str, tenant_id: str) -> dict:
    """Execute risk node - enforce budget limits, fee buffers, min order sizing."""
    settings = get_settings()
    
    # Get intent and signals
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get intent
        cursor.execute("SELECT intent_json FROM runs WHERE run_id = ?", (run_id,))
        intent_row = cursor.fetchone()
        intent = json.loads(intent_row["intent_json"]) if intent_row and "intent_json" in intent_row.keys() and intent_row["intent_json"] else {}
        # Support both "budget_usd" (from TradeIntent) and "amount_usd" (from confirmation metadata)
        budget_usd = intent.get("budget_usd") or intent.get("amount_usd") or 10.0
        
        # Get signals (top symbol)
        cursor.execute(
            """
            SELECT outputs_json FROM dag_nodes 
            WHERE run_id = ? AND name = 'signals'
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,)
        )
        signals_row = cursor.fetchone()
        if not signals_row:
            raise ValueError("Signals node outputs not found")
        
        signals_output = json.loads(signals_row["outputs_json"])
        top_symbol = signals_output.get("top_symbol")
    
    # Enforce budget limits
    max_notional = min(budget_usd, settings.max_notional_per_order_usd)
    
    # Fee buffer: Coinbase Advanced Trade fees ~0.6% for market orders
    # NOTE: fee_buffer is INFORMATIONAL ONLY. Coinbase BUY market orders with
    # quote_size already deduct fees from within the quote amount, so subtracting
    # the fee from the order size would double-count fees and send $1.988 instead
    # of the user's requested $2.
    fee_rate = 0.006  # 0.6%
    fee_buffer = max_notional * fee_rate
    
    # Min order size check (Coinbase typically requires $1 minimum)
    # Validate against the full amount, not the fee-subtracted amount
    min_order_size_usd = 1.0
    if max_notional < min_order_size_usd:
        raise ValueError(f"Order notional ${max_notional:.2f} below minimum ${min_order_size_usd}")
    
    # Final notional is the full budgeted amount (no fee subtraction)
    final_notional = max_notional
    
    risk_output = {
        "budget_usd": budget_usd,
        "requested_notional_usd": budget_usd,
        "max_notional": max_notional,
        "fee_buffer_informational": fee_buffer,
        "fee_rate": fee_rate,
        "final_notional": final_notional,
        "min_order_size_usd": min_order_size_usd,
        "budget_compliance": final_notional <= budget_usd,
        "risk_summary": "Low risk" if final_notional <= budget_usd else "Budget exceeded",
        "top_symbol": top_symbol
    }
    
    # Store in dag_nodes
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE dag_nodes SET outputs_json = ? WHERE node_id = ?",
            (json.dumps(risk_output), node_id)
        )
        conn.commit()
    
    return risk_output