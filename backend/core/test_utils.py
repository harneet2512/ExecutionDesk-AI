"""Test utilities."""
import os
import sys


def is_pytest() -> bool:
    """Check if running under pytest (without importing FastAPI app to prevent circular imports)."""
    return ("PYTEST_CURRENT_TEST" in os.environ) or ("pytest" in sys.modules)


def is_test_mode() -> bool:
    """Check if running in test mode (allows forcing deterministic providers in dev)."""
    return is_pytest() or os.getenv("APP_ENV", "").lower() in ("test", "ci")
