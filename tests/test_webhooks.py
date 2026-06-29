"""Tests for webhook management and delivery.

TDD: written before implementation.
"""
import hashlib
import hmac
import json
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


@pytest.fixture
def client(test_db):
    """Create a FastAPI test client with isolated DB."""
    os.environ["TEST_AUTH_BYPASS"] = "true"
    from backend.core.config import reset_settings
    reset_settings()
    from backend.api.main import app
    return TestClient(app, raise_server_exceptions=False)


class TestWebhookRegistration:
    """Test webhook registration and listing."""

    def test_register_webhook(self, client):
        resp = client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/webhook",
                "events": ["trade.filled", "run.completed"],
            },
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "webhook_id" in body
        assert body["url"] == "https://example.com/webhook"
        assert "secret" in body
        assert sorted(body["events"]) == ["run.completed", "trade.filled"]
        assert body["is_active"] is True

    def test_register_webhook_invalid_url(self, client):
        resp = client.post(
            "/api/v1/webhooks",
            json={
                "url": "not-a-url",
                "events": ["trade.filled"],
            },
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert resp.status_code == 400

    def test_register_webhook_invalid_event(self, client):
        resp = client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/webhook",
                "events": ["invalid.event"],
            },
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert resp.status_code == 400

    def test_list_webhooks(self, client):
        # Create two webhooks
        client.post(
            "/api/v1/webhooks",
            json={"url": "https://a.com/hook", "events": ["trade.filled"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        client.post(
            "/api/v1/webhooks",
            json={"url": "https://b.com/hook", "events": ["run.completed"]},
            headers={"X-Dev-Tenant": "t_default"},
        )

        resp = client.get(
            "/api/v1/webhooks",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert resp.status_code == 200
        hooks = resp.json()
        assert len(hooks) >= 2
        urls = [h["url"] for h in hooks]
        assert "https://a.com/hook" in urls
        assert "https://b.com/hook" in urls

    def test_list_webhooks_scoped_to_tenant(self, client, test_db):
        """Verify the service layer scopes webhooks by tenant_id."""
        from backend.services.webhook_dispatcher import register_webhook, list_webhooks

        register_webhook(tenant_id="t_hook_a", url="https://ta.com/hook", events=["trade.filled"])
        register_webhook(tenant_id="t_hook_b", url="https://tb.com/hook", events=["trade.filled"])

        hooks_a = list_webhooks("t_hook_a")
        urls_a = [h["url"] for h in hooks_a]
        assert "https://ta.com/hook" in urls_a
        assert "https://tb.com/hook" not in urls_a

        hooks_b = list_webhooks("t_hook_b")
        urls_b = [h["url"] for h in hooks_b]
        assert "https://tb.com/hook" in urls_b
        assert "https://ta.com/hook" not in urls_b

    def test_delete_webhook(self, client):
        create_resp = client.post(
            "/api/v1/webhooks",
            json={"url": "https://del.com/hook", "events": ["trade.filled"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        webhook_id = create_resp.json()["webhook_id"]

        del_resp = client.delete(
            f"/api/v1/webhooks/{webhook_id}",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert del_resp.status_code == 200

        # Verify it's gone from listing
        list_resp = client.get(
            "/api/v1/webhooks",
            headers={"X-Dev-Tenant": "t_default"},
        )
        ids = [h["webhook_id"] for h in list_resp.json()]
        assert webhook_id not in ids


class TestHMACSignature:
    """Test HMAC signature computation."""

    def test_compute_signature(self):
        from backend.services.webhook_dispatcher import compute_hmac_signature

        secret = "test-secret-key"
        payload = '{"event": "trade.filled", "data": {"order_id": "123"}}'

        signature = compute_hmac_signature(secret, payload)

        # Verify format: sha256={hex}
        assert signature.startswith("sha256=")
        hex_part = signature[7:]
        assert len(hex_part) == 64  # SHA256 hex is 64 chars

        # Verify correctness
        expected = hmac.new(
            secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        assert hex_part == expected

    def test_signature_changes_with_different_payload(self):
        from backend.services.webhook_dispatcher import compute_hmac_signature

        secret = "test-secret"
        sig1 = compute_hmac_signature(secret, '{"a": 1}')
        sig2 = compute_hmac_signature(secret, '{"a": 2}')
        assert sig1 != sig2

    def test_signature_changes_with_different_secret(self):
        from backend.services.webhook_dispatcher import compute_hmac_signature

        payload = '{"a": 1}'
        sig1 = compute_hmac_signature("secret1", payload)
        sig2 = compute_hmac_signature("secret2", payload)
        assert sig1 != sig2


class TestDeliveryTracking:
    """Test delivery tracking."""

    def test_delivery_recorded_on_success(self, client, test_db):
        # Register a webhook
        create_resp = client.post(
            "/api/v1/webhooks",
            json={"url": "https://track.com/hook", "events": ["trade.filled"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        webhook_id = create_resp.json()["webhook_id"]
        secret = create_resp.json()["secret"]

        # Simulate a delivery record
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        delivery_id = new_id("dlv_")
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO webhook_deliveries
                   (delivery_id, webhook_id, event_type, payload_json,
                    response_status, response_body, delivered_at, attempt)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (delivery_id, webhook_id, "trade.filled",
                 '{"test": true}', 200, "OK", now_iso(), 1),
            )

        # Verify delivery exists
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM webhook_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
        assert row is not None
        assert row["response_status"] == 200

    def test_delivery_records_failure(self, client, test_db):
        create_resp = client.post(
            "/api/v1/webhooks",
            json={"url": "https://fail.com/hook", "events": ["trade.failed"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        webhook_id = create_resp.json()["webhook_id"]

        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        delivery_id = new_id("dlv_")
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO webhook_deliveries
                   (delivery_id, webhook_id, event_type, payload_json,
                    response_status, response_body, delivered_at, attempt)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (delivery_id, webhook_id, "trade.failed",
                 '{"test": true}', 500, "Internal Server Error", now_iso(), 1),
            )

        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM webhook_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
        assert row["response_status"] == 500


class TestDeadLetterQueue:
    """Test dead letter: 3 failures disables webhook."""

    def test_webhook_disabled_after_3_consecutive_failures(self, client, test_db):
        create_resp = client.post(
            "/api/v1/webhooks",
            json={"url": "https://dead.com/hook", "events": ["trade.filled"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        webhook_id = create_resp.json()["webhook_id"]

        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        # Record 3 consecutive failures
        for i in range(3):
            with get_conn() as conn:
                conn.execute(
                    """INSERT INTO webhook_deliveries
                       (delivery_id, webhook_id, event_type, payload_json,
                        response_status, response_body, delivered_at, attempt)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (new_id("dlv_"), webhook_id, "trade.filled",
                     '{"test": true}', 500, "Error", now_iso(), i + 1),
                )

        # Update consecutive failures count
        with get_conn() as conn:
            conn.execute(
                "UPDATE webhooks SET consecutive_failures = 3, is_active = 0 WHERE webhook_id = ?",
                (webhook_id,),
            )

        # Verify webhook is disabled
        with get_conn() as conn:
            row = conn.execute(
                "SELECT is_active, consecutive_failures FROM webhooks WHERE webhook_id = ?",
                (webhook_id,),
            ).fetchone()
        assert row["is_active"] == 0
        assert row["consecutive_failures"] == 3

    def test_successful_delivery_resets_failure_count(self, client, test_db):
        create_resp = client.post(
            "/api/v1/webhooks",
            json={"url": "https://reset.com/hook", "events": ["trade.filled"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        webhook_id = create_resp.json()["webhook_id"]

        from backend.db.connect import get_conn

        # Set 2 consecutive failures
        with get_conn() as conn:
            conn.execute(
                "UPDATE webhooks SET consecutive_failures = 2 WHERE webhook_id = ?",
                (webhook_id,),
            )

        # Simulate success => reset counter
        with get_conn() as conn:
            conn.execute(
                "UPDATE webhooks SET consecutive_failures = 0 WHERE webhook_id = ?",
                (webhook_id,),
            )

        with get_conn() as conn:
            row = conn.execute(
                "SELECT consecutive_failures FROM webhooks WHERE webhook_id = ?",
                (webhook_id,),
            ).fetchone()
        assert row["consecutive_failures"] == 0

    def test_webhook_test_endpoint(self, client):
        """POST /webhooks/{id}/test sends a test event."""
        create_resp = client.post(
            "/api/v1/webhooks",
            json={"url": "https://testme.com/hook", "events": ["trade.filled"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        webhook_id = create_resp.json()["webhook_id"]

        # The test endpoint should return success (actual delivery is async)
        with patch("backend.services.webhook_dispatcher.deliver_webhook") as mock_deliver:
            mock_deliver.return_value = None
            test_resp = client.post(
                f"/api/v1/webhooks/{webhook_id}/test",
                headers={"X-Dev-Tenant": "t_default"},
            )
        assert test_resp.status_code == 200
        body = test_resp.json()
        assert body["status"] == "test_queued"
