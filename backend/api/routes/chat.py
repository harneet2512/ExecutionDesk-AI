"""Chat command API endpoint with natural language parsing and confirmation flow."""
import json
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


def _safe_json_loads(s, default=None):
    """Parse JSON safely, returning default on failure."""
    if not s:
        return default if default is not None else {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}

router = APIRouter()


def _format_portfolio_analysis(brief: Dict[str, Any]) -> str:
    """Format PortfolioBrief into clean, professional output for chat display.
    
    Design principles:
    - No markdown tables (render poorly in chat)
    - No emojis (unprofessional for enterprise)
    - Max 5 holdings shown
    - Clean, scannable structure
    - No internal error details
    """
    lines = []
    
    # Header with mode and timestamp
    mode = brief.get("mode", "UNKNOWN")
    # Handle both string and enum values
    if hasattr(mode, 'value'):
        mode = mode.value
    mode_str = str(mode).replace("ExecutionMode.", "").upper()
    
    as_of = brief.get("as_of", "")
    # Parse and format timestamp cleanly
    try:
        from datetime import datetime
        ts = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        as_of_display = ts.strftime("%b %d, %Y %H:%M UTC")
    except:
        as_of_display = as_of
    
    lines.append("**Portfolio Snapshot**")
    lines.append(f"Mode: {mode_str} | As of: {as_of_display}")
    lines.append("")
    
    # Key metrics
    total_value = brief.get("total_value_usd", 0)
    cash = brief.get("cash_usd", 0)
    lines.append(f"Total Value: **${total_value:,.2f}**")
    lines.append(f"Cash: ${cash:,.2f}")
    lines.append("")
    
    # Top holdings (max 5, as simple list)
    holdings = brief.get("holdings", [])
    if holdings:
        lines.append("**Top Holdings**")
        for h in holdings[:5]:
            symbol = h.get("asset_symbol", "?")
            qty = h.get("qty", 0)
            usd = h.get("usd_value", 0)
            price = h.get("current_price")
            price_str = f"@ ${price:,.2f}" if price else ""
            lines.append(f"  {symbol}: {qty:,.6f} (${usd:,.2f}) {price_str}".strip())
        if len(holdings) > 5:
            lines.append(f"  ... and {len(holdings) - 5} more")
        lines.append("")
    
    # Allocation summary (condensed)
    allocation = brief.get("allocation", [])
    if allocation:
        lines.append("**Allocation**")
        for a in allocation[:5]:
            symbol = a.get("asset_symbol", "?")
            pct = a.get("pct", 0)
            lines.append(f"  {symbol}: {pct:.1f}%")
        lines.append("")
    
    # Risk summary (short bullets, no exaggeration)
    risk = brief.get("risk", {})
    if risk:
        risk_level = risk.get("risk_level", "UNKNOWN")
        # Use cleaner risk level labels
        risk_labels = {
            "VERY_HIGH": "High concentration",
            "HIGH": "Concentrated",
            "MEDIUM": "Moderately diversified",
            "LOW": "Well diversified",
            "UNKNOWN": "Unable to assess"
        }
        risk_label = risk_labels.get(risk_level, risk_level)
        
        lines.append("**Risk**")
        lines.append(f"  Status: {risk_label}")
        
        top1 = risk.get("concentration_pct_top1", 0)
        if top1 > 0:
            lines.append(f"  Largest position: {top1:.0f}% of portfolio")
        
        div_score = risk.get("diversification_score")
        if div_score is not None:
            lines.append(f"  Diversification: {div_score:.2f}/1.00")
        lines.append("")
    
    # Recommendations (max 3, no icons)
    recommendations = brief.get("recommendations", [])
    if recommendations:
        lines.append("**Recommendations**")
        for rec in recommendations[:3]:
            title = rec.get("title", "")
            desc = rec.get("description", "")
            lines.append(f"  {title}")
            if desc:
                lines.append(f"    {desc}")
        lines.append("")
    
    # Warnings (filtered, no internal errors)
    warnings = brief.get("warnings", [])
    # Filter out any warnings that look like internal errors
    clean_warnings = [
        w for w in warnings 
        if not any(x in str(w).lower() for x in ["name '", "traceback", "exception", "error:"])
    ]
    if clean_warnings:
        lines.append("**Notes**")
        for w in clean_warnings[:3]:
            lines.append(f"  {w}")
        lines.append("")
    
    # Data sources (clean wording)
    evidence = brief.get("evidence_refs", {})
    evidence_count = 0
    if evidence.get("accounts_call_id"):
        evidence_count += 1
    evidence_count += len(evidence.get("prices_call_ids", []))
    if evidence.get("orders_call_id"):
        evidence_count += 1
    
    if evidence_count > 0:
        source_word = "source" if evidence_count == 1 else "sources"
        lines.append(f"Data: {evidence_count} {source_word} queried. Full evidence in run artifacts.")
    
    return "\n".join(lines)


