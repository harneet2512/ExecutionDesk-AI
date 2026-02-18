"""Conversations API routes."""
import sqlite3
import traceback
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from typing import List, Optional
from pydantic import BaseModel, Field
import json
from backend.api.deps import require_viewer, require_trader
from backend.db.connect import get_conn, get_conn_retry, row_get
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


def _safe_json_loads(s, default=None):
    """Parse JSON safely, returning default on failure."""
    if not s:
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Malformed JSON in DB column (len=%d): %s",
                        len(str(s)), str(s)[:80])
        return default


def _structured_error(status_code: int, code: str, message: str, request_id: str) -> JSONResponse:
    """Return a structured JSON error with X-Request-ID header."""
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ERROR",
            "error": {"code": code, "message": message, "request_id": request_id},
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )


class ConversationResponse(BaseModel):
    conversation_id: str
    tenant_id: str
    title: Optional[str]
    created_at: str
    updated_at: str
    last_message_at: Optional[str] = None


class MessageResponse(BaseModel):
    message_id: str
    conversation_id: str
    role: str
    content: str
    run_id: Optional[str] = None
    metadata_json: Optional[dict] = None
    created_at: str


class CreateConversationRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    
    model_config = {"extra": "forbid"}


class CreateConversationResponse(BaseModel):
    conversation_id: str
    title: Optional[str]
    created_at: str


class CreateMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    role: str = Field("user", pattern="^(user|assistant)$")
    run_id: Optional[str] = Field(None, max_length=100)
    metadata_json: Optional[dict] = None
    
    model_config = {"extra": "forbid"}


class CreateMessageResponse(BaseModel):
    message_id: str
    conversation_id: str
    created_at: str


@router.get("", response_model=List[ConversationResponse])
async def list_conversations(request: Request, user: dict = Depends(require_viewer)):
    """List all conversations for the tenant."""
    tenant_id = user["tenant_id"]
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    try:
        result = await _list_conversations_impl(tenant_id)
        return result if result is not None else []
    except HTTPException:
        raise
    except sqlite3.OperationalError as e:
        err_lower = str(e).lower()
        if "no such column" in err_lower or "no such table" in err_lower:
            return _structured_error(503, "DB_SCHEMA_OUT_OF_DATE",
                                     "Database schema is outdated. Run migrations.", request_id)
        if "database is locked" in err_lower:
            return _structured_error(503, "DB_BUSY",
                                     "Database is temporarily busy. Try again shortly.", request_id)
        logger.error("list_conversations DB error: %s | req=%s", str(e)[:200], request_id)
        return _structured_error(503, "DB_ERROR", "Database error.", request_id)
    except Exception as e:
        logger.error("list_conversations error: %s | req=%s", str(e)[:200], request_id)
        return _structured_error(500, "INTERNAL_ERROR", str(e)[:200], request_id)


async def _list_conversations_impl(tenant_id: str):
    with get_conn_retry(max_retries=2) as conn:
        cursor = conn.cursor()
        # Get conversations with last message timestamp
        cursor.execute(
            """
            SELECT 
                c.conversation_id,
                c.tenant_id,
                c.title,
                c.created_at,
                c.updated_at,
                MAX(m.created_at) as last_message_at
            FROM conversations c
            LEFT JOIN messages m ON c.conversation_id = m.conversation_id
            WHERE c.tenant_id = ?
            GROUP BY c.conversation_id
            ORDER BY COALESCE(MAX(m.created_at), c.created_at) DESC
            LIMIT 100
            """,
            (tenant_id,)
        )
        rows = cursor.fetchall()
    
    result: list[ConversationResponse] = []
    for row in rows:
        try:
            # Guard against partially-migrated rows to prevent 500s in sidebar.
            result.append(
                ConversationResponse(
                    conversation_id=row_get(row, "conversation_id", ""),
                    tenant_id=row_get(row, "tenant_id", tenant_id),
                    title=row_get(row, "title"),
                    created_at=row_get(row, "created_at", now_iso()),
                    updated_at=row_get(row, "updated_at", row_get(row, "created_at", now_iso())),
                    last_message_at=row_get(row, "last_message_at"),
                )
            )
        except Exception as row_err:
            logger.warning("Skipping corrupt conversation row: %s", str(row_err)[:100])
            continue
    return result


