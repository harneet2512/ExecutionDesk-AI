"""API key authentication service.

Key format: edai_{env}_{random}
Storage: SHA256 hash only (never store plaintext)
Auth: via X-API-Key header
Permissions: read, trade, admin
Supports key rotation with 24h grace period for old keys.
"""
import hashlib
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

from backend.core.logging import get_logger
from backend.core.utils import _safe_json_loads, json_dumps
from backend.db.connect import get_conn

logger = get_logger(__name__)

# Valid permission scopes
VALID_PERMISSIONS = {"read", "trade", "admin"}

# Dead-letter threshold for rate-limit tracking per key
MAX_REQUESTS_PER_MINUTE = 60


def _get_env_prefix() -> str:
    """Return environment prefix for key format."""
    mode = os.getenv("EXECUTION_MODE_DEFAULT", "PAPER").lower()
    if mode == "live":
        return "live"
    return "test"


def generate_api_key() -> str:
    """Generate a new API key in format edai_{env}_{random}."""
    env = _get_env_prefix()
    random_part = secrets.token_hex(24)  # 48 hex chars
    return f"edai_{env}_{random_part}"


def hash_key(api_key: str) -> str:
    """Compute SHA256 hash of an API key."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def create_api_key(
    tenant_id: str,
    name: str,
    permissions: Optional[list] = None,
) -> dict:
    """Create a new API key for a tenant.

    Args:
        tenant_id: Owner tenant
        name: Human-readable key name
        permissions: List of permission scopes (default: ["read"])

    Returns:
        dict with key_id, api_key (full, shown once), name, permissions
    """
    from backend.core.ids import new_id
    from backend.core.time import now_iso

    if permissions is None:
        permissions = ["read"]

    # Validate permissions
    invalid = set(permissions) - VALID_PERMISSIONS
    if invalid:
        raise ValueError(f"Invalid permissions: {invalid}. Valid: {VALID_PERMISSIONS}")

    key_id = new_id("ak_")
    full_key = generate_api_key()
    key_hash_val = hash_key(full_key)
    key_prefix = full_key[:12]

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO api_keys
               (key_id, tenant_id, name, key_hash, key_prefix,
                permissions_json, is_active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
            (key_id, tenant_id, name, key_hash_val, key_prefix,
             json_dumps(sorted(permissions)), now_iso()),
        )

    return {
        "key_id": key_id,
        "api_key": full_key,
        "name": name,
        "permissions": sorted(permissions),
        "key_prefix": key_prefix,
        "created_at": now_iso(),
    }


def list_api_keys(tenant_id: str) -> list:
    """List all API keys for a tenant. Never returns full key or hash."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT key_id, name, key_prefix, permissions_json,
                      is_active, created_at, revoked_at, last_used_at
               FROM api_keys
               WHERE tenant_id = ? AND revoked_at IS NULL
               ORDER BY created_at DESC""",
            (tenant_id,),
        ).fetchall()

    return [
        {
            "key_id": row["key_id"],
            "name": row["name"],
            "key_prefix": row["key_prefix"],
            "permissions": _safe_json_loads(row["permissions_json"], ["read"]),
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "last_used_at": row["last_used_at"],
        }
        for row in rows
    ]


def revoke_api_key(tenant_id: str, key_id: str) -> bool:
    """Revoke an API key. Returns True if found and revoked."""
    from backend.core.time import now_iso

    with get_conn() as conn:
        result = conn.execute(
            """UPDATE api_keys
               SET revoked_at = ?, is_active = 0
               WHERE key_id = ? AND tenant_id = ? AND revoked_at IS NULL""",
            (now_iso(), key_id, tenant_id),
        )
        return result.rowcount > 0


def rotate_api_key(tenant_id: str, key_id: str) -> Optional[dict]:
    """Rotate an API key. Old key stays valid for 24h grace period.

    Returns:
        dict with new key details, or None if key not found
    """
    from backend.core.time import now_iso
    from datetime import timedelta

    with get_conn() as conn:
        row = conn.execute(
            """SELECT key_id, name, key_hash, permissions_json
               FROM api_keys
               WHERE key_id = ? AND tenant_id = ? AND revoked_at IS NULL""",
            (key_id, tenant_id),
        ).fetchone()

        if not row:
            return None

        old_hash = row["key_hash"]
        permissions = _safe_json_loads(row["permissions_json"], ["read"])

        # Generate new key
        new_full_key = generate_api_key()
        new_hash = hash_key(new_full_key)
        new_prefix = new_full_key[:12]

        # Grace period: 24 hours
        grace_expires = (
            datetime.now(timezone.utc) + timedelta(hours=24)
        ).isoformat()

        conn.execute(
            """UPDATE api_keys
               SET key_hash = ?, key_prefix = ?,
                   previous_key_hash = ?, previous_key_expires_at = ?
               WHERE key_id = ?""",
            (new_hash, new_prefix, old_hash, grace_expires, key_id),
        )

    return {
        "key_id": key_id,
        "api_key": new_full_key,
        "name": row["name"],
        "permissions": permissions,
        "key_prefix": new_prefix,
        "rotated_at": now_iso(),
        "previous_key_expires_at": grace_expires,
    }


def authenticate_api_key(api_key: str) -> Optional[dict]:
    """Authenticate an API key. Returns user info dict or None.

    Checks:
    1. Current key hash match
    2. Previous key hash match (within grace period)
    3. Key not revoked
    4. Key is active

    Returns:
        dict with tenant_id, key_id, permissions, role or None
    """
    key_hash_val = hash_key(api_key)

    with get_conn() as conn:
        # Check current key hash
        row = conn.execute(
            """SELECT key_id, tenant_id, permissions_json, is_active,
                      revoked_at, previous_key_hash, previous_key_expires_at
               FROM api_keys
               WHERE key_hash = ? AND revoked_at IS NULL AND is_active = 1""",
            (key_hash_val,),
        ).fetchone()

        if row:
            # Update last_used_at
            from backend.core.time import now_iso
            conn.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE key_id = ?",
                (now_iso(), row["key_id"]),
            )
            permissions = _safe_json_loads(row["permissions_json"], ["read"])
            return {
                "tenant_id": row["tenant_id"],
                "key_id": row["key_id"],
                "permissions": permissions,
                "role": _permissions_to_role(permissions),
                "user_id": f"apikey:{row['key_id']}",
                "email": None,
                "auth_method": "api_key",
            }

        # Check previous key hash (grace period)
        row = conn.execute(
            """SELECT key_id, tenant_id, permissions_json, is_active,
                      revoked_at, previous_key_expires_at
               FROM api_keys
               WHERE previous_key_hash = ? AND revoked_at IS NULL AND is_active = 1""",
            (key_hash_val,),
        ).fetchone()

        if row and row["previous_key_expires_at"]:
            # Check if grace period is still active
            expires_str = row["previous_key_expires_at"]
            try:
                expires = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) < expires:
                    from backend.core.time import now_iso
                    conn.execute(
                        "UPDATE api_keys SET last_used_at = ? WHERE key_id = ?",
                        (now_iso(), row["key_id"]),
                    )
                    permissions = _safe_json_loads(row["permissions_json"], ["read"])
                    return {
                        "tenant_id": row["tenant_id"],
                        "key_id": row["key_id"],
                        "permissions": permissions,
                        "role": _permissions_to_role(permissions),
                        "user_id": f"apikey:{row['key_id']}",
                        "email": None,
                        "auth_method": "api_key",
                        "using_previous_key": True,
                    }
            except (ValueError, TypeError):
                pass

    return None


def check_permission(user_info: Optional[dict], required_permission: str) -> bool:
    """Check if a user has the required permission.

    Args:
        user_info: dict from authenticate_api_key or None
        required_permission: one of 'read', 'trade', 'admin'

    Returns:
        True if user has the permission
    """
    if not user_info:
        return False
    permissions = user_info.get("permissions", [])
    # Admin implies all permissions
    if "admin" in permissions:
        return True
    return required_permission in permissions


def _permissions_to_role(permissions: list) -> str:
    """Map permission list to the closest role for compatibility."""
    if "admin" in permissions:
        return "admin"
    if "trade" in permissions:
        return "trader"
    return "viewer"
