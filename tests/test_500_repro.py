"""Tests for 500 error fixes: hardened conversation endpoints, thread-safe middleware."""
import pytest
import json
import sqlite3
from unittest.mock import patch, MagicMock


class TestGetConversationHardened:
    """get_conversation should never return 500 for recoverable DB issues."""

    def test_returns_404_for_missing_conversation(self, test_db):
        """get_conversation with unknown ID returns 404 JSON, not 500."""
        from backend.api.routes.conversations import _get_conversation_impl
        with pytest.raises(Exception) as exc_info:
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                _get_conversation_impl("nonexistent_conv", "t_default")
            )
        assert "404" in str(exc_info.value.status_code) or exc_info.value.status_code == 404

    def test_impl_returns_conversation_response(self, test_db):
        """_get_conversation_impl returns ConversationResponse for valid conversation."""
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        conv_id = new_id("conv_")
        now = now_iso()
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO conversations (conversation_id, tenant_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (conv_id, "t_default", "Test", now, now)
            )
            conn.commit()

        from backend.api.routes.conversations import _get_conversation_impl
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            _get_conversation_impl(conv_id, "t_default")
        )
        assert result.conversation_id == conv_id
        assert result.tenant_id == "t_default"


class TestDeleteConversationHardened:
    """delete_conversation should never return 500 for recoverable DB issues."""

    def test_returns_404_for_missing_conversation(self, test_db):
        """delete_conversation with unknown ID returns 404, not 500."""
        from backend.api.routes.conversations import _delete_conversation_impl
        with pytest.raises(Exception) as exc_info:
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                _delete_conversation_impl("nonexistent_conv", "t_default")
            )
        assert exc_info.value.status_code == 404

    def test_delete_removes_conversation(self, test_db):
        """delete_conversation actually removes the conversation and messages."""
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        conv_id = new_id("conv_")
        msg_id = new_id("msg_")
        now = now_iso()
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO conversations (conversation_id, tenant_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (conv_id, "t_default", "Test", now, now)
            )
            conn.execute(
                "INSERT INTO messages (message_id, conversation_id, tenant_id, role, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (msg_id, conv_id, "t_default", "user", "Hello", now)
            )
            conn.commit()

        from backend.api.routes.conversations import _delete_conversation_impl
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            _delete_conversation_impl(conv_id, "t_default")
        )
        assert result["deleted"] is True

        # Verify actually removed
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM conversations WHERE conversation_id = ?", (conv_id,))
            assert cursor.fetchone() is None
            cursor.execute("SELECT * FROM messages WHERE conversation_id = ?", (conv_id,))
            assert cursor.fetchone() is None


class TestListMessagesHardened:
    """list_messages should handle concurrent access without 500s."""

    def test_list_messages_empty_conversation(self, test_db):
        """list_messages returns empty list for conversation with no messages."""
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        conv_id = new_id("conv_")
        now = now_iso()
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO conversations (conversation_id, tenant_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (conv_id, "t_default", "Test", now, now)
            )
            conn.commit()

        from backend.api.routes.conversations import _list_messages_impl
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            _list_messages_impl(conv_id, "t_default")
        )
        assert result == []

    def test_list_messages_with_malformed_metadata(self, test_db):
        """list_messages handles corrupt metadata_json without crashing."""
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        conv_id = new_id("conv_")
        msg_id = new_id("msg_")
        now = now_iso()
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO conversations (conversation_id, tenant_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (conv_id, "t_default", "Test", now, now)
            )
            # Insert message with malformed metadata
            conn.execute(
                "INSERT INTO messages (message_id, conversation_id, tenant_id, role, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (msg_id, conv_id, "t_default", "user", "Hello", "{{{bad json", now)
            )
            conn.commit()

        from backend.api.routes.conversations import _list_messages_impl
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            _list_messages_impl(conv_id, "t_default")
        )
        # Should return the message with None metadata, not crash
        assert len(result) == 1
        assert result[0].content == "Hello"
        assert result[0].metadata_json is None


class TestRequestIDMiddlewareThreadSafety:
    """RequestIDMiddleware must use contextvars, not global factory."""

    def test_uses_contextvars_not_factory(self):
        """Verify the middleware dispatch uses contextvars.ContextVar, not logging.setLogRecordFactory."""
        import inspect
        from backend.api.main import RequestIDMiddleware
        # Check only the dispatch method source (not docstrings on the class)
        dispatch_source = inspect.getsource(RequestIDMiddleware.dispatch)
        assert "setLogRecordFactory" not in dispatch_source, "dispatch must not call logging.setLogRecordFactory (not thread-safe)"
        assert "_request_id_ctx" in dispatch_source, "dispatch should use _request_id_ctx ContextVar"

    def test_request_id_filter_exists(self):
        """Verify the RequestIDFilter class exists and is a logging.Filter."""
        import logging
        from backend.api.main import RequestIDFilter
        assert issubclass(RequestIDFilter, logging.Filter)

    def test_request_id_contextvar_exists(self):
        """Verify _request_id_ctx ContextVar is defined."""
        import contextvars
        from backend.api.main import _request_id_ctx
        assert isinstance(_request_id_ctx, contextvars.ContextVar)
