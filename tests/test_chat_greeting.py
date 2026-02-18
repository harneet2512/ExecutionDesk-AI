"""Test chat command endpoint for greeting and error handling."""
import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

os.environ.setdefault("TEST_AUTH_BYPASS", "true")

from backend.api.main import app
from backend.db.connect import init_db

client = TestClient(app, headers={"X-Dev-Tenant": "t_default"})
# Client with raise_server_exceptions=False for testing error responses
error_client = TestClient(
    app,
    headers={"X-Dev-Tenant": "t_default"},
    raise_server_exceptions=False
)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    """Ensure database is initialized."""
    init_db()
    yield


def test_greeting_returns_200():
    """POST 'Hi' returns 200 with valid greeting JSON."""
    resp = client.post("/api/v1/chat/command", json={"text": "Hi"})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    data = resp.json()
    assert "content" in data, f"Missing 'content' key in response: {data}"
    assert data["intent"] == "GREETING"
    assert data["run_id"] is None
    assert data["status"] == "COMPLETED"
    assert len(data["content"]) > 0


def test_greeting_variants():
    """Various greeting texts all return 200 with GREETING intent."""
    for text in ["hello", "hey", "yo", "howdy"]:
        resp = client.post("/api/v1/chat/command", json={"text": text})
        assert resp.status_code == 200, f"'{text}' returned {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["intent"] == "GREETING", f"'{text}' got intent {data.get('intent')}"


def test_conversations_list_returns_200():
    """GET /conversations returns 200 with a list (even if empty)."""
    resp = client.get("/api/v1/conversations")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert isinstance(data, list), f"Expected list, got {type(data).__name__}: {data}"


def test_conversations_create_and_list():
    """POST /conversations creates, then GET /conversations includes it."""
    # Create a conversation
    resp = client.post("/api/v1/conversations", json={"title": "Test Conv"})
    assert resp.status_code == 200, f"Create failed: {resp.status_code}: {resp.text}"
    conv = resp.json()
    assert "conversation_id" in conv

    # List should include the new conversation
    resp = client.get("/api/v1/conversations")
    assert resp.status_code == 200
    convs = resp.json()
    ids = [c["conversation_id"] for c in convs]
    assert conv["conversation_id"] in ids


def test_internal_error_returns_json_shape():
    """Forced exception returns structured JSON error with code, message, request_id."""
    with patch(
        "backend.agents.intent_router.classify_intent",
        side_effect=RuntimeError("Test forced error")
    ):
        resp = error_client.post("/api/v1/chat/command", json={"text": "Hi"})

    assert resp.status_code == 500
    data = resp.json()

    # Must have error object with code, message, request_id
    assert "error" in data, f"Missing 'error' key: {data}"
    err = data["error"]
    assert err["code"] == "INTERNAL_ERROR"
    assert "request_id" in err

    # Must have content for frontend rendering
    assert "content" in data
    assert data["status"] == "FAILED"


def test_trade_receipt_creation_no_crash():
    """_create_trade_receipt does not crash when orders table has correct columns."""
    from backend.orchestrator.runner import _create_trade_receipt
    from backend.db.connect import get_conn
    from backend.core.time import now_iso

    # Create a run
    run_id = f"run_test_{os.urandom(4).hex()}"
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO runs (run_id, tenant_id, status, execution_mode, created_at,
                              parsed_intent_json)
            VALUES (?, 't_default', 'COMPLETED', 'PAPER', ?, ?)
        """, (run_id, now_iso(), '{"side":"SELL","budget_usd":1.50,"universe":["BTC-USD"]}'))

        # Create an order with the actual schema columns
        cursor.execute("""
            INSERT INTO orders (order_id, run_id, tenant_id, provider, symbol, side,
                                order_type, qty, notional_usd, status, created_at,
                                filled_qty, avg_fill_price, total_fees)
            VALUES (?, ?, 't_default', 'PAPER', 'BTC-USD', 'SELL',
                    'MARKET', 0.00001, 1.50, 'FILLED', ?, 0.00001, 100000.0, 0.01)
        """, (f"ord_{os.urandom(4).hex()}", run_id, now_iso()))
        conn.commit()

    # This must not crash (previously it queried non-existent columns)
    _create_trade_receipt(run_id, "COMPLETED")

    # Verify receipt artifact was created
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT artifact_json FROM run_artifacts
            WHERE run_id = ? AND artifact_type = 'trade_receipt'
        """, (run_id,))
        row = cursor.fetchone()

    assert row is not None, "trade_receipt artifact should exist"
    import json
    receipt = json.loads(row["artifact_json"])
    assert receipt["status"] == "EXECUTED"
    assert receipt["mode"] == "PAPER"
    assert receipt["requested_notional_usd"] == 1.50
    assert receipt["executed_notional_usd"] == 1.50
    assert receipt["fees_usd"] == 0.01
    assert receipt["side"] == "SELL"


