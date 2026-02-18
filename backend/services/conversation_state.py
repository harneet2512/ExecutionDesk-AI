"""Conversation state management for pending trade confirmations."""
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from backend.db.connect import get_conn
from backend.core.logging import get_logger

logger = get_logger(__name__)

PENDING_TRADE_EXPIRY_MINUTES = 5


class PendingTrade:
    """Pending trade awaiting confirmation."""
    
    def __init__(
        self,
        conversation_id: str,
        side: str,
        asset: str,
        amount_usd: float,
        mode: str,
        is_most_profitable: bool = False,
        lookback_hours: int = 24,
        created_at: Optional[str] = None
    ):
        self.conversation_id = conversation_id
        self.side = side
        self.asset = asset
        self.amount_usd = amount_usd
        self.mode = mode
        self.is_most_profitable = is_most_profitable
        self.lookback_hours = lookback_hours
        self.created_at = created_at or datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "conversation_id": self.conversation_id,
            "side": self.side,
            "asset": self.asset,
            "amount_usd": self.amount_usd,
            "mode": self.mode,
            "is_most_profitable": self.is_most_profitable,
            "lookback_hours": self.lookback_hours,
            "created_at": self.created_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PendingTrade":
        """Create from dictionary."""
        return cls(**data)
    
    def is_expired(self) -> bool:
        """Check if pending trade has expired (5 minutes)."""
        created = datetime.fromisoformat(self.created_at)
        expiry = created + timedelta(minutes=PENDING_TRADE_EXPIRY_MINUTES)
        return datetime.utcnow() > expiry


def store_pending_trade(pending_trade: PendingTrade) -> None:
    """
    Store pending trade in conversation metadata.
    Replaces any existing pending trade for this conversation.
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        
        # Get current metadata
        cursor.execute(
            "SELECT metadata_json FROM conversations WHERE conversation_id = ?",
            (pending_trade.conversation_id,)
        )
        row = cursor.fetchone()
        
        if not row:
            logger.warning(f"Conversation {pending_trade.conversation_id} not found")
            return
        
        # Update metadata with pending trade
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        metadata["pending_trade"] = pending_trade.to_dict()
        
        cursor.execute(
            "UPDATE conversations SET metadata_json = ? WHERE conversation_id = ?",
            (json.dumps(metadata), pending_trade.conversation_id)
        )
        conn.commit()
        
        logger.info(f"Stored pending trade for conversation {pending_trade.conversation_id}: {pending_trade.side} {pending_trade.amount_usd} {pending_trade.asset} ({pending_trade.mode})")


def get_pending_trade(conversation_id: str) -> Optional[PendingTrade]:
    """
    Retrieve pending trade from conversation metadata.
    Returns None if no pending trade or if expired.
    """
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT metadata_json FROM conversations WHERE conversation_id = ?",
            (conversation_id,)
        )
        row = cursor.fetchone()
        
        if not row or not row["metadata_json"]:
            return None
        
        metadata = json.loads(row["metadata_json"])
        pending_data = metadata.get("pending_trade")
        
        if not pending_data:
            return None
        
        pending_trade = PendingTrade.from_dict(pending_data)
        
        # Check expiration
        if pending_trade.is_expired():
            logger.info(f"Pending trade expired for conversation {conversation_id}")
            clear_pending_trade(conversation_id)
            return None
        
        return pending_trade


def clear_pending_trade(conversation_id: str) -> None:
    """Clear pending trade from conversation metadata."""
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT metadata_json FROM conversations WHERE conversation_id = ?",
            (conversation_id,)
        )
        row = cursor.fetchone()
        
        if not row:
            return
        
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        if "pending_trade" in metadata:
            del metadata["pending_trade"]
            
            cursor.execute(
                "UPDATE conversations SET metadata_json = ? WHERE conversation_id = ?",
                (json.dumps(metadata), conversation_id)
            )
            conn.commit()
            
            logger.info(f"Cleared pending trade for conversation {conversation_id}")


def detect_test_environment() -> bool:
    """Detect if running in pytest environment."""
    import sys
    return 'pytest' in sys.modules or 'PYTEST_CURRENT_TEST' in os.environ
