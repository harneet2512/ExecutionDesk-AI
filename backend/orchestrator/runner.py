"""Orchestrator runner."""
import json
import asyncio
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.orchestrator.state_machine import RunStatus, NodeStatus, can_transition, TERMINAL_RUN_STATUSES
from backend.orchestrator.event_pubsub import event_pubsub
from backend.orchestrator.event_emitter import emit_event as _emit_event
from backend.core.logging import get_logger

logger = get_logger(__name__)

# OpenTelemetry
try:
    from backend.core.otel import get_tracer
    tracer = get_tracer()
except Exception as e:
    logger.warning(f"OpenTelemetry not available: {e}")
    tracer = None

# Import nodes
from backend.orchestrator.nodes.research_node import execute as research_execute
from backend.orchestrator.nodes.signals_node import execute as signals_execute
from backend.orchestrator.nodes.risk_node import execute as risk_execute
from backend.orchestrator.nodes.strategy_node import execute as strategy_execute
from backend.orchestrator.nodes.proposal_node import execute as proposal_execute
from backend.orchestrator.nodes.policy_check_node import execute as policy_check_execute
from backend.orchestrator.nodes.approval_node import execute as approval_execute
from backend.orchestrator.nodes.execution_node import execute as execution_execute
from backend.orchestrator.nodes.post_trade_node import execute as post_trade_execute
from backend.orchestrator.nodes.eval_node import execute as eval_execute
from backend.orchestrator.nodes.news_node import execute as news_execute


def create_run(tenant_id: str, execution_mode: str = "PAPER", source_run_id: str = None) -> str:
    """Create a new run."""
    from backend.core.config import get_settings
    settings = get_settings()
    if settings.force_paper_mode and execution_mode != "PAPER":
        logger.warning(f"FORCE_PAPER_MODE enabled: Overriding mode {execution_mode} -> PAPER for run creation")
        execution_mode = "PAPER"

    run_id = new_id("run_")
    trace_id = new_id("trace_")
    
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO runs (run_id, tenant_id, status, execution_mode, trace_id, source_run_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, tenant_id, RunStatus.CREATED.value, execution_mode, trace_id, source_run_id, now_iso())
        )
        conn.commit()
    
    # Event will be emitted when execute_run starts
    logger.debug("Created run %s in mode %s for tenant %s", run_id, execution_mode, tenant_id)
    return run_id


async def execute_run(run_id: str):
    """Execute a run through all nodes, with timeout protection."""
    from backend.core.config import get_settings
    settings = get_settings()
    timeout_seconds = settings.execution_timeout_seconds
    
    tenant_id = None
    
    try:
        # Wrap entire execution in asyncio timeout
        await asyncio.wait_for(
            _execute_run_with_span(run_id),
            timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        logger.error(f"Run {run_id} timed out after {timeout_seconds}s")
        # Mark run as failed with timeout
        _update_run_status(run_id, RunStatus.FAILED, completed_at=now_iso())
        
        # Persist execution_error artifact
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT tenant_id FROM runs WHERE run_id = ?", (run_id,))
                row = cursor.fetchone()
                tenant_id = row["tenant_id"] if row else "t_default"
            
            error_artifact = {
                "code": "EXECUTION_TIMEOUT",
                "message": f"Run timed out after {timeout_seconds} seconds",
                "timeout_seconds": timeout_seconds,
                "occurred_at": now_iso()
            }
            _persist_artifact(run_id, "execution", "execution_error", error_artifact)
            
            # Create failed trade_receipt
            _create_trade_receipt(run_id, "FAILED", error={"code": "EXECUTION_TIMEOUT", "message": f"Execution timed out after {timeout_seconds}s"})
            
            await _emit_event(run_id, "RUN_STATUS", {"status": "FAILED", "error": "Execution timeout"}, tenant_id=tenant_id)
            await _emit_event(run_id, "RUN_FAILED", {"error": "Execution timeout", "code": "EXECUTION_TIMEOUT"}, tenant_id=tenant_id)
        except Exception as e:
            logger.error(f"Failed to persist timeout artifacts for {run_id}: {e}")


async def _execute_run_with_span(run_id: str):
    """Execute run with optional OTel span."""
    # Create OTel span for entire run execution (optional)
    span = None
    if tracer:
        try:
            from opentelemetry import trace
            # Use regular with (not async with) for context manager
            with tracer.start_as_current_span("execute_run"):
                span = trace.get_current_span()
                if span and hasattr(span, 'set_attribute'):
                    span.set_attribute("run_id", run_id)
                await _execute_run_body(run_id, span)
        except Exception as e:
            if span and hasattr(span, 'record_exception'):
                span.record_exception(e)
            if span and hasattr(span, 'set_attribute'):
                span.set_attribute("status", "failed")
            raise
    else:
        await _execute_run_body(run_id, None)


def _persist_artifact(run_id: str, step_name: str, artifact_type: str, data: dict):
    """Helper to persist a run artifact."""
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (run_id, step_name, artifact_type, json.dumps(data, default=str), now_iso())
        )
        conn.commit()