def test_global_handler_returns_json_on_conversations_error():
    """Exception in conversations endpoint returns JSON 500 via global handler.

    This tests that the global exception handler in main.py does NOT crash
    from the RequestIDMiddleware logging conflict (extra={'request_id': ...}).
    """
    with patch(
        "backend.api.routes.conversations._list_conversations_impl",
        side_effect=RuntimeError("DB connection lost")
    ):
        resp = error_client.get("/api/v1/conversations")

    assert resp.status_code == 500, f"Expected 500, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "error" in data, f"Response must be JSON with 'error' key, got: {resp.text[:200]}"
    assert data["error"]["code"] == "INTERNAL_ERROR"
    assert "request_id" in data["error"]


def test_greeting_includes_request_id():
    """Every successful response includes request_id matching X-Request-ID header."""
    resp = client.post("/api/v1/chat/command", json={"text": "Hi"})
    assert resp.status_code == 200
    data = resp.json()

    # Body must include request_id
    assert "request_id" in data, f"Missing request_id in response body: {list(data.keys())}"

    # X-Request-ID header must be present
    header_rid = resp.headers.get("X-Request-ID")
    assert header_rid is not None, "Missing X-Request-ID header"

    # Body request_id must match header (unified)
    assert data["request_id"] == header_rid, (
        f"Body request_id={data['request_id']} != header={header_rid}"
    )


def test_error_response_includes_content_and_request_id():
    """Global handler 500 includes content, status, and request_id for frontend display."""
    with patch(
        "backend.agents.intent_router.classify_intent",
        side_effect=RuntimeError("Test forced error")
    ):
        resp = error_client.post("/api/v1/chat/command", json={"text": "Hi"})

    assert resp.status_code == 500
    data = resp.json()

    # Must have top-level content and status for frontend rendering
    assert "content" in data, f"Missing 'content' in error response: {data}"
    assert "status" in data, f"Missing 'status' in error response: {data}"
    assert "request_id" in data, f"Missing top-level 'request_id' in error response: {data}"

    # X-Request-ID header must be present
    header_rid = resp.headers.get("X-Request-ID")
    assert header_rid is not None, "Missing X-Request-ID header on 500 response"


def test_portfolio_response_never_500_on_serialization():
    """Portfolio analysis should return 200 even if portfolio_brief contains tricky types."""
    import decimal
    from datetime import datetime

    # Mock portfolio_execute to return a brief with non-standard types
    tricky_brief = {
        "total_value_usd": decimal.Decimal("123.45"),
        "cash_usd": None,
        "mode": "PAPER",
        "holdings": [],
        "risk": {"risk_level": "LOW"},
        "timestamp": datetime.utcnow()
    }

    mock_result = {
        "portfolio_brief": tricky_brief,
        "success": True,
        "error": None
    }

    with patch(
        "backend.orchestrator.nodes.portfolio_node.execute",
        return_value=mock_result
    ):
        resp = error_client.post(
            "/api/v1/chat/command",
            json={"text": "Analyze my portfolio"}
        )

    # Must NOT be 500 - the two-phase response should handle serialization
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
    data = resp.json()
    assert data["status"] == "COMPLETED"
    assert "request_id" in data


