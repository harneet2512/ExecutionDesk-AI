from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import json
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.logging import get_logger

logger = get_logger(__name__)

class TradeConfirmationsRepo:
    def create_pending(
        self,
        tenant_id: str,
        conversation_id: str,
        proposal_json: Dict[str, Any],
        mode: str,
        user_id: Optional[str] = None,
        ttl_seconds: int = 300
    ) -> str:
        """Create a new pending trade confirmation."""
        confirmation_id = new_id("conf_")
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds)
        
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO trade_confirmations (
                    id, tenant_id, conversation_id, user_id, proposal_json, 
                    mode, status, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    confirmation_id, tenant_id, conversation_id, user_id,
                    json.dumps(proposal_json), mode, "PENDING",
                    now.isoformat(), expires_at.isoformat()
                )
            )
            conn.commit()
            
        logger.info(f"Created pending confirmation {confirmation_id} for conversation {conversation_id}")
        return confirmation_id

    def get_by_id(self, tenant_id: str, confirmation_id: str) -> Optional[Dict[str, Any]]:
        """Get confirmation by ID."""
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM trade_confirmations 
                WHERE id = ? AND tenant_id = ?
                """,
                (confirmation_id, tenant_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_latest_pending_for_conversation(self, tenant_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Get latest pending confirmation for a conversation."""
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM trade_confirmations 
                WHERE conversation_id = ? AND tenant_id = ? AND status = 'PENDING'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (conversation_id, tenant_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def mark_confirmed(self, tenant_id: str, confirmation_id: str) -> bool:
        """Mark confirmation as CONFIRMED (single-use, idempotent).
        
        Uses ``AND status = 'PENDING'`` so concurrent requests are safe:
        only the first one succeeds, later ones return False.
        
        Returns True if the row was actually updated, False if already processed.
        """
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE trade_confirmations 
                SET status = 'CONFIRMED', confirmed_at = ?
                WHERE id = ? AND tenant_id = ? AND status = 'PENDING'
                """,
                (datetime.utcnow().isoformat(), confirmation_id, tenant_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def mark_cancelled(self, tenant_id: str, confirmation_id: str):
        """Mark confirmation as CANCELLED."""
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE trade_confirmations 
                SET status = 'CANCELLED'
                WHERE id = ? AND tenant_id = ?
                """,
                (confirmation_id, tenant_id)
            )
            conn.commit()

    def mark_expired(self, tenant_id: str, confirmation_id: str):
        """Mark confirmation as EXPIRED."""
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE trade_confirmations
                SET status = 'EXPIRED'
                WHERE id = ? AND tenant_id = ?
                """,
                (confirmation_id, tenant_id)
            )
            conn.commit()

    def update_proposal(self, confirmation_id: str, proposal: dict) -> None:
        """Update proposal_json on a trade confirmation (e.g., after asset selection)."""
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE trade_confirmations SET proposal_json = ? WHERE id = ?",
                (json.dumps(proposal, default=str), confirmation_id)
            )
            conn.commit()

    def update_insight(self, confirmation_id: str, insight: dict) -> None:
        """Persist insight JSON on a trade confirmation."""
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE trade_confirmations SET insight_json = ? WHERE id = ?",
                (json.dumps(insight, default=str), confirmation_id)
            )
            conn.commit()

    def get_by_id_debug(self, confirmation_id: str) -> Optional[Dict[str, Any]]:
        """Get confirmation by ID regardless of tenant (for debugging tenant mismatches)."""
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM trade_confirmations WHERE id = ?",
                (confirmation_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