def _format_asset_holdings_response(asset: str, brief: Dict[str, Any]) -> str:
    """
    Format a focused response for a specific asset holdings query.
    
    For "How much BTC do I own?" returns:
    - Direct answer with quantity and USD value
    - Evidence reference
    - Brief portfolio context
    """
    lines = []
    mode = brief.get("mode", "UNKNOWN")
    as_of = brief.get("as_of", "")
    
    # Find the specific asset in holdings
    holdings = brief.get("holdings", [])
    asset_holding = None
    for h in holdings:
        if h.get("asset_symbol", "").upper() == asset.upper():
            asset_holding = h
            break
    
    if asset_holding:
        qty = asset_holding.get("qty", 0)
        usd_value = asset_holding.get("usd_value", 0)
        current_price = asset_holding.get("current_price")
        
        # Direct answer
        lines.append(f"## {asset} Holdings")
        lines.append("")
        lines.append(f"**{asset}:** {qty:,.8f}")
        if current_price:
            lines.append(f"**USD Value:** ${usd_value:,.2f} (at ${current_price:,.2f} per {asset})")
        else:
            lines.append(f"**USD Value:** ${usd_value:,.2f}")
        lines.append("")
        lines.append(f"*{mode} mode, as of {as_of}*")
    else:
        # Asset not found - explicitly state 0 balance
        lines.append(f"## {asset} Holdings")
        lines.append("")
        lines.append(f"**{asset}:** 0.00000000")
        lines.append(f"**USD Value:** $0.00")
        lines.append("")
        lines.append(f"You do not currently hold any {asset} in your {mode} portfolio.")
        lines.append("")
        lines.append(f"*{mode} mode, as of {as_of}*")
    
    # Add brief portfolio context
    total_value = brief.get("total_value_usd", 0)
    cash = brief.get("cash_usd", 0)
    holdings_count = len(holdings)
    
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### Portfolio Summary")
    lines.append(f"- **Total Portfolio Value:** ${total_value:,.2f}")
    lines.append(f"- **Cash (USD):** ${cash:,.2f}")
    lines.append(f"- **Holdings:** {holdings_count} asset(s)")
    
    # List other holdings briefly
    if holdings:
        other_holdings = [h for h in holdings if h.get("asset_symbol", "").upper() != asset.upper()]
        if other_holdings:
            lines.append("")
            lines.append("**Other Holdings:**")
            for h in other_holdings[:5]:  # Show top 5
                symbol = h.get("asset_symbol", "?")
                qty = h.get("qty", 0)
                usd = h.get("usd_value", 0)
                lines.append(f"- {symbol}: {qty:,.6f} (${usd:,.2f})")
            if len(other_holdings) > 5:
                lines.append(f"- ... and {len(other_holdings) - 5} more")
    
    # Evidence references
    evidence = brief.get("evidence_refs", {})
    evidence_ids = []
    if evidence.get("accounts_call_id"):
        evidence_ids.append(evidence["accounts_call_id"])
    evidence_ids.extend(evidence.get("prices_call_ids", []))
    
    if evidence_ids:
        lines.append("")
        lines.append(f"*Evidence: {len(evidence_ids)} API calls to Coinbase. Run artifacts contain full data.*")

    return "\n".join(lines)


