"""Policy engine - deterministic checks."""
import json
from typing import Dict, Any
from backend.core.config import get_settings
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)


def check_policy(
    tenant_id: str,
    proposal: Dict[str, Any],
    existing_order_count: int = 0,
    execution_mode: str = "PAPER"
) -> Dict[str, Any]:
    """
    Check proposal against policies.
    
    Returns:
    {
        "decision": "ALLOWED" | "BLOCKED" | "REQUIRES_APPROVAL",
        "reasons": [...]
    }
    """
    settings = get_settings()
    reasons = []
    decision = "ALLOWED"
    
    # Check global kill switch
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT kill_switch_enabled FROM tenants WHERE tenant_id = ?",
            (tenant_id,)
        )
        row = cursor.fetchone()
        tenant_kill_switch = row[0] if row else 0
    
    if settings.kill_switch_enabled or tenant_kill_switch:
        reasons.append("Kill switch enabled")
        decision = "BLOCKED"
        return {"decision": decision, "reasons": reasons}
    
    # Parse symbol allowlist
    allowlist = [s.strip().upper() for s in settings.symbol_allowlist.split(",")]

    # Check if this is an auto-selected asset (locked by the system after tradability verification)
    # If so, the symbol was already verified against the live Coinbase product list and
    # should not be blocked by a static allowlist.
    chosen_product_id = proposal.get("chosen_product_id", "")
    is_system_selected = bool(chosen_product_id)
    
    # Check each order in proposal
    orders = proposal.get("orders", [])
    citations = proposal.get("citations", [])
    
    for order in orders:
        symbol = order.get("symbol", "").upper()
        # Strip "-USD" suffix for allowlist comparison (allowlist uses base symbols)
        symbol_base = symbol.replace("-USD", "")
        notional = float(order.get("notional_usd", 0))
        
        # Symbol allowlist check — skip for system-selected assets that passed tradability preflight
        if symbol_base not in allowlist and not is_system_selected:
            reasons.append(f"Symbol {symbol_base} not in allowlist: {allowlist}")
            decision = "BLOCKED"
        elif symbol_base not in allowlist and is_system_selected:
            reasons.append(f"Symbol {symbol_base} auto-selected by system (tradability pre-verified)")
            # Do NOT block — the system verified this asset is tradeable
        
        # Max notional per order
        if notional > settings.max_notional_per_order_usd:
            reasons.append(f"Notional {notional} exceeds limit {settings.max_notional_per_order_usd}")
            decision = "BLOCKED"
        
        # Check if close to limit (for approval requirement)
        if notional >= 0.8 * settings.max_notional_per_order_usd and decision != "BLOCKED":
            decision = "REQUIRES_APPROVAL"
            reasons.append(f"Notional {notional} is >= 80% of limit {settings.max_notional_per_order_usd}")
    
    # Max trades per run
    total_orders = existing_order_count + len(orders)
    if total_orders > settings.max_trades_per_run:
        reasons.append(f"Total orders {total_orders} exceeds limit {settings.max_trades_per_run}")
        decision = "BLOCKED"
    
    # Min citations required (skip for command-based runs)
    if len(citations) < settings.min_citations_required and not proposal.get("skip_citation_check"):
        reasons.append(f"Citations {len(citations)} below required {settings.min_citations_required}")
        decision = "BLOCKED"
    
    # LIVE trading requires approval unless explicitly allowed
    if execution_mode == "LIVE" and decision == "ALLOWED":
        # Check if user has live_trading_allowed flag (placeholder - would check user table)
        # For now, require approval for all LIVE trades
        decision = "REQUIRES_APPROVAL"
        reasons.append("LIVE trading mode requires approval")
    
    # Additional checks for command-based runs
    for order in orders:
        budget = float(order.get("notional_usd", 0))
        if budget > settings.max_notional_per_order_usd * 2:
            reasons.append(f"Budget {budget} exceeds 2x limit")
            decision = "BLOCKED"
    
    return {
        "decision": decision,
        "reasons": reasons
    }
