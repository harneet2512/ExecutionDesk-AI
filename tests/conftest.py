"""Shared pytest fixtures for the test suite.

Provides:
- Database setup/teardown with proper isolation
- VCR-style HTTP mocking for Coinbase API
- Golden run comparison utilities
- Test data generators
"""
import pytest
import os
import sys
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from typing import Dict, List, Any, Optional

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set test mode environment variables early (BEFORE backend imports)
os.environ["TEST_AUTH_BYPASS"] = "true"
# Ensure LIVE trading is disabled in tests (the .env may override defaults)
os.environ["TRADING_DISABLE_LIVE"] = "true"
os.environ["ENABLE_LIVE_TRADING"] = "false"


@pytest.fixture(autouse=True, scope="session")
def _reset_settings_for_tests():
    """Reset settings singleton so test env vars take effect."""
    try:
        from backend.core.config import reset_settings
        reset_settings()
    except ImportError:
        pass
    yield
    try:
        from backend.core.config import reset_settings
        reset_settings()
    except ImportError:
        pass


# === DATABASE FIXTURES ===

@pytest.fixture(scope="function")
def test_db():
    """Create an isolated test database for each test function.
    
    Creates a fresh SQLite database, runs migrations, and cleans up after.
    """
    # Create temp directory for test DB
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_enterprise.db")
    
    # Set environment variable for test DB
    old_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["TEST_DATABASE_URL"] = f"sqlite:///{db_path}"
    
    # Reset settings singleton to pick up new DATABASE_URL
    try:
        from backend.core.config import reset_settings
        reset_settings()
    except ImportError:
        pass
    
    # Initialize the database
    try:
        from backend.db.connect import init_db, get_conn, _close_connections, reset_canonical_db_path
        _close_connections()  # Close any existing connections
        reset_canonical_db_path()  # Allow new DB path for this test
        init_db()
        
        yield db_path
        
    finally:
        # Cleanup
        _close_connections()
        try:
            from backend.db.connect import reset_canonical_db_path as _reset_dbp
            _reset_dbp()
        except ImportError:
            pass
        
        # Reset settings again to restore original
        try:
            from backend.core.config import reset_settings
            reset_settings()
        except ImportError:
            pass
        
        if old_db_url:
            os.environ["DATABASE_URL"] = old_db_url
        else:
            os.environ.pop("DATABASE_URL", None)
        os.environ.pop("TEST_DATABASE_URL", None)
        
        # Remove temp directory
        try:
            shutil.rmtree(temp_dir)
        except:
            pass


@pytest.fixture(scope="function")
def setup_db(test_db):
    """Alias for test_db fixture for backward compatibility."""
    return test_db


# === VCR-STYLE HTTP MOCKING ===

class MockResponse:
    """Mock HTTP response for VCR-style testing."""
    
    def __init__(self, json_data: Any, status_code: int = 200, headers: Dict = None):
        self._json_data = json_data
        self.status_code = status_code
        self.headers = headers or {}
        self.text = json.dumps(json_data) if json_data else ""
    
    def json(self):
        return self._json_data
    
    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=MagicMock(),
                response=self
            )


def load_vcr_cassette(cassette_name: str) -> Dict[str, Any]:
    """Load a VCR cassette from the fixtures directory.
    
    Args:
        cassette_name: Name of the cassette file (without extension)
        
    Returns:
        Dict mapping URL patterns to response data
    """
    cassette_path = Path(__file__).parent / "fixtures" / "vcr_cassettes" / f"{cassette_name}.json"
    if cassette_path.exists():
        with open(cassette_path) as f:
            return json.load(f)
    return {}


@pytest.fixture
def coinbase_vcr_cassette():
    """Load VCR cassette for Coinbase API calls.
    
    Patches httpx.Client.get to return recorded responses.
    """
    cassette = load_vcr_cassette("coinbase_48h")
    
    def mock_get(url, **kwargs):
        # Try exact match first
        if url in cassette:
            return MockResponse(cassette[url])
        
        # Try pattern matching for product-specific URLs
        for pattern, response in cassette.items():
            if pattern in url:
                return MockResponse(response)
        
        # Return empty response for unknown URLs
        return MockResponse([], 200)
    
    with patch("httpx.Client") as mock_client:
        instance = MagicMock()
        instance.get = mock_get
        instance.__enter__ = lambda s: instance
        instance.__exit__ = lambda s, *args: None
        mock_client.return_value = instance
        yield mock_client


@pytest.fixture
def mock_coinbase_products():
    """Mock Coinbase products list for testing."""
    products = [
        {
            "id": "BTC-USD",
            "base_currency": "BTC",
            "quote_currency": "USD",
            "status": "online"
        },
        {
            "id": "ETH-USD",
            "base_currency": "ETH",
            "quote_currency": "USD",
            "status": "online"
        },
        {
            "id": "SOL-USD",
            "base_currency": "SOL",
            "quote_currency": "USD",
            "status": "online"
        }
    ]
    return products


