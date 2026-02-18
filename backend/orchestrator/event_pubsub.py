"""In-memory pubsub for SSE."""
from typing import Dict, Any
from collections import defaultdict
import asyncio
from backend.core.logging import get_logger

logger = get_logger(__name__)


class EventPubSub:
    """Simple in-memory pubsub."""
    
    def __init__(self):
        self._queues: Dict[str, list] = defaultdict(list)
        self._lock = asyncio.Lock()
    
    async def subscribe(self, run_id: str) -> asyncio.Queue:
        """Subscribe to events for a run."""
        queue = asyncio.Queue()
        async with self._lock:
            self._queues[run_id].append(queue)
        return queue
    
    async def publish(self, run_id: str, event: Dict[str, Any]):
        """Publish event to all subscribers."""
        async with self._lock:
            queues = self._queues[run_id].copy()

        for queue in queues:
            try:
                await queue.put(event)
            except Exception as e:
                logger.error(f"Error publishing to queue: {e}")

    async def unsubscribe(self, run_id: str, queue: asyncio.Queue):
        """Remove a specific queue subscription for a run."""
        async with self._lock:
            if run_id in self._queues:
                try:
                    self._queues[run_id].remove(queue)
                except ValueError:
                    pass
                if not self._queues[run_id]:
                    del self._queues[run_id]

    async def cleanup_run(self, run_id: str):
        """Remove all subscriptions for a completed run."""
        async with self._lock:
            self._queues.pop(run_id, None)


event_pubsub = EventPubSub()