async def _check_asset_balance(tenant_id: str, asset: str, required_usd: float) -> Dict[str, Any]:
    """
    Check if user has sufficient balance of an asset for a SELL order.

    Returns:
        {
            "sufficient": bool,
            "available": float (asset quantity),
            "available_usd": float,
            "current_price": float or None,
            "error": str or None
        }
    """
    from backend.core.config import get_settings

    settings = get_settings()
    result = {
        "sufficient": False,
        "available": 0.0,
        "available_usd": 0.0,
        "current_price": None,
        "error": None
    }

    # Skip balance check for PAPER mode or if it's "AUTO" (most profitable)
    if asset == "AUTO":
        result["sufficient"] = True
        result["error"] = "Cannot validate balance for AUTO selection"
        return result

    # Check if LIVE credentials are available
    if not (settings.enable_live_trading and settings.coinbase_api_key_name and settings.coinbase_api_private_key):
        # In PAPER mode, check paper portfolio
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT positions_json, balances_json
                    FROM portfolio_snapshots
                    WHERE tenant_id = ?
                    ORDER BY ts DESC LIMIT 1
                    """,
                    (tenant_id,)
                )
                row = cursor.fetchone()

                if row:
                    positions = _safe_json_loads(row["positions_json"], {})
                    balances = _safe_json_loads(row["balances_json"], {})

                    # Check for the asset in positions
                    asset_upper = asset.upper()
                    available = positions.get(asset_upper, balances.get(asset_upper, 0.0))

                    if available > 0:
                        # Estimate USD value (rough estimate using default mock data)
                        # In paper mode, we assume balance is sufficient if > 0
                        result["available"] = available
                        result["available_usd"] = available * 50000 if asset_upper == "BTC" else available * 100
                        result["sufficient"] = result["available_usd"] >= required_usd
                    else:
                        result["available"] = 0.0
                        result["available_usd"] = 0.0
                        result["sufficient"] = False
                else:
                    # No portfolio snapshot - assume insufficient in PAPER mode
                    result["error"] = "No portfolio data available"
                    result["sufficient"] = False
        except Exception as e:
            result["error"] = str(e)
            result["sufficient"] = False
        return result

    # LIVE mode: fetch from Coinbase
    try:
        from backend.providers.coinbase_provider import CoinbaseProvider
        from backend.services.coinbase_market_data import get_candles

        provider = CoinbaseProvider()
        balances_result = provider.get_balances(tenant_id)

        balances = balances_result.get("balances", {})
        asset_upper = asset.upper()
        available = float(balances.get(asset_upper, 0.0))

        result["available"] = available

        if available <= 0:
            result["sufficient"] = False
            result["available_usd"] = 0.0
            return result

        # Get current price
        try:
            product_id = f"{asset_upper}-USD"
            candles = get_candles(product_id, granularity="ONE_HOUR", limit=1)
            if candles and len(candles) > 0:
                current_price = candles[0].get("close", 0)
                result["current_price"] = current_price
                result["available_usd"] = available * current_price
            else:
                # Fallback price estimate
                result["available_usd"] = available * 50000 if asset_upper == "BTC" else available * 100
        except Exception as price_err:
            logger.warning(f"Could not get price for {asset}: {price_err}")
            result["available_usd"] = available * 50000 if asset_upper == "BTC" else available * 100

        result["sufficient"] = result["available_usd"] >= required_usd

    except Exception as e:
        logger.error(f"Balance check failed for {asset}: {e}")
        result["error"] = str(e)
        result["sufficient"] = False

    return result


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
    from backend.agents.trade_parser import parse_trade_command, is_missing_amount
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
                response_content = {
                    "run_id": run_id,
                    "parsed_intent": parsed_intent.model_dump(),
                    "content": f"Confirmed. Executing {pending.side} ${pending.amount_usd} of {pending.asset}...",
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

        # Parse proposal and execute
        from backend.agents.planner import plan_execution

        try:
            proposal = json_module.loads(confirmation["proposal_json"])
        except Exception:
            proposal = {}

        side = proposal.get("side", "buy")
        asset = proposal.get("asset", "BTC")
        amount_usd = proposal.get("amount_usd", 10.0)
        mode = confirmation["mode"]

        # S1: Block LIVE trades if master kill switch is active
        if mode == "LIVE":
            _settings = get_settings()
            if _settings.trading_disable_live:
                return JSONResponse(status_code=403, content={
                    "error": {"code": "LIVE_DISABLED", "message": "LIVE trading is disabled via TRADING_DISABLE_LIVE"},
                    "request_id": request_id
                })

        lookback_hours = proposal.get("lookback_hours", 24)
        is_most_profitable = proposal.get("is_most_profitable", False)
        asset_class = proposal.get("asset_class", "CRYPTO")
        news_enabled = proposal.get("news_enabled", True)
        selection_result = proposal.get("selection_result")  # Pre-computed selection

        # Build universe: use pre-selected asset if available, else build universe
        if selection_result and selection_result.get("selected_symbol"):
            # Use the pre-selected asset from the selection engine
            selected_symbol = selection_result["selected_symbol"]
            asset = selected_symbol  # Update asset to the selected one
            universe = [f"{selected_symbol}-USD"]
            display_asset = f"{selected_symbol} (top performer)"
            logger.info(
                "Using pre-selected asset: %s (return: %s%%)",
                selected_symbol, selection_result.get("selected_return_pct", "N/A")
            )
        elif is_most_profitable or asset == "AUTO":
            # Fallback: dynamically build universe (should rarely happen)
            if asset_class == "STOCK":
                # Use stock watchlist for stocks
                universe = [f"{s}-USD" for s in settings.stock_watchlist_list]
                display_asset = "most profitable stock"
            else:
                # Use top crypto universe dynamically
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
        else:
            universe = [f"{asset}-USD"]
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

        parsed_intent = TradeIntent(
            side=side,
            budget_usd=amount_usd,
            universe=universe,
            raw_command=raw_command,
            metric="return",
            window=window,
            lookback_hours=lookback_hours
        )

        run_id = create_run(
            tenant_id=tenant_id,
            execution_mode=mode
        )

        # Build proper execution plan via planner
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

        # Update run with metadata, intent, and execution plan
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
            "news_enabled": news_enabled
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
                    run_id
                )
            )
            conn.commit()

        # Build response BEFORE side effect (two-phase pattern, NF4)
        if asset_class == "STOCK" or mode == "ASSISTED_LIVE":
            content_msg = f"Confirmed. Generating order ticket for {side} ${amount_usd} of {display_asset}..."
            intent_type = "TRADE_TICKET_CREATING"
        else:
            content_msg = f"Confirmed. Executing {side} ${amount_usd} of {display_asset}..."
            intent_type = "TRADE_EXECUTION"

        response_content = {
            "run_id": run_id,
            "parsed_intent": parsed_intent.dict(),
            "content": content_msg,
            "intent": intent_type,
            "status": "EXECUTING",
            "confirmation_id": confirmation_id,
            "asset_class": asset_class,
            "request_id": request_id
        }

        logger.info(
            "confirmation_confirmed: conf=%s tenant=%s run=%s mode=%s asset=%s asset_class=%s news=%s most_profitable=%s",
            confirmation_id, tenant_id, run_id, mode, asset, asset_class, news_enabled, is_most_profitable
        )

        background_tasks.add_task(execute_run, run_id=run_id)

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
        parsed = parse_trade_command(text)

        # Check for missing amount
        if is_missing_amount(parsed):
            resp = missing_amount_prompt(parsed.side or "buy", parsed.asset)
            resp["request_id"] = request_id
            return JSONResponse(content=resp)

        # Check for ambiguous asset class
        if parsed.asset_class == "AMBIGUOUS":
            return JSONResponse(content={
                "content": "I couldn't determine if you want to trade crypto or stocks. Please clarify:\n\n"
                           "- For crypto: 'Buy $50 of BTC' or 'Buy $50 crypto'\n"
                           "- For stocks: 'Buy $50 of AAPL stock' or 'Buy $50 AAPL equity'",
                "run_id": None,
                "intent": "TRADE_EXECUTION_INCOMPLETE",
                "status": "AWAITING_ASSET_CLASS",
                "request_id": request_id
            })

        # Handle "sell last purchase" — resolve from order history
        if parsed.is_sell_last_purchase:
            from backend.services.symbol_resolver import get_last_purchase
            _tenant = user.get("tenant_id", "t_default")
            last = get_last_purchase(_tenant)
            if last:
                parsed.asset = last.base_symbol
                parsed.venue_symbol = last.product_id
                parsed.side = "sell"
                parsed.resolution_source = last.source
                logger.info("sell_last_purchase resolved to %s for tenant %s", last.product_id, _tenant)
            else:
                return JSONResponse(content={
                    "content": "No recent purchase found to sell. You haven't bought any assets yet.",
                    "run_id": None,
                    "intent": "TRADE_EXECUTION_INCOMPLETE",
                    "status": "REJECTED",
                    "reason_code": "NO_LAST_PURCHASE",
                    "request_id": request_id
                })

        # Check for missing asset (and not "most profitable")
        if not parsed.asset and not parsed.is_most_profitable:
            asset_examples = "BTC, ETH, SOL" if parsed.asset_class == "CRYPTO" else "AAPL, MSFT, NVDA"
            asset_type = "cryptocurrency" if parsed.asset_class == "CRYPTO" else "stock"
            return JSONResponse(content={
                "content": f"Which {asset_type} do you want to trade? (e.g., {asset_examples})",
                "run_id": None,
                "intent": "TRADE_EXECUTION_INCOMPLETE",
                "status": "AWAITING_INPUT",
                "request_id": request_id
            })
        
        # If "most profitable", use AUTO asset - strategy node will pick the winner
        if parsed.is_most_profitable:
            parsed.asset = "AUTO"

        tenant_id = user.get("tenant_id", "t_default")
        user_id = user.get("user_id", "u_default")

        # Bug 6 fix: Use unified preflight service for all validation
        # This ensures consistent fee calculations across min_notional and balance checks
        from backend.services.trade_preflight import run_preflight, PreflightRejectReason
        
        preflight_result = await run_preflight(
            tenant_id=tenant_id,
            side=parsed.side,
            asset=parsed.asset,
            amount_usd=parsed.amount_usd,
            asset_class=parsed.asset_class,
            mode=parsed.mode
        )
        
        if not preflight_result.valid:
            # Map preflight rejection to appropriate response
            reason_code = preflight_result.reason_code.value if preflight_result.reason_code else "VALIDATION_FAILED"
            
            response_content = {
                "content": preflight_result.message,
                "run_id": None,
                "intent": "TRADE_EXECUTION",
                "status": "REJECTED",
                "reason_code": reason_code,
                "request_id": request_id,
                "remediation": preflight_result.remediation,
            }
            
            # Add specific fields based on rejection reason
            if preflight_result.reason_code == PreflightRejectReason.MIN_NOTIONAL_TOO_LOW:
                response_content["requested_notional_usd"] = preflight_result.requested_usd
                response_content["min_notional_usd"] = preflight_result.effective_min_notional
                response_content["estimated_fee"] = preflight_result.estimated_fee
            elif preflight_result.reason_code in (PreflightRejectReason.INSUFFICIENT_BALANCE, PreflightRejectReason.INSUFFICIENT_CASH):
                response_content["requested_usd"] = preflight_result.requested_usd
                response_content["available_balance"] = preflight_result.available_balance
                response_content["available_usd"] = preflight_result.available_usd
                response_content["asset"] = parsed.asset
            
            return JSONResponse(content=response_content)

        # --- Auto-sell path: preflight passed but requires selling holdings first ---
        if preflight_result.requires_auto_sell and preflight_result.auto_sell_proposal:
            auto_sell = preflight_result.auto_sell_proposal
            logger.info(
                "auto_sell_required: tenant=%s sell=%s amount=$%.2f to fund BUY $%.2f of %s",
                tenant_id, auto_sell.get("sell_base_symbol"), auto_sell.get("sell_amount_usd", 0),
                parsed.amount_usd, parsed.asset,
            )

        # Block LIVE confirmation when LIVE is disabled - redirect to PAPER
        if parsed.mode == "LIVE" and settings.trading_disable_live:
            parsed.mode = "PAPER"
            logger.info("Downgraded LIVE -> PAPER (trading_disable_live=true): tenant=%s", tenant_id)

        # Store pending trade and request confirmation
        from backend.db.repo.trade_confirmations_repo import TradeConfirmationsRepo

        # 1. Store in memory (legacy, for conversation-based lookups)
        if conversation_id:
            pending_trade = PendingTrade(
                conversation_id=conversation_id,
                side=parsed.side,
                asset=parsed.asset,
                amount_usd=parsed.amount_usd,
                mode=parsed.mode,
                is_most_profitable=parsed.is_most_profitable,
                lookback_hours=parsed.lookback_hours
            )
            store_pending_trade(pending_trade)

        # 2. ALWAYS store DURABLE confirmation in DB (source of truth)
        repo = TradeConfirmationsRepo()

        # Determine news_enabled: use request value if provided, else default True
        news_enabled = request_body.news_enabled if request_body.news_enabled is not None else True

        # For direct asset commands (not "most profitable"), lock the product_id immediately
        direct_locked_product_id = None
        if not parsed.is_most_profitable and parsed.asset and parsed.asset != "AUTO":
            direct_locked_product_id = parsed.venue_symbol or f"{parsed.asset}-USD"

        proposal_json = {
            "side": parsed.side,
            "asset": parsed.asset,
            "amount_usd": parsed.amount_usd,
            "mode": parsed.mode,
            "lookback_hours": parsed.lookback_hours,
            "is_most_profitable": parsed.is_most_profitable,
            "asset_class": parsed.asset_class,
            "news_enabled": news_enabled,
            "locked_product_id": direct_locked_product_id,
        }

        # Attach auto-sell metadata if funds recycling is needed
        if preflight_result.requires_auto_sell and preflight_result.auto_sell_proposal:
            proposal_json["auto_sell"] = preflight_result.auto_sell_proposal

        # Use conversation_id if available, otherwise use a placeholder
        effective_conversation_id = conversation_id or f"ephemeral_{new_id('eph')}"

        confirmation_id = repo.create_pending(
            tenant_id=tenant_id,
            conversation_id=effective_conversation_id,
            proposal_json=proposal_json,
            mode=parsed.mode,
            user_id=user_id,
            ttl_seconds=300
        )

        from datetime import datetime, timedelta
        logger.info(
            "confirmation_created: conf=%s tenant=%s conv=%s mode=%s asset=%s amount=%s asset_class=%s news=%s",
            confirmation_id, tenant_id, effective_conversation_id, parsed.mode, parsed.asset,
            parsed.amount_usd, parsed.asset_class, news_enabled
        )

        # For "most profitable" queries, run the asset selection engine
        selection_result = None
        if parsed.is_most_profitable:
            try:
                from backend.services.asset_selection_engine import select_asset, selection_result_to_dict
                
                # Determine selection criteria from parsed command
                criteria = parsed.selection_criteria or "highest_performing"
                universe_constraint = parsed.universe_constraint or "top_25_volume"
                
                selection_result = await select_asset(
                    criteria=criteria,
                    lookback_hours=parsed.lookback_hours,
                    notional_usd=parsed.amount_usd,
                    universe_constraint=universe_constraint,
                    threshold_pct=parsed.threshold_pct,
                    asset_class=parsed.asset_class
                )
                
                # Update the parsed asset with the selected symbol
                parsed.asset = selection_result.selected_symbol
                parsed.venue_symbol = f"{selection_result.selected_symbol}-USD"
                
                # Update the proposal in the confirmation repo with the selected asset
                # Store locked_product_id so confirmation endpoint can persist it on the run
                proposal_json["asset"] = parsed.asset
                proposal_json["locked_product_id"] = parsed.venue_symbol
                proposal_json["selection_result"] = selection_result_to_dict(selection_result)

                # Persist updated proposal back to DB so confirmation reads locked_product_id
                repo.update_proposal(confirmation_id, proposal_json)
                
                logger.info(
                    "Asset selection completed: selected=%s locked_product_id=%s return=%.2f%% window=%s",
                    selection_result.selected_symbol,
                    parsed.venue_symbol,
                    selection_result.selected_return_pct,
                    selection_result.window_description
                )
            except Exception as selection_err:
                # Check if this is a NoMarketDataError or NoTradeableAssetError
                from backend.services.asset_selection_engine import NoMarketDataError, NoTradeableAssetError
                if isinstance(selection_err, NoMarketDataError):
                    logger.warning("No market data for top performer: %s", str(selection_err)[:200])
                    return JSONResponse(content={
                        "content": str(selection_err),
                        "run_id": None,
                        "intent": "TRADE_EXECUTION",
                        "status": "REJECTED",
                        "reason_code": "NO_MARKET_DATA",
                        "request_id": request_id,
                    })
                if isinstance(selection_err, NoTradeableAssetError):
                    logger.warning("No tradeable asset found: %s", str(selection_err)[:200])
                    return JSONResponse(content={
                        "content": f"Order not submitted. No trade was placed. {selection_err}",
                        "run_id": None,
                        "intent": "TRADE_EXECUTION",
                        "status": "REJECTED",
                        "executed": False,
                        "reason_code": "NO_TRADEABLE_TOP_PERFORMER",
                        "request_id": request_id,
                    })
                logger.warning("Asset selection failed, using fallback: %s", str(selection_err)[:200])
                # Fallback to BTC if selection fails for transient reasons
                parsed.asset = "BTC"
                parsed.venue_symbol = "BTC-USD"

        # Display "most profitable crypto/stock" instead of "AUTO" in the prompt
        if parsed.is_most_profitable and selection_result:
            display_asset = f"{selection_result.selected_symbol} (top performer, {selection_result.selected_return_pct:+.2f}% in {selection_result.window_description})"
        elif parsed.is_most_profitable:
            display_asset = "most profitable stock" if parsed.asset_class == "STOCK" else "most profitable crypto"
        else:
            display_asset = parsed.asset

        # ── TRADABILITY PREFLIGHT: Verify product is tradeable before showing CONFIRM ──
        # This prevents the user from confirming a non-tradeable asset.
        if parsed.mode == "LIVE" and parsed.asset_class == "CRYPTO":
            product_id_to_check = parsed.venue_symbol or f"{parsed.asset}-USD"
            try:
                from backend.services.asset_selection_engine import verify_product_tradeable
                if not verify_product_tradeable(product_id_to_check):
                    logger.warning(
                        "PREFLIGHT_FAIL: %s not tradeable on Coinbase, blocking confirmation",
                        product_id_to_check
                    )
                    return JSONResponse(content={
                        "content": (
                            f"Order not submitted. No trade was placed. "
                            f"{product_id_to_check} is not currently tradeable on Coinbase "
                            f"(product offline or not available for your account)."
                        ),
                        "run_id": None,
                        "intent": "TRADE_EXECUTION",
                        "status": "REJECTED",
                        "executed": False,
                        "reason_code": "PRODUCT_NOT_TRADEABLE",
                        "request_id": request_id,
                    })
                logger.info("PREFLIGHT_PASS: %s is tradeable", product_id_to_check)
            except Exception as preflight_err:
                logger.warning("Tradability preflight failed (non-blocking): %s", str(preflight_err)[:200])

        # Send push notification for pending confirmation
        try:
            from backend.services.notifications.pushover import notify_pending_confirmation
            notify_pending_confirmation(
                mode=parsed.mode,
                side=parsed.side,
                symbol=display_asset,
                notional_usd=parsed.amount_usd,
                conversation_id=conversation_id
            )
        except Exception as notif_err:
            logger.warning(f"Failed to send pending confirmation notification: {notif_err}")

        # Generate pre-confirm financial insight (always, regardless of news toggle)
        financial_insight = None
        try:
            from backend.services.pre_confirm_insight import generate_insight
            financial_insight = await generate_insight(
                asset=parsed.asset,
                side=parsed.side,
                notional_usd=parsed.amount_usd,
                asset_class=parsed.asset_class,
                news_enabled=news_enabled,
                mode=parsed.mode,
                request_id=request_id
            )
            # Persist insight on the confirmation row
            repo.update_insight(confirmation_id, financial_insight)
        except Exception as insight_err:
            logger.warning("Pre-confirm insight failed: %s", str(insight_err)[:200])
            # I1: Provide fallback insight so frontend always renders something
            financial_insight = {
                "headline": "Market insight temporarily unavailable",
                "why_it_matters": "Unable to retrieve market data. Proceed with caution.",
                "key_facts": [],
                "risk_flags": [],
                "confidence": 0.0,
                "generated_by": "fallback",
                "sources": {},
            }

        # Use different prompt for stocks (ASSISTED_LIVE creates Order Ticket, not execution)
        resp = trade_confirmation_prompt(
            side=parsed.side,
            asset=display_asset,
            amount_usd=parsed.amount_usd,
            mode=parsed.mode,
            confirmation_id=confirmation_id,
            asset_class=parsed.asset_class
        )
        resp["request_id"] = request_id
        if financial_insight:
            try:
                json.dumps(financial_insight)
                resp["financial_insight"] = financial_insight
            except (TypeError, ValueError):
                logger.warning("Financial insight not serializable, omitting")
        
        # Include selection result if asset was auto-selected
        if selection_result:
            try:
                from backend.services.asset_selection_engine import selection_result_to_dict
                resp["selection_result"] = selection_result_to_dict(selection_result)
            except Exception as sel_err:
                logger.warning("Failed to serialize selection result: %s", str(sel_err)[:100])

        # Include auto-sell proposal if funds recycling is needed
        if preflight_result.requires_auto_sell and preflight_result.auto_sell_proposal:
            resp["auto_sell_proposal"] = preflight_result.auto_sell_proposal
            # Augment the content message
            sell_sym = preflight_result.auto_sell_proposal.get("sell_base_symbol", "asset")
            sell_amt = preflight_result.auto_sell_proposal.get("sell_amount_usd", 0)
            resp["content"] = (
                f"{resp.get('content', '')}\n\n"
                f"Note: Insufficient cash — will auto-sell ${sell_amt:.2f} of {sell_sym} first to fund this trade."
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

            safe_response["content"] = content
            safe_response["portfolio_brief"] = portfolio_brief
            safe_response["queried_asset"] = queried_asset

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
            if is_live:
                content = "No portfolio data found. Try 'Analyze my portfolio' to fetch your live Coinbase holdings."
            else:
                content = "No portfolio data found yet. Execute a trade first to create portfolio snapshots, or configure Coinbase API credentials for live data."
            return JSONResponse(content={
                "content": content,
                "run_id": None,
                "intent": intent_value,
                "status": "COMPLETED",
                "request_id": request_id
            })

        balances = _safe_json_loads(row["balances_json"], {})
        positions = _safe_json_loads(row["positions_json"], {})
        total_value = row["total_value_usd"] or 0.0
        ts = row["ts"]

        # Build formatted output
        lines = [
            f"## Portfolio Snapshot ({mode_str} Mode)",
            f"*As of: {ts}*",
            "",
            f"**Total Value:** ${total_value:,.2f}",
            ""
        ]
        
        # Add holdings table if there are positions
        if positions:
            lines.append("### Positions")
            lines.append("| Asset | Quantity |")
            lines.append("|-------|----------|")
            for asset, qty in positions.items():
                lines.append(f"| {asset} | {qty:,.6f} |")
            lines.append("")
        
        # Add cash balances
        lines.append("### Cash Balances")
        lines.append("| Currency | Amount |")
        lines.append("|----------|--------|")
        for currency, amount in balances.items():
            if currency == "USD":
                lines.append(f"| {currency} | ${amount:,.2f} |")
            else:
                lines.append(f"| {currency} | {amount:,.6f} |")
        
        # Add mode-specific note
        if not is_live:
            lines.append("")
            lines.append("*Note: This is paper trading data. Configure Coinbase API credentials to see your real portfolio.*")

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

        return JSONResponse(content={
            "content": "\n".join(lines),
            "run_id": None,
            "intent": intent_value,
            "status": "COMPLETED",
            "request_id": request_id
        })

    # Fallback for unhandled intents
    return JSONResponse(content={
        "content": "I'm not sure how to handle that request. Try asking about trading, portfolio analysis, or market data.",
        "run_id": None,
        "intent": intent.value if hasattr(intent, 'value') else str(intent),
        "status": "COMPLETED",
        "request_id": request_id
    })