def test_rate_limit_returns_429_not_500():
    """Rate limit exceeded returns 429 JSON (not 500) with retry_after_seconds."""
    from backend.api.middleware.rate_limit import _rate_limit_store
    import time

    # Seed the in-memory store to simulate exhausted limit for a specific key
    # The key format is tenant_id:user_id:path
    key = "t_default:anonymous:/api/v1/chat/command"
    _rate_limit_store[key] = (999, time.time())  # 999 requests, just started

    try:
        resp = error_client.post("/api/v1/chat/command", json={"text": "Hi"})
    finally:
        # Clean up so other tests are not affected
        _rate_limit_store.pop(key, None)

    assert resp.status_code == 429, f"Expected 429, got {resp.status_code}: {resp.text[:300]}"
    data = resp.json()

    # Must be structured JSON, not HTML or generic 500
    assert "error" in data, f"Missing 'error' key in 429 response: {data}"
    assert data["error"]["code"] == "RATE_LIMITED"
    assert "retry_after_seconds" in data, f"Missing retry_after_seconds: {data}"
    assert data["retry_after_seconds"] > 0
    assert "request_id" in data, f"Missing request_id in 429 response: {data}"

    # Retry-After header must be present
    retry_hdr = resp.headers.get("Retry-After")
    assert retry_hdr is not None, "Missing Retry-After header"

    # X-Request-ID header must be present
    rid_hdr = resp.headers.get("X-Request-ID")
    assert rid_hdr is not None, "Missing X-Request-ID header on 429 response"


def test_orders_repo_uses_correct_pk():
    """orders_repo queries use order_id, not id (fixes 'no such column: id')."""
    from backend.db.repo.orders_repo import OrdersRepo
    from backend.db.connect import get_conn

    repo = OrdersRepo()
    oid = f"ord_test_{os.urandom(4).hex()}"
    run_id = f"run_test_{os.urandom(4).hex()}"
    tenant = "t_default"

    # Ensure the run exists (FK constraint)
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO runs (run_id, tenant_id, status, execution_mode, created_at) VALUES (?, ?, 'CREATED', 'PAPER', datetime('now'))",
            (run_id, tenant)
        )
        conn.commit()

    # Create order via repo (should use order_id column, not id)
    repo.create_order({
        "order_id": oid,
        "run_id": run_id,
        "tenant_id": tenant,
        "provider": "PAPER",
        "symbol": "BTC-USD",
        "side": "BUY",
        "order_type": "MARKET",
        "notional_usd": 10.0,
        "status": "PENDING",
    })

    # Get order back (should use WHERE order_id, not id)
    result = repo.get_order(oid, tenant)
    assert result is not None, "get_order should find the order"
    assert result["order_id"] == oid
    assert result["symbol"] == "BTC-USD"

    # Update order status (should use WHERE order_id, not id)
    repo.update_order_status(oid, "FILLED")

    # Verify update
    updated = repo.get_order(oid, tenant)
    assert updated["status"] == "FILLED"


def test_approvals_repo_uses_correct_pk():
    """approvals_repo queries use approval_id, not id (fixes 'no such column: id')."""
    from backend.db.repo.approvals_repo import ApprovalsRepo
    from backend.db.connect import get_conn

    repo = ApprovalsRepo()
    aid = f"appr_test_{os.urandom(4).hex()}"
    run_id = f"run_test_{os.urandom(4).hex()}"
    tenant = "t_default"

    # Ensure the run exists
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO runs (run_id, tenant_id, status, execution_mode, created_at) VALUES (?, ?, 'CREATED', 'PAPER', datetime('now'))",
            (run_id, tenant)
        )
        conn.commit()

    # Create approval via repo
    repo.create_approval({
        "approval_id": aid,
        "run_id": run_id,
        "tenant_id": tenant,
        "status": "PENDING",
    })

    # Get approval back
    result = repo.get_approval(aid, tenant)
    assert result is not None, "get_approval should find the approval"
    assert result["approval_id"] == aid

    # Update approval (should use WHERE approval_id, not id)
    repo.update_approval(aid, "APPROVED", "test_admin", "Looks good")

    # Verify update
    updated = repo.get_approval(aid, tenant)
    assert updated["status"] == "APPROVED"
    assert updated["decided_by"] == "test_admin"


