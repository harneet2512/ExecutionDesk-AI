"""Request size limiting middleware."""
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from backend.core.logging import get_logger

logger = get_logger(__name__)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to limit request body size for sensitive endpoints."""
    
    # Max request size per route (bytes)
    SIZE_LIMITS = {
        "/api/v1/chat/command": 1 * 1024 * 1024,  # 1MB
        "/api/v1/commands/execute": 1 * 1024 * 1024,
        "/api/v1/runs/trigger": 512 * 1024,  # 512KB
        "/api/v1/approvals": 512 * 1024,
        "/api/v1/conversations": 512 * 1024,
        "/api/v1/conversations/{id}/messages": 1 * 1024 * 1024,
    }
    
    async def dispatch(self, request: Request, call_next):
        """Check request size before processing."""
        path = request.url.path
        
        # Check if this route has a size limit
        max_size = None
        for route_pattern, limit in self.SIZE_LIMITS.items():
            if path.startswith(route_pattern.split("{")[0]):
                max_size = limit
                break
        
        if max_size and request.method in ("POST", "PUT", "PATCH"):
            # Check Content-Length header
            content_length = request.headers.get("Content-Length")
            if content_length:
                try:
                    size = int(content_length)
                    if size > max_size:
                        logger.warning("Request too large: %s (%s bytes > %s bytes)", path, size, max_size)
                        request_id = getattr(request.state, 'request_id', '')
                        return JSONResponse(
                            status_code=413,
                            content={
                                "status": "ERROR",
                                "error": {
                                    "code": "REQUEST_TOO_LARGE",
                                    "message": f"Request body too large. Maximum size: {max_size} bytes",
                                    "request_id": request_id,
                                },
                                "request_id": request_id,
                            },
                            headers={"X-Request-ID": request_id},
                        )
                except ValueError:
                    pass  # Invalid Content-Length, let request proceed (will fail at body parsing)
        
        return await call_next(request)
