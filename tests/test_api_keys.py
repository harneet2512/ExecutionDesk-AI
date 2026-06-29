"""Tests for API key management endpoints.

TDD: written before implementation.
"""
import hashlib
import json
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client(test_db):
    """Create a FastAPI test client with isolated DB."""
    os.environ["TEST_AUTH_BYPASS"] = "true"
    from backend.core.config import reset_settings
    reset_settings()
    from backend.api.main import app
    return TestClient(app, raise_server_exceptions=False)


class TestKeyGeneration:
    """Test key generation returns key_id + full key."""

    def test_generate_key_returns_key_id_and_full_key(self, client):
        resp = client.post(
            "/api/v1/api-keys",
            json={"name": "My Test Key", "permissions": ["read"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "key_id" in body
        assert "api_key" in body
        # Key format: edai_{env}_{random}
        assert body["api_key"].startswith("edai_")
        assert body["name"] == "My Test Key"
        assert body["permissions"] == ["read"]

    def test_generate_key_stores_hash_not_plaintext(self, client):
        resp = client.post(
            "/api/v1/api-keys",
            json={"name": "Hash Check", "permissions": ["read"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert resp.status_code == 201
        full_key = resp.json()["api_key"]
        key_id = resp.json()["key_id"]

        # Verify in DB: stored value is SHA256 hash, not the key itself
        from backend.db.connect import get_conn, row_get
        with get_conn() as conn:
            row = conn.execute(
                "SELECT key_hash, key_prefix FROM api_keys WHERE key_id = ?",
                (key_id,),
            ).fetchone()
        assert row is not None
        expected_hash = hashlib.sha256(full_key.encode()).hexdigest()
        assert row["key_hash"] == expected_hash
        # key_prefix should be first 12 chars
        assert row["key_prefix"] == full_key[:12]

    def test_generate_key_default_permissions(self, client):
        resp = client.post(
            "/api/v1/api-keys",
            json={"name": "Default Perms"},
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert resp.status_code == 201
        body = resp.json()
        # Default permissions should be read-only
        assert body["permissions"] == ["read"]


class TestKeyListing:
    """Test key list shows prefix only, never full key."""

    def test_list_keys_shows_prefix_only(self, client):
        # Create a key
        create_resp = client.post(
            "/api/v1/api-keys",
            json={"name": "List Test", "permissions": ["read"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        full_key = create_resp.json()["api_key"]

        # List keys
        list_resp = client.get(
            "/api/v1/api-keys",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert list_resp.status_code == 200
        keys = list_resp.json()
        assert len(keys) >= 1
        # Find our key
        our_key = next(k for k in keys if k["name"] == "List Test")
        assert "key_prefix" in our_key
        # Full key must NEVER appear in listing
        assert "api_key" not in our_key
        assert full_key not in json.dumps(our_key)

    def test_list_keys_scoped_to_tenant(self, client, test_db):
        """Verify the service layer scopes keys by tenant_id."""
        from backend.services.api_key_auth import create_api_key, list_api_keys

        create_api_key(tenant_id="t_a", name="Tenant A Key", permissions=["read"])
        create_api_key(tenant_id="t_b", name="Tenant B Key", permissions=["read"])

        keys_a = list_api_keys("t_a")
        names_a = [k["name"] for k in keys_a]
        assert "Tenant A Key" in names_a
        assert "Tenant B Key" not in names_a

        keys_b = list_api_keys("t_b")
        names_b = [k["name"] for k in keys_b]
        assert "Tenant B Key" in names_b
        assert "Tenant A Key" not in names_b


class TestKeyRevocation:
    """Test revoked key returns 401."""

    def test_revoke_key_returns_success(self, client):
        # Create, then revoke
        create_resp = client.post(
            "/api/v1/api-keys",
            json={"name": "Revoke Me", "permissions": ["read"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        key_id = create_resp.json()["key_id"]

        del_resp = client.delete(
            f"/api/v1/api-keys/{key_id}",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert del_resp.status_code == 200
        assert del_resp.json()["revoked"] is True

    def test_revoked_key_is_marked_in_db(self, client):
        create_resp = client.post(
            "/api/v1/api-keys",
            json={"name": "Check Revoked", "permissions": ["read"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        key_id = create_resp.json()["key_id"]

        client.delete(
            f"/api/v1/api-keys/{key_id}",
            headers={"X-Dev-Tenant": "t_default"},
        )

        from backend.db.connect import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT revoked_at FROM api_keys WHERE key_id = ?",
                (key_id,),
            ).fetchone()
        assert row["revoked_at"] is not None

    def test_revoked_key_auth_returns_401(self, client):
        """A revoked API key used for authentication must return 401."""
        # Create and get the key
        create_resp = client.post(
            "/api/v1/api-keys",
            json={"name": "Auth Revoke Test", "permissions": ["read"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        key_id = create_resp.json()["key_id"]
        api_key = create_resp.json()["api_key"]

        # Revoke
        client.delete(
            f"/api/v1/api-keys/{key_id}",
            headers={"X-Dev-Tenant": "t_default"},
        )

        # Now try to authenticate with the revoked key
        from backend.services.api_key_auth import authenticate_api_key
        from backend.db.connect import get_conn
        result = authenticate_api_key(api_key)
        assert result is None  # Authentication should fail


class TestPermissionScoping:
    """Test permission scoping: read-only key can't POST."""

    def test_read_only_key_has_read_permission(self, client):
        create_resp = client.post(
            "/api/v1/api-keys",
            json={"name": "Read Only", "permissions": ["read"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        api_key = create_resp.json()["api_key"]

        from backend.services.api_key_auth import authenticate_api_key
        result = authenticate_api_key(api_key)
        assert result is not None
        assert "read" in result["permissions"]
        assert "trade" not in result["permissions"]

    def test_trade_key_has_both_permissions(self, client):
        create_resp = client.post(
            "/api/v1/api-keys",
            json={"name": "Trader Key", "permissions": ["read", "trade"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        api_key = create_resp.json()["api_key"]

        from backend.services.api_key_auth import authenticate_api_key
        result = authenticate_api_key(api_key)
        assert result is not None
        assert "read" in result["permissions"]
        assert "trade" in result["permissions"]

    def test_check_permission_helper(self, client):
        create_resp = client.post(
            "/api/v1/api-keys",
            json={"name": "Perm Check", "permissions": ["read"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        api_key = create_resp.json()["api_key"]

        from backend.services.api_key_auth import authenticate_api_key, check_permission
        user_info = authenticate_api_key(api_key)
        assert check_permission(user_info, "read") is True
        assert check_permission(user_info, "trade") is False
        assert check_permission(user_info, "admin") is False


class TestKeyRotation:
    """Test key rotation: old key valid for 24h."""

    def test_rotate_key_returns_new_key(self, client):
        # Create original key
        create_resp = client.post(
            "/api/v1/api-keys",
            json={"name": "Rotate Me", "permissions": ["read", "trade"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        key_id = create_resp.json()["key_id"]
        old_key = create_resp.json()["api_key"]

        # Rotate
        rotate_resp = client.post(
            f"/api/v1/api-keys/{key_id}/rotate",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert rotate_resp.status_code == 200
        body = rotate_resp.json()
        assert "api_key" in body
        new_key = body["api_key"]
        assert new_key != old_key
        assert new_key.startswith("edai_")

    def test_old_key_still_valid_during_grace_period(self, client):
        """After rotation, old key stays valid for 24h grace period."""
        create_resp = client.post(
            "/api/v1/api-keys",
            json={"name": "Grace Period", "permissions": ["read"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        key_id = create_resp.json()["key_id"]
        old_key = create_resp.json()["api_key"]

        # Rotate
        client.post(
            f"/api/v1/api-keys/{key_id}/rotate",
            headers={"X-Dev-Tenant": "t_default"},
        )

        # Old key should still authenticate (within grace period)
        from backend.services.api_key_auth import authenticate_api_key
        result = authenticate_api_key(old_key)
        assert result is not None, "Old key should be valid during 24h grace period"

    def test_new_key_works_after_rotation(self, client):
        create_resp = client.post(
            "/api/v1/api-keys",
            json={"name": "New Key Works", "permissions": ["read", "trade"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        key_id = create_resp.json()["key_id"]

        rotate_resp = client.post(
            f"/api/v1/api-keys/{key_id}/rotate",
            headers={"X-Dev-Tenant": "t_default"},
        )
        new_key = rotate_resp.json()["api_key"]

        from backend.services.api_key_auth import authenticate_api_key
        result = authenticate_api_key(new_key)
        assert result is not None
        assert result["permissions"] == ["read", "trade"]

    def test_old_key_invalid_after_grace_period(self, client):
        """After the 24h grace period, old key must be rejected."""
        from datetime import datetime, timezone, timedelta

        create_resp = client.post(
            "/api/v1/api-keys",
            json={"name": "Expired Grace", "permissions": ["read"]},
            headers={"X-Dev-Tenant": "t_default"},
        )
        key_id = create_resp.json()["key_id"]
        old_key = create_resp.json()["api_key"]

        # Rotate
        client.post(
            f"/api/v1/api-keys/{key_id}/rotate",
            headers={"X-Dev-Tenant": "t_default"},
        )

        # Manually set the previous_key_expires_at to the past
        from backend.db.connect import get_conn
        expired_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with get_conn() as conn:
            conn.execute(
                "UPDATE api_keys SET previous_key_expires_at = ? WHERE key_id = ?",
                (expired_time, key_id),
            )

        from backend.services.api_key_auth import authenticate_api_key
        result = authenticate_api_key(old_key)
        assert result is None, "Old key should be invalid after grace period expires"