def test_http_exception_handler_preserves_status():
    """HTTPException raised in a route returns proper status (not 500)."""
    from fastapi import HTTPException

    # Patch classify_intent to raise a 403 HTTPException
    with patch(
        "backend.agents.intent_router.classify_intent",
        side_effect=HTTPException(status_code=403, detail="Forbidden test")
    ):
        resp = error_client.post("/api/v1/chat/command", json={"text": "Hi"})

    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text[:300]}"
    data = resp.json()
    assert "error" in data, f"Missing 'error' in response: {data}"
    assert data["error"]["code"] == "HTTP_403"
    assert "request_id" in data


def test_exception_group_unwraps_to_correct_status():
    """ExceptionGroup wrapping an HTTPException returns original status, not 500.

    This is the systemic regression test for the BaseHTTPMiddleware wrapping bug:
    when call_next() propagates an HTTPException, Starlette wraps it in
    ExceptionGroup, which bypasses FastAPI's HTTPException handler and falls
    to the generic Exception handler (500). Our ExceptionGroup handler must
    unwrap it and return the correct status code.
    """
    from backend.api.main import app, exception_group_handler
    from fastapi import HTTPException as HTTPE
    from starlette.testclient import TestClient as STC

    # Simulate an ExceptionGroup wrapping a 429
    eg = ExceptionGroup("wrapped", [HTTPE(status_code=429, detail="Too many")])

    # Verify the handler extracts the 429
    import asyncio
    from starlette.requests import Request as StarletteRequest
    from starlette.datastructures import Headers

    # Build a minimal ASGI scope for the handler
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "query_string": b"",
        "headers": [],
    }
    fake_request = StarletteRequest(scope)

    response = asyncio.get_event_loop().run_until_complete(
        exception_group_handler(fake_request, eg)
    )
    assert response.status_code == 429, (
        f"ExceptionGroup wrapping 429 should return 429, got {response.status_code}"
    )


