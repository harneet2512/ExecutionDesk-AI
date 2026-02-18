"""Portfolio analysis node - fetches real account data and produces PortfolioBrief artifact.

This node:
1. Resolves execution mode (LIVE vs PAPER)
2. Fetches holdings/balances from Coinbase
3. Fetches current prices for held assets
4. Fetches recent order history (last 30 days)
5. Computes allocation, risk, and trading behavior metrics
6. Persists everything for REPLAY determinism
7. Returns a structured PortfolioBrief artifact

HARD CONSTRAINTS:
- Tool-first, LLM-second: LLM cannot invent holdings or prices
- Multi-tenant safe: every fetch is scoped to tenant_id
- No secrets in logs: account IDs and API tokens are redacted
- Analysis-only: never places trades
"""
import asyncio
import json
import math
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.core.logging import get_logger
from backend.core.config import get_settings
from backend.core.tool_calls import record_tool_call
from backend.agents.schemas import (
    PortfolioBrief, Holding, AllocationRow, TradeSummary, RiskSnapshot,
    PortfolioRecommendation, EvidenceRefs, FailureArtifact, ExecutionMode
)

logger = get_logger(__name__)


async def execute(run_id: str, node_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Execute portfolio analysis node.
    
    Returns:
        Dict with:
            - portfolio_brief: PortfolioBrief artifact (JSON-serializable)
            - success: bool
            - error: Optional error message
            - evidence_refs: List of tool_call_ids
            - safe_summary: Human-readable summary for UI
    """
    settings = get_settings()
    evidence_refs = EvidenceRefs()
    warnings = []
    
    # Determine execution mode from run metadata
    execution_mode = await _get_execution_mode(run_id, tenant_id)
    logger.info(f"Portfolio analysis starting - mode={execution_mode}, run_id={run_id}, tenant_id={tenant_id}")
    
    # Check for LIVE credentials
    live_creds_available = _check_live_credentials()
    
    # Determine actual mode to use
    use_live = execution_mode == "LIVE" and live_creds_available
    
    if execution_mode == "LIVE" and not live_creds_available:
        warnings.append("LIVE mode requested but credentials not available. Falling back to PAPER snapshot.")
        # Try to use PAPER snapshot instead
        use_live = False
    
    try:
        if use_live:
            # LIVE mode: fetch from Coinbase
            result = await _execute_live_analysis(
                run_id=run_id,
                node_id=node_id,
                tenant_id=tenant_id,
                evidence_refs=evidence_refs,
                warnings=warnings
            )
        else:
            # PAPER mode: use stored snapshots
            result = await _execute_paper_analysis(
                run_id=run_id,
                node_id=node_id,
                tenant_id=tenant_id,
                evidence_refs=evidence_refs,
                warnings=warnings
            )
        
        if result is None:
            # No data available
            failure = FailureArtifact(
                error_code="NO_DATA",
                error_message="No portfolio data available. Execute a trade first or configure LIVE credentials.",
                recoverable=True,
                suggested_action="Execute a trade to create portfolio snapshots, or add COINBASE_API_KEY_NAME and COINBASE_API_PRIVATE_KEY for LIVE mode."
            )
            brief = PortfolioBrief(
                as_of=now_iso(),
                mode=ExecutionMode.PAPER,
                total_value_usd=0.0,
                cash_usd=0.0,
                holdings=[],
                allocation=[],
                trade_summary=None,
                risk=RiskSnapshot(
                    concentration_pct_top1=0.0,
                    concentration_pct_top3=0.0,
                    risk_level="UNKNOWN"
                ),
                recommendations=[],
                warnings=warnings,
                evidence_refs=evidence_refs,
                failure=failure
            )
            return {
                "portfolio_brief": brief.dict(),
                "success": False,
                "error": failure.error_message,
                "evidence_refs": [evidence_refs.accounts_call_id] if evidence_refs.accounts_call_id else [],
                "safe_summary": "Portfolio analysis failed: No data available"
            }
        
        return result
        
    except Exception as e:
        logger.error(f"Portfolio analysis failed: {e}", exc_info=True)
        failure = FailureArtifact(
            error_code="UNKNOWN",
            error_message=str(e),
            recoverable=True,
            suggested_action="Check API credentials and retry."
        )
        brief = PortfolioBrief(
            as_of=now_iso(),
            mode=ExecutionMode.LIVE if use_live else ExecutionMode.PAPER,
            total_value_usd=0.0,
            cash_usd=0.0,
            holdings=[],
            allocation=[],
            trade_summary=None,
            risk=RiskSnapshot(
                concentration_pct_top1=0.0,
                concentration_pct_top3=0.0,
                risk_level="UNKNOWN"
            ),
            recommendations=[],
            warnings=warnings + [str(e)],
            evidence_refs=evidence_refs,
            failure=failure
        )
        return {
            "portfolio_brief": brief.dict(),
            "success": False,
            "error": str(e),
            "evidence_refs": [],
            "safe_summary": f"Portfolio analysis failed: {str(e)[:50]}"
        }


async def _get_execution_mode(run_id: str, tenant_id: str) -> str:
    """Get execution mode from run or config settings."""
    with get_conn() as conn:
        cursor = conn.cursor()
        # Check run's execution mode first
        cursor.execute(
            "SELECT execution_mode FROM runs WHERE run_id = ?",
            (run_id,)
        )
        row = cursor.fetchone()
        if row and row["execution_mode"]:
            return row["execution_mode"]
    
    # Fall back to config-based default: LIVE if credentials configured, else PAPER
    settings = get_settings()
    if settings.coinbase_api_key_name and settings.coinbase_api_private_key:
        return "LIVE"
    return "PAPER"


def _check_live_credentials() -> bool:
    """Check if LIVE Coinbase credentials are available."""
    settings = get_settings()
    return bool(
        settings.enable_live_trading and
        settings.coinbase_api_key_name and
        settings.coinbase_api_private_key
    )


async def _execute_live_analysis(
    run_id: str,
    node_id: str,
    tenant_id: str,
    evidence_refs: EvidenceRefs,
    warnings: List[str]
) -> Optional[Dict[str, Any]]:
    """Execute portfolio analysis with LIVE Coinbase data."""
    from backend.providers.coinbase_provider import CoinbaseProvider
    from backend.services.coinbase_market_data import get_candles
    
    try:
        provider = CoinbaseProvider()
    except ValueError as e:
        warnings.append(f"Failed to initialize Coinbase provider: {e}")
        return None
    
    # 1. Fetch accounts/balances
    # Note: Pass node_id=None since we're outside the DAG runner and the node_id 
    # doesn't exist in dag_nodes (which would cause FK constraint violation)
    accounts_data = provider.get_accounts_detailed(
        tenant_id=tenant_id,
        run_id=run_id,
        node_id=None  # Portfolio analysis runs outside DAG - skip node tracking
    )
    
    # Record the accounts call ID
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id FROM tool_calls 
               WHERE run_id = ? AND tool_name = 'get_accounts_detailed' 
               ORDER BY ts DESC LIMIT 1""",
            (run_id,)
        )
        row = cursor.fetchone()
        if row:
            evidence_refs.accounts_call_id = row["id"]
    
    if not accounts_data.get("accounts"):
        warnings.append("No accounts found in Coinbase response")
        return None
    
    # 1b. Store holdings_raw artifact (sanitized) for debugging and replay
    import hashlib
    
    # Build key_scope_hash from account UUIDs (for debugging without exposing actual IDs)
    account_uuids = [acc.get("uuid", "") for acc in accounts_data["accounts"]]
    key_scope_hash = hashlib.sha256("|".join(sorted(account_uuids)).encode()).hexdigest()[:12]
    
    # Create sanitized holdings_raw artifact
    holdings_raw = {
        "fetch_ts": now_iso(),
        "key_scope_hash": key_scope_hash,  # Hash of account IDs for debugging
        "account_count": len(accounts_data["accounts"]),
        "accounts_summary": [
            {
                "currency": acc.get("currency"),
                "available_balance": acc.get("available_balance", 0),
                "type": acc.get("type"),
                "active": acc.get("active", True),
                # UUID redacted - only first 4 and last 4 chars shown
                "uuid_hint": f"{acc.get('uuid', '')[:4]}...{acc.get('uuid', '')[-4:]}" if acc.get("uuid") else None
            }
            for acc in accounts_data["accounts"]
            if acc.get("available_balance", 0) > 0  # Only include non-zero balances
        ],
        "mode": "LIVE",
        "tenant_id": tenant_id,
        "run_id": run_id
    }
    
    # Store artifact in DB
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "fetch_accounts",
                "holdings_raw",
                json.dumps(holdings_raw),
                now_iso()
            )
        )
        conn.commit()
    
    logger.info(f"Stored holdings_raw artifact: key_scope_hash={key_scope_hash}, accounts={len(holdings_raw['accounts_summary'])}")
    
    # 2. Process accounts into holdings
    holdings = []
    cash_usd = 0.0
    assets_to_price = []
    
    for acc in accounts_data["accounts"]:
        currency = acc["currency"]
        balance = acc["available_balance"]
        
        if balance <= 0:
            continue
        
        if currency == "USD":
            cash_usd = balance
        else:
            # We need to fetch price for this asset
            assets_to_price.append(currency)
            holdings.append({
                "currency": currency,
                "balance": balance,
                "usd_value": 0.0  # To be filled after price fetch
            })
    
    # 3. Fetch prices for held assets
    prices = {}
    for currency in assets_to_price:
        product_id = f"{currency}-USD"
        try:
            # Get recent candles to get current price and compute volatility
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=24)
            
            candles = get_candles(
                product_id=product_id,
                start=start_time.isoformat() + "Z",
                end=end_time.isoformat() + "Z",
                granularity="ONE_HOUR"
            )
            
            if candles:
                current_price = float(candles[-1]["close"])
                prices[currency] = {
                    "price": current_price,
                    "candles": candles
                }
                
                # Record tool call ID for prices
                with get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """SELECT id FROM tool_calls 
                           WHERE run_id = ? AND tool_name LIKE '%candle%' 
                           ORDER BY ts DESC LIMIT 1""",
                        (run_id,)
                    )
                    row = cursor.fetchone()
                    if row and row["id"] not in evidence_refs.prices_call_ids:
                        evidence_refs.prices_call_ids.append(row["id"])
        except Exception as e:
            logger.warning(f"Failed to fetch price for {currency}: {e}")
            warnings.append(f"Could not fetch price for {currency}")
    
    # 4. Compute USD values for holdings
    processed_holdings = []
    for h in holdings:
        currency = h["currency"]
        balance = h["balance"]
        
        if currency in prices:
            price = prices[currency]["price"]
            usd_value = balance * price
        else:
            usd_value = 0.0
            warnings.append(f"No price available for {currency}, USD value set to 0")
        
        processed_holdings.append(Holding(
            asset_symbol=currency,
            qty=balance,
            usd_value=usd_value,
            current_price=prices.get(currency, {}).get("price"),
            cost_basis_usd=None,  # Would need historical data
            unrealized_pnl_usd=None,
            unrealized_pnl_pct=None
        ))
    
    # 5. Compute total value and allocation
    total_holdings_usd = sum(h.usd_value for h in processed_holdings)
    total_value_usd = total_holdings_usd + cash_usd
    
    allocation = []
    for h in processed_holdings:
        if total_value_usd > 0:
            pct = (h.usd_value / total_value_usd) * 100
        else:
            pct = 0.0
        allocation.append(AllocationRow(
            asset_symbol=h.asset_symbol,
            pct=pct,
            usd_value=h.usd_value
        ))
    
    # Add cash to allocation if non-zero
    if cash_usd > 0 and total_value_usd > 0:
        allocation.append(AllocationRow(
            asset_symbol="USD",
            pct=(cash_usd / total_value_usd) * 100,
            usd_value=cash_usd
        ))
    
    # Sort allocation by value descending
    allocation.sort(key=lambda x: x.usd_value, reverse=True)
    
    # 6. Fetch order history for trading behavior
    end_date = datetime.utcnow().isoformat() + "Z"
    start_date = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
    
    logger.info("Fetching order history via asyncio thread...")
    try:
        orders = await asyncio.to_thread(
            provider.get_order_history,
            tenant_id=tenant_id,
            run_id=run_id,
            node_id=None,
            start_date=start_date,
            end_date=end_date,
            limit=100
        )
        logger.info(f"Order history fetched: {len(orders)} orders")
    except Exception as e:
        logger.error(f"Failed to fetch order history: {e}", exc_info=True)
        # Clean user-facing message - no internal exception details
        warnings.append("Order history unavailable right now.")
        orders = []
    
    # Record orders call ID
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id FROM tool_calls 
               WHERE run_id = ? AND tool_name = 'get_order_history' 
               ORDER BY ts DESC LIMIT 1""",
            (run_id,)
        )
        row = cursor.fetchone()
        if row:
            evidence_refs.orders_call_id = row["id"]
    
    # 7. Compute trading summary
    trade_summary = _compute_trade_summary(orders, 30)
    
    # 8. Compute risk metrics
    risk = _compute_risk_metrics(processed_holdings, allocation, prices, total_value_usd)
    
    # 9. Generate recommendations
    recommendations = _generate_recommendations(
        holdings=processed_holdings,
        allocation=allocation,
        risk=risk,
        trade_summary=trade_summary,
        total_value_usd=total_value_usd
    )
    
    # 10. Build final PortfolioBrief
    brief = PortfolioBrief(
        as_of=now_iso(),
        mode=ExecutionMode.LIVE,
        total_value_usd=total_value_usd,
        cash_usd=cash_usd,
        holdings=processed_holdings,
        allocation=allocation,
        trade_summary=trade_summary,
        risk=risk,
        recommendations=recommendations,
        warnings=warnings,
        evidence_refs=evidence_refs,
        failure=None
    )
    
    # 11. Store for REPLAY determinism
    await _store_analysis_snapshot(run_id, tenant_id, brief)
    
    # Generate human-readable summary
    safe_summary = _generate_safe_summary(brief)
    
    return {
        "portfolio_brief": brief.dict(),
        "success": True,
        "error": None,
        "evidence_refs": _collect_evidence_ids(evidence_refs),
        "safe_summary": safe_summary
    }


async def _execute_paper_analysis(
    run_id: str,
    node_id: str,
    tenant_id: str,
    evidence_refs: EvidenceRefs,
    warnings: List[str]
) -> Optional[Dict[str, Any]]:
    """Execute portfolio analysis with PAPER snapshot data."""
    from backend.services.coinbase_market_data import get_candles
    
    # Fetch latest portfolio snapshot from DB
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT snapshot_id, balances_json, positions_json, total_value_usd, ts
            FROM portfolio_snapshots
            WHERE tenant_id = ?
            ORDER BY ts DESC LIMIT 1
            """,
            (tenant_id,)
        )
        row = cursor.fetchone()
    
    if not row:
        # Fallback to deterministic mock data for DEMO/PAPER mode if no history exists
        logger.info(f"No portfolio snapshot found for tenant {tenant_id}. Using deterministic MOCK data.")
        balances = {"USD": 10000.0, "BTC": 0.5, "ETH": 5.0}
        positions = {}
        snapshot_ts = now_iso()
    else:
        balances = json.loads(row["balances_json"]) if row["balances_json"] else {}
        positions = json.loads(row["positions_json"]) if row["positions_json"] else {}
        snapshot_ts = row["ts"]
    
    # Process balances into holdings
    holdings = []
    cash_usd = balances.get("USD", 0.0)
    assets_to_price = []
    
    for currency, balance in balances.items():
        if currency == "USD":
            continue
        if balance > 0:
            assets_to_price.append(currency)
            holdings.append({
                "currency": currency,
                "balance": balance,
                "usd_value": 0.0
            })
    
    # Fetch prices for held assets
    prices = {}
    # Note: asyncio already imported at top level
    
    # 1. Create tasks for all assets
    tasks = []
    task_currencies = []
    
    for currency in assets_to_price:
        product_id = f"{currency}-USD"
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=24)
        
        task = asyncio.to_thread(
            get_candles,
            product_id=product_id,
            start=start_time.isoformat() + "Z",
            end=end_time.isoformat() + "Z",
            granularity="ONE_HOUR"
        )
        tasks.append(task)
        task_currencies.append(currency)
    
    # 2. Run in parallel (with error handling wrapper)
    try:
         # Limit concurrency if needed (e.g. semaphore) but thread pool handles it usually
         results = await asyncio.gather(*tasks, return_exceptions=True)
         
         for i, result in enumerate(results):
             currency = task_currencies[i]
             if isinstance(result, Exception):
                 logger.warning(f"Failed to fetch price for {currency}: {result}")
                 warnings.append(f"Could not fetch price for {currency}")
             elif result:
                 # result is candles list
                 current_price = float(result[-1]["close"])
                 prices[currency] = {
                     "price": current_price,
                     "candles": result
                 }
    except Exception as e:
         logger.error(f"Parallel fetch failed: {e}")
         warnings.append("Failed to fetch market data")
    
    # Compute USD values
    processed_holdings = []
    for h in holdings:
        currency = h["currency"]
        balance = h["balance"]
        
        if currency in prices:
            price = prices[currency]["price"]
            usd_value = balance * price
        else:
            usd_value = 0.0
        
        processed_holdings.append(Holding(
            asset_symbol=currency,
            qty=balance,
            usd_value=usd_value,
            current_price=prices.get(currency, {}).get("price"),
            cost_basis_usd=None,
            unrealized_pnl_usd=None,
            unrealized_pnl_pct=None
        ))
    
    # Compute totals and allocation
    total_holdings_usd = sum(h.usd_value for h in processed_holdings)
    total_value_usd = total_holdings_usd + cash_usd
    
    allocation = []
    for h in processed_holdings:
        if total_value_usd > 0:
            pct = (h.usd_value / total_value_usd) * 100
        else:
            pct = 0.0
        allocation.append(AllocationRow(
            asset_symbol=h.asset_symbol,
            pct=pct,
            usd_value=h.usd_value
        ))
    
    if cash_usd > 0 and total_value_usd > 0:
        allocation.append(AllocationRow(
            asset_symbol="USD",
            pct=(cash_usd / total_value_usd) * 100,
            usd_value=cash_usd
        ))
    
    allocation.sort(key=lambda x: x.usd_value, reverse=True)
    
    # Fetch order history from DB (PAPER orders)
    with get_conn() as conn:
        cursor = conn.cursor()
        thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
        cursor.execute(
            """
            SELECT order_id, symbol, side, notional_usd, status, created_at
            FROM orders
            WHERE tenant_id = ? AND created_at >= ? AND status = 'FILLED'
            ORDER BY created_at DESC
            LIMIT 100
            """,
            (tenant_id, thirty_days_ago)
        )
        db_orders = cursor.fetchall()
    
    orders = [
        {
            "order_id": o["order_id"],
            "product_id": o["symbol"],
            "side": o["side"],
            "filled_value": str(o["notional_usd"]),
            "status": o["status"],
            "created_time": o["created_at"]
        }
        for o in db_orders
    ]
    
    trade_summary = _compute_trade_summary(orders, 30)
    risk = _compute_risk_metrics(processed_holdings, allocation, prices, total_value_usd)
    recommendations = _generate_recommendations(
        holdings=processed_holdings,
        allocation=allocation,
        risk=risk,
        trade_summary=trade_summary,
        total_value_usd=total_value_usd
    )
    
    brief = PortfolioBrief(
        as_of=now_iso(),
        mode=ExecutionMode.PAPER,
        total_value_usd=total_value_usd,
        cash_usd=cash_usd,
        holdings=processed_holdings,
        allocation=allocation,
        trade_summary=trade_summary,
        risk=risk,
        recommendations=recommendations,
        warnings=warnings + [f"Using PAPER snapshot from {snapshot_ts}"],
        evidence_refs=evidence_refs,
        failure=None
    )
    
    await _store_analysis_snapshot(run_id, tenant_id, brief)
    safe_summary = _generate_safe_summary(brief)
    
    return {
        "portfolio_brief": brief.dict(),
        "success": True,
        "error": None,
        "evidence_refs": _collect_evidence_ids(evidence_refs),
        "safe_summary": safe_summary
    }


