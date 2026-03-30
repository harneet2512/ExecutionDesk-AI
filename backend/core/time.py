"""Time utilities."""
import sys
from datetime import datetime, timezone



def now_iso() -> str:
    """Get current time as ISO 8601 string with Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

# Alias for legacy compatibility
time_utils = sys.modules[__name__]