def test_status_endpoint_includes_stale_order_ids():
    """Status endpoint response includes stale_order_ids field."""
    from backend.db.connect import get_conn
    from backend.core.time import now_iso

    run_id = f"run_stale_{os.urandom(4).hex()}"
    tenant = "t_default"

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO runs (run_id, tenant_id, status, execution_mode,
                                 created_at, started_at)
               VALUES (?, ?, 'RUNNING', 'PAPER', datetime('now'), datetime('now'))""",
            (run_id, tenant),
        )
        # Insert a dag_node so total_steps > 0
        cursor.execute(
            """INSERT INTO dag_nodes (node_id, run_id, name, node_type, status, started_at)
               VALUES (?, ?, 'test_node', 'STEP', 'COMPLETED', datetime('now'))""",
            (f"node_{os.urandom(4).hex()}", run_id),
        )
        conn.commit()

    resp = client.get(f"/api/v1/runs/status/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "stale_order_ids" in data, (
        f"Status response must include stale_order_ids field: {list(data.keys())}"
    )
    assert isinstance(data["stale_order_ids"], list)


def test_reconcile_endpoint_returns_404_for_missing_order():
    """POST /orders/{order_id}/reconcile returns 404 for non-existent order."""
    resp = error_client.post("/api/v1/orders/fake_order_id/reconcile")
    assert resp.status_code == 404, (
        f"Expected 404 for missing order, got {resp.status_code}: {resp.text[:200]}"
    )


# ====================================================================
# Fix 28: Messages endpoint hardening tests
# ====================================================================

def test_list_messages_never_500_on_bad_metadata_json():
    """Seed DB with a message containing invalid JSON in metadata_json.

    The list_messages endpoint must still return 200 with metadata_json=None
    for that row, not crash with a 500.
    """
    from backend.db.connect import get_conn
    from backend.core.ids import new_id
    from backend.core.time import now_iso

    conv_id = new_id("conv_")
    msg_id = new_id("msg_")
    tenant = "t_default"
    now = now_iso()

    with get_conn() as conn:
        c = conn.cursor()
        # Create conversation
        c.execute(
            "INSERT INTO conversations (conversation_id, tenant_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
            (conv_id, tenant, "test", now, now),
        )
        # Insert message with corrupt metadata_json
        c.execute(
            "INSERT INTO messages (message_id, conversation_id, tenant_id, role, content, metadata_json, created_at) VALUES (?,?,?,?,?,?,?)",
            (msg_id, conv_id, tenant, "user", "hello", "{{{NOT VALID JSON", now),
        )
        conn.commit()

    resp = error_client.get(f"/api/v1/conversations/{conv_id}/messages")
    assert resp.status_code == 200, (
        f"Expected 200 for bad metadata, got {resp.status_code}: {resp.text[:300]}"
    )
    msgs = resp.json()
    assert len(msgs) == 1
    # metadata_json should be None (safe fallback), not crash
    assert msgs[0]["metadata_json"] is None


def test_schema_out_of_date_returns_503_not_500():
    """When a query hits a missing column, the endpoint must return 503
    with error code DB_SCHEMA_OUT_OF_DATE, not a generic 500."""
    from unittest.mock import patch
    import sqlite3

    with patch(
        "backend.api.routes.conversations._list_messages_impl",
        side_effect=sqlite3.OperationalError("no such column: foobar"),
    ):
        resp = error_client.get("/api/v1/conversations/conv_fake/messages")

    assert resp.status_code == 503, (
        f"Expected 503 for schema error, got {resp.status_code}: {resp.text[:300]}"
    )
    data = resp.json()
    assert data["error"]["code"] == "DB_SCHEMA_OUT_OF_DATE", (
        f"Expected DB_SCHEMA_OUT_OF_DATE, got: {data}"
    )
    assert data.get("request_id") or data["error"].get("request_id"), (
        f"Missing request_id in 503 response: {data}"
    )


def test_rate_limit_stays_429():
    """Rate limiter must return 429, never 500, even under BaseHTTPMiddleware."""
    # The messages endpoint is rate-limited to 60/min.
    # We'll hammer it until we get a 429 (or exhaust attempts).
    from backend.db.connect import get_conn
    from backend.core.ids import new_id
    from backend.core.time import now_iso

    conv_id = new_id("conv_")
    tenant = "t_default"
    now = now_iso()

    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO conversations (conversation_id, tenant_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
            (conv_id, tenant, "rate test", now, now),
        )
        conn.commit()

    got_429 = False
    got_500 = False
    # The rate limiter is per-path, per-user. We need to send enough to exceed.
    # messages endpoint allows 60/min. We use a dedicated client to avoid
    # conflicting with other tests' rate state.
    rl_client = TestClient(app, headers={"X-Dev-Tenant": "t_rate_test"}, raise_server_exceptions=False)
    for i in range(70):
        r = rl_client.get(f"/api/v1/conversations/{conv_id}/messages")
        if r.status_code == 429:
            got_429 = True
            # Verify JSON envelope
            data = r.json()
            assert "error" in data, f"429 missing error envelope: {data}"
            break
        if r.status_code == 500:
            got_500 = True
            break

    assert not got_500, "Rate limit produced 500 instead of 429!"
    assert got_429, "Could not trigger rate limit after 70 requests"
