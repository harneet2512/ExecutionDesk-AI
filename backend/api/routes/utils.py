"""Utility functions for API routes."""
import json
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


def json_dumps(obj: Any) -> str:
    """Serialize object to JSON string, handling special types."""
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
