"""Chat command API endpoint with natural language parsing and confirmation flow."""
import asyncio
import json
import os
import re
import traceback
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator, Field
from typing import Optional, Dict, Any, List
from backend.api.deps import require_trader
from backend.orchestrator.runner import create_run, execute_run
from backend.agents.intent_parser import parse_intent_with_llm
from backend.db.connect import get_conn
from backend.core.logging import get_logger
from backend.core.ids import new_id

logger = get_logger(__name__)
DEBUG_PRECONFIRM_NEWS = os.getenv("DEBUG_PRECONFIRM_NEWS", "0").lower() in ("1", "true", "yes")
DEBUG_TRADE_DIAGNOSTICS = os.getenv("DEBUG_TRADE_DIAGNOSTICS", "0").lower() in ("1", "true", "yes")


def _safe_json_loads(s, default=None):
    """Parse JSON safely, returning default on failure."""
    if not s:
        return default if default is not None else {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}

router = APIRouter()


def _fetch_executable_state(tenant_id: str):
    from backend.services.executable_state import fetch_executable_state

    return fetch_executable_state(tenant_id)


def _build_product_catalog(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    from backend.services.product_catalog import get_product_catalog

    catalog = get_product_catalog()
    out: Dict[str, Dict[str, Any]] = {}
    for sym in symbols:
        s = (sym or "").upper().strip()
        if not s:
            continue
        for pid in (f"{s}-USD", f"{s}-USDC"):
            product = catalog.get_product(pid)
            if not product:
                continue
            out[pid] = {
                "trading_disabled": bool(getattr(product, "trading_disabled", False)),
                "is_disabled": str(getattr(product, "status", "online")).lower() != "online",
                "limit_only": False,
                "cancel_only": False,
            }
    return out


def _format_portfolio_analysis(brief: Dict[str, Any]) -> str:
    """Format PortfolioBrief into a strict 5-line narrative."""
    from backend.agents.narrative import format_portfolio_narrative
    return format_portfolio_narrative(brief)


async def _resolve_amount_from_portfolio(
    tenant_id: str,
    parsed_commands: List[Any],
    executable_state: Any = None,
) -> Dict[str, Any]:
    """
    Resolve derivable command fields from latest state.

    Resolves:
    - Portfolio references (largest holding)
    - amount_mode=ALL/PERCENT/QUANTITY/TARGET_ALLOC into amount_usd
    - SELL sizing from executable balances (available_qty), not snapshot qty
    """
    from backend.agents.trade_parser import AmountMode
    from backend.services.market_data import get_price

    issues: List[str] = []
    resolved = []
    positions: Dict[str, float] = {}
    balances: Dict[str, float] = {}
    total_value_usd = 0.0

    snapshot_ts = None
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT ts, positions_json, balances_json, total_value_usd
            FROM portfolio_snapshots
            WHERE tenant_id = ?
            ORDER BY ts DESC LIMIT 1
            """,
            (tenant_id,),
        )
        row = cursor.fetchone()
        if not row:
            return {
                "commands": parsed_commands,
                "snapshot_failed": True,
                "issues": ["Portfolio state could not be retrieved; no snapshot available."],
                "evidence_links": [{"label": "Portfolio page", "href": "url:/runs"}],
            }
        snapshot_ts = row["ts"]
        positions = _safe_json_loads(row["positions_json"], {})
        balances = _safe_json_loads(row["balances_json"], {})
        total_value_usd = float(row["total_value_usd"] or 0.0)

    # Build observed holding values using market data tool output.
    holding_values: Dict[str, Dict[str, float]] = {}
    for sym, qty in positions.items():
        qty_f = float(qty or 0.0)
        if qty_f <= 0:
            continue
        price = None
        try:
            price = float(get_price(sym))
        except Exception:
            price = None
        if price is None or price <= 0:
            issues.append(f"Current market price could not be determined for {sym}; unable to compute USD value.")
            continue
        holding_values[sym.upper()] = {"qty": qty_f, "price": price, "usd_value": qty_f * price}

    for parsed in parsed_commands:
        # Resolve "largest holding" reference.
        if getattr(parsed, "is_portfolio_reference", False) and getattr(parsed, "portfolio_ref_type", None) == "largest_holding":
            if holding_values:
                largest_sym = max(holding_values.items(), key=lambda kv: kv[1]["usd_value"])[0]
                parsed.asset = largest_sym
                parsed.venue_symbol = f"{largest_sym}-USD"
                parsed.resolution_source = "portfolio"
            else:
                issues.append("No holdings available to identify the largest position.")

        if not parsed.asset and parsed.amount_mode != AmountMode.TARGET_ALLOC.value:
            resolved.append(parsed)
            continue

        asset = (parsed.asset or "").upper()
        state_balance = None
        if executable_state is not None:
            state_balance = (getattr(executable_state, "balances", {}) or {}).get(asset)
        available_qty = float(getattr(state_balance, "available_qty", 0.0) or 0.0) if state_balance else 0.0
        hold_qty = float(getattr(state_balance, "hold_qty", 0.0) or 0.0) if state_balance else 0.0
        holding = holding_values.get(asset)

        if parsed.amount_mode == AmountMode.ALL.value:
            # For SELL, ALL means full executable quantity now.
            if (parsed.side or "").lower() == "sell":
                if state_balance is None:
                    issues.append(f"{asset} is not held in executable balances.")
                    parsed._resolution_status = "NOT_HELD"
                elif available_qty <= 0 and hold_qty > 0:
                    issues.append(f"{asset} funds are on hold and not currently executable.")
                    parsed._resolution_status = "FUNDS_ON_HOLD"
                elif available_qty <= 0:
                    issues.append(f"Available quantity is 0 for {asset}.")
                    parsed._resolution_status = "QTY_ZERO"
                else:
                    parsed.amount_qty = float(available_qty)
                    if holding:
                        parsed.amount_usd = float(holding["price"]) * float(available_qty)
                    # else: leave amount_usd as-is (None = display unavailable, NOT blocked)
            elif not holding:
                issues.append(f"No position data available for {asset} in the current snapshot.")
                parsed._resolution_status = "NOT_HELD"
            else:
                parsed.amount_usd = float(holding["usd_value"])
                parsed.amount_qty = float(holding["qty"])

        elif parsed.amount_mode == AmountMode.PERCENT.value and parsed.amount_pct is not None:
            if (parsed.side or "").lower() == "sell":
                if state_balance is None:
                    issues.append(f"{asset} is not held in executable balances.")
                    parsed._resolution_status = "NOT_HELD"
                elif available_qty <= 0 and hold_qty > 0:
                    issues.append(f"{asset} funds are on hold and not currently executable.")
                    parsed._resolution_status = "FUNDS_ON_HOLD"
                elif available_qty <= 0:
                    issues.append(f"Available quantity is 0 for {asset}.")
                    parsed._resolution_status = "QTY_ZERO"
                else:
                    pct = float(parsed.amount_pct) / 100.0
                    qty = float(available_qty) * pct
                    parsed.amount_qty = qty
                    if holding:
                        parsed.amount_usd = qty * float(holding["price"])
                    # else: leave amount_usd as-is (None = display unavailable, NOT blocked)
            elif not holding:
                issues.append(f"No position data available for {asset} in the current snapshot.")
                parsed._resolution_status = "NOT_HELD"
            else:
                parsed.amount_usd = float(holding["usd_value"]) * float(parsed.amount_pct) / 100.0

        elif parsed.amount_mode == AmountMode.QUANTITY.value and parsed.amount_qty is not None:
            compare_qty = available_qty if (parsed.side or "").lower() == "sell" else float(positions.get(asset, balances.get(asset, 0.0)) or 0.0)
            if parsed.amount_qty > compare_qty + 1e-12:
                issues.append(
                    f"Requested quantity {parsed.amount_qty:g} {asset} exceeds available quantity {compare_qty:g}."
                )
                parsed._resolution_status = "QTY_MISSING"
            elif not holding:
                if (parsed.side or "").lower() == "sell":
                    if state_balance is None:
                        issues.append(f"{asset} is not held in executable balances.")
                        parsed._resolution_status = "NOT_HELD"
                    elif available_qty <= 0 and hold_qty > 0:
                        issues.append(f"{asset} funds are on hold and not currently executable.")
                        parsed._resolution_status = "FUNDS_ON_HOLD"
                    else:
                        issues.append(f"Available quantity is 0 for {asset}.")
                        parsed._resolution_status = "QTY_ZERO"
                else:
                    issues.append(f"No position data available for {asset} in the current snapshot.")
                    parsed._resolution_status = "QTY_MISSING"
            elif (parsed.side or "").lower() == "sell" and available_qty <= 0 and hold_qty > 0:
                issues.append(f"{asset} funds are on hold and not currently executable.")
                parsed._resolution_status = "FUNDS_ON_HOLD"
            elif (parsed.side or "").lower() == "sell" and available_qty <= 0:
                issues.append(f"Available quantity is 0 for {asset}.")
                parsed._resolution_status = "QTY_MISSING"
            else:
                parsed.amount_usd = float(parsed.amount_qty) * float(holding["price"])

        elif parsed.amount_mode == AmountMode.TARGET_ALLOC.value and parsed.amount_pct is not None:
            if total_value_usd <= 0:
                issues.append("Portfolio total value is unavailable for target allocation.")
                parsed._resolution_status = "QTY_MISSING"
            else:
                target_value = total_value_usd * float(parsed.amount_pct) / 100.0
                current_value = float(holding["usd_value"]) if holding else 0.0
                delta = target_value - current_value
                parsed.side = "buy" if delta > 0 else "sell"
                parsed.amount_usd = abs(delta)
                if parsed.amount_usd <= 0:
                    issues.append(f"{asset} is already at approximately {parsed.amount_pct:.2f}% allocation.")

        resolved.append(parsed)

    # Evidence label uses the requested trade assets, not all snapshot holdings.
    requested_product_ids = []
    for p in parsed_commands:
        if p.asset:
            pid = p.venue_symbol or f"{p.asset.upper()}-USD"
            if pid not in requested_product_ids:
                requested_product_ids.append(pid)
    evidence_links = []
    ts_label = f"{snapshot_ts} UTC" if snapshot_ts else "latest"
    source = getattr(executable_state, "source", "state") if executable_state else "state"
    evidence_links.append({
        "label": "Executable balances snapshot",
        "href": "url:/runs",
    })
    evidence_links.append({
        "label": f"Portfolio snapshot view ({ts_label})",
        "href": "url:/runs",
    })
    quote_label = ", ".join(requested_product_ids[:3]) if requested_product_ids else None
    if quote_label:
        evidence_links.append({
            "label": f"Market quotes ({quote_label})",
            "href": "url:/runs",
        })

    return {
        "commands": resolved,
        "snapshot_failed": False,
        "issues": issues,
        "evidence_links": evidence_links,
        "snapshot_ts": snapshot_ts,
        "positions": positions,
    }


def _format_asset_holdings_response(asset: str, brief: Dict[str, Any]) -> str:
    """Format a focused response for a specific asset holdings query."""
    from backend.agents.narrative import format_asset_holdings_narrative
    return format_asset_holdings_narrative(asset, brief)


async def _check_min_notional(asset: str, asset_class: str = "CRYPTO") -> Dict[str, Any]:
    """
    Check the minimum notional (order size) for a product on Coinbase.

    Returns:
        {
            "min_notional_usd": float,
            "product_id": str,
            "error": str or None
        }
    """
    from backend.core.config import get_settings

    # Default minimum notional for crypto (Coinbase generally allows >= $1)
    DEFAULT_MIN_NOTIONAL = 1.0

    result = {
        "min_notional_usd": DEFAULT_MIN_NOTIONAL,
        "product_id": f"{asset.upper()}-USD",
        "error": None
    }

    # For stocks or AUTO, use default
    if asset_class == "STOCK" or asset == "AUTO":
        return result

    settings = get_settings()

    # Try to fetch product details from Coinbase
    if settings.coinbase_api_key_name and settings.coinbase_api_private_key:
        try:
            from backend.providers.coinbase_provider import CoinbaseProvider
            import httpx

            provider = CoinbaseProvider()
            product_id = f"{asset.upper()}-USD"
            path = f"/api/v3/brokerage/products/{product_id}"
            headers = provider._get_headers("GET", path)

            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"https://api.coinbase.com{path}", headers=headers)
                if response.status_code == 200:
                    product_data = response.json()
                    min_market_funds = product_data.get("min_market_funds")
                    if min_market_funds:
                        result["min_notional_usd"] = float(min_market_funds)
        except Exception as e:
            logger.warning(f"Could not fetch min notional for {asset}: {e}")
            # Use default

    return result


class CommandRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="Natural language command")
    conversation_id: Optional[str] = None  # For state tracking
    confirmation_id: Optional[str] = None  # For confirming a specific trade
    news_enabled: Optional[bool] = None  # Toggle for news analysis (None = use default True)

    model_config = {"extra": "ignore"}

    @field_validator('text')
    @classmethod
    def validate_text(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Command text cannot be empty")
        v = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', v)
        v = re.sub(r'[ \t]+', ' ', v)
        v = re.sub(r'\n{3,}', '\n\n', v)
        v = v.strip()
        if len(v) > 5000:
            raise ValueError("Command text exceeds 5000 characters")
        return v


class CommandResponse(BaseModel):
    run_id: Optional[str] = None
    parsed_intent: Optional[dict] = None
    trace_id: Optional[str] = None
    content: Optional[str] = None
    intent: Optional[str] = None
    status: Optional[str] = None


@router.post("/command")
async def chat_command(
    request_body: CommandRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_trader),
    request: Request = None
):
    """
    Execute natural language command with confirmation flow.

    Flow:
    1. Classify intent
    2. Handle GREETING/CAPABILITIES/OUT_OF_SCOPE (message-only)
    3. Check for CONFIRM/CANCEL commands
    4. Parse trade command
    5. Check for missing parameters
    6. Store pending trade and request confirmation
    7. Execute trade only after CONFIRM
    """
    request_id = getattr(request.state, 'request_id', None) if request else None
    if not request_id:
        request_id = str(uuid.uuid4())[:8]
    try:
        return await _chat_command_impl(request_body, background_tasks, user, request, request_id)
    except HTTPException:
        raise
    except Exception as e:
        # Note: Do NOT pass request_id in extra - the RequestIDMiddleware already
        # sets it via the log record factory. Passing it in extra causes
        # "Attempt to overwrite 'request_id' in LogRecord" which crashes the handler.
        try:
            logger.error(
                "chat_command_internal_error: %s | req=%s | text=%s",
                str(e)[:200],
                request_id,
                request_body.text[:100] if request_body else "N/A"
            )
        except Exception:
            pass  # Never let logging crash the error handler
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": f"Command failed: {str(e)[:200]}",
                    "request_id": request_id
                },
                "content": "Something went wrong processing your request.",
                "run_id": None,
                "intent": "ERROR",
                "status": "FAILED",
                "request_id": request_id
            },
            headers={"X-Request-ID": request_id}
        )


async def _chat_command_impl(
    request_body: CommandRequest,
    background_tasks: BackgroundTasks,
    user: dict,
    request: Request,
    request_id: str
):
    """Internal implementation of chat_command with full error propagation to caller."""
    from backend.agents.intent_router import classify_intent, IntentType
    from backend.agents.trade_parser import is_missing_amount
    from backend.services.conversation_state import (
        get_pending_trade, store_pending_trade, clear_pending_trade, PendingTrade
    )
    from backend.agents.response_templates import (
        greeting_response, capabilities_response, out_of_scope_response,
        app_diagnostics_response, missing_amount_prompt, trade_confirmation_prompt,
        trade_cancelled_response, confirmation_not_recognized_response,
        pending_trade_expired_response
    )
    from backend.core.config import get_settings
    
    settings = get_settings()
    text = request_body.text.strip()
    text_upper = text.upper()
    conversation_id = request_body.conversation_id
    
    # STEP 1: Check for CONFIRM/CANCEL commands first
    if text_upper in ["CONFIRM", "CONFIRM LIVE"]:
        from backend.db.repo.trade_confirmations_repo import TradeConfirmationsRepo
        from backend.agents.schemas import TradeIntent
        from backend.api.routes.utils import json_dumps
        import json as json_module

        tenant_id = user.get("tenant_id", "t_default")
        user_id = user.get("user_id", "u_default")
        confirmation_id = request_body.confirmation_id

        # Try to find confirmation: 1) from request, 2) from DB by conversation, 3) from in-memory
        repo = TradeConfirmationsRepo()
        confirmation = None

        if confirmation_id:
            confirmation = repo.get_by_id(tenant_id, confirmation_id)
            logger.info(f"Confirm received via confirmation_id={confirmation_id}, tenant={tenant_id}")
        elif conversation_id:
            confirmation = repo.get_latest_pending_for_conversation(tenant_id, conversation_id)
            if confirmation:
                confirmation_id = confirmation["id"]
                logger.info(f"Confirm received via conversation lookup, confirmation_id={confirmation_id}, tenant={tenant_id}")

        # If no DB confirmation found, try in-memory as fallback
        if not confirmation and conversation_id:
            pending = get_pending_trade(conversation_id)
            if pending:
                # S1: Block LIVE trades if master kill switch is active
                if pending.mode == "LIVE":
                    _settings = get_settings()
                    if _settings.trading_disable_live:
                        return JSONResponse(status_code=403, content={
                            "error": {"code": "LIVE_DISABLED", "message": "LIVE trading is disabled via TRADING_DISABLE_LIVE"},
                            "request_id": request_id
                        })

                # Execute from in-memory pending trade
                clear_pending_trade(conversation_id)

                parsed_intent = parse_intent_with_llm(
                    f"{pending.side} ${pending.amount_usd} of {pending.asset}",
                    budget_usd=pending.amount_usd,
                    universe=[f"{pending.asset}-USD"],
                    lookback_hours=pending.lookback_hours
                )

                run_id = create_run(
                    tenant_id=tenant_id,
                    execution_mode=pending.mode
                )

                # Store metadata via UPDATE (create_run only accepts tenant_id, execution_mode, source_run_id)
                from backend.api.routes.utils import json_dumps
                metadata = {
                    "intent": "TRADE_EXECUTION",
                    "confirmed": True,
                    "side": pending.side,
                    "asset": pending.asset,
                    "amount_usd": pending.amount_usd,
                    "mode": pending.mode
                }
                with get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE runs SET metadata_json = ?, intent_json = ? WHERE run_id = ?",
                        (json_dumps(metadata), json_dumps(metadata), run_id)
                    )
                    conn.commit()

                # Build response BEFORE side effect (two-phase pattern, NF4)
                from backend.agents.narrative import format_trade_execution_narrative
                response_content = {
                    "run_id": run_id,
                    "parsed_intent": parsed_intent.model_dump(),
                    "content": format_trade_execution_narrative(
                        side=pending.side,
                        amount_usd=pending.amount_usd,
                        asset=pending.asset,
                        run_id=run_id,
                    ),
                    "intent": "TRADE_EXECUTION",
                    "status": "EXECUTING",
                    "request_id": request_id
                }

                logger.info(f"Executing confirmed {pending.mode} trade (in-memory): {pending.side} ${pending.amount_usd} {pending.asset}, run_id={run_id}")

                background_tasks.add_task(execute_run, run_id=run_id)

                return JSONResponse(content=response_content)

        # If no confirmation found anywhere
        if not confirmation:
            return JSONResponse(content={
                "content": "No pending trade found. Please submit a new trade request or use the CONFIRM button in the conversation.",
                "run_id": None,
                "intent": "CONFIRMATION_NOT_FOUND",
                "status": "ERROR",
                "request_id": request_id
            })

        # Check status
        if confirmation["status"] != "PENDING":
            return JSONResponse(content={
                "content": f"This trade confirmation is already {confirmation['status'].lower()}.",
                "run_id": None,
                "status": confirmation["status"],
                "request_id": request_id
            })

        # Check expiration
        from datetime import datetime
        try:
            expires_at = datetime.fromisoformat(confirmation["expires_at"])
        except (ValueError, TypeError):
            expires_at = datetime.utcnow()  # Treat malformed as expired
        if datetime.utcnow() > expires_at:
            repo.mark_expired(tenant_id, confirmation_id)
            resp = pending_trade_expired_response()
            resp["request_id"] = request_id
            return JSONResponse(content=resp)

        # Mark confirmed (idempotent: mark_confirmed returns False if already confirmed)
        was_updated = repo.mark_confirmed(tenant_id, confirmation_id)
        if not was_updated:
            # Already confirmed by another request – check for existing run
            reloaded = repo.get_by_id(tenant_id, confirmation_id)
            existing_run_id = reloaded.get("run_id") if reloaded and hasattr(reloaded, 'get') else (reloaded["run_id"] if reloaded and "run_id" in reloaded else None)
            if existing_run_id:
                return JSONResponse(content={
                    "run_id": existing_run_id,
                    "status": "EXECUTING",
                    "message": "Confirmation already processed",
                    "confirmation_id": confirmation_id,
                    "intent": "TRADE_EXECUTION",
                    "request_id": request_id
                })

        # Concurrency guard: one active run per tenant (include CREATED/PAUSED)
        with get_conn() as _gc:
            _gcur = _gc.cursor()
            _gcur.execute(
                "SELECT run_id FROM runs WHERE tenant_id = ? AND status IN ('RUNNING','CREATED') LIMIT 1",
                (tenant_id,)
            )
            _active = _gcur.fetchone()
            if _active:
                return JSONResponse(status_code=409, content={
                    "error": {
                        "code": "RUN_ALREADY_ACTIVE",
                        "message": "A trade is currently executing. Wait for it to complete.",
                        "active_run_id": _active["run_id"],
                    },
                    "request_id": request_id
                })

        # Clear in-memory state if exists
        if conversation_id:
            clear_pending_trade(conversation_id)

        # Parse proposal and execute SEQUENTIALLY (one order per confirmation).
        from backend.agents.planner import plan_execution

        try:
            proposal = json_module.loads(confirmation["proposal_json"])
        except Exception:
            proposal = {}

        actions = proposal.get("actions")
        if not actions:
            actions = [{
                "side": proposal.get("side", "buy"),
                "asset": proposal.get("asset", "BTC"),
                "amount_usd": proposal.get("amount_usd", 10.0),
                "mode": confirmation["mode"],
                "lookback_hours": proposal.get("lookback_hours", 24),
                "is_most_profitable": proposal.get("is_most_profitable", False),
                "asset_class": proposal.get("asset_class", "CRYPTO"),
                "step_index": 0,
                "step_status": "READY",
            }]

        current_idx = int(proposal.get("current_action_index", 0))
        is_sequential = bool(proposal.get("sequential", False)) and len(actions) > 1
        news_enabled = proposal.get("news_enabled", True)

        # Find the first READY action at or after current_action_index.
        current_action = None
        for idx in range(current_idx, len(actions)):
            if actions[idx].get("step_status") in ("READY", "QUEUED", None):
                current_action = actions[idx]
                current_idx = idx
                break

        if not current_action:
            return JSONResponse(content={
                "content": "All queued actions have been completed or are blocked. No further steps to execute.",
                "run_id": None,
                "intent": "TRADE_EXECUTION",
                "status": "COMPLETED",
                "request_id": request_id,
            })

        # Execute ONLY the current action.
        action = current_action
        side = action.get("side", "buy")
        asset = action.get("asset", "BTC")
        amount_usd = float(action.get("amount_usd", 10.0))
        mode = action.get("mode", confirmation["mode"])
        lookback_hours = float(action.get("lookback_hours", 24))
        is_most_profitable = bool(action.get("is_most_profitable", False))
        asset_class = action.get("asset_class", "CRYPTO")

        if mode == "LIVE":
            _settings = get_settings()
            if _settings.trading_disable_live:
                return JSONResponse(status_code=403, content={
                    "error": {
                        "code": "LIVE_DISABLED",
                        "message": "Live trading is disabled by safety policy.",
                    },
                    "request_id": request_id,
                })

        if lookback_hours <= 1:
            window = "1h"
        elif lookback_hours <= 24:
            window = "24h"
        elif lookback_hours <= 168:
            window = f"{lookback_hours}h"
        else:
            window = "7d"

        symbol = action.get("venue_symbol") or (f"{asset}-USD")
        universe = [symbol]
        qty_for_sell = action.get("base_size")
        raw_command = f"Confirmed {mode} trade: {side} ${amount_usd} of {asset}"

        parsed_intent = TradeIntent(
            side=side,
            budget_usd=amount_usd,
            universe=universe,
            raw_command=raw_command,
            metric="return",
            window=window,
            lookback_hours=int(lookback_hours),
        )

        run_id = create_run(tenant_id=tenant_id, execution_mode=mode)
        execution_plan = plan_execution(parsed_intent, run_id)
        execution_plan_dict = execution_plan.dict()
        if not is_most_profitable and asset != "AUTO":
            execution_plan_dict["selected_asset"] = symbol
            order_spec = {"symbol": symbol, "side": side, "notional_usd": amount_usd}
            if qty_for_sell and side.lower() == "sell":
                order_spec["qty"] = qty_for_sell
            execution_plan_dict["selected_order"] = order_spec

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
            "asset_class": asset_class,
            "news_enabled": news_enabled,
            "step_index": current_idx,
            "total_steps": len(actions),
        }

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE runs
                SET command_text = ?, metadata_json = ?, intent_json = ?,
                    parsed_intent_json = ?, execution_plan_json = ?,
                    news_enabled = ?, asset_class = ?
                WHERE run_id = ?
                """,
                (
                    raw_command,
                    json_dumps(metadata),
                    json_dumps(metadata),
                    json_dumps(parsed_intent.dict()),
                    json_dumps(execution_plan_dict),
                    1 if news_enabled else 0,
                    asset_class,
                    run_id,
                ),
            )
            conn.commit()

        background_tasks.add_task(execute_run, run_id=run_id)

        # Mark current action as EXECUTING and advance the index for the next confirmation.
        actions[current_idx]["step_status"] = "EXECUTING"
        actions[current_idx]["run_id"] = run_id
        next_idx = current_idx + 1

        remaining_actions = [a for a in actions[next_idx:] if a.get("step_status") in ("QUEUED", "READY", None)]

        # If sequential and there are remaining actions, re-preflight and store updated proposal.
        next_confirmation_id = None
        next_step_blocked_reason = None
        if is_sequential and remaining_actions:
            next_action = remaining_actions[0]
            try:
                from backend.services.trade_preflight import run_preflight as repreflight
                from backend.services.asset_resolver import resolve_from_executable_state, RESOLUTION_OK
                from backend.agents.trade_parser import ParsedTradeCommand
                next_exec_state = _fetch_executable_state(tenant_id)
                next_catalog = _build_product_catalog(list((getattr(next_exec_state, "balances", {}) or {}).keys()))
                repf_cmds = [ParsedTradeCommand(
                    side=next_action.get("side", "buy"),
                    asset=next_action.get("asset"),
                    amount_mode=next_action.get("amount_mode", "quote_usd"),
                    amount_usd=next_action.get("amount_usd"),
                    asset_class=next_action.get("asset_class", "CRYPTO"),
                )]
                refreshed = await _resolve_amount_from_portfolio(tenant_id, repf_cmds, next_exec_state)
                if refreshed.get("snapshot_failed"):
                    next_step_blocked_reason = "Portfolio state unavailable after Step " + str(current_idx + 1)
                    next_action["step_status"] = "BLOCKED"
                    next_action["blocked_reason"] = next_step_blocked_reason
                else:
                    refreshed_issues = refreshed.get("issues", [])
                    if refreshed_issues:
                        next_step_blocked_reason = "; ".join(refreshed_issues[:2])
                        next_action["step_status"] = "BLOCKED"
                        next_action["blocked_reason"] = next_step_blocked_reason
                    else:
                        refreshed_cmd = refreshed.get("commands", repf_cmds)[0]
                        resolution = None
                        if (refreshed_cmd.side or "").lower() == "sell" and refreshed_cmd.asset:
                            resolution = resolve_from_executable_state(refreshed_cmd.asset, next_exec_state, next_catalog)
                            if resolution.resolution_status != RESOLUTION_OK:
                                next_step_blocked_reason = resolution.user_message_if_blocked
                                next_action["step_status"] = "BLOCKED"
                                next_action["blocked_reason"] = next_step_blocked_reason
                                resolution = None
                        if next_action.get("step_status") == "BLOCKED":
                            raise ValueError(next_step_blocked_reason or "Next step blocked")
                        if refreshed_cmd.amount_usd and float(refreshed_cmd.amount_usd) > 0:
                            next_action["amount_usd"] = float(refreshed_cmd.amount_usd)
                        if getattr(refreshed_cmd, "amount_qty", None):
                            next_action["base_size"] = float(refreshed_cmd.amount_qty)
                        re_pf = await repreflight(
                            tenant_id=tenant_id,
                            side=refreshed_cmd.side,
                            asset=refreshed_cmd.asset,
                            amount_usd=float(refreshed_cmd.amount_usd or 0.0),
                            asset_class=refreshed_cmd.asset_class,
                            mode="LIVE",
                            executable_qty=(resolution.executable_qty if resolution else None),
                            hold_qty=(resolution.hold_qty if resolution else None),
                            product_flags=(resolution.product_flags if resolution else None),
                        )
                        if not re_pf.valid:
                            next_step_blocked_reason = re_pf.user_message or "Next step preflight failed"
                            next_action["step_status"] = "BLOCKED"
                            next_action["blocked_reason"] = next_step_blocked_reason
                        else:
                            next_action["step_status"] = "READY"
            except Exception as repf_err:
                logger.warning("Re-preflight for next step failed: %s", str(repf_err)[:200])
                if next_action.get("step_status") != "BLOCKED":
                    next_action["step_status"] = "READY"

            updated_proposal = dict(proposal)
            updated_proposal["actions"] = actions
            updated_proposal["current_action_index"] = next_idx
            next_confirmation_id = repo.create_pending(
                tenant_id=tenant_id,
                conversation_id=confirmation.get("conversation_id", f"ephemeral_{new_id('eph')}"),
                proposal_json=updated_proposal,
                mode=remaining_actions[0].get("mode", mode),
                user_id=user_id,
                ttl_seconds=300,
            )
            if news_enabled and next_confirmation_id:
                try:
                    next_asset = (next_action.get("asset") or "").strip().upper() or (
                        (next_action.get("venue_symbol") or "").split("-")[0].upper()
                    )
                    next_asset = next_asset or "UNKNOWN"
                    next_insight = await asyncio.wait_for(
                        generate_insight(
                            asset=next_asset,
                            side=next_action.get("side", "buy"),
                            notional_usd=float(next_action.get("amount_usd", 0.0) or 0.0),
                            asset_class=next_action.get("asset_class", "CRYPTO"),
                            news_enabled=True,
                            mode=next_action.get("mode", mode),
                            lookback_hours=int(next_action.get("lookback_hours") or 24),
                            request_id=request_id,
                        ),
                        timeout=12.0,
                    )
                    next_insight["current_step_asset"] = next_asset
                    next_insight["queued_steps_notice"] = "Queued steps will run news checks at execution time."
                    repo.update_insight(next_confirmation_id, next_insight)
                except Exception as next_insight_err:
                    logger.warning(
                        "next_step_insight_failed request_id=%s next_conf=%s asset=%s err=%s",
                        request_id,
                        next_confirmation_id,
                        next_action.get("asset"),
                        str(next_insight_err)[:200],
                    )

        from backend.agents.narrative import format_trade_execution_narrative
        base_narrative = format_trade_execution_narrative(
            side=side,
            amount_usd=amount_usd,
            asset=asset,
            run_id=run_id,
        )

        response_content = {
            "run_id": run_id,
            "run_ids": [run_id],
            "parsed_intent": parsed_intent.dict(),
            "content": base_narrative,
            "intent": "TRADE_EXECUTION",
            "status": "EXECUTING",
            "confirmation_id": confirmation_id,
            "request_id": request_id,
            "step_index": current_idx,
            "total_steps": len(actions),
            "remaining_steps": len(remaining_actions),
            "next_confirmation_id": next_confirmation_id,
            "next_step_blocked": next_step_blocked_reason,
            "pending_trade": {
                "side": side,
                "asset": asset,
                "amount_usd": amount_usd,
                "mode": mode,
            },
        }
        return JSONResponse(content=response_content)
    
    if text_upper == "CANCEL":
        from backend.db.repo.trade_confirmations_repo import TradeConfirmationsRepo

        tenant_id = user.get("tenant_id", "t_default")
        confirmation_id = request_body.confirmation_id

        # Cancel in-memory pending trade
        if conversation_id:
            clear_pending_trade(conversation_id)

        # Cancel in DB if confirmation_id provided or found via conversation
        repo = TradeConfirmationsRepo()
        if confirmation_id:
            repo.mark_cancelled(tenant_id, confirmation_id)
            logger.info(f"Confirmation cancelled: confirmation_id={confirmation_id}, tenant={tenant_id}")
        elif conversation_id:
            confirmation = repo.get_latest_pending_for_conversation(tenant_id, conversation_id)
            if confirmation:
                repo.mark_cancelled(tenant_id, confirmation["id"])
                logger.info(f"Confirmation cancelled via conversation: confirmation_id={confirmation['id']}, tenant={tenant_id}")

        resp = trade_cancelled_response()
        resp["request_id"] = request_id
        return JSONResponse(content=resp)
    
    # STEP 2: Classify intent
    intent = classify_intent(text)
    logger.info(f"Classified intent: {intent} for command: {text[:100]}")
    
    # STEP 3: Handle message-only intents
    if intent == IntentType.GREETING:
        resp = greeting_response()
        resp["request_id"] = request_id
        return JSONResponse(content=resp)

    if intent == IntentType.CAPABILITIES_HELP:
        resp = capabilities_response()
        resp["request_id"] = request_id
        return JSONResponse(content=resp)

    if intent == IntentType.OUT_OF_SCOPE:
        resp = out_of_scope_response()
        resp["request_id"] = request_id
        return JSONResponse(content=resp)

    if intent == IntentType.APP_DIAGNOSTICS:
        resp = app_diagnostics_response(text)
        resp["request_id"] = request_id
        return JSONResponse(content=resp)
    
    # STEP 4: Handle TRADE_EXECUTION intent
    if intent == IntentType.TRADE_EXECUTION:
        from backend.agents.trade_parser import parse_trade_commands, AmountMode
        from backend.services.trade_preflight import run_preflight
        from backend.db.repo.trade_confirmations_repo import TradeConfirmationsRepo
        from backend.services.pre_confirm_insight import generate_insight
        from backend.services.asset_selection_engine import select_asset, selection_result_to_dict
        from backend.services.relative_asset_selector import select_relative_asset
        from backend.services.asset_resolver import (
            resolve_from_executable_state,
            resolve_all_holdings,
            RESOLUTION_OK,
        )
        from backend.agents.trade_reasoner import reason_about_plan

        tenant_id = user.get("tenant_id", "t_default")
        user_id = user.get("user_id", "u_default")
        news_enabled = request_body.news_enabled if request_body.news_enabled is not None else True
        logger.info(
            "trade_news_toggle request_id=%s intent=TRADE_EXECUTION news_enabled=%s",
            request_id,
            news_enabled,
        )
        parsed_commands = parse_trade_commands(text)
        if not parsed_commands:
            from backend.agents.narrative import format_no_parse_narrative, build_narrative_structured
            no_parse_content = format_no_parse_narrative()
            return JSONResponse(content={
                "content": no_parse_content,
                "run_id": None,
                "intent": "TRADE_EXECUTION",
                "status": "REJECTED",
                "request_id": request_id,
                "narrative_structured": build_narrative_structured(no_parse_content),
            })

        executable_state = _fetch_executable_state(tenant_id)
        state_symbols = list((getattr(executable_state, "balances", {}) or {}).keys())
        product_catalog = _build_product_catalog(state_symbols)

        # Expand "sell all holdings" into per-asset SELL actions from executable balances.
        expanded_commands: List[Any] = []
        for parsed in parsed_commands:
            is_multi_sell_all = (
                (parsed.side or "").lower() == "sell"
                and parsed.amount_mode == AmountMode.ALL.value
                and not parsed.asset
            )
            if not is_multi_sell_all:
                expanded_commands.append(parsed)
                continue
            tradable, skipped = resolve_all_holdings(executable_state, product_catalog)
            if tradable:
                for r in tradable:
                    cmd = parsed.model_copy(deep=True)
                    cmd.asset = r.symbol
                    cmd.venue_symbol = r.product_id
                    cmd.amount_qty = float(r.executable_qty or 0.0)
                    cmd.amount_mode = AmountMode.ALL.value
                    expanded_commands.append(cmd)
            else:
                expanded_commands.append(parsed)
            for r in skipped:
                parsed._expand_skipped = getattr(parsed, "_expand_skipped", []) + [r.user_message_if_blocked]
        parsed_commands = expanded_commands

        # State-first: fetch portfolio snapshot for reference + display value only.
        requires_state = any(
            (p.side or "").lower() in ("sell", "close")
            or getattr(p, "is_portfolio_reference", False)
            or p.amount_mode in ("all", "percent", "quantity", "target_alloc")
            for p in parsed_commands
        )
        state_issues: List[str] = []
        evidence_links: List[Dict[str, str]] = [{"label": "Command parse trace", "href": "url:/chat"}]

        resolved = await _resolve_amount_from_portfolio(tenant_id, parsed_commands, executable_state)

        if resolved.get("snapshot_failed"):
            if requires_state:
                from backend.agents.narrative import format_snapshot_failed_narrative, build_narrative_structured
                content = format_snapshot_failed_narrative()
                return JSONResponse(content={
                    "content": content,
                    "run_id": None,
                    "intent": "TRADE_EXECUTION",
                    "status": "REJECTED",
                    "request_id": request_id,
                    "narrative_structured": build_narrative_structured(content),
                    "suggestions": ["Analyze my portfolio"],
                })
            # For buy-only requests, proceed without snapshot data.
        else:
            parsed_commands = resolved.get("commands", parsed_commands)
            state_issues = list(resolved.get("issues", []))
            evidence_links = resolved.get("evidence_links", evidence_links)
            for p in parsed_commands:
                state_issues.extend(getattr(p, "_expand_skipped", []))

        # Phase 4: State coherence guard.
        # Trigger a balances refresh if EITHER:
        #   (a) snapshot is newer than balances by > 2 minutes (preventive staleness refresh), OR
        #   (b) snapshot shows asset qty > 0 but executable balances show 0 (reactive mismatch refresh).
        _forced_refresh = False
        _resolved_positions = resolved.get("positions", {}) if not resolved.get("snapshot_failed") else {}

        # (a) Timestamp-based staleness check
        _snapshot_ts_str = resolved.get("snapshot_ts") if not resolved.get("snapshot_failed") else None
        _balances_ts_str = getattr(executable_state, "fetched_at", None)
        _ts_stale = False
        if _snapshot_ts_str and _balances_ts_str:
            try:
                from datetime import datetime, timezone
                _snap_dt = datetime.fromisoformat(_snapshot_ts_str.replace("Z", "+00:00"))
                _bal_dt = datetime.fromisoformat(_balances_ts_str.replace("Z", "+00:00"))
                if (_snap_dt - _bal_dt).total_seconds() > 120:
                    _ts_stale = True
            except Exception:
                pass

        # (b) Qty-mismatch check
        _state_mismatch_assets = []
        for _p in parsed_commands:
            _a = (_p.asset or "").upper()
            if not _a or ((_p.side or "").lower() != "sell"):
                continue
            _snap_qty = float(_resolved_positions.get(_a, 0) or 0)
            _exec_bal = (getattr(executable_state, "balances", {}) or {}).get(_a)
            _exec_qty = float(getattr(_exec_bal, "available_qty", 0) or 0) if _exec_bal else 0.0
            if _snap_qty > 0 and _exec_qty <= 0:
                _state_mismatch_assets.append(_a)

        if _ts_stale or _state_mismatch_assets:
            _refresh_reason = []
            if _ts_stale:
                _refresh_reason.append(f"snapshot_ts={_snapshot_ts_str} is >2min newer than balances_fetched_at={_balances_ts_str}")
            if _state_mismatch_assets:
                _refresh_reason.append(f"qty_mismatch assets={_state_mismatch_assets}")
            logger.info("state_coherence_refresh: %s — refreshing balances", " | ".join(_refresh_reason))
            executable_state = _fetch_executable_state(tenant_id)
            state_symbols = list((getattr(executable_state, "balances", {}) or {}).keys())
            product_catalog = _build_product_catalog(state_symbols)
            _forced_refresh = True

        _existing_labels = {e.get("label") for e in evidence_links}
        for _ev in [
            {"label": "Executable balances snapshot", "href": "url:/runs"},
            {"label": "Product tradability check", "href": "url:/runs"},
            {"label": "Trade preflight report", "href": "url:/runs"},
        ]:
            if _ev["label"] not in _existing_labels:
                evidence_links.append(_ev)

        valid_actions: List[Dict[str, Any]] = []
        blocked_messages: List[str] = []
        blocked_suggestions: List[str] = []
        adjustment_messages: List[str] = []

        from backend.services.trade_preflight import HUMAN_MESSAGES as PREFLIGHT_MESSAGES

        for parsed in parsed_commands:
            selected_result_dict = None
            if parsed.asset_class == "AMBIGUOUS":
                blocked_messages.append(
                    f"{PREFLIGHT_MESSAGES['ASSET_NOT_FOUND']} ({parsed.asset or 'unknown'})"
                )
                continue

            if parsed.is_sell_last_purchase:
                from backend.services.symbol_resolver import get_last_purchase
                last = get_last_purchase(tenant_id)
                if not last:
                    blocked_messages.append("No recent purchase found to sell.")
                    continue
                parsed.asset = last.base_symbol
                parsed.venue_symbol = last.product_id
                parsed.side = "sell"
                parsed.resolution_source = last.source

            if not parsed.asset:
                try:
                    rel = await select_relative_asset(
                        command_text=text,
                        lookback_hours=float(parsed.lookback_hours or 24.0),
                        executable_state=executable_state,
                        product_catalog=product_catalog,
                    )
                except Exception:
                    rel = None
                if rel:
                    parsed.asset = rel.symbol
                    parsed.venue_symbol = rel.product_id
                    parsed.asset_class = "CRYPTO"
                    parsed.resolution_source = "relative_selector"
                    selected_result_dict = {
                        "selected_symbol": rel.symbol,
                        "selected_return_pct": round(float(rel.metric_value), 4),
                        "top_candidates": [{"symbol": rel.symbol, "product_id": rel.product_id}],
                        "universe_description": f"holdings universe ({rel.universe_size})",
                        "window_description": rel.timeframe_label,
                        "why_explanation": rel.rationale,
                        "fallback_used": False,
                        "lookback_hours": float(parsed.lookback_hours or 24.0),
                        "universe_size": rel.universe_size,
                        "evaluated_count": rel.universe_size,
                    }
                    label = f"Selection rationale ({rel.symbol}, {rel.timeframe_label})"
                    if not any((e.get("label") == label) for e in evidence_links):
                        evidence_links.append({"label": label, "href": "url:/runs"})

            if parsed.is_most_profitable and not parsed.asset:
                try:
                    if parsed.universe_constraint == "holdings_only":
                        rel = await select_relative_asset(
                            command_text=text,
                            lookback_hours=float(parsed.lookback_hours or 24.0),
                            executable_state=executable_state,
                            product_catalog=product_catalog,
                        )
                        if not rel:
                            blocked_messages.append(
                                "Could not determine which holding matches your request. "
                                "Try naming the asset directly (e.g. 'sell BTC')."
                            )
                            continue
                        parsed.asset = rel.symbol
                        parsed.venue_symbol = rel.product_id
                        parsed.asset_class = "CRYPTO"
                        parsed.resolution_source = "relative_selector"
                        selected_result_dict = {
                            "selected_symbol": rel.symbol,
                            "selected_return_pct": round(float(rel.metric_value), 4),
                            "top_candidates": [{"symbol": rel.symbol, "product_id": rel.product_id}],
                            "universe_description": f"holdings universe ({rel.universe_size})",
                            "window_description": rel.timeframe_label,
                            "why_explanation": rel.rationale,
                            "fallback_used": False,
                            "lookback_hours": float(parsed.lookback_hours or 24.0),
                            "universe_size": rel.universe_size,
                            "evaluated_count": rel.universe_size,
                        }
                    else:
                        selection = await select_asset(
                            criteria=parsed.selection_criteria or "highest_performing",
                            lookback_hours=parsed.lookback_hours,
                            notional_usd=parsed.amount_usd or 10.0,
                            universe_constraint=parsed.universe_constraint or "top_25_volume",
                            threshold_pct=parsed.threshold_pct,
                            asset_class=parsed.asset_class,
                        )
                        parsed.asset = selection.selected_symbol
                        parsed.venue_symbol = f"{selection.selected_symbol}-USD"
                        parsed.resolution_source = "selection_engine"
                        selected_result_dict = selection_result_to_dict(selection)
                except Exception as selection_err:
                    logger.warning("Asset selection failed: %s", str(selection_err)[:200])
                    blocked_messages.append(PREFLIGHT_MESSAGES["MARKET_UNAVAILABLE"])
                    continue

            # Heuristic fallback for "sell biggest loser/down the most" phrasing:
            # if no symbol resolved, use the largest executable non-fiat holding.
            if (
                not parsed.asset
                and (parsed.side or "").lower() == "sell"
                and ("biggest loser" in text.lower() or "down the most" in text.lower())
            ):
                balances_map = getattr(executable_state, "balances", {}) or {}
                candidates = []
                for _sym, _bal in balances_map.items():
                    sym_u = str(_sym or "").upper()
                    if not sym_u or sym_u in ("USD", "USDC", "USDT"):
                        continue
                    qty = float(getattr(_bal, "available_qty", 0.0) or 0.0)
                    if qty > 0:
                        candidates.append((sym_u, qty))
                if candidates:
                    candidates.sort(key=lambda x: x[1], reverse=True)
                    parsed.asset = candidates[0][0]
                    parsed.venue_symbol = f"{parsed.asset}-USD"

            if not parsed.asset and not parsed.is_most_profitable:
                blocked_messages.append(PREFLIGHT_MESSAGES["ASSET_NOT_FOUND"])
                continue

            resolution = None
            if (parsed.side or "").lower() == "sell" and parsed.asset:
                resolution = resolve_from_executable_state(parsed.asset, executable_state, product_catalog)
                parsed.venue_symbol = resolution.product_id or parsed.venue_symbol
                if resolution.resolution_status != RESOLUTION_OK:
                    blocked_messages.append(resolution.user_message_if_blocked)
                    continue
                if parsed.amount_mode == AmountMode.ALL.value:
                    parsed.amount_qty = float(resolution.executable_qty or 0.0)

            # Skip duplicate block if _resolve_amount_from_portfolio already
            # recorded a resolution_status explaining why amount is missing.
            already_blocked = getattr(parsed, "_resolution_status", None)
            if already_blocked:
                continue

            if DEBUG_TRADE_DIAGNOSTICS:
                _asset_upper_dbg = (parsed.asset or "").upper()
                _exec_bal_dbg = (getattr(executable_state, "balances", {}) or {}).get(_asset_upper_dbg)
                _avail_qty_dbg = float(getattr(_exec_bal_dbg, "available_qty", 0) or 0) if _exec_bal_dbg else 0.0
                logger.debug(
                    "trade_action_debug asset=%s side=%s amount_mode=%s "
                    "available_qty=%s balance_present=%s amount_usd=%s amount_qty=%s",
                    parsed.asset,
                    parsed.side,
                    parsed.amount_mode,
                    _avail_qty_dbg,
                    _exec_bal_dbg is not None,
                    parsed.amount_usd,
                    getattr(parsed, "amount_qty", None),
                )

            if is_missing_amount(parsed):
                blocked_messages.append(
                    f"Please specify quantity, percent, or quote amount for {parsed.asset or 'the asset'}."
                )
                continue

            if not parsed.side:
                blocked_messages.append(
                    f"Please specify whether to buy or sell {parsed.asset or 'the asset'}."
                )
                continue

            parsed.mode = "LIVE"
            if settings.trading_disable_live:
                # Downgrade LIVE -> PAPER when master kill switch is active
                parsed.mode = "PAPER"
                logger.info("Downgraded LIVE -> PAPER (trading_disable_live=true): tenant=%s", tenant_id)

            # For SELL ALL: executable qty is sufficient — USD value is display-only.
            _is_sell_all = (parsed.side or "").lower() == "sell" and parsed.amount_mode == AmountMode.ALL.value
            _has_qty = getattr(parsed, "amount_qty", None) is not None and float(parsed.amount_qty or 0) > 0
            _has_usd = parsed.amount_usd is not None and float(parsed.amount_usd or 0) > 0

            if not _has_usd and not _has_qty:
                # Truly nothing to trade — emit a specific reason code
                _asset_upper = (parsed.asset or "").upper()
                _bal = (getattr(executable_state, "balances", {}) or {}).get(_asset_upper)
                if _bal is None:
                    _code, _msg = "ASSET_NOT_IN_BALANCES", (
                        f"{_asset_upper} is not in your executable balances. "
                        "If the portfolio view shows this asset, it may be pending settlement "
                        "or on a different account."
                    )
                elif float(getattr(_bal, "hold_qty", 0) or 0) > 0 and float(getattr(_bal, "available_qty", 0) or 0) <= 0:
                    _code, _msg = "FUNDS_ON_HOLD", (
                        f"{_asset_upper} has funds on hold ({getattr(_bal, 'hold_qty', '?')} units) "
                        "with 0 available. Retry after hold clears."
                    )
                elif float(getattr(_bal, "available_qty", 0) or 0) <= 0:
                    _code, _msg = "NO_AVAILABLE_BALANCE", (
                        f"{_asset_upper} available balance is 0. Check your Coinbase account."
                    )
                else:
                    _code, _msg = "PRICE_UNAVAILABLE", (
                        f"Could not compute sell value for {_asset_upper} — market price unavailable. "
                        "Retry in a moment."
                    )
                blocked_messages.append(f"[{_code}] {_msg}")
                continue

            elif not _has_usd and _is_sell_all and _has_qty:
                # SELL ALL with qty but no USD price — proceed; USD is display-only.
                # Best-effort price lookup (non-blocking):
                try:
                    from backend.services.market_data import get_price as _get_price_fallback
                    _px = float(_get_price_fallback(parsed.asset))
                    if _px > 0:
                        parsed.amount_usd = float(parsed.amount_qty) * _px
                except Exception:
                    pass
                # If price still unavailable, amount_usd stays None — UI shows "≈ unavailable"
                # Do NOT block here

            elif not _has_usd and not _is_sell_all:
                # Non-sell-all trade without USD value: block
                blocked_messages.append(
                    f"[AMOUNT_MISSING] Could not determine trade amount for {parsed.asset or 'the asset'}."
                )
                continue

            artifact_refs = {
                "balances_artifact": f"run:pending#balances_{parsed.asset}",
                "product_check_artifact": f"run:pending#product_{parsed.asset}",
                "preflight_artifact": f"run:pending#preflight_{parsed.asset}",
            }
            available_usd = None
            if (parsed.side or "").lower() == "sell" and resolution and resolution.executable_qty:
                try:
                    from backend.services.market_data import get_price

                    _price = float(get_price(parsed.asset))
                    if _price > 0:
                        available_usd = float(resolution.executable_qty) * _price
                except Exception:
                    available_usd = None

            preflight = await run_preflight(
                tenant_id=tenant_id,
                side=parsed.side,
                asset=parsed.asset,
                amount_usd=float(parsed.amount_usd or 0.0),
                asset_class=parsed.asset_class,
                mode=parsed.mode,
                executable_qty=(resolution.executable_qty if resolution else None),
                hold_qty=(resolution.hold_qty if resolution else None),
                available_usd=available_usd,
                requested_qty=(float(parsed.amount_qty) if getattr(parsed, "amount_qty", None) is not None else None),
                sell_all_requested=((parsed.side or "").lower() == "sell" and parsed.amount_mode == AmountMode.ALL.value),
                product_flags=(resolution.product_flags if resolution else None),
                artifacts=artifact_refs,
                executable_state=executable_state,
            )
            if DEBUG_TRADE_DIAGNOSTICS:
                _pf_reason = getattr(preflight.reason_code, "value", None) if preflight.reason_code else None
                logger.debug(
                    "trade_preflight_debug asset=%s side=%s preview_called=True preview_valid=%s "
                    "preflight_reason=%s preflight_message=%s",
                    parsed.asset,
                    parsed.side,
                    preflight.valid,
                    _pf_reason or "N/A",
                    (preflight.user_message or "")[:120],
                )

            if not preflight.valid:
                base_msg = preflight.user_message or "Trade blocked by preflight."
                if preflight.fixes:
                    base_msg = f"{base_msg} Options: {', '.join(preflight.fixes)}."
                    blocked_suggestions.extend([str(f) for f in preflight.fixes if f])
                blocked_messages.append(base_msg)
                continue

            if preflight.requires_adjustment and preflight.adjusted_amount_usd is not None:
                original_amount_usd = float(parsed.amount_usd or 0.0)
                parsed.amount_usd = float(preflight.adjusted_amount_usd)
                if (parsed.side or "").lower() == "sell" and preflight.adjusted_qty is not None:
                    parsed.amount_qty = float(preflight.adjusted_qty)
                qty_text = (
                    f" ({float(preflight.adjusted_qty):.8f} {parsed.asset})"
                    if preflight.adjusted_qty is not None and parsed.asset
                    else ""
                )
                adjustment_messages.append(
                    f"You requested ${original_amount_usd:.2f} of {parsed.asset} but only "
                    f"~${float(preflight.adjusted_amount_usd):.2f}{qty_text} is sellable; "
                    "I can sell the maximum available instead."
                )

            base_size = None
            if (parsed.side or "").lower() == "sell" and getattr(parsed, "amount_qty", None):
                base_size = float(parsed.amount_qty)

            valid_actions.append({
                "side": parsed.side,
                "asset": parsed.asset,
                "amount_usd": float(parsed.amount_usd) if parsed.amount_usd is not None else None,
                "base_size": base_size,
                "amount_mode": parsed.amount_mode,
                "mode": parsed.mode,
                "asset_class": parsed.asset_class,
                "lookback_hours": parsed.lookback_hours,
                "is_most_profitable": parsed.is_most_profitable,
                "venue_symbol": parsed.venue_symbol or (f"{parsed.asset}-USD" if parsed.asset else None),
                "selection_result": selected_result_dict,
                "product_flags": resolution.product_flags if resolution else {},
                "preflight": preflight.to_dict(),
            })

        # ── Estimate portfolio total for reasoning context ────────────────
        _portfolio_total_usd = 0.0
        try:
            _balances = getattr(executable_state, "balances", {}) or {}
            from backend.services.market_data import get_price
            for _sym, _bal in _balances.items():
                _qty = float(getattr(_bal, "available_qty", 0) or 0)
                try:
                    _p = get_price(_sym)
                    if _p:
                        _portfolio_total_usd += _qty * float(_p)
                except Exception:
                    pass
        except Exception:
            pass

        all_failures = state_issues + blocked_messages

        # ── LLM Trade Reasoning ───────────────────────────────────────────
        # One call that reasons about the verified plan before user confirms.
        # Adds risk flags, portfolio impact, alternatives, plain-English summary.
        # Pipeline ALWAYS continues - reasoning failure is non-fatal.
        # Only call when there are valid actions — blocked-only commands don't need LLM reasoning.
        if valid_actions:
            _trade_reasoning = reason_about_plan(
                user_text=text,
                valid_actions=valid_actions,
                all_failures=all_failures,
                executable_state=executable_state,
                total_portfolio_usd=_portfolio_total_usd,
            )
        else:
            from backend.agents.trade_reasoner import TradeReasoning
            _trade_reasoning = TradeReasoning(confidence="low", plan_summary="")

        if not valid_actions:
            from backend.agents.narrative import format_trade_blocked_narrative, build_narrative_structured
            content = format_trade_blocked_narrative(
                candidate_count=len(parsed_commands),
                failures=all_failures,
                evidence_items=evidence_links,
            )
            dedup_suggestions: List[str] = []
            for s in blocked_suggestions:
                if s not in dedup_suggestions:
                    dedup_suggestions.append(s)
            return JSONResponse(content={
                "content": content,
                "run_id": None,
                "intent": "TRADE_EXECUTION",
                "status": "REJECTED",
                "request_id": request_id,
                "narrative_structured": build_narrative_structured(content),
                "suggestions": dedup_suggestions[:4] if dedup_suggestions else None,
            })

        # ── Build TradeContext for downstream consumers ─────────────────
        _trade_context_snapshot = None
        try:
            from backend.services.trade_context import build_trade_context, TradeAction as TCAction
            _tc_actions = []
            for va in valid_actions:
                _tc_actions.append(TCAction(
                    side=(va.get("side") or "BUY").upper(),
                    asset=(va.get("asset") or "").upper(),
                    product_id=va.get("venue_symbol") or f"{(va.get('asset') or '').upper()}-USD",
                    amount_usd=float(va.get("amount_usd") or 0),
                    amount_mode=va.get("amount_mode") or "quote_usd",
                    sell_all=va.get("amount_mode") == "all",
                    requested_qty=va.get("base_size"),
                ))
            _trade_ctx = build_trade_context(
                tenant_id=tenant_id,
                execution_mode=settings.execution_mode_default,
                actions=_tc_actions,
            )
            _trade_context_snapshot = {
                "tenant_id": _trade_ctx.tenant_id,
                "execution_mode": _trade_ctx.execution_mode,
                "built_at": _trade_ctx.built_at,
                "balances": {
                    k: {"available_qty": v.available_qty, "hold_qty": v.hold_qty}
                    for k, v in _trade_ctx.executable_balances.items()
                },
                "products": {
                    k: {
                        "rule_source": v.rule_source,
                        "base_min_size": str(v.base_min_size) if v.base_min_size is not None else None,
                        "base_increment": str(v.base_increment) if v.base_increment is not None else None,
                        "min_market_funds": str(v.min_market_funds) if v.min_market_funds is not None else None,
                        "verified": v.verified,
                    }
                    for k, v in _trade_ctx.resolved_products.items()
                },
                "prices": _trade_ctx.market_prices,
            }
        except Exception as _tc_err:
            logger.warning("TradeContext build failed (non-fatal): %s", str(_tc_err)[:200])

        # Phase 6: Collect staging diagnostics (balances, product rules, preflight decisions).
        _staging_diag = None
        try:
            from backend.services.run_diagnostics import build_staging_diagnostics
            _preflight_map = {}
            for _va in valid_actions:
                _key = f"{(_va.get('side') or '').upper()}_{(_va.get('asset') or '').upper()}_{(_va.get('amount_mode') or '').upper()}"
                _preflight_map[_key] = _va.get("preflight", {})
            _staging_diag = build_staging_diagnostics(
                tenant_id=tenant_id,
                referenced_assets=[va["asset"] for va in valid_actions if va.get("asset")],
                executable_state=executable_state,
                analysis_snapshot_asof=resolved.get("snapshot_ts") if not resolved.get("snapshot_failed") else None,
                preflight_map=_preflight_map,
                forced_refresh=_forced_refresh,
            )
        except Exception as _diag_err:
            logger.debug("staging_diagnostics_failed (non-fatal): %s", str(_diag_err)[:200])

        # Store pending trade(s) with sequential execution plan.
        repo = TradeConfirmationsRepo()
        first = valid_actions[0]

        # Tag each action with a step index and status for sequential execution.
        for idx, action in enumerate(valid_actions):
            action["step_index"] = idx
            action["step_status"] = "READY" if idx == 0 else "QUEUED"

        proposal_json = {
            "side": first["side"],
            "asset": first["asset"],
            "amount_usd": first["amount_usd"],
            "mode": first["mode"],
            "lookback_hours": first["lookback_hours"],
            "is_most_profitable": first["is_most_profitable"],
            "asset_class": first["asset_class"],
            "news_enabled": news_enabled,
            "locked_product_id": first.get("venue_symbol"),
            "actions": valid_actions,
            "current_action_index": 0,
            "sequential": len(valid_actions) > 1,
            "trade_context": _trade_context_snapshot,
            "diagnostics": _staging_diag,
        }

        if conversation_id:
            pending_trade = PendingTrade(
                conversation_id=conversation_id,
                side=first["side"],
                asset=first["asset"],
                amount_usd=float(first["amount_usd"] or 0.0),
                mode=first["mode"],
                is_most_profitable=first["is_most_profitable"],
                lookback_hours=first["lookback_hours"],
            )
            store_pending_trade(pending_trade)

        effective_conversation_id = conversation_id or f"ephemeral_{new_id('eph')}"
        confirmation_id = repo.create_pending(
            tenant_id=tenant_id,
            conversation_id=effective_conversation_id,
            proposal_json=proposal_json,
            mode=first["mode"],
            user_id=user_id,
            ttl_seconds=300,
        )

        financial_insight = None
        if news_enabled:
            try:
                insight_asset = (first.get("asset") or "").strip().upper() or (
                    (first.get("venue_symbol") or "").split("-")[0].upper()
                )
                insight_asset = insight_asset or "UNKNOWN"
                financial_insight = await asyncio.wait_for(
                    generate_insight(
                        asset=insight_asset,
                        side=first["side"],
                        notional_usd=float(first["amount_usd"] or 0.0),
                        asset_class=first.get("asset_class") or "CRYPTO",
                        news_enabled=True,
                        mode=first.get("mode") or "PAPER",
                        lookback_hours=int(first.get("lookback_hours") or 24),
                        request_id=request_id,
                    ),
                    timeout=12.0,
                )
                financial_insight["current_step_asset"] = insight_asset
                if len(valid_actions) > 1:
                    financial_insight["queued_steps_notice"] = "Queued steps will run news checks at execution time."
                repo.update_insight(confirmation_id, financial_insight)
                logger.info(
                    "trade_news_insight_generated request_id=%s conf=%s asset=%s status=%s headlines=%s",
                    request_id,
                    confirmation_id,
                    first["asset"],
                    ((financial_insight or {}).get("news_outcome") or {}).get("status"),
                    len((((financial_insight or {}).get("sources") or {}).get("headlines") or [])),
                )
            except Exception as insight_err:
                logger.warning(
                    "trade_news_insight_failed request_id=%s conf=%s asset=%s err=%s",
                    request_id,
                    confirmation_id,
                    first["asset"],
                    str(insight_err)[:200],
                )
                financial_insight = {
                    "headline": "Market insight unavailable",
                    "why_it_matters": "Unable to generate insight. Confirm or cancel at your discretion.",
                    "key_facts": [],
                    "risk_flags": ["insight_unavailable"],
                    "confidence": 0.0,
                    "sources": {"price_source": "none", "headlines": []},
                    "generated_by": "template",
                    "request_id": request_id,
                    "impact_summary": "No headline signal found; decision is based on portfolio + price checks only.",
                    "market_headlines": [],
                    "news_outcome": {
                        "queries": [first.get("asset", "UNKNOWN"), f"{first.get('asset', 'UNKNOWN')}-USD"],
                        "lookback": f"{int(first.get('lookback_hours') or 24)}h",
                        "sources": ["RSS", "GDELT"],
                        "status": "error",
                        "reason": f"News unavailable for {first.get('asset', 'UNKNOWN')} right now (provider error).",
                        "items": 0,
                    },
                    "asset_news_evidence": {
                        "assets": [first.get("asset", "UNKNOWN")],
                        "queries": [first.get("asset", "UNKNOWN"), f"{first.get('asset', 'UNKNOWN')}-USD"],
                        "lookback": f"{int(first.get('lookback_hours') or 24)}h",
                        "sources": ["RSS", "GDELT"],
                        "status": "error",
                        "items": [],
                        "reason_if_empty_or_error": f"News unavailable for {first.get('asset', 'UNKNOWN')} right now (provider error).",
                    },
                    "market_news_evidence": None,
                    "current_step_asset": first.get("asset", "UNKNOWN"),
                    "queued_steps_notice": "Queued steps will run news checks at execution time." if len(valid_actions) > 1 else None,
                }

        if news_enabled:
            news_label = f"News evidence ({first['asset']}, last 24h)"
            if not any((e.get("label") == news_label) for e in evidence_links):
                evidence_links.insert(0, {"label": news_label, "href": "url:/runs"})

        resp = trade_confirmation_prompt(
            side=first["side"],
            asset=first["asset"],
            amount_usd=float(first["amount_usd"] or 0.0),
            mode=first["mode"],
            confirmation_id=confirmation_id,
            asset_class=first["asset_class"],
            actions=valid_actions,
            failures=all_failures,
            evidence_links=(
                evidence_links
                + [
                    {"label": "Product tradability check", "href": "url:/runs"},
                    {"label": "Trade preflight report", "href": "url:/runs"},
                ]
            ),
            trade_reasoning=_trade_reasoning,
        )
        resp["request_id"] = request_id
        resp["valid_actions_count"] = len(valid_actions)
        resp["blocked_actions_count"] = len(all_failures)
        resp["partial_success"] = len(all_failures) > 0
        resp["news_enabled"] = news_enabled
        if _staging_diag is not None:
            resp["diagnostics"] = _staging_diag
        if adjustment_messages:
            resp["adjustments"] = adjustment_messages
            resp["suggestions"] = ["CONFIRM SELL MAX", "CANCEL"]
        if news_enabled:
            canonical_preconfirm_insight = financial_insight or {
                "headline": "Market insight unavailable",
                "why_it_matters": "Unable to generate insight. Confirm or cancel at your discretion.",
                "key_facts": [],
                "risk_flags": ["insight_unavailable"],
                "confidence": 0.0,
                "sources": {"price_source": "none", "headlines": []},
                "generated_by": "template",
                "request_id": request_id,
                "impact_summary": "No headline signal found; decision is based on portfolio + price checks only.",
                "market_headlines": [],
                "news_outcome": {
                    "queries": [first.get("asset", "UNKNOWN"), f"{first.get('asset', 'UNKNOWN')}-USD"],
                    "lookback": f"{int(first.get('lookback_hours') or 24)}h",
                    "sources": ["RSS", "GDELT"],
                    "status": "error",
                    "reason": f"News unavailable for {first.get('asset', 'UNKNOWN')} right now (provider error).",
                    "items": 0,
                },
                "asset_news_evidence": {
                    "assets": [first.get("asset", "UNKNOWN")],
                    "queries": [first.get("asset", "UNKNOWN"), f"{first.get('asset', 'UNKNOWN')}-USD"],
                    "lookback": f"{int(first.get('lookback_hours') or 24)}h",
                    "sources": ["RSS", "GDELT"],
                    "status": "error",
                    "items": [],
                    "reason_if_empty_or_error": f"News unavailable for {first.get('asset', 'UNKNOWN')} right now (provider error).",
                },
                "market_news_evidence": None,
                "current_step_asset": first.get("asset", "UNKNOWN"),
                "queued_steps_notice": "Queued steps will run news checks at execution time." if len(valid_actions) > 1 else None,
            }
            resp["preconfirm_insight"] = canonical_preconfirm_insight
            # Backward compatibility path for older clients; canonical key is preconfirm_insight.
            resp["financial_insight"] = canonical_preconfirm_insight
        if DEBUG_PRECONFIRM_NEWS:
            logger.info(
                "preconfirm_news_payload request_id=%s intent=%s news_enabled=%s has_preconfirm_insight=%s insight_keys=%s",
                request_id,
                resp.get("intent"),
                news_enabled,
                bool(resp.get("preconfirm_insight")),
                list((resp.get("preconfirm_insight") or {}).keys()) if isinstance(resp.get("preconfirm_insight"), dict) else [],
            )
        return JSONResponse(content=resp)
    
    # STEP 5: Handle PORTFOLIO_ANALYSIS intent (deep analysis with dedicated run)
    if intent == IntentType.PORTFOLIO_ANALYSIS:
        from backend.orchestrator.nodes.portfolio_node import execute as portfolio_execute
        from backend.api.routes.utils import json_dumps
        from backend.core.config import get_settings
        from backend.agents.intent_router import extract_holdings_asset, is_holdings_query
        
        tenant_id = user.get("tenant_id", "t_default")
        user_id = user.get("user_id", "u_default")
        
        # Check if this is a specific asset holdings query
        queried_asset = extract_holdings_asset(text) if is_holdings_query(text) else None
        
        # Determine execution mode: respect EXECUTION_MODE_DEFAULT, then check LIVE eligibility
        settings = get_settings()
        default_mode = getattr(settings, 'execution_mode_default', 'PAPER').upper()
        if settings.force_paper_mode:
            execution_mode = "PAPER"
            logger.info("FORCE_PAPER_MODE enabled: Forcing PAPER execution for portfolio analysis")
        elif default_mode == "PAPER":
            execution_mode = "PAPER"
        elif settings.coinbase_api_key_name and settings.coinbase_api_private_key:
            execution_mode = "LIVE"
        else:
            execution_mode = "PAPER"
        
        logger.info(f"Portfolio analysis using mode: {execution_mode}, queried_asset: {queried_asset}")
        
        # Create a dedicated run for portfolio analysis
        run_id = create_run(
            tenant_id=tenant_id,
            execution_mode=execution_mode
        )
        logger.debug("chat.py obtained run_id %s", run_id)
        
        # Store run metadata
        metadata = {
            "intent": "PORTFOLIO_ANALYSIS",
            "command_text": text,
            "user_id": user_id,
            "queried_asset": queried_asset
        }
        
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE runs 
                SET command_text = ?, metadata_json = ?, intent_json = ?
                WHERE run_id = ?
                """,
                (text, json_dumps(metadata), json_dumps(metadata), run_id)
            )
            conn.commit()
        
        # Execute portfolio analysis
        node_id = new_id("node_")
        result = await portfolio_execute(run_id, node_id, tenant_id)
        
        portfolio_brief = result.get("portfolio_brief", {})
        success = result.get("success", False)
        error = result.get("error")
        
        if not success:
            # Update run status to FAILED
            from backend.core.time import now_iso
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE runs SET status = 'FAILED', completed_at = ? WHERE run_id = ?",
                    (now_iso(), run_id)
                )
                conn.commit()

            # Return failure artifact
            failure = portfolio_brief.get("failure", {})
            # Normalize portfolio_brief to JSON-safe types
            try:
                portfolio_brief = json.loads(json_dumps(portfolio_brief))
            except Exception:
                portfolio_brief = {}
            return JSONResponse(content={
                "content": failure.get("error_message", error or "Portfolio analysis failed"),
                "run_id": run_id,
                "intent": "PORTFOLIO_ANALYSIS",
                "status": "FAILED",
                "portfolio_brief": portfolio_brief,
                "portfolio_snapshot_card_data": portfolio_brief,
                "suggested_action": failure.get("suggested_action", ""),
                "request_id": request_id
            })
        
        # PHASE 1: Capture safe primary response BEFORE any side effects
        # This ensures we always have something to return even if DB/notification/formatting fails.
        total_val = float(portfolio_brief.get("total_value_usd") or 0)
        safe_content = f"Portfolio analysis complete. Total value: ${total_val:,.2f}"
        safe_response = {
            "content": safe_content,
            "run_id": run_id,
            "intent": "PORTFOLIO_ANALYSIS",
            "status": "COMPLETED",
            "request_id": request_id
        }

        # PHASE 2: Try optional enhancements (DB update, artifact, notification, formatting)
        # If any of these fail, we still return the safe_response from Phase 1.
        try:
            # Format response based on query type
            if queried_asset:
                content = _format_asset_holdings_response(queried_asset, portfolio_brief)
            else:
                content = _format_portfolio_analysis(portfolio_brief)

            # Update run status to COMPLETED
            from backend.core.time import now_iso
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE runs SET status = 'COMPLETED', completed_at = ? WHERE run_id = ?",
                    (now_iso(), run_id)
                )
                conn.commit()

            # Persist portfolio_brief as run_artifact for PortfolioCard component
            try:
                with get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json, created_at)
                           VALUES (?, 'portfolio', 'portfolio_brief', ?, ?)""",
                        (run_id, json_dumps(portfolio_brief), now_iso())
                    )
                    conn.commit()
            except Exception:
                pass  # Non-critical observability

            # Send push notification for portfolio analysis
            try:
                from backend.services.notifications.pushover import notify_portfolio_analysis
                notify_portfolio_analysis(
                    mode=portfolio_brief.get("mode", "PAPER"),
                    total_value_usd=total_val,
                    cash_usd=float(portfolio_brief.get("cash_usd") or 0),
                    holdings_count=len(portfolio_brief.get("holdings", [])),
                    risk_level=portfolio_brief.get("risk", {}).get("risk_level", "UNKNOWN"),
                    run_id=run_id
                )
            except Exception as notif_err:
                logger.warning("Failed to send portfolio notification: %s", str(notif_err)[:200])

            # Normalize portfolio_brief to JSON-safe types (handles Decimal, Enum, datetime)
            try:
                portfolio_brief = json.loads(json_dumps(portfolio_brief))
            except Exception:
                portfolio_brief = {}

            from backend.agents.narrative import build_narrative_structured
            safe_response["content"] = content
            safe_response["portfolio_brief"] = portfolio_brief
            safe_response["portfolio_snapshot_card_data"] = portfolio_brief
            safe_response["queried_asset"] = queried_asset
            safe_response["narrative_structured"] = build_narrative_structured(content, brief=portfolio_brief)

        except Exception as phase2_err:
            logger.warning("Portfolio post-analysis enhancement failed (returning safe response): %s", str(phase2_err)[:200])

        return JSONResponse(content=safe_response)
    
    # STEP 6: Handle PORTFOLIO / FINANCE_ANALYSIS intents (simple snapshot)
    # Note: PORTFOLIO_ANALYSIS (detailed) is handled above in STEP 5
    if intent in (IntentType.FINANCE_ANALYSIS, IntentType.PORTFOLIO):
        from backend.core.config import get_settings
        
        tenant_id = user.get("tenant_id", "t_default")
        intent_value = intent.value if hasattr(intent, 'value') else str(intent)
        settings = get_settings()
        
        # Determine mode: respect EXECUTION_MODE_DEFAULT
        default_mode = getattr(settings, 'execution_mode_default', 'PAPER').upper()
        is_live = default_mode == "LIVE" and bool(settings.coinbase_api_key_name and settings.coinbase_api_private_key)
        mode_str = "LIVE" if is_live else "PAPER"

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT balances_json, positions_json, total_value_usd, ts
                FROM portfolio_snapshots
                WHERE tenant_id = ?
                ORDER BY ts DESC LIMIT 1
                """,
                (tenant_id,)
            )
            row = cursor.fetchone()

        if not row:
            from backend.agents.narrative import format_no_snapshot_narrative, build_narrative_structured
            content = format_no_snapshot_narrative(mode_str)
            return JSONResponse(content={
                "content": content,
                "run_id": None,
                "intent": intent_value,
                "status": "COMPLETED",
                "request_id": request_id,
                "narrative_structured": build_narrative_structured(content),
            })

        balances = _safe_json_loads(row["balances_json"], {})
        positions = _safe_json_loads(row["positions_json"], {})
        total_value = row["total_value_usd"] or 0.0
        ts = row["ts"]

        top_positions = sorted(
            [(str(asset), float(qty or 0.0)) for asset, qty in positions.items()],
            key=lambda kv: kv[1],
            reverse=True
        )[:3]
        usd_cash = float(balances.get("USD", 0.0) or 0.0)
        from backend.agents.narrative import format_simple_portfolio_narrative
        content_text = format_simple_portfolio_narrative(
            mode_str=mode_str,
            ts=ts,
            total_value=total_value,
            cash_usd=usd_cash,
            top_positions=top_positions,
        )

        # Send push notification for portfolio snapshot (LIVE mode only)
        if is_live:
            try:
                from backend.services.notifications.pushover import notify_portfolio_analysis
                notify_portfolio_analysis(
                    mode=mode_str,
                    total_value_usd=total_value,
                    cash_usd=balances.get("USD", 0),
                    holdings_count=len(positions),
                    risk_level="UNKNOWN",
                    run_id=None
                )
            except Exception as notif_err:
                logger.warning(f"Failed to send portfolio snapshot notification: {notif_err}")
        else:
            # Record skipped notification for PAPER mode
            try:
                from backend.services.notifications.pushover import record_skipped_notification
                record_skipped_notification(
                    action="portfolio_snapshot",
                    reason="PAPER mode - notifications only sent for LIVE mode",
                    run_id=None
                )
            except Exception:
                pass  # Don't fail on notification logging issues

        from backend.agents.narrative import build_narrative_structured
        simple_snapshot_brief = {
            "as_of": ts,
            "mode": mode_str,
            "total_value_usd": float(total_value or 0.0),
            "cash_usd": usd_cash,
            "holdings": [
                {"asset_symbol": str(asset), "qty": float(qty or 0.0), "usd_value": 0.0}
                for asset, qty in positions.items()
            ],
            "recommendations": [],
            "warnings": [],
        }
        return JSONResponse(content={
            "content": content_text,
            "run_id": None,
            "intent": intent_value,
            "status": "COMPLETED",
            "request_id": request_id,
            "portfolio_snapshot_card_data": simple_snapshot_brief,
            "narrative_structured": build_narrative_structured(content_text),
        })

    # Fallback for unhandled intents
    return JSONResponse(content={
        "content": "I'm not sure how to handle that request. Try asking about trading, portfolio analysis, or market data.",
        "run_id": None,
        "intent": intent.value if hasattr(intent, 'value') else str(intent),
        "status": "COMPLETED",
        "request_id": request_id
    })
