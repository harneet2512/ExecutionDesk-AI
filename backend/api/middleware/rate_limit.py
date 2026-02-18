"""Rate limiting middleware."""
import time
from typing import Dict, Tuple
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from backend.core.logging import get_logger

logger = get_logger(__name__)

# In-memory rate limiter (in production, use Redis or similar)
_rate_limit_store: Dict[str, Tuple[int, float]] = {}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware for sensitive endpoints."""

    # Rate limits per route: (max_requests, window_seconds)
    RATE_LIMITS = {
        "/api/v1/chat/command": (10, 60),  # 10 requests per minute (write)
        "/api/v1/commands/execute": (10, 60),  # Write
        "/api/v1/runs/trigger": (10, 60),  # Write
        "/api/v1/runs/status/{id}": (120, 60),  # 120/min - lightweight status polling
        "/api/v1/runs": (30, 60),  # GET (read)
        "/api/v1/runs/{id}": (30, 60),  # GET (read)
        "/api/v1/runs/{id}/events": (30, 60),  # SSE (read, but counts as connection)
        "/api/v1/conversations": (30, 60),  # GET (read)
        "/api/v1/conversations/{id}/messages": (60, 60),  # Read-heavy (GET+POST), 60/min
        "/api/v1/telemetry/runs": (30, 60),  # GET (read)
        "/api/v1/telemetry/runs/{id}": (30, 60),  # GET (read)
        "/api/v1/approvals/{id}/approve": (10, 60),  # POST (write)
        "/api/v1/approvals/{id}/deny": (10, 60),  # POST (write)
        "/api/v1/auth/login": (10, 60),  # POST (auth)
        "/api/v1/auth/dev-token": (5, 60),  # POST (auth, stricter)
    }
    
    async def dispatch(self, request: Request, call_next):
        """Check rate limits before processing request."""
        path = request.url.path
        
        # Find matching rate limit (handle path patterns like /runs/{id})
        max_requests = None
        window_seconds = 60
        
        # Try exact match first
        if path in self.RATE_LIMITS:
            max_requests, window_seconds = self.RATE_LIMITS[path]
        else:
            # Try pattern matching (e.g., /runs/{id})
            for pattern, limits in self.RATE_LIMITS.items():
                if "{" in pattern:
                    # Match prefix AND segment count to prevent over-matching.
                    # e.g. /conversations/{id}/messages (6 segments) must NOT match
                    # /conversations/conv_123 (5 segments).
                    prefix = pattern.split("{")[0]
                    if path.startswith(prefix) and len(path.split("/")) == len(pattern.split("/")):
                        max_requests, window_seconds = limits
                        break
        
        # Skip rate limiting if no limit defined
        if max_requests is None:
            return await call_next(request)
        
        # Get tenant_id and user_id from request state (set by get_current_user) or headers
        tenant_id = getattr(request.state, "tenant_id", None) or request.headers.get("X-Dev-Tenant", "default")
        user_id = getattr(request.state, "user_id", None) or "anonymous"
        client_ip = request.client.host if request.client else "unknown"
        
        # Key = tenant_id:user_id:path (for per-user limits)
        key = f"{tenant_id}:{user_id}:{path}"
        
        # Check rate limit
        now = time.time()
        requests, last_reset = _rate_limit_store.get(key, (0, now))
        
        # Reset if window expired
        if now - last_reset >= window_seconds:
            requests = 0
            last_reset = now
        
        # Check if limit exceeded - return JSONResponse directly (never raise
        # inside BaseHTTPMiddleware.dispatch; Starlette wraps raised HTTPException
        # in ExceptionGroup which bypasses FastAPI's handler and surfaces as 500)
        if requests >= max_requests:
            retry_after = int(window_seconds - (now - last_reset))
            if retry_after < 1:
                retry_after = 1
            logger.warning("Rate limit exceeded for %s: %s/%s requests", key, requests, max_requests)
            request_id = getattr(request.state, 'request_id', '')
            return JSONResponse(
                status_code=429,
                content={
                    "status": "ERROR",
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                        "request_id": request_id,
                    },
                    "content": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                    "request_id": request_id,
                    "retry_after_seconds": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-Request-ID": request_id,
                },
            )
        
        # Increment counter
        _rate_limit_store[key] = (requests + 1, last_reset)
        
        return await call_next(request)