@router.post("", response_model=CreateConversationResponse)
async def create_conversation(
    body: CreateConversationRequest,
    http_request: Request,
    user: dict = Depends(require_trader)
):
    """Create a new conversation."""
    tenant_id = user["tenant_id"]
    conversation_id = new_id("conv_")
    title = body.title or "New Conversation"
    now = now_iso()
    request_id = getattr(http_request.state, "request_id", str(uuid.uuid4())[:8])

    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO conversations (conversation_id, tenant_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, tenant_id, title, now, now)
            )
            conn.commit()
    except sqlite3.OperationalError as e:
        err_lower = str(e).lower()
        if "database is locked" in err_lower:
            return _structured_error(503, "DB_BUSY",
                                     "Database is temporarily busy. Try again shortly.", request_id)
        logger.error("create_conversation DB error: %s | req=%s", str(e)[:200], request_id)
        return _structured_error(503, "DB_ERROR", "Database error.", request_id)
    except Exception as e:
        logger.error("create_conversation error: %s | req=%s", str(e)[:200], request_id)
        return _structured_error(500, "INTERNAL_ERROR", str(e)[:200], request_id)

    return CreateConversationResponse(
        conversation_id=conversation_id,
        title=title,
        created_at=now
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    request: Request,
    user: dict = Depends(require_viewer)
):
    """Get conversation details."""
    tenant_id = user["tenant_id"]
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    try:
        return await _get_conversation_impl(conversation_id, tenant_id)
    except HTTPException:
        raise
    except sqlite3.OperationalError as e:
        err_lower = str(e).lower()
        if "no such column" in err_lower or "no such table" in err_lower:
            return _structured_error(503, "DB_SCHEMA_OUT_OF_DATE",
                                     "Database schema is outdated. Run migrations.", request_id)
        if "database is locked" in err_lower:
            return _structured_error(503, "DB_BUSY",
                                     "Database is temporarily busy. Try again shortly.", request_id)
        logger.error("get_conversation DB error: %s | req=%s", str(e)[:200], request_id)
        return _structured_error(503, "DB_ERROR", "Database error.", request_id)
    except Exception as e:
        logger.error("get_conversation error: %s | req=%s", str(e)[:200], request_id)
        return _structured_error(500, "INTERNAL_ERROR", str(e)[:200], request_id)


