"""SSE connection tracking and limits."""
from typing import Dict
from collections import defaultdict
import time
from backend.core.logging import get_logger

logger = get_logger(__name__)

# Track SSE connections per user
# Structure: {user_key: {connection_id: (run_id, timestamp)}}
_sse_connections: Dict[str, Dict[str, tuple]] = defaultdict(dict)

# Max concurrent SSE connections per user
MAX_SSE_CONNECTIONS_PER_USER = 3

# Idle timeout (seconds) - prune stale connections
SSE_IDLE_TIMEOUT = 300  # 5 minutes


def track_sse_connection(user_key: str, connection_id: str, run_id: str) -> bool:
    """
    Track SSE connection. Prunes stale entries before checking limit.

    Returns:
        True if connection allowed, False if limit exceeded
    """
    connections = _sse_connections[user_key]

    # Prune connections older than SSE_IDLE_TIMEOUT
    now = time.time()
    stale = [cid for cid, (_, ts) in connections.items() if now - ts > SSE_IDLE_TIMEOUT]
    for cid in stale:
        del connections[cid]

    # Check limit after cleanup
    if len(connections) >= MAX_SSE_CONNECTIONS_PER_USER:
        logger.warning(f"SSE connection limit exceeded for user {user_key}: {len(connections)}/{MAX_SSE_CONNECTIONS_PER_USER}")
        return False

    connections[connection_id] = (run_id, now)
    return True


def untrack_sse_connection(user_key: str, connection_id: str):
    """Remove SSE connection tracking."""
    if user_key in _sse_connections and connection_id in _sse_connections[user_key]:
        del _sse_connections[user_key][connection_id]
        # Clean up empty user entries
        if not _sse_connections[user_key]:
            del _sse_connections[user_key]


def get_sse_connection_count(user_key: str) -> int:
    """Get number of active SSE connections for a user."""
    return len(_sse_connections.get(user_key, {}))