def _create_trade_receipt(run_id: str, status: str, error: dict = None, error_code: str = None):
    """Create trade_receipt.json artifact for terminal trade states.
    
    Args:
        run_id: Run identifier
        status: Terminal status (COMPLETED or FAILED)
        error: Error dictionary with code and message
        error_code: Structured error code (overrides error['code'] if provided)
    """
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            
            # Get run details
            cursor.execute("""
                SELECT execution_mode, parsed_intent_json, execution_plan_json, completed_at, started_at
                FROM runs WHERE run_id = ?
            """, (run_id,))
            run_row = cursor.fetchone()
            if not run_row:
                return
            
            mode = run_row["execution_mode"] or "PAPER"
            parsed_intent = {}
            if run_row["parsed_intent_json"]:
                try:
                    parsed_intent = json.loads(run_row["parsed_intent_json"])
                except: pass
            
            # Get order from orders table (columns: order_id, symbol, side,
            # notional_usd, filled_qty, avg_fill_price, total_fees, status,
            # status_reason, created_at -- NOT fees_usd/placed_at/completed_at)
            cursor.execute("""
                SELECT order_id, symbol, side, notional_usd, filled_qty, avg_fill_price,
                       total_fees, status, status_reason, created_at
                FROM orders WHERE run_id = ? ORDER BY created_at DESC LIMIT 1
            """, (run_id,))
            order_row = cursor.fetchone()

            # Requested notional from user intent (never overwritten with 0)
            requested_notional = parsed_intent.get("budget_usd", parsed_intent.get("amount_usd", 0))
            # Executed notional from actual order (may differ or be None if no order)
            executed_notional = float(order_row["notional_usd"]) if order_row and order_row["notional_usd"] else None

            # Enhance error with structured code and remediation
            enhanced_error = error
            if error and error_code:
                # Override with structured error code
                from backend.core.error_codes import get_error_message, TradeErrorCode
                try:
                    code_enum = TradeErrorCode(error_code)
                    error_info = get_error_message(code_enum)
                    enhanced_error = {
                        "code": error_code,
                        "message": error.get("message", error_info["message"]),
                        "remediation": error_info["remediation"]
                    }
                except (ValueError, KeyError):
                    # Invalid error code, keep original
                    enhanced_error = error

            # Build receipt
            receipt = {
                "status": "EXECUTED" if status == "COMPLETED" else "FAILED",
                "mode": mode,
                "side": parsed_intent.get("side", "UNKNOWN").upper(),
                "asset_class": "crypto",
                "symbol": order_row["symbol"] if order_row else parsed_intent.get("universe", ["UNKNOWN"])[0].replace("-USD", ""),
                "requested_notional_usd": requested_notional,
                "executed_notional_usd": executed_notional,
                "notional_usd": executed_notional if executed_notional else requested_notional,
                "order_id": order_row["order_id"] if order_row else None,
                "filled_qty": order_row["filled_qty"] if order_row else None,
                "avg_fill_price": order_row["avg_fill_price"] if order_row else None,
                "fees_usd": float(order_row["total_fees"]) if order_row and order_row["total_fees"] else None,
                "placed_at": order_row["created_at"] if order_row else None,
                "completed_at": run_row["completed_at"] or now_iso(),
                "error": enhanced_error,
                "evidence": []
            }
            
            # Add evidence refs from execution artifacts
            cursor.execute("""
                SELECT artifact_type, step_name FROM run_artifacts 
                WHERE run_id = ? AND artifact_type IN ('order_response', 'provider_order')
            """, (run_id,))
            for art_row in cursor.fetchall():
                receipt["evidence"].append({
                    "type": art_row["artifact_type"],
                    "step": art_row["step_name"]
                })
            
            _persist_artifact(run_id, "terminal", "trade_receipt", receipt)
            
            # Also create run_status_summary for UI
            summary_artifact = {
                "run_id": run_id,
                "status": status,
                "ended_at": run_row["completed_at"] or now_iso(),
                "summary": f"{receipt['mode']} {receipt['side']} ${receipt['requested_notional_usd']:.2f} {receipt['symbol']} - {receipt['status']}"
            }
            _persist_artifact(run_id, "terminal", "run_status_summary", summary_artifact)
            
    except Exception as e:
        logger.error(f"Failed to create trade_receipt for {run_id}: {e}")


