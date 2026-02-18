"""Authentication endpoints."""
from fastapi import APIRouter, HTTPException, status, Request
from pydantic import BaseModel, Field
from backend.core.security import hash_password, verify_password, create_access_token
from backend.core.config import get_settings
from backend.db.connect import get_conn
from backend.core.logging import get_logger
from backend.core.time import now_iso
from backend.core.ids import new_id

logger = get_logger(__name__)

router = APIRouter()


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=255)


class DevTokenRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=100)
    tenant_id: str = Field(default="t_default", min_length=1, max_length=100)
    role: str = Field(default="viewer", pattern="^(viewer|trader|admin)$")
    email: str = Field(default="dev@local", min_length=1, max_length=255)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600  # seconds


@router.post("/login", response_model=TokenResponse)
async def login(login_req: LoginRequest, request: Request = None):
    """Login and get JWT token."""
    settings = get_settings()
    
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Find user by email (search across tenants for simplicity, but validate tenant later)
        cursor.execute(
            "SELECT user_id, tenant_id, email, role, password_hash FROM users WHERE email = ?",
            (login_req.email,)
        )
        user = cursor.fetchone()
        
        if not user:
            # Log auth failure
            try:
                from backend.core.redaction import redact_request_json
                from backend.api.middleware.audit_log import _write_audit_log
                _write_audit_log(
                    tenant_id="unknown",
                    actor="system",
                    action="auth.failure",
                    entity_type="user",
                    entity_id=login_req.email,
                    request_json_str=redact_request_json({"email": login_req.email}),
                    response_status=401,
                    ip_address=request.client.host if request and request.client else None,
                    user_agent=request.headers.get("User-Agent") if request else None,
                    request_id=getattr(request.state, "request_id", None) if request else None,
                    trace_id=None
                )
            except Exception as e:
                logger.warning(f"Failed to log auth failure: {e}")
            
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )
        
        # Verify password
        if not verify_password(login_req.password, user["password_hash"]):
            # Log auth failure
            try:
                from backend.core.redaction import redact_request_json
                from backend.api.middleware.audit_log import _write_audit_log
                _write_audit_log(
                    tenant_id=user["tenant_id"],
                    actor=user["user_id"],
                    action="auth.failure",
                    entity_type="user",
                    entity_id=user["user_id"],
                    request_json_str=redact_request_json({"email": login_req.email}),
                    response_status=401,
                    ip_address=request.client.host if request and request.client else None,
                    user_agent=request.headers.get("User-Agent") if request else None,
                    request_id=getattr(request.state, "request_id", None) if request else None,
                    trace_id=None
                )
            except Exception as e:
                logger.warning(f"Failed to log auth failure: {e}")
            
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )
        
        # Create token with user claims
        token = create_access_token({
            "tenant_id": user["tenant_id"],
            "user_id": user["user_id"],
            "email": user["email"],
            "role": user["role"],
            "sub": user["user_id"]  # Standard JWT subject claim
        })
        
        # Log successful auth
        try:
            from backend.core.redaction import redact_request_json
            from backend.api.middleware.audit_log import _write_audit_log
            _write_audit_log(
                tenant_id=user["tenant_id"],
                actor=user["user_id"],
                action="auth.success",
                entity_type="user",
                entity_id=user["user_id"],
                request_json_str=redact_request_json({"email": login_req.email}),
                response_status=200,
                ip_address=request.client.host if request and request.client else None,
                user_agent=request.headers.get("User-Agent") if request else None,
                request_id=getattr(request.state, "request_id", None) if request else None,
                trace_id=None
            )
        except Exception as e:
            logger.warning(f"Failed to log auth success: {e}")
        
        return TokenResponse(
            access_token=token,
            expires_in=settings.jwt_exp_minutes * 60
        )


@router.post("/dev-token", response_model=TokenResponse)
async def create_dev_token(request_body: DevTokenRequest, request: Request = None):
    """
    Create a dev token for testing (demo-only).
    
    Protected by ENABLE_DEV_AUTH env var.
    DO NOT ENABLE IN PRODUCTION.
    """
    settings = get_settings()
    
    if not settings.enable_dev_auth:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev token endpoint is disabled. Set ENABLE_DEV_AUTH=true to enable (demo only)."
        )
    
    # Log dev token creation
    try:
        from backend.core.redaction import redact_request_json
        from backend.api.middleware.audit_log import _write_audit_log
        _write_audit_log(
            tenant_id=request_body.tenant_id,
            actor="system",
            action="auth.dev_token",
            entity_type="user",
            entity_id=request_body.user_id,
            request_json_str=redact_request_json(request_body.dict()),
            response_status=200,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("User-Agent") if request else None,
            request_id=getattr(request.state, "request_id", None) if request else None,
            trace_id=None
        )
    except Exception as e:
        logger.warning(f"Failed to log dev token creation: {e}")
    
    # Create token
    token = create_access_token({
        "tenant_id": request_body.tenant_id,
        "user_id": request_body.user_id,
        "email": request_body.email,
        "role": request_body.role,
        "sub": request_body.user_id
    })
    
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_exp_minutes * 60
    )