@pytest.fixture
def mock_candles_btc():
    """Mock BTC candles for 48h lookback."""
    from datetime import datetime, timedelta
    
    end_time = datetime.utcnow()
    candles = []
    
    # Generate 60 hourly candles
    for i in range(60):
        ts = end_time - timedelta(hours=60-i)
        price = 45000 + (i * 50)  # Steadily increasing
        candles.append({
            "start_time": ts.isoformat() + "Z",
            "end_time": (ts + timedelta(hours=1)).isoformat() + "Z",
            "open": price,
            "high": price + 100,
            "low": price - 50,
            "close": price + 50,
            "volume": 1000000
        })
    
    return candles


# === GOLDEN RUN UTILITIES ===

def load_golden_run(golden_name: str) -> Optional[Dict]:
    """Load a golden run fixture.
    
    Args:
        golden_name: Name of the golden run file (without extension)
        
    Returns:
        Golden run data or None if not found
    """
    golden_path = Path(__file__).parent / "fixtures" / "golden_runs" / f"{golden_name}.json"
    if golden_path.exists():
        with open(golden_path) as f:
            return json.load(f)
    return None


def canonicalize_artifacts(artifacts: Dict) -> str:
    """Canonicalize artifacts for deterministic comparison.
    
    Sorts all keys and removes non-deterministic fields.
    
    Args:
        artifacts: Artifacts dict to canonicalize
        
    Returns:
        Canonical JSON string
    """
    # Remove non-deterministic fields
    non_deterministic = ["created_at", "ts", "timestamp", "computed_at", "fetched_at", "failed_at"]
    
    def clean(obj):
        if isinstance(obj, dict):
            return {
                k: clean(v) 
                for k, v in sorted(obj.items()) 
                if k not in non_deterministic
            }
        elif isinstance(obj, list):
            return [clean(item) for item in obj]
        return obj
    
    cleaned = clean(artifacts)
    return json.dumps(cleaned, sort_keys=True, indent=2)


def assert_artifacts_match(run_id: str, expected_artifacts: Dict):
    """Assert that run artifacts match expected golden artifacts.
    
    Args:
        run_id: Run ID to check
        expected_artifacts: Expected artifact data
    """
    from backend.db.connect import get_conn
    
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT artifact_type, artifact_json FROM run_artifacts WHERE run_id = ?",
            (run_id,)
        )
        actual_artifacts = {
            row["artifact_type"]: json.loads(row["artifact_json"])
            for row in cursor.fetchall()
        }
    
    actual_canonical = canonicalize_artifacts(actual_artifacts)
    expected_canonical = canonicalize_artifacts(expected_artifacts)
    
    assert actual_canonical == expected_canonical, (
        f"Artifacts mismatch:\n"
        f"Expected:\n{expected_canonical}\n"
        f"Actual:\n{actual_canonical}"
    )


# === TEST DATA GENERATORS ===

def make_candles(
    symbol: str = "BTC-USD",
    count: int = 48,
    start_price: float = 45000,
    price_change_pct: float = 0.05
) -> List[Dict]:
    """Generate synthetic candles for testing.
    
    Args:
        symbol: Product symbol
        count: Number of candles
        start_price: Starting price
        price_change_pct: Total price change as decimal
        
    Returns:
        List of candle dicts
    """
    from datetime import datetime, timedelta
    
    end_time = datetime.utcnow()
    candles = []
    
    price_change_per_candle = (start_price * price_change_pct) / count
    
    for i in range(count):
        ts = end_time - timedelta(hours=count-i)
        price = start_price + (i * price_change_per_candle)
        candles.append({
            "start_time": ts.isoformat() + "Z",
            "end_time": (ts + timedelta(hours=1)).isoformat() + "Z",
            "open": price,
            "high": price * 1.005,
            "low": price * 0.995,
            "close": price + price_change_per_candle,
            "volume": 1000000
        })
    
    return candles


def make_run(
    tenant_id: str = "t_default",
    execution_mode: str = "PAPER",
    command_text: str = None,
    intent: Dict = None
) -> str:
    """Create a test run in the database.
    
    Args:
        tenant_id: Tenant ID
        execution_mode: PAPER, LIVE, or REPLAY
        command_text: Optional command text
        intent: Optional intent dict
        
    Returns:
        Created run ID
    """
    from backend.db.connect import get_conn
    from backend.core.ids import new_id
    from backend.core.time import now_iso
    
    run_id = new_id("run_")
    
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO runs (run_id, tenant_id, status, execution_mode, command_text, intent_json, created_at)
            VALUES (?, ?, 'CREATED', ?, ?, ?, ?)
            """,
            (run_id, tenant_id, execution_mode, command_text, json.dumps(intent) if intent else None, now_iso())
        )
        conn.commit()
    
    return run_id


# === AUTH BYPASS FOR TESTS ===

@pytest.fixture
def bypass_auth():
    """Bypass authentication for tests."""
    os.environ["TEST_AUTH_BYPASS"] = "true"
    yield
    os.environ.pop("TEST_AUTH_BYPASS", None)


# === ASYNC TEST SUPPORT ===

@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# === CLEANUP ===

@pytest.fixture(autouse=True)
def reset_api_stats():
    """Reset API call stats before each test."""
    try:
        from backend.services.coinbase_market_data import reset_api_stats
        reset_api_stats()
    except:
        pass
    yield


@pytest.fixture(autouse=True)
def reset_products_cache():
    """Reset products cache before each test."""
    try:
        from backend.services.coinbase_market_data import _products_cache
        _products_cache.clear()
    except:
        pass
    yield
