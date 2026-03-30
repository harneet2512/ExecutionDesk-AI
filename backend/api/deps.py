"""FastAPI dependencies."""
from typing import Optional, List
from fastapi import Depends, HTTPException, status, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from backend.core.security import decode_access_token
from backend.core.config import get_settings

security = HTTPBearer(auto_error=False)


async def get_current_user(
    x_dev_tenant: Optional[str] = Header(None, alias="X-Dev-Tenant"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    request: Request = None
) -> dict:
    """
    Get current user from JWT or dev header.
    
    Security: For security decisions, JWT tenant_id is authoritative.
    X-Dev-Tenant is only allowed if ENABLE_DEV_AUTH=false (fallback, not secure).
    
    Also supports ?tenant=... query parameter for SSE/EventSource connections
    which cannot set custom HTTP headers.
    """
    settings = get_settings()
    
    # Test auth bypass (pytest only)
    if settings.test_auth_bypass:
        return {
            "tenant_id": "t_default",
            "user_id": "test-user",
            "role": "admin",
            "email": "test@test.com"
        }
    
    # Dev mode fallback: allow X-Dev-Tenant header (NOT for security, convenience only)
    if not settings.enable_dev_auth and settings.api_secret_key == "dev-secret-key-change-in-production" and x_dev_tenant:
        return {
            "tenant_id": x_dev_tenant,
            "user_id": "dev-user",
            "role": "admin",
            "email": "dev@local"
        }
    
    # Dev mode fallback: allow ?tenant=... query parameter for SSE (EventSource
    # cannot send custom headers).  Same security check as X-Dev-Tenant.
    if not settings.enable_dev_auth and settings.api_secret_key == "dev-secret-key-change-in-production":
        if request and not x_dev_tenant:
            qs_tenant = request.query_params.get("tenant")
            if qs_tenant:
                return {
                    "tenant_id": qs_tenant,
                    "user_id": "dev-user",
                    "role": "admin",
                    "email": "dev@local"
                }
    
    # JWT auth (required for security)
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    
    # Extract required fields
    tenant_id = payload.get("tenant_id")
    user_id = payload.get("user_id") or payload.get("sub")
    role = payload.get("role", "viewer")
    email = payload.get("email")
    
    if not tenant_id or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing required claims (tenant_id, user_id)"
        )
    
    # Store user info in request state for audit logging
    if request:
        request.state.user_id = user_id
        request.state.tenant_id = tenant_id
        request.state.role = role
    
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "role": role,
        "email": email
    }


def require_role(allowed_roles: List[str]):
    """
    Dependency factory to require specific roles.
    
    Usage:
        @router.post("/admin/action")
        async def admin_action(user: dict = Depends(require_role(["admin"]))):
            ...
    """
    async def role_checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role: {', '.join(allowed_roles)}. Your role: {user.get('role')}"
            )
        return user
    
    return role_checker


# Convenience dependencies for common role requirements
async def require_viewer(user: dict = Depends(require_role(["viewer", "trader", "admin"]))) -> dict:
    """Require viewer or higher."""
    return user


async def require_trader(user: dict = Depends(require_role(["trader", "admin"]))) -> dict:
    """Require trader or higher."""
    return user


async def require_admin(user: dict = Depends(require_role(["admin"]))) -> dict:
    """Require admin role."""
    return user
