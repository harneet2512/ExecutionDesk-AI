"""Tool call recording helper for audit trail."""
import json
import asyncio
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.orchestrator.event_emitter import emit_event as _emit_event


async def record_tool_call(
    run_id: str,
    node_id: str,
    tool_name: str,
    mcp_server: str,
    request_json: dict,
    response_json: dict = None,
    status: str = "SUCCESS",
    latency_ms: int = None,
    error_text: str = None,
    http_status: int = None,
    attempt: int = 1,
    wait_time_seconds: float = None
) -> str:
    """
    Record a tool call to the audit trail with enhanced metadata.
    
    Args:
        run_id: Run ID
        node_id: Node ID
        tool_name: Tool name (e.g., "fetch_candles", "place_order")
        mcp_server: MCP server name (e.g., "market_data_server", "coinbase_provider")
        request_json: Request payload (will be redacted if contains secrets)
        response_json: Response payload (will be redacted if contains secrets)
        status: Status (SUCCESS, FAILED, TIMEOUT, etc.)
        latency_ms: Latency in milliseconds
        error_text: Error message if failed
        http_status: HTTP status code if applicable
        attempt: Retry attempt number (default 1)
    
    Returns:
        tool_call_id
    """
    tool_call_id = new_id("tool_")
    
    # Redact sensitive fields
    def redact_dict(d):
        if not d:
            return d
        redacted = d.copy()
        sensitive_keys = ["api_key", "api_secret", "private_key", "CB-ACCESS-KEY", "CB-ACCESS-SIGN", "Authorization"]
        for key in sensitive_keys:
            if key.lower() in str(d).lower():
                if isinstance(redacted, dict):
                    for k in redacted.keys():
                        if key.lower() in k.lower():
                            redacted[k] = "***REDACTED***"
        return redacted
    
    safe_request = redact_dict(request_json)
    safe_response = redact_dict(response_json)
    
    # Emit TOOL_CALL event (before execution for retries, during execution for first attempt)
    if attempt == 1:
        try:
            await _emit_event(run_id, "TOOL_CALL", {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "mcp_server": mcp_server,
                "node_id": node_id,
                "request_summary": _summarize_request(safe_request),
                "attempt": attempt
            }, tenant_id=None)  # Will be fetched in emit_event
        except Exception as e:
            pass  # Don't fail if event emission fails
    
    # Emit RETRY event if this is a retry attempt
    if attempt > 1:
        try:
            await _emit_event(run_id, "RETRY", {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "mcp_server": mcp_server,
                "node_id": node_id,
                "attempt": attempt,
                "wait_time_seconds": wait_time_seconds or 0.0,
                "reason": f"Retrying tool call (attempt {attempt})"
            }, tenant_id=None)
        except Exception:
            pass
    
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO tool_calls (
                id, run_id, node_id, tool_name, mcp_server, 
                request_json, response_json, status, 
                latency_ms, error_text, http_status, attempt, ts
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tool_call_id, run_id, node_id, tool_name, mcp_server,
                json.dumps(safe_request),
                json.dumps(safe_response) if safe_response else None,
                status,
                latency_ms, error_text, http_status, attempt, now_iso()
            )
        )
        conn.commit()
    
    # Emit TOOL_RESULT event after storing
    try:
        await _emit_event(run_id, "TOOL_RESULT", {
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "mcp_server": mcp_server,
            "node_id": node_id,
            "status": status,
            "latency_ms": latency_ms,
            "response_summary": _summarize_response(safe_response, status, error_text),
            "attempt": attempt
        }, tenant_id=None)
    except Exception:
        pass
    
    return tool_call_id