async def _execute_run_body(run_id: str, span):
    """Execute run body with optional span."""
    tenant_id = None
    
    try:
        # Get run
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT tenant_id, status, execution_mode, trace_id, source_run_id,
                          news_enabled, asset_class
                   FROM runs WHERE run_id = ?""",
                (run_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Run {run_id} not found")
            tenant_id = row["tenant_id"]
            execution_mode = row["execution_mode"]
            trace_id = row["trace_id"] if row and "trace_id" in row.keys() else None
            source_run_id = row["source_run_id"] if row and "source_run_id" in row.keys() else None
            # news_enabled: default True, stored as INTEGER (1/0) or NULL
            news_enabled = True
            if "news_enabled" in row.keys() and row["news_enabled"] is not None:
                news_enabled = bool(row["news_enabled"])
            # asset_class: default CRYPTO
            asset_class = row["asset_class"] if row and "asset_class" in row.keys() and row["asset_class"] else "CRYPTO"
        
        if span and hasattr(span, 'set_attribute'):
            span.set_attribute("tenant_id", tenant_id)
            span.set_attribute("execution_mode", execution_mode)
            span.set_attribute("asset_class", asset_class)
            span.set_attribute("news_enabled", news_enabled)
            if trace_id:
                span.set_attribute("trace_id", trace_id)
            if source_run_id:
                span.set_attribute("source_run_id", source_run_id)
        
        # Transition to RUNNING
        started_at_ts = now_iso()
        _update_run_status(run_id, RunStatus.RUNNING, started_at=started_at_ts)
        
        # Initialize telemetry
        try:
            from backend.core.telemetry_repo import create_or_update_run_telemetry
            create_or_update_run_telemetry(
                run_id=run_id,
                tenant_id=tenant_id,
                started_at=started_at_ts,
                trace_id=trace_id
            )
        except Exception as e:
            logger.warning(f"Failed to initialize telemetry for run {run_id}: {e}")
        
        # Create initial portfolio snapshot (Snapshot 1: run start)
        from backend.providers.paper import PaperProvider
        with get_conn() as conn:
            cursor = conn.cursor()
            # Get current portfolio state
            provider = PaperProvider()
            balances, positions, total_value = provider._get_portfolio_state(conn, cursor, tenant_id)
            
            snapshot_id = new_id("snap_")
            cursor.execute(
                """
                INSERT INTO portfolio_snapshots (
                    snapshot_id, run_id, tenant_id, balances_json, positions_json, total_value_usd, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (snapshot_id, run_id, tenant_id, json.dumps(balances), json.dumps(positions), total_value, now_iso())
            )
            conn.commit()
        
        # Log with correlation IDs (inline to avoid extra= conflicts with LogRecord attrs)
        logger.info(
            "Starting run %s mode=%s tenant=%s asset_class=%s news=%s trace=%s",
            run_id, execution_mode, tenant_id, asset_class, news_enabled, trace_id or "none"
        )
        
        # Node sequence (check if command-based run)
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT command_text FROM runs WHERE run_id = ?",
                (run_id,)
            )
            row = cursor.fetchone()
            is_command_run = row and row["command_text"] if row else False
        
        # Parallelization groups: research+news can run concurrently,
        # signals+risk can run concurrently after research completes.
        # Remaining nodes must be sequential.
        # The "parallel_group" key groups nodes for concurrent execution.
        if is_command_run:
            market_desc = "Fetch stock data (EOD)" if asset_class == "STOCK" else "Fetch market data for universe"
            rank_desc = "Rank by EOD return" if asset_class == "STOCK" else "Rank candidates by 24h return"
            exec_desc = "Generate order ticket" if execution_mode == "ASSISTED_LIVE" else "Place order via provider"

            nodes = [
                ("research", market_desc, research_execute),
            ]
            if news_enabled:
                nodes.append(("news", "Analyze news sentiment", news_execute))
            else:
                logger.info(f"Skipping news node for run {run_id} (news_enabled=False)")

            nodes.extend([
                ("signals", rank_desc, signals_execute),
                ("risk", "Assess portfolio risk", risk_execute),
                ("proposal", "Create order proposal", proposal_execute),
                ("policy_check", "Validate policy/risk/budget constraints", policy_check_execute),
                ("approval", "Await user approval (LIVE mode)", approval_execute),
                ("execution", exec_desc, execution_execute),
                ("post_trade", "Fetch fills and update portfolio", post_trade_execute),
                ("eval", "Run evaluations", eval_execute),
            ])
        else:
            nodes = [
                ("research", "Research market data", research_execute),
            ]
            if news_enabled:
                nodes.append(("news", "News analysis", news_execute))
            nodes.extend([
                ("signals", "Generate signals", signals_execute),
                ("risk", "Risk assessment", risk_execute),
                ("proposal", "Create proposal", proposal_execute),
                ("policy_check", "Policy validation", policy_check_execute),
                ("approval", "Approval check", approval_execute),
                ("execution", "Execute orders", execution_execute),
                ("post_trade", "Post-trade processing", post_trade_execute),
                ("eval", "Run evaluations", eval_execute),
            ])
        
        # Create explicit execution plan and emit PLAN_CREATED event
        # Check if execution_plan_json already exists (e.g., from command route with selected_asset)
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT execution_plan_json FROM runs WHERE run_id = ?",
                (run_id,)
            )
            row = cursor.fetchone()
            existing_plan = None
            if row and row["execution_plan_json"]:
                try:
                    existing_plan = json.loads(row["execution_plan_json"])
                except:
                    pass
        
        # Create new plan structure
        new_plan = {
            "steps": [
                {
                    "step_id": f"step_{i+1}",
                    "step_name": node_name,
                    "description": description,
                    "sequence": i + 1,
                    "status": "pending"
                }
                for i, (node_name, description, _) in enumerate(nodes)
            ]
        }
        
        # Merge with existing plan if it has selected_asset (preserve direct symbol selection)
        if existing_plan:
            if "selected_asset" in existing_plan:
                new_plan["selected_asset"] = existing_plan["selected_asset"]
            if "selected_order" in existing_plan:
                new_plan["selected_order"] = existing_plan["selected_order"]
            if "decision_trace" in existing_plan:
                new_plan["decision_trace"] = existing_plan["decision_trace"]
            else:
                new_plan["decision_trace"] = []
        else:
            new_plan["decision_trace"] = []
        
        execution_plan = new_plan
        
        # Store plan in run
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE runs SET execution_plan_json = ? WHERE run_id = ?",
                (json.dumps(execution_plan), run_id)
            )
            conn.commit()
        
        # Emit PLAN_CREATED event
        await _emit_event(run_id, "PLAN_CREATED", {
            "plan": execution_plan,
            "step_count": len(nodes)
        }, tenant_id=tenant_id)
        
        await _emit_event(run_id, "RUN_CREATED", {"run_id": run_id}, tenant_id=tenant_id)
        await _emit_event(run_id, "RUN_STARTED", {"run_id": run_id, "started_at": now_iso()}, tenant_id=tenant_id)
        await _emit_event(run_id, "RUN_STATUS", {"status": RunStatus.RUNNING.value}, tenant_id=tenant_id)
        
        node_sequence = 0
        for node_name, description, node_func in nodes:
            node_sequence += 1
            
            # Check if node already completed (Resumability)
            try:
                with get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT status FROM dag_nodes WHERE run_id = ? AND name = ?",
                        (run_id, node_name)
                    )
                    row = cursor.fetchone()
                    if row and row["status"] == "COMPLETED":
                        logger.info(f"Skipping completed node {node_name} for run {run_id}")
                        continue
            except Exception as e:
                logger.error(f"Resumability check failed for node {node_name}: {e}")
                
            logger.info(f"Runner: preparing to execute node {node_name}")
            node_id = new_id("node_")
            
            # Create OTel span for node execution
            node_span = None
            node_span_context = None
            
            if tracer:
                try:
                    node_span_context = tracer.start_as_current_span(
                        f"node.{node_name}",
                        attributes={
                            "run_id": run_id,
                            "tenant_id": tenant_id,
                            "node_name": node_name,
                            "mode": execution_mode,
                            "attempt": 1,
                            "node_id": node_id,
                            "sequence": node_sequence
                        }
                    )
                    node_span = node_span_context.__enter__()
                except Exception as span_err:
                    logger.warning(f"Failed to create span for node {node_name}: {span_err}")
            
            try:
                # Create node
                step_started_ts = now_iso()
                with get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO dag_nodes (node_id, run_id, name, node_type, status, started_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (node_id, run_id, node_name, node_name, NodeStatus.RUNNING.value, step_started_ts)
                    )
                    conn.commit()
                
                # Emit STEP_STARTED event (user-visible execution trace)
                step_id = node_id
                step_name = node_name
                await _emit_event(run_id, "STEP_STARTED", {
                    "step_id": step_id,
                    "step_name": step_name,
                    "node_id": node_id,
                    "sequence": node_sequence,
                    "description": description,
                    "started_at": step_started_ts
                }, tenant_id=tenant_id)
                
                await _emit_event(run_id, "NODE_STARTED", {"node_id": node_id, "node_name": node_name}, tenant_id=tenant_id)
                
                # Execute node
                result = await node_func(run_id, node_id, tenant_id)
                
                # Extract evidence refs from result if present
                evidence_refs = result.get("evidence_refs", [])
                safe_summary = result.get("safe_summary", f"{step_name} completed successfully")
                
                # Update node
                with get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        UPDATE dag_nodes 
                        SET status = ?, completed_at = ?, outputs_json = ?
                        WHERE node_id = ?
                        """,
                        (NodeStatus.COMPLETED.value, now_iso(), json.dumps(result), node_id)
                    )
                    conn.commit()
                
                # Emit STEP_FINISHED event (user-visible execution trace)
                step_completed_ts = now_iso()
                try:
                    from datetime import datetime as dt
                    start_dt = dt.fromisoformat(step_started_ts.replace("Z", "+00:00"))
                    end_dt = dt.fromisoformat(step_completed_ts.replace("Z", "+00:00"))
                    duration_ms = int((end_dt - start_dt).total_seconds() * 1000)
                except Exception:
                    duration_ms = None
                
                await _emit_event(run_id, "STEP_COMPLETED", {
                    "step_id": step_id,
                    "step_name": step_name,
                    "sequence": node_sequence,
                    "status": "completed",
                    "started_at": step_started_ts,
                    "completed_at": step_completed_ts,
                    "duration_ms": duration_ms,
                    "evidence_refs": evidence_refs,
                    "summary": safe_summary
                }, tenant_id=tenant_id)
                
                # Also emit STEP_FINISHED for backwards compatibility
                await _emit_event(run_id, "STEP_FINISHED", {
                    "step_id": step_id,
                    "step_name": step_name,
                    "sequence": node_sequence,
                    "status": "completed",
                    "started_at": step_started_ts,
                    "completed_at": step_completed_ts,
                    "duration_ms": duration_ms,
                    "evidence_refs": evidence_refs,
                    "summary": safe_summary
                }, tenant_id=tenant_id)
                
                await _emit_event(run_id, "NODE_FINISHED", {"node_id": node_id, "node_name": node_name, "result": result}, tenant_id=tenant_id)

                # Record Prometheus node latency
                try:
                    from backend.api.routes.prometheus import record_node_latency
                    if duration_ms:
                        record_node_latency(node=node_name, duration_seconds=duration_ms / 1000)
                except Exception:
                    pass
                
                # Record node metrics on span
                if node_span and hasattr(node_span, 'set_attribute'):
                    try:
                        node_span.set_attribute("status", "completed")
                        node_span.set_attribute("duration_ms", duration_ms if duration_ms else 0)
                        
                        # Record additional metrics from result if available
                        if isinstance(result, dict):
                            # External calls count (from tool_calls)
                            with get_conn() as conn:
                                cursor = conn.cursor()
                                cursor.execute(
                                    "SELECT COUNT(*) as cnt FROM tool_calls WHERE node_id = ?",
                                    (node_id,)
                                )
                                row = cursor.fetchone()
                                external_calls = row["cnt"] if row else 0
                            node_span.set_attribute("external_calls_count", external_calls)
                            
                            # Research node specific metrics
                            if node_name == "research":
                                drop_reasons = result.get("drop_reasons", {})
                                returns = result.get("returns_by_symbol", {})
                                node_span.set_attribute("ranked_assets_count", len(returns))
                                node_span.set_attribute("dropped_assets_count", len(drop_reasons))
                                
                                # Check for rate limit hits
                                rate_limit_count = sum(
                                    1 for r in drop_reasons.values() 
                                    if "rate" in str(r).lower() or "429" in str(r)
                                )
                                node_span.set_attribute("rate_limit_hits", rate_limit_count)
                                
                                # Cache hits from api stats if available
                                if "api_call_stats" in result:
                                    stats = result["api_call_stats"]
                                    node_span.set_attribute("cache_hits", stats.get("cache_hits", 0))
                    except Exception as span_attr_err:
                        logger.debug(f"Failed to set span attributes: {span_attr_err}")
                
                # Close node span
                if node_span_context:
                    try:
                        node_span_context.__exit__(None, None, None)
                    except Exception:
                        pass
                
                # Check if approval required
                if result.get("requires_approval"):
                    logger.info(f"Run {run_id} paused for approval at node {node_name}")
                    _update_run_status(run_id, RunStatus.PAUSED)
                    
                    # Emit events
                    await _emit_event(run_id, "RUN_STATUS", {"status": RunStatus.PAUSED.value}, tenant_id=tenant_id)
                    await _emit_event(run_id, "APPROVAL_REQUESTED", {
                        "run_id": run_id,
                        "approval_id": result.get("approval_id")
                    }, tenant_id=tenant_id)
                    
                    if span and hasattr(span, 'set_attribute'):
                        try:
                            span.set_attribute("status", "paused")
                        except Exception:
                            pass
                    
                    # Stop execution loop
                    return
                
            except Exception as e:
                if node_span and hasattr(node_span, 'record_exception'):
                    try:
                        node_span.record_exception(e)
                    except Exception:
                        pass
                if node_span and hasattr(node_span, 'set_attribute'):
                    try:
                        node_span.set_attribute("status", "failed")
                        node_span.set_attribute("error_class", type(e).__name__)
                    except Exception:
                        pass
                
                # Close node span on error
                if node_span_context:
                    try:
                        node_span_context.__exit__(type(e), e, e.__traceback__)
                    except Exception:
                        pass
                
                import traceback
                logger.error(f"Node {node_name} failed: {e}\n{traceback.format_exc()}")
                
                # Extract structured error code if available
                from backend.core.error_codes import TradeErrorException
                error_code = None
                error_dict = {"code": type(e).__name__, "message": str(e)[:500]}
                
                if isinstance(e, TradeErrorException):
                    error_code = e.error_code.value
                    error_dict = e.to_dict()
                elif "product details unavailable" in str(e).lower():
                    error_code = "PRODUCT_DETAILS_UNAVAILABLE"
                elif "timeout" in str(e).lower():
                    error_code = "EXECUTION_TIMEOUT"
                elif "rate limit" in str(e).lower():
                    error_code = "PRODUCT_API_RATE_LIMITED"
                
                # Update node with error
                with get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        UPDATE dag_nodes 
                        SET status = ?, completed_at = ?, error_json = ?
                        WHERE node_id = ?
                        """,
                        (NodeStatus.FAILED.value, now_iso(), json.dumps({"error": str(e), "error_code": error_code}), node_id)
                    )
                    conn.commit()
                
                # Emit STEP_FAILED event
                await _emit_event(run_id, "STEP_FAILED", {
                    "step_id": step_id,
                    "step_name": node_name,
                    "sequence": node_sequence,
                    "status": "failed",
                    "error": str(e),
                    "error_code": error_code,
                    "started_at": step_started_ts if 'step_started_ts' in locals() else now_iso()
                }, tenant_id=tenant_id)
                
                _update_run_status(run_id, RunStatus.FAILED, error=str(e))
                
                # Emit execution failure eval
                try:
                    from backend.evals.runtime_evals import emit_execution_eval
                    emit_execution_eval(run_id, tenant_id, success=False, mode=execution_mode, error=str(e)[:200])
                except Exception:
                    pass

                # Create trade_receipt for failed run with structured error code
                _create_trade_receipt(run_id, "FAILED", error=error_dict, error_code=error_code)
                
                await _emit_event(run_id, "RUN_STATUS", {
                    "status": RunStatus.FAILED.value,
                    "error": str(e),
                    "executed": False,
                    "order_status": "not_submitted",
                }, tenant_id=tenant_id)
                await _emit_event(run_id, "RUN_FAILED", {
                    "error": str(e),
                    "executed": False,
                    "order_status": "not_submitted",
                    "error_code": error_code,
                    "message": "Order not submitted. No trade was placed.",
                }, tenant_id=tenant_id)

                # Record Prometheus metrics for failure
                try:
                    from backend.api.routes.prometheus import record_run_failure, record_node_failure
                    record_run_failure(mode=execution_mode, reason=str(e)[:50])
                    record_node_failure(node=node_name, error_class=type(e).__name__)
                except Exception:
                    pass
                return
        
        # Emit runtime evals for the completed run
        try:
            from backend.evals.runtime_evals import emit_insight_evals, emit_news_coverage_eval, emit_execution_eval
            # Get conversation_id if available
            conv_id = None
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT conversation_id FROM messages WHERE run_id = ? LIMIT 1", (run_id,))
                row = cursor.fetchone()
                if row:
                    conv_id = row["conversation_id"]

            # Emit execution success eval
            emit_execution_eval(run_id, tenant_id, success=True, mode=execution_mode, conversation_id=conv_id)

            # Emit insight evals if insight exists
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT insight_json FROM trade_confirmations WHERE run_id = ? LIMIT 1",
                    (run_id,)
                )
                row = cursor.fetchone()
                if row and row["insight_json"]:
                    try:
                        insight = json.loads(row["insight_json"]) if isinstance(row["insight_json"], str) else row["insight_json"]
                        emit_insight_evals(run_id, tenant_id, insight, conversation_id=conv_id)
                        # Emit news coverage eval
                        headlines = insight.get("sources", {}).get("headlines", [])
                        emit_news_coverage_eval(run_id, tenant_id, news_enabled, len(headlines), conversation_id=conv_id)
                    except Exception as ie:
                        logger.warning("Failed to parse insight for evals: %s", ie)
        except Exception as eval_err:
            logger.warning("Runtime eval emission failed (non-fatal): %s", str(eval_err)[:200])

        # Mark completed
        completed_at_ts = now_iso()
        _update_run_status(run_id, RunStatus.COMPLETED, completed_at=completed_at_ts)
        
        # Create trade_receipt artifact for trade intents
        _create_trade_receipt(run_id, "COMPLETED")
        
        await _emit_event(run_id, "RUN_STATUS", {"status": RunStatus.COMPLETED.value}, tenant_id=tenant_id)
        
        # Fetch summary from run_status_summary artifact to include in completion event
        run_summary = None
        order_status = None
        filled_qty = None
        avg_fill_price = None
        try:
            with get_conn() as conn:
                cursor = conn.execute(
                    "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'run_status_summary' LIMIT 1",
                    (run_id,)
                )
                row = cursor.fetchone()
                if row:
                    summary_data = json.loads(row[0])
                    run_summary = summary_data.get("summary")
                
                # Bug 2 fix: Fetch order status to include in completion event
                # This allows frontend to know if trade was FILLED vs just SUBMITTED
                order_cursor = conn.execute(
                    "SELECT status, filled_qty, avg_fill_price FROM orders WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
                    (run_id,)
                )
                order_row = order_cursor.fetchone()
                if order_row:
                    order_status = order_row["status"] if order_row["status"] else None
                    filled_qty = order_row["filled_qty"] if order_row["filled_qty"] else None
                    avg_fill_price = order_row["avg_fill_price"] if order_row["avg_fill_price"] else None
        except Exception:
            pass
        
        # Include order status in completion event so frontend can show accurate outcome
        completion_payload = {"summary": run_summary, "status": "COMPLETED"}
        if order_status:
            completion_payload["order_status"] = order_status
        if filled_qty is not None:
            completion_payload["filled_qty"] = filled_qty
        if avg_fill_price is not None:
            completion_payload["avg_fill_price"] = avg_fill_price
        await _emit_event(run_id, "RUN_COMPLETED", completion_payload, tenant_id=tenant_id)

        # Record Prometheus metrics for successful run
        try:
            from backend.api.routes.prometheus import record_run_success
            _prom_duration = None
            try:
                from datetime import datetime as _dt
                _prom_start = _dt.fromisoformat(started_at_ts.replace("Z", "+00:00"))
                _prom_end = _dt.fromisoformat(completed_at_ts.replace("Z", "+00:00"))
                _prom_duration = (_prom_end - _prom_start).total_seconds()
            except Exception:
                _prom_duration = 0
            record_run_success(mode=execution_mode, duration_seconds=_prom_duration)
        except Exception as prom_err:
            logger.debug(f"Prometheus metrics recording skipped: {prom_err}")
        
        # Update telemetry with completion data
        try:
            from backend.core.telemetry_repo import create_or_update_run_telemetry
            
            # Calculate duration
            try:
                with get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT started_at FROM runs WHERE run_id = ?", (run_id,))
                    row = cursor.fetchone()
                    if row and row["started_at"]:
                        from datetime import datetime
                        start_dt = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
                        end_dt = datetime.fromisoformat(completed_at_ts.replace("Z", "+00:00"))
                        duration_ms = int((end_dt - start_dt).total_seconds() * 1000)
                    else:
                        duration_ms = None
                    
                    # Count tool calls and errors
                    cursor.execute("SELECT COUNT(*) as count FROM tool_calls WHERE run_id = ?", (run_id,))
                    row = cursor.fetchone()
                    tool_calls_count = row["count"] if row else 0
                    cursor.execute("SELECT COUNT(*) as count FROM tool_calls WHERE run_id = ? AND status = 'FAILED'", (run_id,))
                    row = cursor.fetchone()
                    error_count = row["count"] if row else 0
                    cursor.execute("SELECT COUNT(*) as count FROM run_events WHERE run_id = ?", (run_id,))
                    row = cursor.fetchone()
                    sse_events_count = row["count"] if row else 0
            except Exception as e:
                logger.warning(f"Failed to calculate telemetry metrics for run {run_id}: {e}")
                tool_calls_count = 0
                sse_events_count = 0
                error_count = 0
                duration_ms = None
            
            create_or_update_run_telemetry(
                run_id=run_id,
                tenant_id=tenant_id,
                ended_at=completed_at_ts,
                duration_ms=duration_ms,
                tool_calls_count=tool_calls_count,
                sse_events_count=sse_events_count,
                error_count=error_count,
                trace_id=trace_id
            )
        except Exception as e:
            logger.warning(f"Failed to update telemetry for run {run_id}: {e}")
        
        if span:
            span.set_attribute("status", "completed")
        
    except Exception as e:
        logger.error(f"Run {run_id} execution failed: {e}")
        if span and hasattr(span, 'record_exception'):
            try:
                span.record_exception(e)
            except Exception:
                pass
        if span and hasattr(span, 'set_attribute'):
            try:
                span.set_attribute("status", "failed")
            except Exception:
                pass
        failed_at_ts = now_iso()
        _update_run_status(run_id, RunStatus.FAILED, error=str(e))
        # Try to get tenant_id for error event
        try:
            with get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT tenant_id, trace_id FROM runs WHERE run_id = ?", (run_id,))
                row = cursor.fetchone()
                err_tenant_id = row["tenant_id"] if row else "t_default"
                err_trace_id = row["trace_id"] if row and "trace_id" in row.keys() else None
            await _emit_event(run_id, "RUN_STATUS", {"status": RunStatus.FAILED.value, "error": str(e)}, tenant_id=err_tenant_id)
        except:
            err_tenant_id = "t_default"
            err_trace_id = None
            await _emit_event(run_id, "RUN_STATUS", {"status": RunStatus.FAILED.value, "error": str(e)}, tenant_id="t_default")
        
        # Update telemetry with failure data
        try:
            from backend.core.telemetry_repo import create_or_update_run_telemetry
            
            # Calculate duration and counts
            try:
                with get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT started_at FROM runs WHERE run_id = ?", (run_id,))
                    row = cursor.fetchone()
                    duration_ms = None
                    if row and row["started_at"]:
                        from datetime import datetime
                        start_dt = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
                        end_dt = datetime.fromisoformat(failed_at_ts.replace("Z", "+00:00"))
                        duration_ms = int((end_dt - start_dt).total_seconds() * 1000)
                    
                    cursor.execute("SELECT COUNT(*) as count FROM tool_calls WHERE run_id = ?", (run_id,))
                    row = cursor.fetchone()
                    tool_calls_count = row["count"] if row else 0
                    cursor.execute("SELECT COUNT(*) as count FROM tool_calls WHERE run_id = ? AND status = 'FAILED'", (run_id,))
                    row = cursor.fetchone()
                    error_count = row["count"] if row else 0
                    error_count += 1  # Add one for the run failure itself
                    cursor.execute("SELECT COUNT(*) as count FROM run_events WHERE run_id = ?", (run_id,))
                    row = cursor.fetchone()
                    sse_events_count = row["count"] if row else 0
            except Exception as e2:
                logger.warning(f"Failed to calculate telemetry metrics for failed run {run_id}: {e2}")
                tool_calls_count = 0
                sse_events_count = 0
                error_count = 1
                duration_ms = None
            
            create_or_update_run_telemetry(
                run_id=run_id,
                tenant_id=err_tenant_id,
                ended_at=failed_at_ts,
                duration_ms=duration_ms,
                tool_calls_count=tool_calls_count,
                sse_events_count=sse_events_count,
                error_count=error_count,
                last_error=str(e),
                trace_id=err_trace_id
            )
        except Exception as e3:
            logger.warning(f"Failed to update telemetry for failed run {run_id}: {e3}")


