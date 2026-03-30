"""Central secret redaction utility."""
import json
import re
import base64
from typing import Any, Dict, List, Union, Optional


# Keys that should be redacted (case-insensitive)
REDACTED_KEYS = {
    'api_key', 'api_secret', 'secret', 'token', 'authorization', 'auth',
    'private_key', 'passphrase', 'password', 'pwd', 'credential',
    'access_token', 'refresh_token', 'jwt', 'session_id'
}


def is_base64_like(s: str) -> bool:
    """Heuristically detect base64-encoded strings (likely secrets)."""
    if not isinstance(s, str) or len(s) < 20:
        return False
    
    # Check if string looks like base64 (alphanumeric, +, /, =)
    base64_pattern = re.compile(r'^[A-Za-z0-9+/=]{20,}$')
    if not base64_pattern.match(s):
        return False
    
    # Try to decode; if it succeeds and result is mostly binary/non-printable, likely a secret
    try:
        decoded = base64.b64decode(s, validate=True)
        # If >50% non-printable, likely binary/secret
        non_printable = sum(1 for b in decoded if b < 32 or b > 126)
        if len(decoded) > 0 and non_printable / len(decoded) > 0.5:
            return True
    except Exception:
        pass
    
    # Long base64-like strings are suspicious
    if len(s) > 100:
        return True
    
    return False


def redact_secrets(data: Any, max_string_length: int = 5000) -> Any:
    """
    Recursively redact secrets from data structures.
    
    Args:
        data: Data structure (dict, list, or primitive)
        max_string_length: Truncate strings longer than this (before redaction)
    
    Returns:
        Redacted copy of data
    """
    if isinstance(data, dict):
        redacted = {}
        for key, value in data.items():
            key_lower = key.lower()
            
            # Redact if key matches sensitive pattern
            if any(sensitive in key_lower for sensitive in REDACTED_KEYS):
                redacted[key] = "***REDACTED***"
            # Redact if value is a base64-like string (likely secret)
            elif isinstance(value, str) and is_base64_like(value):
                redacted[key] = "***REDACTED_BASE64***"
            # Truncate long strings (but don't redact)
            elif isinstance(value, str) and len(value) > max_string_length:
                redacted[key] = value[:max_string_length] + "... [TRUNCATED]"
            else:
                # Recursively redact nested structures
                redacted[key] = redact_secrets(value, max_string_length)
        
        return redacted
    
    elif isinstance(data, list):
        return [redact_secrets(item, max_string_length) for item in data]
    
    elif isinstance(data, str):
        # Truncate very long strings
        if len(data) > max_string_length:
            return data[:max_string_length] + "... [TRUNCATED]"
        return data
    
    else:
        # Primitive types (int, float, bool, None) - return as-is
        return data


def redact_request_json(request_json: Any, max_size_bytes: int = 10000) -> Optional[str]:
    """
    Redact secrets from request JSON and return as JSON string.
    
    Returns None if request_json is None or empty.
    """
    if not request_json:
        return None
    
    try:
        redacted = redact_secrets(request_json)
        json_str = json.dumps(redacted, default=str)
        
        # Limit size (for audit log storage)
        if len(json_str) > max_size_bytes:
            json_str = json_str[:max_size_bytes] + "... [TRUNCATED]"
        
        return json_str
    except Exception:
        # If JSON serialization fails, return redacted summary
        return json.dumps({"error": "failed_to_serialize_request"}, default=str)
