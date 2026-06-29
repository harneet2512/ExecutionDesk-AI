"""API key management endpoints.

POST /api/v1/api-keys       - generate new key
GET  /api/v1/api-keys       - list keys (prefix only)
DELETE /api/v1/api-keys/{id} - revoke key
POST /api/v1/api-keys/{id}/rotate - rotate key
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from backend.api.deps import require_trader
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


class CreateKeyRequest(BaseModel):
    name: str
    permissions: Optional[List[str]] = None


class KeyResponse(BaseModel):
    key_id: str
    api_key: str
    name: str
    permissions: List[str]
    key_prefix: str
    created_at: str


class KeyListItem(BaseModel):
    key_id: str
    name: str
    key_prefix: str
    permissions: List[str]
    is_active: bool
    created_at: str
    last_used_at: Optional[str] = None


@router.post("", status_code=201)
async def generate_key(
    body: CreateKeyRequest,
    user: dict = Depends(require_trader),
):
    """Generate a new API key. The full key is returned only once."""
    try:
        from backend.services.api_key_auth import create_api_key
        result = create_api_key(
            tenant_id=user["tenant_id"],
            name=body.name,
            permissions=body.permissions,
        )
        logger.info("API key created: %s for tenant %s", result["key_id"], user["tenant_id"])
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("")
async def list_keys(user: dict = Depends(require_trader)):
    """List all API keys for the tenant. Never returns full key."""
    from backend.services.api_key_auth import list_api_keys
    return list_api_keys(user["tenant_id"])


@router.delete("/{key_id}")
async def revoke_key(
    key_id: str,
    user: dict = Depends(require_trader),
):
    """Revoke an API key. Immediate effect."""
    from backend.services.api_key_auth import revoke_api_key
    revoked = revoke_api_key(user["tenant_id"], key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found or already revoked")
    logger.info("API key revoked: %s by tenant %s", key_id, user["tenant_id"])
    return {"key_id": key_id, "revoked": True}


@router.post("/{key_id}/rotate")
async def rotate_key(
    key_id: str,
    user: dict = Depends(require_trader),
):
    """Rotate an API key. Old key remains valid for 24 hours."""
    from backend.services.api_key_auth import rotate_api_key
    result = rotate_api_key(user["tenant_id"], key_id)
    if not result:
        raise HTTPException(status_code=404, detail="API key not found or already revoked")
    logger.info("API key rotated: %s for tenant %s", key_id, user["tenant_id"])
    return result
