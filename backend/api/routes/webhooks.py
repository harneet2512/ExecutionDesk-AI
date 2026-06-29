"""Webhook management endpoints.

POST   /api/v1/webhooks              - register webhook
GET    /api/v1/webhooks              - list webhooks
DELETE /api/v1/webhooks/{id}         - remove webhook
POST   /api/v1/webhooks/{id}/test    - send test event
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List

from backend.api.deps import require_trader
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


class RegisterWebhookRequest(BaseModel):
    url: str
    events: List[str]


class WebhookResponse(BaseModel):
    webhook_id: str
    url: str
    events: List[str]
    secret: str
    is_active: bool
    created_at: str


@router.post("", status_code=201)
async def register_webhook(
    body: RegisterWebhookRequest,
    user: dict = Depends(require_trader),
):
    """Register a new webhook endpoint."""
    try:
        from backend.services.webhook_dispatcher import register_webhook
        result = register_webhook(
            tenant_id=user["tenant_id"],
            url=body.url,
            events=body.events,
        )
        logger.info(
            "Webhook registered: %s -> %s for tenant %s",
            result["webhook_id"], body.url, user["tenant_id"],
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("")
async def list_webhooks_endpoint(user: dict = Depends(require_trader)):
    """List all active webhooks for the tenant."""
    from backend.services.webhook_dispatcher import list_webhooks
    return list_webhooks(user["tenant_id"])


@router.delete("/{webhook_id}")
async def remove_webhook(
    webhook_id: str,
    user: dict = Depends(require_trader),
):
    """Remove a webhook."""
    from backend.services.webhook_dispatcher import delete_webhook
    deleted = delete_webhook(user["tenant_id"], webhook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook not found")
    logger.info("Webhook removed: %s by tenant %s", webhook_id, user["tenant_id"])
    return {"webhook_id": webhook_id, "deleted": True}


@router.post("/{webhook_id}/test")
async def test_webhook(
    webhook_id: str,
    user: dict = Depends(require_trader),
):
    """Send a test event to a webhook."""
    from backend.services.webhook_dispatcher import list_webhooks, deliver_webhook
    from backend.core.time import now_iso

    # Verify webhook belongs to tenant
    hooks = list_webhooks(user["tenant_id"])
    hook = next((h for h in hooks if h["webhook_id"] == webhook_id), None)
    if not hook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    # Send test event
    test_payload = {
        "test": True,
        "message": "This is a test webhook delivery",
        "timestamp": now_iso(),
    }
    deliver_webhook(webhook_id, "test.ping", test_payload)
    logger.info("Test webhook queued: %s for tenant %s", webhook_id, user["tenant_id"])

    return {
        "status": "test_queued",
        "webhook_id": webhook_id,
        "event": "test.ping",
    }