def _update_run_status(run_id: str, status: RunStatus, started_at: str = None, completed_at: str = None, error: str = None):
    """Update run status with transition validation.

    Reads the current status from DB, validates the transition via the state
    machine, and applies the update.  If the transition is invalid, logs a
    warning and skips the update (idempotent for terminal states).
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        # Read current status for transition validation
        cursor.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        if row:
            current_str = row["status"]
            try:
                current = RunStatus(current_str)
            except ValueError:
                current = None

            if current is not None:
                if not can_transition(current, status):
                    # Already in terminal state -- idempotent, just skip
                    if current in TERMINAL_RUN_STATUSES:
                        logger.debug(
                            "Skipping no-op transition %s -> %s for run %s (already terminal)",
                            current.value, status.value, run_id,
                        )
                        return
                    logger.warning(
                        "Invalid run transition %s -> %s for run %s; skipping to preserve state integrity",
                        current.value, status.value, run_id,
                    )
                    return

        if started_at:
            cursor.execute(
                "UPDATE runs SET status = ?, started_at = ? WHERE run_id = ?",
                (status.value, started_at, run_id)
            )
        elif completed_at:
            cursor.execute(
                "UPDATE runs SET status = ?, completed_at = ? WHERE run_id = ?",
                (status.value, completed_at, run_id)
            )
        else:
            if error:
                try:
                    cursor.execute(
                        "UPDATE runs SET status = ?, failure_reason = ? WHERE run_id = ?",
                        (status.value, error, run_id)
                    )
                except Exception as update_err:
                    logger.error(f"Failed to update run status/error: {update_err}")
                    # Fallback to just status update
                    cursor.execute(
                        "UPDATE runs SET status = ? WHERE run_id = ?",
                        (status.value, run_id)
                    )
            else:
                cursor.execute(
                    "UPDATE runs SET status = ? WHERE run_id = ?",
                    (status.value, run_id)
                )
        conn.commit()