# Sync wrapper for backward compatibility (emits events in background)
def record_tool_call_sync(
    run_id: str,
    node_id: str,
    tool_name: str,
    mcp_server: str,
    request_json: dict,
    response_json: dict = None,
    status: str = "SUCCESS",
    latency_ms: int = None,
    error_text: str = None,
    http_status: int = None,
    attempt: int = 1,
    wait_time_seconds: float = None
) -> str:
    """
    Synchronous wrapper for record_tool_call (for use in sync contexts).
    Events are emitted asynchronously in the background.
    """
    # Store in DB synchronously
    tool_call_id = new_id("tool_")
    
    def redact_dict(d):
        if not d:
            return d
        redacted = d.copy()
        sensitive_keys = ["api_key", "api_secret", "private_key", "CB-ACCESS-KEY", "CB-ACCESS-SIGN", "Authorization"]
        for key in sensitive_keys:
            if key.lower() in str(d).lower():
                if isinstance(redacted, dict):
                    for k in redacted.keys():
                        if key.lower() in k.lower():
                            redacted[k] = "***REDACTED***"
        return redacted
    
    safe_request = redact_dict(request_json)
    safe_response = redact_dict(response_json)
    
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO tool_calls (
                id, run_id, node_id, tool_name, mcp_server, 
                request_json, response_json, status, 
                latency_ms, error_text, http_status, attempt, ts
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tool_call_id, run_id, node_id, tool_name, mcp_server,
                json.dumps(safe_request),
                json.dumps(safe_response) if safe_response else None,
                status,
                latency_ms, error_text, http_status, attempt, now_iso()
            )
        )
        conn.commit()
    
    # Emit events asynchronously in background (best effort).
    # Avoid asyncio.get_event_loop() + run_until_complete() which crashes
    # with "This event loop is already running" inside FastAPI async context.
    try:
        loop = asyncio.get_running_loop()
        # We are inside a running loop; schedule as a background task
        loop.create_task(_emit_tool_events(run_id, tool_call_id, tool_name, mcp_server, node_id, safe_request, safe_response, status, latency_ms, error_text, attempt, wait_time_seconds))
    except RuntimeError:
        # No running loop; fire-and-forget in a new thread
        import threading
        def _bg():
            try:
                asyncio.run(_emit_tool_events(run_id, tool_call_id, tool_name, mcp_server, node_id, safe_request, safe_response, status, latency_ms, error_text, attempt, wait_time_seconds))
            except Exception:
                pass
        threading.Thread(target=_bg, daemon=True).start()
    
    return tool_call_id


async def _emit_tool_events(run_id, tool_call_id, tool_name, mcp_server, node_id, safe_request, safe_response, status, latency_ms, error_text, attempt, wait_time_seconds):
    """Helper to emit tool call events asynchronously."""
    if attempt == 1:
        try:
            await _emit_event(run_id, "TOOL_CALL", {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "mcp_server": mcp_server,
                "node_id": node_id,
                "request_summary": _summarize_request(safe_request),
                "attempt": attempt
            }, tenant_id=None)
        except Exception:
            pass
    
    if attempt > 1:
        try:
            await _emit_event(run_id, "RETRY", {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "mcp_server": mcp_server,
                "node_id": node_id,
                "attempt": attempt,
                "wait_time_seconds": wait_time_seconds or 0.0,
                "reason": f"Retrying tool call (attempt {attempt})"
            }, tenant_id=None)
        except Exception:
            pass
    
    try:
        await _emit_event(run_id, "TOOL_RESULT", {
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "mcp_server": mcp_server,
            "node_id": node_id,
            "status": status,
            "latency_ms": latency_ms,
            "response_summary": _summarize_response(safe_response, status, error_text),
            "attempt": attempt
        }, tenant_id=None)
    except Exception:
        pass


def _summarize_request(request_json: dict) -> str:
    """Create a summary string from request JSON for UI display."""
    if not request_json:
        return "No request details"
    
    # Extract key fields
    parts = []
    if "product_id" in request_json or "symbol" in request_json:
        sym = request_json.get("product_id") or request_json.get("symbol")
        parts.append(f"symbol={sym}")
    if "notional_usd" in request_json:
        parts.append(f"amount=${request_json['notional_usd']}")
    if "side" in request_json:
        parts.append(f"side={request_json['side']}")
    
    return " | ".join(parts) if parts else str(request_json)[:100]


def _summarize_response(response_json: dict, status: str, error_text: str = None) -> str:
    """Create a summary string from response JSON for UI display."""
    if status != "SUCCESS" and error_text:
        return f"Error: {error_text[:100]}"
    
    if not response_json:
        return "No response details"
    
    # Extract key fields
    if "order_id" in response_json:
        return f"Order placed: {response_json['order_id']}"
    if "candles_count" in response_json:
        return f"Fetched {response_json['candles_count']} candles"
    if "fills_count" in response_json:
        return f"Found {response_json['fills_count']} fills"
    
    return str(response_json)[:100]
