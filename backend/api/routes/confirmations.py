import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime
from backend.api.deps import require_trader
from backend.db.repo.trade_confirmations_repo import TradeConfirmationsRepo
from backend.orchestrator.runner import create_run, execute_run
from backend.agents.planner import plan_execution
from backend.core.logging import get_logger
import json

router = APIRouter()
logger = get_logger(__name__)
confirmations_repo = TradeConfirmationsRepo()


def _run_in_thread(run_id: str):
    """Synchronous wrapper to run execute_run in a background thread."""
    import asyncio
    import traceback
    try:
        # asyncio.run() creates a fresh event loop, runs the coroutine, and
        # cleans up.  This avoids "This event loop is already running" errors
        # that occur with manual new_event_loop() + run_until_complete().
        asyncio.run(execute_run(run_id=run_id))
        # S2: Audit log on successful completion
        logger.info("TRADE_EXEC_DONE: run=%s result=SUCCESS", run_id)
    except Exception as e:
        # S2: Audit log on failure with full traceback
        error_msg = str(e)[:300]
        error_traceback = traceback.format_exc()[:1000]
        logger.error("TRADE_EXEC_DONE: run=%s result=FAILED error=%s\n%s", run_id, error_msg, error_traceback)
        
        # Mark the run as FAILED with error details persisted
        # Retry up to 3 times with backoff in case DB is locked (NF7)
        for attempt in range(3):
            try:
                from backend.orchestrator.runner import _update_run_status, RunStatus
                from backend.core.time import now_iso
                from backend.db.connect import get_conn
                
                # Update run status
                _update_run_status(run_id, RunStatus.FAILED, completed_at=now_iso())
                
                # Persist error details to database
                with get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """UPDATE runs SET 
                           failure_reason = ?,
                           failure_code = ?,
                           error_summary = ?
                           WHERE run_id = ?""",
                        (error_msg, type(e).__name__, error_msg, run_id)
                    )
                    conn.commit()
                break
            except Exception as mark_err:
                logger.error(
                    "Failed to mark run %s as FAILED (attempt %d/3): %s",
                    run_id, attempt + 1, str(mark_err)[:200]
                )
                if attempt < 2:
                    import time
                    time.sleep(0.5 * (attempt + 1))

class ConfirmRequest(BaseModel):
    pass

class CancelRequest(BaseModel):
    pass

@router.post("/{confirmation_id}/confirm")
async def confirm_trade(
    confirmation_id: str,
    request_body: ConfirmRequest = None,
    user: dict = Depends(require_trader),
    request: Request = None
):
    """
    Confirm a pending trade.

    Returns:
    - 400: invalid_confirmation_id_format
    - 404: confirmation_not_found
    - 409: confirmation_expired or already processed
    - 503: schema unhealthy
    - 200: {run_id, status, confirmation_id, content}
    """
    # Schema health guard: block trades when DB schema is broken
    from backend.api.main import is_schema_healthy
    if not is_schema_healthy():
        import platform
        is_windows = platform.system() == "Windows"
        cmd = (
            "python -m uvicorn backend.api.main:app --port 8000"
            if is_windows
            else "uvicorn backend.api.main:app --port 8000"
        )
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "error_code": "DB_SCHEMA_OUTDATED",
                    "code": "DB_SCHEMA_OUTDATED",
                    "message": "Database schema is outdated. Restart backend to apply migrations.",
                    "request_id": getattr(request.state, 'request_id', '') if request else '',
                    "remediation": f"Restart backend: {cmd}",
                }
            }
        )

    import uuid
    request_id = getattr(request.state, 'request_id', None) if request else None
    if not request_id:
        request_id = str(uuid.uuid4())[:8]
    tenant_id = user.get("tenant_id", "t_default")
    user_id = user.get("user_id", "u_default")
    
    try:
        return await _confirm_trade_impl(confirmation_id, tenant_id, user_id, request_id)
    except HTTPException:
        # Re-raise HTTP exceptions as-is (they have proper status codes)
        raise
    except Exception as e:
        # Log the full stack trace for debugging
        # Note: Do NOT pass request_id in extra - the RequestIDMiddleware already
        # sets it via the log record factory, causing "Attempt to overwrite" errors.
        import traceback
        try:
            logger.error(
                "confirmation_internal_error: %s | req=%s | conf=%s | tenant=%s",
                str(e)[:500], request_id, confirmation_id, tenant_id
            )
        except Exception:
            pass  # Never let logging crash the error handler
        # Return a clean JSON error shape, never expose stack traces to client
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "error_code": "INTERNAL_ERROR",
                    "message": "Confirmation failed due to an internal error",
                    "request_id": request_id,
                    "remediation": None,
                }
            }
        )


