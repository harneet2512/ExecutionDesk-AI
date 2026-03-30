"""Token bucket rate limiter for API calls.

Used to enforce Polygon.io free tier limits (5 calls/min).
Thread-safe implementation.
"""
import time
import threading
from backend.core.logging import get_logger

logger = get_logger(__name__)


class TokenBucketRateLimiter:
    """Token bucket rate limiter.

    Tokens refill at a constant rate. Each API call consumes one token.
    If no tokens available, caller blocks until a token is available or timeout.
    """

    def __init__(self, tokens_per_minute: int = 5):
        """Initialize rate limiter.

        Args:
            tokens_per_minute: Maximum tokens (API calls) per minute.
        """
        self.tokens_per_minute = tokens_per_minute
        self.tokens = float(tokens_per_minute)  # Start full
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._total_waits = 0
        self._total_acquired = 0

    def acquire(self, timeout_seconds: float = 60.0) -> bool:
        """Block until a token is available or timeout.

        Args:
            timeout_seconds: Maximum time to wait for a token.

        Returns:
            True if token acquired, False if timeout.
        """
        deadline = time.monotonic() + timeout_seconds
        wait_logged = False

        while time.monotonic() < deadline:
            with self._lock:
                self._refill()
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    self._total_acquired += 1
                    return True

            # No token available, wait
            if not wait_logged:
                logger.debug(
                    "Rate limiter: waiting for token (current=%.2f, limit=%s)",
                    self.tokens, self.tokens_per_minute
                )
                self._total_waits += 1
                wait_logged = True

            # Sleep briefly before retry
            time.sleep(0.5)

        logger.warning(
            "Rate limiter: timeout after %ss (tokens=%.2f)",
            timeout_seconds, self.tokens
        )
        return False

    def try_acquire(self) -> bool:
        """Non-blocking attempt to acquire a token.

        Returns:
            True if token acquired, False otherwise.
        """
        with self._lock:
            self._refill()
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                self._total_acquired += 1
                return True
        return False

    def _refill(self):
        """Refill tokens based on elapsed time. Must be called with lock held."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        # Tokens refill at rate of tokens_per_minute / 60 per second
        new_tokens = elapsed * (self.tokens_per_minute / 60.0)
        self.tokens = min(float(self.tokens_per_minute), self.tokens + new_tokens)
        self.last_refill = now

    @property
    def available_tokens(self) -> float:
        """Current number of available tokens (approximate, may change)."""
        with self._lock:
            self._refill()
            return self.tokens

    def get_stats(self) -> dict:
        """Get rate limiter statistics."""
        with self._lock:
            self._refill()
            return {
                "tokens_per_minute": self.tokens_per_minute,
                "current_tokens": round(self.tokens, 2),
                "total_acquired": self._total_acquired,
                "total_waits": self._total_waits
            }

    def reset(self):
        """Reset rate limiter to full capacity (for testing)."""
        with self._lock:
            self.tokens = float(self.tokens_per_minute)
            self.last_refill = time.monotonic()
            self._total_waits = 0
            self._total_acquired = 0


# Global rate limiter instance for Polygon API
_polygon_rate_limiter: TokenBucketRateLimiter = None


def get_polygon_rate_limiter() -> TokenBucketRateLimiter:
    """Get or create the global Polygon rate limiter."""
    global _polygon_rate_limiter
    if _polygon_rate_limiter is None:
        from backend.core.config import get_settings
        settings = get_settings()
        _polygon_rate_limiter = TokenBucketRateLimiter(
            tokens_per_minute=settings.stock_rate_limit_per_minute
        )
    return _polygon_rate_limiter


def reset_polygon_rate_limiter():
    """Reset the global Polygon rate limiter (for testing)."""
    global _polygon_rate_limiter
    _polygon_rate_limiter = None
