"""Coinbase Advanced Trade JWT authentication (ES256)."""
import jwt
import time
import secrets
from typing import Optional
from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.core.env_utils import get_coinbase_private_key
import os

logger = get_logger(__name__)


def build_jwt(
    method: str,
    path: str,
    host: str = "api.coinbase.com",
    api_key_name: Optional[str] = None,
    api_private_key_pem: Optional[str] = None
) -> str:
    """
    Build JWT token for Coinbase Advanced Trade API (ES256).
    
    Args:
        method: HTTP method (GET, POST, etc.)
        path: API path (e.g., /api/v3/brokerage/orders)
        host: API host (default: api.coinbase.com)
        api_key_name: API key name/ID (from COINBASE_API_KEY_NAME env var)
        api_private_key_pem: Private key in PEM format (from env or file)
    
    Returns:
        JWT token string for Authorization: Bearer header
    
    Coinbase CDP JWT format:
    - Header: { "alg": "ES256", "kid": key_name, "nonce": random_hex }
    - Payload: { "sub": key_name, "iss": "cdp", "nbf": now, "exp": now+120, "uri": "METHOD host/path" }
    """
    settings = get_settings()
    
    # Get credentials from env or settings
    key_name = api_key_name or os.getenv("COINBASE_API_KEY_NAME") or settings.coinbase_api_key
    
    # Use provided key or get from env_utils (handles file/env fallback and normalization)
    if api_private_key_pem:
        private_key_pem = api_private_key_pem
    else:
        try:
            private_key_pem = get_coinbase_private_key()
        except ValueError as e:
            # Fallback to legacy settings for backward compatibility
            private_key_pem = settings.coinbase_api_secret
            if not private_key_pem:
                raise ValueError(f"Coinbase private key not available: {e}") from e
    
    if not key_name:
        raise ValueError("COINBASE_API_KEY_NAME must be set")
    if not private_key_pem:
        raise ValueError("Coinbase private key must be configured")
    
    # Normalize path (remove trailing slash, no query string)
    path = path.rstrip("/")
    if "?" in path:
        path = path.split("?")[0]
    
    # Build URI claim: "METHOD host/path"
    uri_claim = f"{method.upper()} {host}{path}"
    
    # Current time
    now = int(time.time())
    
    # Generate nonce (random hex string)
    nonce = secrets.token_hex(16)
    
    # JWT header
    header = {
        "alg": "ES256",
        "kid": key_name,
        "nonce": nonce
    }
    
    # JWT payload
    payload = {
        "sub": key_name,
        "iss": "cdp",
        "nbf": now,
        "exp": now + 120,  # 2 minutes validity
        "uri": uri_claim
    }
    
    try:
        # Sign JWT with ES256 (PEM already normalized by env_utils)
        token = jwt.encode(
            payload,
            private_key_pem,
            algorithm="ES256",
            headers=header
        )
        
        return token
        
    except Exception as e:
        # Never include key material in error messages
        logger.error(f"JWT signing failed: {type(e).__name__}")
        raise ValueError(f"Failed to sign JWT: {type(e).__name__}") from e