async def _confirm_trade_impl(confirmation_id: str, tenant_id: str, user_id: str, request_id: str):
    """Internal implementation of confirm_trade to enable try/except wrapper."""

    # Validate confirmation_id format
    if not confirmation_id or not confirmation_id.startswith("conf_"):
        logger.warning(
            "confirmation_invalid_format: tenant=%s conf=%s",
            tenant_id, confirmation_id
        )
        raise HTTPException(status_code=400, detail="invalid_confirmation_id_format")

    logger.info(
        "confirmation_lookup_start: tenant=%s conf=%s user=%s",
        tenant_id, confirmation_id, user_id
    )

    # 1. Load confirmation
    confirmation = confirmations_repo.get_by_id(tenant_id, confirmation_id)
    if not confirmation:
        # Debug: check if exists for different tenant
        debug_check = confirmations_repo.get_by_id_debug(confirmation_id)
        logger.warning(
            "confirmation_lookup_failed: tenant=%s conf=%s reason=not_found exists_other=%s actual_tenant=%s",
            tenant_id, confirmation_id, debug_check is not None,
            debug_check.get("tenant_id") if debug_check else None
        )
        raise HTTPException(status_code=404, detail="confirmation_not_found")

    # 2. Check status - must be PENDING
    if confirmation["status"] != "PENDING":
        status = confirmation["status"]
        logger.info(
            "confirmation_already_%s: tenant=%s conf=%s",
            status, tenant_id, confirmation_id
        )
        # Include run_id so frontend can track the existing run
        existing_run_id = confirmation["run_id"] if isinstance(confirmation, dict) and "run_id" in confirmation else None
        return {
            "status": status,
            "message": f"Confirmation is already {status}",
            "confirmation_id": confirmation_id,
            "run_id": existing_run_id,
            "already_confirmed": True,
        }

    # 3. Check expiration
    expires_at = datetime.fromisoformat(confirmation["expires_at"])
    if datetime.utcnow() > expires_at:
        confirmations_repo.mark_expired(tenant_id, confirmation_id)
        logger.info(
            "confirmation_expired: tenant=%s conf=%s",
            tenant_id, confirmation_id
        )
        return {
            "status": "EXPIRED",
            "message": "Confirmation expired. Please submit a new trade request.",
            "confirmation_id": confirmation_id
        }

    # 4a. Parse proposal FIRST so we can check mode before marking confirmed
    try:
        proposal = json.loads(confirmation["proposal_json"])
    except Exception:
        proposal = {}

    side = proposal.get("side", "buy")
    asset = proposal.get("asset", "BTC")
    amount_usd = proposal.get("amount_usd", 10.0)
    mode = confirmation["mode"]

    # S1: Block LIVE trades if master kill switch is active
    # MUST happen BEFORE mark_confirmed to avoid leaving confirmation in
    # CONFIRMED state with no run when LIVE is disabled.
    if mode == "LIVE":
        from backend.core.config import get_settings
        settings = get_settings()
        if settings.trading_disable_live:
            logger.warning("LIVE trade blocked by TRADING_DISABLE_LIVE: conf=%s tenant=%s", confirmation_id, tenant_id)
            raise HTTPException(status_code=403, detail={
                "error": {
                    "code": "LIVE_DISABLED",
                    "error_code": "LIVE_DISABLED",
                    "message": "LIVE trading is disabled. The trade was not executed.",
                    "request_id": request_id,
                    "remediation": "Set TRADING_DISABLE_LIVE=false and ENABLE_LIVE_TRADING=true in your environment, then restart the backend.",
                }
            })

    # 4b. Mark confirmed (only after LIVE check passes)
    # Single-use: if another concurrent request already confirmed, return early
    was_updated = confirmations_repo.mark_confirmed(tenant_id, confirmation_id)
    if not was_updated:
        # Another thread/request already confirmed this – reload to return run_id
        reloaded = confirmations_repo.get_by_id(tenant_id, confirmation_id)
        existing_run_id = reloaded["run_id"] if reloaded and "run_id" in reloaded else None
        # D1: Check if there's already a RUNNING run for this confirmation
        if existing_run_id:
            from backend.db.connect import get_conn as _gc
            with _gc() as _c:
                _cur = _c.cursor()
                _cur.execute("SELECT status FROM runs WHERE run_id = ?", (existing_run_id,))
                _row = _cur.fetchone()
                if _row and _row["status"] == "RUNNING":
                    return {
                        "status": "EXECUTING",
                        "message": "Trade is already executing",
                        "confirmation_id": confirmation_id,
                        "run_id": existing_run_id,
                    }
        return {
            "status": reloaded["status"] if reloaded else "CONFIRMED",
            "message": "Confirmation already processed",
            "confirmation_id": confirmation_id,
            "run_id": existing_run_id,
            "already_confirmed": True,
        }

    # E1: Concurrency guard -- one active run per conversation (not per tenant)
    # This allows a tenant to have concurrent runs in different conversations.
    conf_conversation_id = confirmation.get("conversation_id") if isinstance(confirmation, dict) else None
    from backend.db.connect import get_conn as _get_conn_guard
    with _get_conn_guard() as _guard_conn:
        _guard_cur = _guard_conn.cursor()
        if conf_conversation_id:
            # Scoped guard: only block if there's an active run linked to the same conversation
            _guard_cur.execute(
                """SELECT r.run_id FROM runs r
                   JOIN messages m ON m.run_id = r.run_id
                   WHERE r.tenant_id = ? AND r.status IN ('CREATED','RUNNING')
                     AND m.conversation_id = ?
                   LIMIT 1""",
                (tenant_id, conf_conversation_id)
            )
        else:
            # Fallback: per-tenant guard when conversation_id is unavailable
            _guard_cur.execute(
                "SELECT run_id FROM runs WHERE tenant_id = ? AND status IN ('CREATED','RUNNING') LIMIT 1",
                (tenant_id,)
            )
        active_row = _guard_cur.fetchone()
        if active_row:
            logger.warning(
                "concurrency_guard: tenant=%s conv=%s already has RUNNING run=%s, blocking new run for conf=%s",
                tenant_id, conf_conversation_id, active_row["run_id"], confirmation_id
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "code": "RUN_ALREADY_ACTIVE",
                        "error_code": "RUN_ALREADY_ACTIVE",
                        "message": "A trade is currently executing. Wait for it to complete.",
                        "request_id": request_id,
                        "active_run_id": active_row["run_id"],
                    }
                }
            )

    lookback_hours = proposal.get("lookback_hours", 24)
    is_most_profitable = proposal.get("is_most_profitable", False)
    news_enabled = proposal.get("news_enabled", True)
    asset_class = proposal.get("asset_class", "CRYPTO")
    selection_result = proposal.get("selection_result")  # Pre-computed selection

    # ── DECISION LOCK: Determine the locked product_id at confirmation time ──
    # This product_id is immutable once confirmed. The execution node MUST use it.
    # First check if chat.py already stored it in the proposal
    locked_product_id = proposal.get("locked_product_id")  # May already be set

    # Build universe: use pre-selected asset if available, else build universe
    if selection_result and selection_result.get("selected_symbol"):
        # Use the pre-selected asset from the selection engine
        selected_symbol = selection_result["selected_symbol"]
        asset = selected_symbol  # Update asset to the selected one
        locked_product_id = f"{selected_symbol}-USD"
        universe = [locked_product_id]
        display_asset = f"{selected_symbol} (top performer)"
        logger.info(
            "DECISION_LOCK: Using pre-selected asset: %s product_id=%s (return: %s%%)",
            selected_symbol, locked_product_id, selection_result.get("selected_return_pct", "N/A")
        )
    elif is_most_profitable or asset == "AUTO":
        # Fallback: dynamically build universe (should rarely happen)
        try:
            from backend.services.coinbase_market_data import list_products
            products = list_products(quote="USD")
            # Filter out stablecoins and take top 25
            STABLECOINS = {"USDC", "USDT", "DAI", "BUSD", "TUSD", "USDP", "GUSD"}
            universe = [
                p["product_id"] for p in products
                if p.get("base_currency_id", "").upper() not in STABLECOINS
            ][:25]
            if not universe:
                universe = ["BTC-USD", "ETH-USD", "SOL-USD", "MATIC-USD", "AVAX-USD"]
        except Exception as e:
            logger.warning("Failed to fetch dynamic universe: %s", str(e)[:100])
            universe = ["BTC-USD", "ETH-USD", "SOL-USD", "MATIC-USD", "AVAX-USD"]
        display_asset = "most profitable crypto"
        # NOTE: locked_product_id stays None — should not happen if chat.py did its job
        logger.warning("DECISION_LOCK: No pre-selected asset for most_profitable, universe fallback")
    else:
        locked_product_id = f"{asset}-USD"
        universe = [locked_product_id]
        display_asset = asset

    # Map lookback_hours to window string
    if lookback_hours <= 1:
        window = "1h"
    elif lookback_hours <= 24:
        window = "24h"
    elif lookback_hours <= 168:
        window = f"{lookback_hours}h"
    else:
        window = "7d"

    raw_command = f"Confirmed {mode} trade: {side} ${amount_usd} of {display_asset}"

    from backend.agents.schemas import TradeIntent

    parsed_intent = TradeIntent(
        side=side,
        budget_usd=amount_usd,
        universe=universe,
        raw_command=raw_command,
        metric="return",
        window=window,
        lookback_hours=lookback_hours
    )

    # 6. Create run
    run_id = create_run(
        tenant_id=tenant_id,
        execution_mode=mode
    )

    # 6b. Store run_id back to confirmation for recovery/linking
    from backend.db.connect import get_conn as _get_conn
    with _get_conn() as _conn:
        _cur = _conn.cursor()
        _cur.execute(
            "UPDATE trade_confirmations SET run_id = ? WHERE id = ? AND tenant_id = ?",
            (run_id, confirmation_id, tenant_id)
        )
        _conn.commit()

    # 7. Build proper execution plan via planner
    execution_plan = plan_execution(parsed_intent, run_id)
    execution_plan_dict = execution_plan.dict()

    # For direct asset (not "most profitable"), pre-select the asset
    if not is_most_profitable and asset != "AUTO":
        symbol = f"{asset}-USD"
        execution_plan_dict["selected_asset"] = symbol
        execution_plan_dict["selected_order"] = {
            "symbol": symbol,
            "side": side,
            "notional_usd": amount_usd
        }

    # 8. Update run with command_text, intent, and execution plan
    from backend.db.connect import get_conn
    from backend.api.routes.utils import json_dumps

    metadata = {
        "intent": "TRADE_EXECUTION",
        "confirmed": True,
        "side": side,
        "asset": asset,
        "amount_usd": amount_usd,
        "mode": mode,
        "confirmation_id": confirmation_id,
        "is_most_profitable": is_most_profitable,
        "lookback_hours": lookback_hours,
        "universe": universe,
        "locked_product_id": locked_product_id,
        "selection_basis": {
            "criteria": selection_result.get("why_explanation") if selection_result else None,
            "return_pct": selection_result.get("selected_return_pct") if selection_result else None,
            "window": selection_result.get("window_description") if selection_result else None,
        } if selection_result else None,
    }

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE runs
            SET command_text = ?, metadata_json = ?, intent_json = ?,
                parsed_intent_json = ?, execution_plan_json = ?,
                news_enabled = ?, locked_product_id = ?, tradability_verified = ?
            WHERE run_id = ?
            """,
            (
                raw_command,
                json_dumps(metadata),
                json_dumps(metadata),
                json_dumps(parsed_intent.dict()),
                json_dumps(execution_plan_dict),
                1 if news_enabled else 0,
                locked_product_id,
                1 if locked_product_id else 0,
                run_id
            )
        )
        conn.commit()

    logger.info(
        "DECISION_LOCK_PERSISTED: run=%s locked_product_id=%s tradability_verified=%s",
        run_id, locked_product_id, bool(locked_product_id)
    )

    # 9. Build response BEFORE starting thread (two-phase pattern, NF3)
    # If response construction fails, we must NOT have already started execution
    response_dict = {
        "run_id": run_id,
        "status": "EXECUTING",
        "executed": True,
        "order_status": "submitted",
        "confirmation_id": confirmation_id,
        "intent": "TRADE_EXECUTION",
        "execution_mode": mode,
        "news_enabled": news_enabled,
        "content": f"{mode} trade confirmed. Executing {side} ${amount_usd} of {display_asset}..."
    }

    # I2: Include stored financial insight from DB so frontend can render it
    try:
        insight_raw = confirmation["insight_json"] if "insight_json" in (confirmation.keys() if hasattr(confirmation, 'keys') else confirmation) else None
        if insight_raw:
            import json as _json
            response_dict["financial_insight"] = _json.loads(insight_raw) if isinstance(insight_raw, str) else insight_raw
    except Exception:
        pass  # Non-critical: skip if insight can't be parsed

    # S2: Structured audit log for every trade execution
    logger.info(
        "TRADE_EXEC_START: run=%s mode=%s asset=%s side=%s amount_usd=%s tenant=%s conf=%s most_profitable=%s",
        run_id, mode, asset, side, amount_usd, tenant_id, confirmation_id, is_most_profitable
    )

    # 10. Start background execution AFTER response is fully built
    import threading
    thread = threading.Thread(target=_run_in_thread, args=(run_id,), daemon=True)
    thread.start()

    return response_dict

@router.get("/{confirmation_id}/status")
async def get_confirmation_status(
    confirmation_id: str,
    user: dict = Depends(require_trader),
    request: Request = None
):
    """
    Get deterministic status of a confirmation (for recovery after network errors).
    Returns whether the trade was executed, order status, and run details.
    """
    import uuid
    request_id = getattr(request.state, 'request_id', None) if request else None
    if not request_id:
        request_id = str(uuid.uuid4())[:8]
    tenant_id = user.get("tenant_id", "t_default")

    confirmation = confirmations_repo.get_by_id(tenant_id, confirmation_id)
    if not confirmation:
        raise HTTPException(status_code=404, detail="confirmation_not_found")

    status = confirmation["status"]
    run_id = confirmation.get("run_id") if isinstance(confirmation, dict) else None

    # Determine execution state
    executed = status in ("CONFIRMED",)
    order_status = "not_submitted"
    order_id = None

    if run_id:
        try:
            from backend.db.connect import get_conn as _gc
            with _gc() as conn:
                cur = conn.cursor()
                # Check run status
                cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
                run_row = cur.fetchone()
                run_status = run_row["status"] if run_row else "UNKNOWN"

                # Check for orders
                cur.execute(
                    "SELECT order_id, status FROM orders WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
                    (run_id,)
                )
                order_row = cur.fetchone()
                if order_row:
                    order_id = order_row["order_id"]
                    order_status = order_row["status"].lower()
                elif run_status in ("COMPLETED", "RUNNING"):
                    order_status = "submitted"
                elif run_status == "FAILED":
                    order_status = "failed"
                    executed = False
        except Exception as e:
            logger.warning("status_check_db_error: %s", str(e)[:200])

    return {
        "confirmation_id": confirmation_id,
        "status": status,
        "executed": executed,
        "order_id": order_id,
        "order_status": order_status,
        "run_id": run_id,
        "request_id": request_id,
    }


@router.post("/{confirmation_id}/cancel")
async def cancel_trade(
    confirmation_id: str,
    request_body: CancelRequest = None,
    user: dict = Depends(require_trader),
    request: Request = None
):
    """
    Cancel a pending trade.
    """
    import uuid
    request_id = getattr(request.state, 'request_id', None) if request else None
    if not request_id:
        request_id = str(uuid.uuid4())[:8]
    tenant_id = user.get("tenant_id", "t_default")

    try:
        return await _cancel_trade_impl(confirmation_id, tenant_id, request_id)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        try:
            logger.error(
                "cancel_internal_error: %s | req=%s | conf=%s | tenant=%s",
                str(e)[:500], request_id, confirmation_id, tenant_id
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "error_code": "INTERNAL_ERROR",
                    "message": "Cancellation failed due to an internal error",
                    "request_id": request_id,
                    "remediation": None,
                }
            }
        )


async def _cancel_trade_impl(confirmation_id: str, tenant_id: str, request_id: str):
    """Internal implementation of cancel_trade to enable try/except wrapper."""

    logger.info("cancel_received: conf=%s tenant=%s", confirmation_id, tenant_id)

    # 1. Load confirmation
    confirmation = confirmations_repo.get_by_id(tenant_id, confirmation_id)
    if not confirmation:
        logger.warning(
            "confirmation_not_found_cancel: tenant=%s conf=%s",
            tenant_id, confirmation_id
        )
        raise HTTPException(status_code=404, detail="confirmation_not_found")

    # 2. Check status
    if confirmation["status"] != "PENDING":
        status = confirmation["status"]
        logger.info("cancel_rejected_already_%s: conf=%s", status, confirmation_id)
        run_id = confirmation["run_id"] if isinstance(confirmation, dict) and "run_id" in confirmation else None
        return {
            "status": status,
            "message": f"Confirmation is already {status}",
            "confirmation_id": confirmation_id,
            "run_id": run_id,
        }

    # 3. Mark cancelled
    confirmations_repo.mark_cancelled(tenant_id, confirmation_id)

    logger.info("confirmation_cancelled: conf=%s tenant=%s", confirmation_id, tenant_id)

    return {
        "status": "CANCELLED",
        "message": "Trade cancelled",
        "confirmation_id": confirmation_id
    }
