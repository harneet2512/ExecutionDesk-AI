"""Audit logging middleware."""
import json
import hashlib
from typing import Any, Dict, Optional
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.core.logging import get_logger
from backend.core.redaction import redact_request_json
from backend.db.connect import get_conn

logger = get_logger(__name__)


def _write_audit_log(
    tenant_id: str,
    actor: str,
    action: str,
    entity_type: Optional[str],
    entity_id: Optional[str],
    request_json_str: Optional[str],
    response_status: int,
    ip_address: Optional[str],
    user_agent: Optional[str],
    request_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    role: Optional[str] = None
):
    """Write audit log entry (centralized utility)."""
    try:
        audit_id = new_id("audit_")
        
        # Compute request_hash (SHA256) for tamper detection
        request_hash = None
        if request_json_str:
            request_hash = hashlib.sha256(request_json_str.encode('utf-8')).hexdigest()
        
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO audit_logs (
                    id, tenant_id, actor, action, entity_type, entity_id,
                    request_json, request_hash, response_status,
                    ip_address, user_agent, request_id, trace_id, role, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id, tenant_id, actor, action, entity_type, entity_id,
                    request_json_str, request_hash, response_status,
                    ip_address, user_agent, request_id, trace_id, role, now_iso()
                )
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"Failed to write audit log: {e}")


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Audit logging middleware for critical actions."""
    
    # Actions to audit
    AUDIT_ACTIONS = {
        "POST /api/v1/chat/command": "commands.execute",
        "POST /api/v1/commands/execute": "commands.execute",
        "POST /api/v1/runs/trigger": "runs.trigger",
        "POST /api/v1/approvals/{approval_id}/approve": "approvals.approve",
        "POST /api/v1/approvals/{approval_id}/deny": "approvals.deny",
        "GET /api/v1/telemetry/runs": "telemetry.access",
        "GET /api/v1/telemetry/runs/{run_id}": "telemetry.access",
        "POST /api/v1/confirmations/{id}/confirm": "confirmations.confirm",
        "POST /api/v1/confirmations/{id}/cancel": "confirmations.cancel",
        "POST /api/v1/orders/{id}/reconcile": "orders.reconcile",
        "DELETE /api/v1/conversations/{id}": "conversations.delete",
    }
    
    async def dispatch(self, request: Request, call_next):
        """Log audit events for critical actions."""
        method = request.method
        path = request.url.path
        
        # Check if this action should be audited
        action_key = f"{method} {path}"
        action = None
        
        # Try exact match first
        if action_key in self.AUDIT_ACTIONS:
            action = self.AUDIT_ACTIONS[action_key]
        else:
            # Try pattern matching (e.g., /approvals/{id}/approve, /telemetry/runs/{id})
            for pattern, audit_action in self.AUDIT_ACTIONS.items():
                if pattern.startswith(method):
                    pattern_path = pattern.split(" ", 1)[1] if " " in pattern else pattern
                    # Handle path patterns with {id}
                    if "{" in pattern_path:
                        prefix = pattern_path.rsplit("/{", 1)[0]
                        if path.startswith(prefix):
                            action = audit_action
                            break
                    elif path == pattern_path:
                        action = audit_action
                        break
        
        if not action:
            # Not an audited action
            return await call_next(request)
        
        # Get user info from request state (set by get_current_user dependency)
        tenant_id = getattr(request.state, "tenant_id", None) or "unknown"
        actor = getattr(request.state, "user_id", None) or "system"
        role = getattr(request.state, "role", None)
        request_id = getattr(request.state, "request_id", None)
        trace_id = None  # Will be extracted from response headers if available
        
        # Read request body if available (for POST/PUT/PATCH)
        request_json = None
        request_body_bytes = None
        try:
            if method in ("POST", "PUT", "PATCH"):
                request_body_bytes = await request.body()
                if request_body_bytes:
                    request_json = json.loads(request_body_bytes.decode('utf-8'))
        except Exception:
            pass
        
        # Get entity info from path/body
        entity_type = "run"  # Default
        entity_id = None
        if "run_id" in path:
            # Extract run_id from path (e.g., /runs/run_12345/...)
            parts = path.split("/")
            for i, part in enumerate(parts):
                if part.startswith("run_") or (i > 0 and parts[i-1] == "runs"):
                    entity_id = part
                    break
        elif request_json:
            entity_id = request_json.get("run_id") or request_json.get("approval_id") or request_json.get("source_run_id")
        
        # Process request first - catch HTTPException (and ExceptionGroup-wrapped
        # HTTPException) to prevent further wrapping by outer BaseHTTPMiddleware layers
        try:
            response = await call_next(request)
        except Exception as exc:
            http_exc = None
            if isinstance(exc, HTTPException):
                http_exc = exc
            elif isinstance(exc, ExceptionGroup):
                # Recursively search for HTTPException inside ExceptionGroup
                from backend.api.main import _find_http_exception
                http_exc = _find_http_exception(exc)

            if http_exc:
                from fastapi.responses import JSONResponse
                req_id = getattr(request.state, 'request_id', '')
                # Pass through structured error dicts from endpoints
                detail = http_exc.detail
                if isinstance(detail, dict) and "error" in detail:
                    content = {
                        "status": "ERROR",
                        "detail": detail,
                        "request_id": req_id,
                    }
                else:
                    content = {
                        "status": "ERROR",
                        "error": {"code": f"HTTP_{http_exc.status_code}", "message": str(detail), "request_id": req_id},
                        "content": str(detail),
                        "request_id": req_id,
                    }
                response = JSONResponse(
                    status_code=http_exc.status_code,
                    content=content,
                    headers={"X-Request-ID": req_id},
                )
            else:
                raise

        # Extract trace_id from response headers
        trace_id = response.headers.get("X-Trace-ID")
        
        # Log audit event (synchronous for non-repudiation)
        request_json_str = redact_request_json(request_json, max_size_bytes=10000)
        
        _write_audit_log(
            tenant_id=tenant_id,
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            request_json_str=request_json_str,
            response_status=response.status_code,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
            request_id=request_id,
            trace_id=trace_id,
            role=role
        )
        
        return response
