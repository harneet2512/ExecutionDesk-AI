"""Run diagnostics artifact builder.

Emits a structured diagnostic snapshot for every trade run, capturing
environment state, referenced balances, product rules, and preflight
decisions.  Asset-agnostic: works for any set of requested instruments.

See docs/trading_truth_contracts.md Section 5 for the schema contract.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.core.time import now_iso
from backend.db.connect import get_conn, _parse_db_url

logger = get_logger(__name__)


def _catalog_count() -> int:
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS cnt FROM product_catalog")
            row = cur.fetchone()
            return int(row["cnt"]) if row else 0
    except Exception:
        return -1


def _migrations_applied() -> int:
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS cnt FROM schema_migrations")
            row = cur.fetchone()
            return int(row["cnt"]) if row else 0
    except Exception:
        return -1


def _collect_balances(
    referenced_assets: List[str],
    tenant_id: str,
) -> Dict[str, Dict[str, float]]:
    """Collect executable balances for all referenced assets."""
    balances: Dict[str, Dict[str, float]] = {}
    try:
        from backend.services.executable_state import fetch_executable_state
        state = fetch_executable_state(tenant_id)
        for asset in referenced_assets:
            key = asset.upper()
            bal = (state.balances or {}).get(key)
            if bal:
                balances[key] = {
                    "available_qty": bal.available_qty,
                    "hold_qty": bal.hold_qty,
                }
            else:
                balances[key] = {"available_qty": 0.0, "hold_qty": 0.0}
        usd = (state.balances or {}).get("USD")
        if usd and "USD" not in balances:
            balances["USD"] = {
                "available_qty": usd.available_qty,
                "hold_qty": usd.hold_qty,
            }
    except Exception as exc:
        logger.warning("run_diagnostics: balance collection failed: %s", str(exc)[:200])
    return balances


def _collect_product_rules(
    product_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Collect product rules for all referenced product IDs."""
    rules: Dict[str, Dict[str, Any]] = {}
    for pid in product_ids:
        entry: Dict[str, Any] = {
            "rule_source": "unavailable",
            "base_min_size": None,
            "base_increment": None,
            "min_market_funds": None,
            "verified": False,
        }
        try:
            from backend.services.market_metadata import get_metadata_service
            svc = get_metadata_service()
            result = svc.get_product_details_sync(pid, allow_stale=True)
            if result.success and result.data:
                entry["rule_source"] = "metadata_service"
                entry["base_min_size"] = result.data.get("base_min_size")
                entry["base_increment"] = result.data.get("base_increment")
                entry["min_market_funds"] = result.data.get("min_market_funds")
                entry["verified"] = not result.used_stale_cache
                rules[pid] = entry
                continue
        except Exception:
            pass

        try:
            from backend.services.product_catalog import get_product_catalog
            cat = get_product_catalog()
            prod = cat.get_product(pid)
            if prod:
                entry["rule_source"] = "catalog"
                entry["base_min_size"] = prod.base_min_size
                entry["base_increment"] = prod.base_increment
                entry["min_market_funds"] = prod.min_market_funds
                entry["verified"] = False
        except Exception:
            pass

        rules[pid] = entry
    return rules


def build_staging_diagnostics(
    tenant_id: str,
    referenced_assets: List[str],
    executable_state: Any,
    analysis_snapshot_asof: Optional[str] = None,
    preflight_map: Optional[Dict[str, Any]] = None,
    forced_refresh: bool = False,
) -> Dict[str, Any]:
    """Build diagnostics emitted at trade staging time (before run creation).

    Parameters
    ----------
    tenant_id : str
        Tenant for balance lookups.
    referenced_assets : list[str]
        Asset symbols referenced in the valid trade actions (e.g. ["BTC"]).
    executable_state : ExecutableState
        Already-fetched executable state (avoids double fetch).
    analysis_snapshot_asof : str | None
        Timestamp of the portfolio snapshot that informed the analysis.
    preflight_map : dict | None
        Per-action preflight outcomes keyed by action label.
    forced_refresh : bool
        Whether a state-mismatch guard triggered a forced balance refresh.
    """
    settings = get_settings()
    db_path = os.path.abspath(_parse_db_url(settings.database_url))

    assets = [a.upper() for a in (referenced_assets or [])]
    product_ids = [f"{a}-USD" for a in assets if a not in ("USD", "USDC", "USDT")]

    # State diagnostics
    state_diag: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "analysis_snapshot_asof": analysis_snapshot_asof,
        "trade_balances_fetched_at": getattr(executable_state, "fetched_at", None),
        "balances_source": getattr(executable_state, "source", "unknown"),
        "forced_refresh_performed": forced_refresh,
        "db_path": db_path,
        "migrations_applied": _migrations_applied(),
        "catalog_count": _catalog_count(),
    }

    # Balances diagnostics
    bal_diag: Dict[str, Any] = {
        "provider_fetch_status": "ok" if getattr(executable_state, "source", "") not in ("error", "") else "unknown",
        "currencies_present": list((getattr(executable_state, "balances", {}) or {}).keys()),
        "per_asset": {},
    }
    for asset in assets:
        bal = (getattr(executable_state, "balances", {}) or {}).get(asset)
        bal_diag["per_asset"][asset] = {
            "matched": bal is not None,
            "available_qty": float(getattr(bal, "available_qty", 0) or 0) if bal else 0.0,
            "hold_qty": float(getattr(bal, "hold_qty", 0) or 0) if bal else 0.0,
        }

    # Rule source diagnostics
    rule_diag: Dict[str, Any] = {"per_product": _collect_product_rules(product_ids)}

    # Preflight decisions
    pf_diag: Dict[str, Any] = {"per_action": preflight_map or {}}

    return {
        "state_diagnostics": state_diag,
        "balances_diagnostics": bal_diag,
        "rule_source_diagnostics": rule_diag,
        "preflight_decisions": pf_diag,
        "built_at": now_iso(),
    }


def build_run_diagnostics(
    run_id: str,
    tenant_id: str,
    execution_mode: str,
    referenced_assets: Optional[List[str]] = None,
    preflight_decisions: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build the run_diagnostics payload.

    Parameters
    ----------
    run_id : str
        The run identifier (for logging only; not stored in the payload).
    tenant_id : str
        Tenant for balance lookups.
    execution_mode : str
        PAPER or LIVE.
    referenced_assets : list[str] | None
        Asset symbols mentioned in the trade intent (e.g. ["BTC", "ETH"]).
        When None, the balances/product_rules sections will be empty.
    preflight_decisions : dict | None
        Per-action preflight outcomes keyed by action label
        (e.g. {"SELL_BTC_ALL": {"status": "READY", ...}}).
    """
    settings = get_settings()
    db_path = os.path.abspath(_parse_db_url(settings.database_url))

    assets = [a.upper() for a in (referenced_assets or [])]
    product_ids = [f"{a}-USD" for a in assets if a != "USD"]

    return {
        "env": {
            "execution_mode": execution_mode,
            "tenant_id": tenant_id,
            "db_path": db_path,
            "catalog_count": _catalog_count(),
            "migrations_applied": _migrations_applied(),
            "provider_mode": settings.market_data_mode,
        },
        "balances": _collect_balances(assets, tenant_id),
        "product_rules": _collect_product_rules(product_ids),
        "decisions": preflight_decisions or {},
        "built_at": now_iso(),
    }