async def _get_conversation_impl(conversation_id: str, tenant_id: str):
    with get_conn_retry(max_retries=2) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                c.conversation_id,
                c.tenant_id,
                c.title,
                c.created_at,
                c.updated_at,
                MAX(m.created_at) as last_message_at
            FROM conversations c
            LEFT JOIN messages m ON c.conversation_id = m.conversation_id
            WHERE c.conversation_id = ? AND c.tenant_id = ?
            GROUP BY c.conversation_id
            """,
            (conversation_id, tenant_id)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Conversation not found")

    return ConversationResponse(
        conversation_id=row["conversation_id"],
        tenant_id=row["tenant_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_message_at=row["last_message_at"]
    )


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    request: Request,
    user: dict = Depends(require_trader)
):
    """Delete a conversation and all associated data.

    Deletes:
    - All messages in the conversation (via CASCADE)
    - Pending trade confirmations for this conversation
    - The conversation record itself
    """
    tenant_id = user["tenant_id"]
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    try:
        return await _delete_conversation_impl(conversation_id, tenant_id)
    except HTTPException:
        raise
    except sqlite3.OperationalError as e:
        err_lower = str(e).lower()
        if "no such column" in err_lower or "no such table" in err_lower:
            return _structured_error(503, "DB_SCHEMA_OUT_OF_DATE",
                                     "Database schema is outdated. Run migrations.", request_id)
        if "database is locked" in err_lower:
            return _structured_error(503, "DB_BUSY",
                                     "Database is temporarily busy. Try again shortly.", request_id)
        logger.error("delete_conversation DB error: %s | req=%s", str(e)[:200], request_id)
        return _structured_error(503, "DB_ERROR", "Database error.", request_id)
    except Exception as e:
        logger.error("delete_conversation error: %s | req=%s", str(e)[:200], request_id)
        return _structured_error(500, "INTERNAL_ERROR", str(e)[:200], request_id)


async def _delete_conversation_impl(conversation_id: str, tenant_id: str):
    with get_conn() as conn:
        cursor = conn.cursor()

        # Verify conversation exists and belongs to tenant
        cursor.execute(
            "SELECT conversation_id FROM conversations WHERE conversation_id = ? AND tenant_id = ?",
            (conversation_id, tenant_id)
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Delete pending trade confirmations for this conversation
        cursor.execute(
            "DELETE FROM trade_confirmations WHERE conversation_id = ? AND tenant_id = ?",
            (conversation_id, tenant_id)
        )

        # Delete messages (should cascade from FK, but explicit is safer)
        cursor.execute(
            "DELETE FROM messages WHERE conversation_id = ? AND tenant_id = ?",
            (conversation_id, tenant_id)
        )

        # Delete the conversation
        cursor.execute(
            "DELETE FROM conversations WHERE conversation_id = ? AND tenant_id = ?",
            (conversation_id, tenant_id)
        )

        conn.commit()

    return {"deleted": True, "conversation_id": conversation_id}


@router.get("/{conversation_id}/messages", response_model=List[MessageResponse])
async def list_messages(
    conversation_id: str,
    request: Request,
    user: dict = Depends(require_viewer)
):
    """List messages in a conversation.

    Hardened against: corrupt metadata JSON, missing columns, DB locks.
    Never returns 500 for recoverable DB issues.
    """
    tenant_id = user["tenant_id"]
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    try:
        return await _list_messages_impl(conversation_id, tenant_id)
    except HTTPException:
        raise
    except sqlite3.OperationalError as e:
        err_lower = str(e).lower()
        if "no such column" in err_lower or "no such table" in err_lower:
            logger.error("Schema error in list_messages: %s | req=%s", str(e)[:200], request_id)
            return _structured_error(503, "DB_SCHEMA_OUT_OF_DATE",
                                     "Database schema is outdated. Run migrations.", request_id)
        if "database is locked" in err_lower or "database table is locked" in err_lower:
            logger.warning("DB busy in list_messages | req=%s", request_id)
            return _structured_error(503, "DB_BUSY",
                                     "Database is temporarily busy. Try again shortly.", request_id)
        logger.error("DB OperationalError in list_messages: %s | req=%s", str(e)[:200], request_id)
        return _structured_error(503, "DB_ERROR", "Database error. Try again shortly.", request_id)
    except Exception as e:
        logger.error("list_messages error: %s | req=%s", str(e)[:200], request_id)
        return _structured_error(500, "INTERNAL_ERROR", str(e)[:200], request_id)


async def _list_messages_impl(conversation_id: str, tenant_id: str):
    # Use retry-capable connection for reads
    with get_conn_retry(max_retries=2) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT conversation_id FROM conversations WHERE conversation_id = ? AND tenant_id = ?",
            (conversation_id, tenant_id)
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Get messages
        cursor.execute(
            """
            SELECT message_id, conversation_id, role, content, run_id, metadata_json, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            """,
            (conversation_id,)
        )
        rows = cursor.fetchall()

    # Build response with per-row safety: one corrupt row cannot crash the whole list
    result = []
    for row in rows:
        try:
            result.append(MessageResponse(
                message_id=row["message_id"],
                conversation_id=row["conversation_id"],
                role=row["role"],
                content=row["content"] or "",
                run_id=row["run_id"],
                metadata_json=_safe_json_loads(row["metadata_json"]),
                created_at=row["created_at"]
            ))
        except Exception as row_err:
            logger.warning("Skipping corrupt message row %s: %s",
                           row["message_id"] if "message_id" in row.keys() else "?",
                           str(row_err)[:100])
            continue
    return result


@router.post("/{conversation_id}/messages", response_model=CreateMessageResponse)
async def create_message(
    conversation_id: str,
    body: CreateMessageRequest,
    http_request: Request,
    user: dict = Depends(require_trader)
):
    """Create a message in a conversation."""
    tenant_id = user["tenant_id"]
    message_id = new_id("msg_")
    now = now_iso()
    request_id = getattr(http_request.state, "request_id", str(uuid.uuid4())[:8])

    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT conversation_id FROM conversations WHERE conversation_id = ? AND tenant_id = ?",
                (conversation_id, tenant_id)
            )
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Conversation not found")

            # If this is the first user message and conversation has default title, update title
            if body.role == "user" and not body.content.startswith("New Conversation"):
                cursor.execute(
                    "SELECT COUNT(*) as count FROM messages WHERE conversation_id = ?",
                    (conversation_id,)
                )
                msg_count = cursor.fetchone()["count"]
                if msg_count == 0:
                    title = body.content[:50].strip()
                    if len(body.content) > 50:
                        title += "..."
                    cursor.execute(
                        "UPDATE conversations SET title = ?, updated_at = ? WHERE conversation_id = ?",
                        (title, now, conversation_id)
                    )

            # Safely serialize metadata_json
            try:
                metadata_str = json.dumps(body.metadata_json, default=str) if body.metadata_json else None
            except (TypeError, ValueError):
                metadata_str = None

            cursor.execute(
                """
                INSERT INTO messages (message_id, conversation_id, tenant_id, role, content, run_id, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, conversation_id, tenant_id, body.role, body.content, body.run_id, metadata_str, now)
            )
            cursor.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                (now, conversation_id)
            )
            conn.commit()
    except HTTPException:
        raise
    except sqlite3.OperationalError as e:
        err_lower = str(e).lower()
        if "database is locked" in err_lower:
            return _structured_error(503, "DB_BUSY",
                                     "Database is temporarily busy. Try again shortly.", request_id)
        logger.error("create_message DB error: %s | req=%s", str(e)[:200], request_id)
        return _structured_error(503, "DB_ERROR", "Database error.", request_id)
    except Exception as e:
        logger.error("create_message error: %s | req=%s", str(e)[:200], request_id)
        return _structured_error(500, "INTERNAL_ERROR", str(e)[:200], request_id)

    return CreateMessageResponse(
        message_id=message_id,
        conversation_id=conversation_id,
        created_at=now
    )
