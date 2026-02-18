"""Core utility functions for the backend."""
import json
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


def _safe_json_loads(s, default=None):
    """Parse JSON safely, returning default on failure.
    
    Args:
        s: JSON string to parse
        default: Default value to return on failure (defaults to {})
        
    Returns:
        Parsed JSON object or default value
    """
    if not s:
        return default if default is not None else {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}


def json_dumps(obj: Any) -> str:
    """Serialize object to JSON string, handling special types.
    
    Handles:
    - datetime objects (ISO format)
    - Enum objects (value)
    - Decimal objects (float)
    - set/frozenset (list)
    - bytes (UTF-8 decode)
    - Pydantic models (.dict())
    
    Args:
        obj: Object to serialize
        
    Returns:
        JSON string
    """
    def default_handler(o):
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, Enum):
            return o.value
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (set, frozenset)):
            return list(o)
        if isinstance(o, bytes):
            return o.decode("utf-8", errors="replace")
        if hasattr(o, "dict"):
            return o.dict()
        return str(o)

    return json.dumps(obj, default=default_handler)
