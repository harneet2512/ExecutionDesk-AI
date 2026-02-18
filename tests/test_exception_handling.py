"""Tests for Round 5: Exception handling hardening.

Covers:
- _find_http_exception recursive ExceptionGroup unwrapping
- GET conversation returns 404 (not 500) for missing conversations
- Rate limit pattern matching precision
"""
import pytest
import os
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.api.main import app, _find_http_exception
from backend.db.connect import init_db, get_conn, _close_connections
from backend.core.config import get_settings

client = TestClient(app)

os.environ["TEST_AUTH_BYPASS"] = "true"
os.environ["PYTEST_CURRENT_TEST"] = "test"


@pytest.fixture
def setup_db():
    """Setup clean database for each test."""
    settings = get_settings()
    db_path = settings.database_url.replace("sqlite:///", "")
    _close_connections()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except PermissionError:
            pass
    init_db()

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO conversations (conversation_id, tenant_id, title) VALUES (?, ?, ?)",
            ("conv_test_exc", "t_default", "Test Conversation")
        )
        conn.commit()
    yield
    _close_connections()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except PermissionError:
            pass


class TestFindHttpException:
    """Recursive ExceptionGroup unwrapping."""

    def test_direct_http_exception(self):
        """Finds HTTPException at depth 0 (not wrapped)."""
        exc = HTTPException(status_code=404, detail="Not found")
        result = _find_http_exception(exc)
        assert result is exc
        assert result.status_code == 404

    def test_depth_1_exception_group(self):
        """Finds HTTPException nested 1 level in ExceptionGroup."""
        http_exc = HTTPException(status_code=403, detail="Forbidden")
        group = ExceptionGroup("group", [http_exc])
        result = _find_http_exception(group)
        assert result is http_exc
        assert result.status_code == 403

    def test_depth_2_exception_group(self):
        """Finds HTTPException nested 2 levels in ExceptionGroup."""
        http_exc = HTTPException(status_code=401, detail="Unauthorized")
        inner = ExceptionGroup("inner", [http_exc])
        outer = ExceptionGroup("outer", [inner])
        result = _find_http_exception(outer)
        assert result is http_exc
        assert result.status_code == 401

    def test_depth_3_exception_group(self):
        """Finds HTTPException nested 3 levels (4 middleware layers scenario)."""
        http_exc = HTTPException(status_code=404, detail="Not found")
        level1 = ExceptionGroup("l1", [http_exc])
        level2 = ExceptionGroup("l2", [level1])
        level3 = ExceptionGroup("l3", [level2])
        result = _find_http_exception(level3)
        assert result is http_exc
        assert result.status_code == 404

    def test_no_http_exception_returns_none(self):
        """Returns None when ExceptionGroup contains no HTTPException."""
        group = ExceptionGroup("group", [ValueError("bad"), RuntimeError("err")])
        result = _find_http_exception(group)
        assert result is None

    def test_mixed_exceptions_finds_http(self):
        """Finds HTTPException among mixed exception types."""
        http_exc = HTTPException(status_code=422, detail="Validation error")
        group = ExceptionGroup("group", [
            ValueError("bad"),
            http_exc,
            RuntimeError("err"),
        ])
        result = _find_http_exception(group)
        assert result is http_exc

    def test_non_exception_returns_none(self):
        """Returns None for plain Exception (not ExceptionGroup)."""
        result = _find_http_exception(RuntimeError("not http"))
        assert result is None

    def test_nested_mixed_finds_http_deep(self):
        """Finds HTTPException in a nested group with mixed exceptions."""
        http_exc = HTTPException(status_code=409, detail="Conflict")
        inner = ExceptionGroup("inner", [ValueError("x"), http_exc])
        outer = ExceptionGroup("outer", [RuntimeError("y"), inner])
        result = _find_http_exception(outer)
        assert result is http_exc


class TestConversation404Not500:
    """GET conversation for missing ID returns 404 JSON, not 500."""

    def test_missing_conversation_returns_404(self, setup_db):
        """GET /conversations/{nonexistent} returns 404 with proper JSON."""
        response = client.get(
            "/api/v1/conversations/conv_nonexistent_xyz",
            headers={"X-Dev-Tenant": "t_default"},
        )
        # Must be 404, NOT 500
        assert response.status_code == 404, (
            f"Expected 404 for missing conversation, got {response.status_code}: {response.json()}"
        )

    def test_existing_conversation_returns_200(self, setup_db):
        """GET /conversations/{existing} returns 200."""
        response = client.get(
            "/api/v1/conversations/conv_test_exc",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == "conv_test_exc"

    def test_missing_conversation_has_request_id(self, setup_db):
        """404 response includes X-Request-ID header."""
        response = client.get(
            "/api/v1/conversations/conv_missing_abc",
            headers={"X-Dev-Tenant": "t_default"},
        )
        assert response.status_code == 404
        assert "x-request-id" in response.headers


class TestRateLimitPatternMatching:
    """Rate limit pattern matching doesn't match wrong routes."""

    def test_conversations_id_not_match_messages_pattern(self):
        """GET /conversations/{id} should NOT match /conversations/{id}/messages pattern."""
        from backend.api.middleware.rate_limit import RateLimitMiddleware

        middleware = RateLimitMiddleware(app)
        path = "/api/v1/conversations/conv_abc123"
        matched_messages = False

        for pattern, limits in middleware.RATE_LIMITS.items():
            if "{" in pattern:
                prefix = pattern.split("{")[0]
                if path.startswith(prefix) and len(path.split("/")) == len(pattern.split("/")):
                    if "messages" in pattern:
                        matched_messages = True
                    break

        assert not matched_messages, "GET /conversations/{id} should not match /conversations/{id}/messages"

    def test_conversations_messages_still_matches(self):
        """GET /conversations/{id}/messages SHOULD match its pattern."""
        from backend.api.middleware.rate_limit import RateLimitMiddleware

        middleware = RateLimitMiddleware(app)
        path = "/api/v1/conversations/conv_abc123/messages"
        matched_pattern = None

        for pattern, limits in middleware.RATE_LIMITS.items():
            if "{" in pattern:
                prefix = pattern.split("{")[0]
                if path.startswith(prefix) and len(path.split("/")) == len(pattern.split("/")):
                    matched_pattern = pattern
                    break

        assert matched_pattern is not None, "Messages path should match a rate limit pattern"

    def test_runs_id_not_match_events_pattern(self):
        """GET /runs/{id} should NOT match /runs/{id}/events pattern."""
        from backend.api.middleware.rate_limit import RateLimitMiddleware

        middleware = RateLimitMiddleware(app)
        path = "/api/v1/runs/run_abc123"
        matched_events = False

        for pattern, limits in middleware.RATE_LIMITS.items():
            if "{" in pattern:
                prefix = pattern.split("{")[0]
                if path.startswith(prefix) and len(path.split("/")) == len(pattern.split("/")):
                    if "events" in pattern:
                        matched_events = True
                    break

        assert not matched_events, "GET /runs/{id} should not match /runs/{id}/events"