def _compute_trade_summary(orders: List[Dict], window_days: int) -> Optional[TradeSummary]:
    """Compute trading behavior summary from order history."""
    if not orders:
        return TradeSummary(
            window_days=window_days,
            total_trades=0,
            total_notional_usd=0.0,
            avg_trade_usd=0.0,
            buys=0,
            sells=0,
            top_assets=[]
        )
    
    total_trades = len(orders)
    buys = sum(1 for o in orders if o.get("side", "").upper() == "BUY")
    sells = sum(1 for o in orders if o.get("side", "").upper() == "SELL")
    
    # Compute total notional
    total_notional = 0.0
    asset_counts = {}
    
    for order in orders:
        filled_value = order.get("filled_value")
        if filled_value:
            try:
                total_notional += float(filled_value)
            except (ValueError, TypeError):
                pass
        
        product_id = order.get("product_id", "")
        if product_id:
            asset = product_id.split("-")[0]
            asset_counts[asset] = asset_counts.get(asset, 0) + 1
    
    avg_trade = total_notional / total_trades if total_trades > 0 else 0.0
    
    # Top traded assets
    top_assets = sorted(asset_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_asset_names = [a[0] for a in top_assets]
    
    return TradeSummary(
        window_days=window_days,
        total_trades=total_trades,
        total_notional_usd=total_notional,
        avg_trade_usd=avg_trade,
        buys=buys,
        sells=sells,
        top_assets=top_asset_names,
        win_rate=None,  # Would need entry/exit price data
        realized_pnl_usd=None
    )


def _compute_risk_metrics(
    holdings: List[Holding],
    allocation: List[AllocationRow],
    prices: Dict[str, Dict],
    total_value_usd: float
) -> RiskSnapshot:
    """Compute risk metrics for the portfolio."""
    if not allocation or total_value_usd <= 0:
        return RiskSnapshot(
            concentration_pct_top1=0.0,
            concentration_pct_top3=0.0,
            risk_level="UNKNOWN"
        )
    
    # Sort by percentage descending (excluding USD cash)
    non_cash_alloc = [a for a in allocation if a.asset_symbol != "USD"]
    sorted_alloc = sorted(non_cash_alloc, key=lambda x: x.pct, reverse=True)
    
    # Concentration metrics
    top1_pct = sorted_alloc[0].pct if len(sorted_alloc) >= 1 else 0.0
    top3_pct = sum(a.pct for a in sorted_alloc[:3]) if len(sorted_alloc) >= 1 else 0.0
    
    # Volatility proxy (average of recent price volatility)
    volatility_proxies = []
    for currency, price_data in prices.items():
        candles = price_data.get("candles", [])
        if len(candles) >= 2:
            returns = []
            for i in range(1, len(candles)):
                prev_close = float(candles[i-1]["close"])
                curr_close = float(candles[i]["close"])
                if prev_close > 0:
                    ret = (curr_close - prev_close) / prev_close
                    returns.append(ret)
            
            if returns:
                # Standard deviation of returns
                mean_ret = sum(returns) / len(returns)
                variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
                std_dev = math.sqrt(variance) if variance > 0 else 0
                volatility_proxies.append(std_dev)
    
    avg_volatility = sum(volatility_proxies) / len(volatility_proxies) if volatility_proxies else None
    
    # Diversification score (inverse of Herfindahl index)
    if non_cash_alloc:
        hhi = sum((a.pct / 100) ** 2 for a in non_cash_alloc)
        diversification = 1 - hhi if hhi < 1 else 0
    else:
        diversification = 0
    
    # Determine risk level
    if top1_pct >= 80:
        risk_level = "VERY_HIGH"
    elif top1_pct >= 60:
        risk_level = "HIGH"
    elif top1_pct >= 40:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"
    
    return RiskSnapshot(
        concentration_pct_top1=top1_pct,
        concentration_pct_top3=top3_pct,
        volatility_proxy=avg_volatility,
        drawdown_proxy=None,  # Would need historical portfolio value
        risk_level=risk_level,
        diversification_score=diversification,
        liquidity_score=None  # Would need volume data
    )


def _generate_recommendations(
    holdings: List[Holding],
    allocation: List[AllocationRow],
    risk: RiskSnapshot,
    trade_summary: Optional[TradeSummary],
    total_value_usd: float
) -> List[PortfolioRecommendation]:
    """Generate actionable recommendations based on analysis."""
    recommendations = []
    
    # Check concentration risk
    if risk.concentration_pct_top1 >= 70:
        recommendations.append(PortfolioRecommendation(
            category="REBALANCING",
            priority="HIGH",
            title="High Concentration Risk",
            description=f"Your portfolio has {risk.concentration_pct_top1:.1f}% in a single asset. Consider diversifying to reduce risk.",
            action_required=True
        ))
    elif risk.concentration_pct_top1 >= 50:
        recommendations.append(PortfolioRecommendation(
            category="REBALANCING",
            priority="MEDIUM",
            title="Moderate Concentration",
            description=f"Consider spreading positions more evenly. Top asset is {risk.concentration_pct_top1:.1f}% of portfolio.",
            action_required=False
        ))
    
    # Check diversification
    if risk.diversification_score is not None and risk.diversification_score < 0.3:
        recommendations.append(PortfolioRecommendation(
            category="DIVERSIFICATION",
            priority="MEDIUM",
            title="Low Diversification",
            description="Portfolio is concentrated in few assets. Consider adding positions in different asset types.",
            action_required=False
        ))
    
    # Check trading frequency
    if trade_summary and trade_summary.total_trades > 50:
        recommendations.append(PortfolioRecommendation(
            category="POSITION_SIZING",
            priority="LOW",
            title="High Trading Frequency",
            description=f"{trade_summary.total_trades} trades in {trade_summary.window_days} days. High frequency may increase costs.",
            action_required=False
        ))
    
    # Check volatility
    if risk.volatility_proxy is not None and risk.volatility_proxy > 0.05:
        recommendations.append(PortfolioRecommendation(
            category="RISK_CAP",
            priority="MEDIUM",
            title="High Volatility Exposure",
            description=f"Portfolio shows elevated volatility ({risk.volatility_proxy:.2%}). Consider reducing position sizes.",
            action_required=False
        ))
    
    # If no issues found
    if not recommendations:
        recommendations.append(PortfolioRecommendation(
            category="OTHER",
            priority="LOW",
            title="Portfolio Looks Healthy",
            description="No immediate concerns identified. Continue monitoring.",
            action_required=False
        ))
    
    return recommendations


async def _store_analysis_snapshot(run_id: str, tenant_id: str, brief: PortfolioBrief) -> None:
    """Store portfolio analysis for REPLAY determinism."""
    with get_conn() as conn:
        cursor = conn.cursor()
        snapshot_id = new_id("analysis_")
        cursor.execute(
            """
            INSERT INTO portfolio_analysis_snapshots (
                snapshot_id, run_id, tenant_id, mode, total_value_usd,
                brief_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id, run_id, tenant_id, brief.mode.value,
                brief.total_value_usd, json.dumps(brief.dict()), now_iso()
            )
        )
        conn.commit()


def _collect_evidence_ids(evidence_refs: EvidenceRefs) -> List[str]:
    """Collect all evidence IDs into a flat list."""
    ids = []
    if evidence_refs.accounts_call_id:
        ids.append(evidence_refs.accounts_call_id)
    ids.extend(evidence_refs.prices_call_ids)
    if evidence_refs.orders_call_id:
        ids.append(evidence_refs.orders_call_id)
    ids.extend(evidence_refs.additional_call_ids)
    return ids


def _generate_safe_summary(brief: PortfolioBrief) -> str:
    """Generate human-readable summary for UI display."""
    lines = [
        f"Portfolio Analysis ({brief.mode.value} mode)",
        f"Total Value: ${brief.total_value_usd:,.2f}",
        f"Holdings: {len(brief.holdings)} assets",
    ]
    
    if brief.risk:
        lines.append(f"Risk Level: {brief.risk.risk_level}")
    
    if brief.trade_summary and brief.trade_summary.total_trades > 0:
        lines.append(f"Recent Trades: {brief.trade_summary.total_trades} in {brief.trade_summary.window_days} days")
    
    if brief.recommendations:
        high_priority = [r for r in brief.recommendations if r.priority in ("HIGH", "CRITICAL")]
        if high_priority:
            lines.append(f"Alerts: {len(high_priority)} high-priority recommendation(s)")
    
    return " | ".join(lines)
