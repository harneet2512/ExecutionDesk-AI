"""Tests for WebSocket market data streaming.

Tests cover:
- WebSocket connection lifecycle (connect, subscribe, receive, disconnect)
- Subscription management (subscribe/unsubscribe channels)
- Max connection limit (6th connection rejected for same tenant)
- Heartbeat timeout
- Broadcast reaches all subscribers on a channel
"""
import asyncio
import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from starlette.testclient import TestClient as StarletteTestClient
from starlette.websockets import WebSocketDisconnect

from backend.api.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_ws_manager():
    """Reset the global WS manager singleton between tests."""
    from backend.services import ws_manager as wsm
    wsm._manager = None
    yield
    wsm._manager = None


# ---------------------------------------------------------------------------
# 1. Connection lifecycle
# ---------------------------------------------------------------------------

class TestWebSocketLifecycle:
    """WebSocket connect / subscribe / receive / disconnect."""

    def test_connect_and_disconnect(self):
        """Client can connect and cleanly disconnect."""
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/market-data?tenant=t_default") as ws:
            # Should receive a welcome message on connect
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert "connection_id" in data

    def test_subscribe_and_receive_ack(self):
        """Client subscribes to a channel and receives an ack."""
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/market-data?tenant=t_default") as ws:
            ws.receive_json()  # welcome
            ws.send_json({"action": "subscribe", "channel": "prices:BTC-USD"})
            ack = ws.receive_json()
            assert ack["type"] == "subscribed"
            assert ack["channel"] == "prices:BTC-USD"

    def test_unsubscribe(self):
        """Client can unsubscribe from a channel."""
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/market-data?tenant=t_default") as ws:
            ws.receive_json()  # welcome
            ws.send_json({"action": "subscribe", "channel": "prices:ETH-USD"})
            ws.receive_json()  # ack
            ws.send_json({"action": "unsubscribe", "channel": "prices:ETH-USD"})
            ack = ws.receive_json()
            assert ack["type"] == "unsubscribed"
            assert ack["channel"] == "prices:ETH-USD"

    def test_invalid_action(self):
        """Unknown action returns error message."""
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/market-data?tenant=t_default") as ws:
            ws.receive_json()  # welcome
            ws.send_json({"action": "foobar"})
            resp = ws.receive_json()
            assert resp["type"] == "error"

    def test_malformed_json(self):
        """Non-JSON text returns error, connection stays alive."""
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/market-data?tenant=t_default") as ws:
            ws.receive_json()  # welcome
            ws.send_text("not json at all")
            resp = ws.receive_json()
            assert resp["type"] == "error"


# ---------------------------------------------------------------------------
# 2. Subscription management
# ---------------------------------------------------------------------------

class TestSubscriptionManagement:
    """Channel subscribe / unsubscribe book-keeping."""

    def test_subscribe_multiple_channels(self):
        """Client can subscribe to several channels."""
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/market-data?tenant=t_default") as ws:
            ws.receive_json()  # welcome
            channels = ["prices:BTC-USD", "prices:ETH-USD", "book:BTC-USD"]
            for ch in channels:
                ws.send_json({"action": "subscribe", "channel": ch})
                ack = ws.receive_json()
                assert ack["type"] == "subscribed"
                assert ack["channel"] == ch

    def test_duplicate_subscribe_is_idempotent(self):
        """Subscribing twice to the same channel succeeds without error."""
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/market-data?tenant=t_default") as ws:
            ws.receive_json()  # welcome
            ws.send_json({"action": "subscribe", "channel": "prices:BTC-USD"})
            ws.receive_json()  # first ack
            ws.send_json({"action": "subscribe", "channel": "prices:BTC-USD"})
            ack = ws.receive_json()
            assert ack["type"] == "subscribed"

    def test_unsubscribe_unknown_channel(self):
        """Unsubscribing from a channel never subscribed returns ack (idempotent)."""
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/market-data?tenant=t_default") as ws:
            ws.receive_json()  # welcome
            ws.send_json({"action": "unsubscribe", "channel": "prices:DOGE-USD"})
            ack = ws.receive_json()
            assert ack["type"] == "unsubscribed"

    def test_channel_format_validation(self):
        """Channels must match <type>:<symbol> format."""
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/market-data?tenant=t_default") as ws:
            ws.receive_json()  # welcome
            ws.send_json({"action": "subscribe", "channel": "invalid_no_colon"})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "channel" in resp.get("message", "").lower()


# ---------------------------------------------------------------------------
# 3. Max connection limit
# ---------------------------------------------------------------------------

