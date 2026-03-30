"""Trade tickets repository for ASSISTED_LIVE execution mode (stocks).

Users receive order tickets, execute manually in their brokerage, then submit receipts.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import json
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.logging import get_logger

logger = get_logger(__name__)


class TradeTicketsRepo:
    """Repository for trade tickets (ASSISTED_LIVE mode for stocks)."""

    def create_ticket(
        self,
        tenant_id: str,
        run_id: str,
        symbol: str,
        side: str,
        notional_usd: float,
        est_qty: Optional[float] = None,
        suggested_limit: Optional[float] = None,
        tif: str = "DAY",
        ttl_hours: int = 24,
        asset_class: str = "STOCK"
    ) -> str:
        """Create a new trade ticket for manual execution.

        Args:
            tenant_id: Tenant identifier
            run_id: Run that generated this ticket
            symbol: Stock symbol (e.g., AAPL)
            side: BUY or SELL
            notional_usd: Dollar amount
            est_qty: Estimated quantity (optional)
            suggested_limit: Suggested limit price (optional)
            tif: Time in force (default DAY)
            ttl_hours: Hours until ticket expires (default 24)
            asset_class: Asset class (default STOCK)

        Returns:
            ticket_id: Unique ticket identifier
        """
        ticket_id = new_id("ticket_")
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=ttl_hours)

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO trade_tickets (
                    id, tenant_id, run_id, asset_class, symbol, side,
                    notional_usd, est_qty, suggested_limit, tif,
                    expires_at, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id, tenant_id, run_id, asset_class, symbol, side,
                    notional_usd, est_qty, suggested_limit, tif,
                    expires_at.isoformat(), "PENDING", now.isoformat()
                )
            )
            conn.commit()

        logger.info(
            "Created trade ticket %s for %s %s run=%s",
            ticket_id, side, symbol, run_id
        )
        return ticket_id

    def get_by_id(self, tenant_id: str, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Get ticket by ID."""
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM trade_tickets
                WHERE id = ? AND tenant_id = ?
                """,
                (ticket_id, tenant_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_by_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get ticket for a run."""
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM trade_tickets
                WHERE run_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (run_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_pending_for_tenant(self, tenant_id: str) -> list:
        """Get all pending tickets for a tenant."""
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM trade_tickets
                WHERE tenant_id = ? AND status = 'PENDING'
                ORDER BY created_at DESC
                """,
                (tenant_id,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def mark_executed(self, tenant_id: str, ticket_id: str, receipt_json: Dict[str, Any]):
        """Mark ticket as executed with broker receipt.

        Args:
            tenant_id: Tenant identifier
            ticket_id: Ticket to mark
            receipt_json: Receipt data from broker (order confirmation, fill details)
        """
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE trade_tickets
                SET status = 'EXECUTED', receipt_json = ?
                WHERE id = ? AND tenant_id = ?
                """,
                (json.dumps(receipt_json), ticket_id, tenant_id)
            )
            conn.commit()

        logger.info(f"Marked ticket {ticket_id} as EXECUTED")

    def mark_expired(self, tenant_id: str, ticket_id: str):
        """Mark ticket as expired."""
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE trade_tickets
                SET status = 'EXPIRED'
                WHERE id = ? AND tenant_id = ?
                """,
                (ticket_id, tenant_id)
            )
            conn.commit()

    def mark_cancelled(self, tenant_id: str, ticket_id: str):
        """Mark ticket as cancelled."""
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE trade_tickets
                SET status = 'CANCELLED'
                WHERE id = ? AND tenant_id = ?
                """,
                (ticket_id, tenant_id)
            )
            conn.commit()

    def expire_stale_tickets(self) -> int:
        """Expire all tickets past their expiration time.

        Returns:
            count: Number of tickets expired
        """
        now = datetime.utcnow().isoformat()
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE trade_tickets
                SET status = 'EXPIRED'
                WHERE status = 'PENDING' AND expires_at < ?
                """,
                (now,)
            )
            count = cursor.rowcount
            conn.commit()

        if count > 0:
            logger.info(f"Expired {count} stale trade tickets")
        return count
