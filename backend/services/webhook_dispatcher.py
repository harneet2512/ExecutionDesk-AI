"""Webhook event dispatcher.

HMAC signature: sha256={hex}
Async delivery with 3 retries
Dead letter queue after 3 consecutive failures (webhook disabled)
Events: trade.filled, trade.failed, run.completed, run.failed,
        approval.needed, policy.blocked
"""
import hashlib
import hmac as hmac_mod
import json
import threading
from typing import Optional

from backend.core.logging import get_logger
from backend.core.utils import _safe_json_loads, json_dumps
from backend.db.connect import get_conn

logger = get_logger(__name__)

# Supported event types
VALID_EVENTS = {
    "trade.filled",
    "trade.failed",
    "run.completed",
    "run.failed",
    "approval.needed",
    "policy.blocked",
}

MAX_CONSECUTIVE_FAILURES = 3
MAX_DELIVERY_ATTEMPTS = 3


def compute_hmac_signature(secret: str, payload: str) -> str:
    """Compute HMAC-SHA256 signature for webhook payload.

    Args:
        secret: Webhook secret key
        payload: JSON payload string

    Returns:
        Signature in format sha256={hex}
    """
    digest = hmac_mod.new(
        secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


def register_webhook(
    tenant_id: str,
    url: str,
    events: list,
    secret: Optional[str] = None,
) -> dict:
    """Register a new webhook.

    Args:
        tenant_id: Owner tenant
        url: Delivery URL (must be https in production)
        events: List of event types to subscribe to
        secret: Optional webhook secret (generated if not provided)

    Returns:
        dict with webhook_id, url, events, secret, is_active
    """
    import secrets
    from backend.core.ids import new_id
    from backend.core.time import now_iso

    # Validate URL
    if not url.startswith("http://") and not url.startswith("https://"):
        raise ValueError("Webhook URL must start with http:// or https://")

    # Validate events
    invalid = set(events) - VALID_EVENTS
    if invalid:
        raise ValueError(
            f"Invalid events: {invalid}. Valid: {sorted(VALID_EVENTS)}"
        )

    if not events:
        raise ValueError("At least one event type is required")

    webhook_id = new_id("wh_")
    if secret is None:
        secret = secrets.token_hex(32)

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO webhooks
               (webhook_id, tenant_id, url, secret, events_json,
                is_active, consecutive_failures, created_at)
               VALUES (?, ?, ?, ?, ?, 1, 0, ?)""",
            (webhook_id, tenant_id, url, secret,
             json_dumps(sorted(events)), now_iso()),
        )

    return {
        "webhook_id": webhook_id,
        "url": url,
        "events": sorted(events),
        "secret": secret,
        "is_active": True,
        "created_at": now_iso(),
    }


def list_webhooks(tenant_id: str) -> list:
    """List all active webhooks for a tenant."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT webhook_id, url, events_json, is_active,
                      consecutive_failures, created_at
               FROM webhooks
               WHERE tenant_id = ? AND is_active = 1
               ORDER BY created_at DESC""",
            (tenant_id,),
        ).fetchall()

    return [
        {
            "webhook_id": row["webhook_id"],
            "url": row["url"],
            "events": _safe_json_loads(row["events_json"], []),
            "is_active": bool(row["is_active"]),
            "consecutive_failures": row["consecutive_failures"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def delete_webhook(tenant_id: str, webhook_id: str) -> bool:
    """Delete (deactivate) a webhook. Returns True if found."""
    with get_conn() as conn:
        result = conn.execute(
            """UPDATE webhooks SET is_active = 0
               WHERE webhook_id = ? AND tenant_id = ?""",
            (webhook_id, tenant_id),
        )
        return result.rowcount > 0


def deliver_webhook(
    webhook_id: str,
    event_type: str,
    payload: dict,
) -> None:
    """Deliver a webhook event asynchronously with retries.

    Runs in a background thread. Records delivery attempts.
    Disables webhook after MAX_CONSECUTIVE_FAILURES.

    Args:
        webhook_id: Target webhook ID
        event_type: Event type string
        payload: Event payload dict
    """
    thread = threading.Thread(
        target=_deliver_sync,
        args=(webhook_id, event_type, payload),
        daemon=True,
    )
    thread.start()


def _deliver_sync(
    webhook_id: str,
    event_type: str,
    payload: dict,
) -> None:
    """Synchronous delivery with retries (runs in background thread)."""
    import time
    from backend.core.ids import new_id
    from backend.core.time import now_iso

    with get_conn() as conn:
        row = conn.execute(
            "SELECT url, secret, is_active FROM webhooks WHERE webhook_id = ?",
            (webhook_id,),
        ).fetchone()

    if not row or not row["is_active"]:
        logger.warning("Webhook %s not found or inactive, skipping delivery", webhook_id)
        return

    url = row["url"]
    secret = row["secret"]
    payload_str = json_dumps({"event": event_type, "data": payload})
    signature = compute_hmac_signature(secret, payload_str)

    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": signature,
        "X-Webhook-Event": event_type,
    }

    last_status = None
    last_body = None
    success = False

    for attempt in range(1, MAX_DELIVERY_ATTEMPTS + 1):
        try:
            import httpx
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, content=payload_str, headers=headers)
                last_status = resp.status_code
                last_body = resp.text[:500]

                if 200 <= resp.status_code < 300:
                    success = True
                    break
        except Exception as e:
            last_status = 0
            last_body = str(e)[:500]
            logger.warning(
                "Webhook delivery attempt %d/%d to %s failed: %s",
                attempt, MAX_DELIVERY_ATTEMPTS, url, str(e)[:100],
            )

        if attempt < MAX_DELIVERY_ATTEMPTS:
            time.sleep(2 ** attempt)  # Exponential backoff

    # Record delivery
    delivery_id = new_id("dlv_")
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO webhook_deliveries
               (delivery_id, webhook_id, event_type, payload_json,
                response_status, response_body, delivered_at, attempt)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (delivery_id, webhook_id, event_type, payload_str,
             last_status, last_body, now_iso(),
             MAX_DELIVERY_ATTEMPTS if not success else 1),
        )

        if success:
            # Reset failure counter on success
            conn.execute(
                "UPDATE webhooks SET consecutive_failures = 0 WHERE webhook_id = ?",
                (webhook_id,),
            )
        else:
            # Increment failure counter
            conn.execute(
                """UPDATE webhooks
                   SET consecutive_failures = consecutive_failures + 1
                   WHERE webhook_id = ?""",
                (webhook_id,),
            )
            # Check if we should disable
            row = conn.execute(
                "SELECT consecutive_failures FROM webhooks WHERE webhook_id = ?",
                (webhook_id,),
            ).fetchone()
            if row and row["consecutive_failures"] >= MAX_CONSECUTIVE_FAILURES:
                conn.execute(
                    "UPDATE webhooks SET is_active = 0 WHERE webhook_id = ?",
                    (webhook_id,),
                )
                logger.warning(
                    "Webhook %s disabled after %d consecutive failures",
                    webhook_id, MAX_CONSECUTIVE_FAILURES,
                )


def dispatch_event(tenant_id: str, event_type: str, payload: dict) -> int:
    """Dispatch an event to all matching webhooks for a tenant.

    Args:
        tenant_id: Tenant whose webhooks to check
        event_type: Event type to dispatch
        payload: Event data

    Returns:
        Number of webhooks the event was dispatched to
    """
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT webhook_id, events_json
               FROM webhooks
               WHERE tenant_id = ? AND is_active = 1""",
            (tenant_id,),
        ).fetchall()

    dispatched = 0
    for row in rows:
        events = _safe_json_loads(row["events_json"], [])
        if event_type in events:
            deliver_webhook(row["webhook_id"], event_type, payload)
            dispatched += 1

    if dispatched > 0:
        logger.info(
            "Dispatched %s event to %d webhooks for tenant %s",
            event_type, dispatched, tenant_id,
        )
    return dispatched