class TestMaxConnections:
    """Enforce max 5 concurrent WebSocket connections per tenant."""

    def test_sixth_connection_rejected(self):
        """6th WebSocket from the same tenant is rejected."""
        client = TestClient(app)
        # Open 5 connections
        contexts = []
        websockets = []
        for i in range(5):
            ctx = client.websocket_connect("/api/v1/ws/market-data?tenant=t_limit_test")
            ws = ctx.__enter__()
            ws.receive_json()  # welcome
            contexts.append(ctx)
            websockets.append(ws)

        try:
            # 6th should be rejected
            with pytest.raises(Exception):
                with client.websocket_connect("/api/v1/ws/market-data?tenant=t_limit_test") as ws6:
                    ws6.receive_json()
        finally:
            for ctx in contexts:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    pass

    def test_different_tenant_not_limited(self):
        """Connections from different tenants are independent limits."""
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/market-data?tenant=t_alpha") as ws1:
            ws1.receive_json()
            with client.websocket_connect("/api/v1/ws/market-data?tenant=t_beta") as ws2:
                ws2.receive_json()
                # Both connected fine


# ---------------------------------------------------------------------------
# 4. Heartbeat
# ---------------------------------------------------------------------------

class TestHeartbeat:
    """Heartbeat / ping mechanism."""

    def test_pong_response(self):
        """Client sends ping, server replies pong."""
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/market-data?tenant=t_default") as ws:
            ws.receive_json()  # welcome
            ws.send_json({"action": "ping"})
            pong = ws.receive_json()
            assert pong["type"] == "pong"


# ---------------------------------------------------------------------------
# 5. Broadcast
# ---------------------------------------------------------------------------

class TestBroadcast:
    """Broadcast reaches all subscribers on a channel."""

    def test_broadcast_to_subscribers(self):
        """Two clients on the same channel both receive a broadcast."""
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/market-data?tenant=t_a") as ws1:
            ws1.receive_json()  # welcome
            ws1.send_json({"action": "subscribe", "channel": "prices:BTC-USD"})
            ws1.receive_json()  # ack

            with client.websocket_connect("/api/v1/ws/market-data?tenant=t_b") as ws2:
                ws2.receive_json()  # welcome
                ws2.send_json({"action": "subscribe", "channel": "prices:BTC-USD"})
                ws2.receive_json()  # ack

                # Trigger a broadcast via the HTTP endpoint (async-safe)
                resp = client.post(
                    "/api/v1/ws/broadcast",
                    headers={"X-Dev-Tenant": "t_default"},
                    json={
                        "channel": "prices:BTC-USD",
                        "message": {"type": "price", "symbol": "BTC-USD", "price": 67500.0, "change_pct": 1.2},
                    },
                )
                assert resp.status_code == 200

                msg1 = ws1.receive_json()
                assert msg1["type"] == "price"
                assert msg1["symbol"] == "BTC-USD"

                msg2 = ws2.receive_json()
                assert msg2["type"] == "price"
                assert msg2["symbol"] == "BTC-USD"

    def test_non_subscriber_does_not_receive(self):
        """Client subscribed to a different channel does not receive broadcast."""
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/market-data?tenant=t_c") as ws1:
            ws1.receive_json()  # welcome
            ws1.send_json({"action": "subscribe", "channel": "prices:ETH-USD"})
            ws1.receive_json()  # ack

            with client.websocket_connect("/api/v1/ws/market-data?tenant=t_d") as ws2:
                ws2.receive_json()  # welcome
                ws2.send_json({"action": "subscribe", "channel": "prices:BTC-USD"})
                ws2.receive_json()  # ack

                # Broadcast to BTC channel only
                resp = client.post(
                    "/api/v1/ws/broadcast",
                    headers={"X-Dev-Tenant": "t_default"},
                    json={
                        "channel": "prices:BTC-USD",
                        "message": {"type": "price", "symbol": "BTC-USD", "price": 67500.0},
                    },
                )
                assert resp.status_code == 200

                # ws2 should get it
                msg = ws2.receive_json()
                assert msg["symbol"] == "BTC-USD"

                # ws1 should NOT get it (subscribed to ETH only)
                # We send a ping so we can verify no price message arrived first
                ws1.send_json({"action": "ping"})
                pong = ws1.receive_json()
                assert pong["type"] == "pong"  # no price message before pong


# ---------------------------------------------------------------------------
# 6. Channel type validation
# ---------------------------------------------------------------------------

class TestChannelTypes:
    """Validate supported channel prefixes."""

    @pytest.mark.parametrize("channel", [
        "prices:BTC-USD",
        "book:BTC-USD",
        "trades:BTC-USD",
        "prices:pm_market_123",
    ])
    def test_valid_channels(self, channel):
        """Valid channel formats are accepted."""
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/market-data?tenant=t_default") as ws:
            ws.receive_json()  # welcome
            ws.send_json({"action": "subscribe", "channel": channel})
            ack = ws.receive_json()
            assert ack["type"] == "subscribed"

    def test_invalid_channel_prefix(self):
        """Unknown channel prefix is rejected."""
        client = TestClient(app)
        with client.websocket_connect("/api/v1/ws/market-data?tenant=t_default") as ws:
            ws.receive_json()  # welcome
            ws.send_json({"action": "subscribe", "channel": "unknown:BTC-USD"})
            resp = ws.receive_json()
            assert resp["type"] == "error"
