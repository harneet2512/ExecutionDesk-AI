"""Pushover notification service for trade events."""
import requests
from typing import Optional, Dict, Any
from datetime import datetime
from backend.core.logging import get_logger
from backend.core.config import get_settings
from backend.db.connect import get_conn

logger = get_logger(__name__)

PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"
TIMEOUT_SECONDS = 5
MAX_RETRIES = 2


def send_pushover(
    message: str,
    title: str = "Trading Agent",
    priority: int = 0,
    url: Optional[str] = None,
    url_title: Optional[str] = None,
    run_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    order_id: Optional[str] = None,
    action: str = "notification"
) -> bool:
    """
    Send Pushover notification with retry logic.
    
    Args:
        message: Notification message body
        title: Notification title
        priority: -2 (lowest) to 2 (emergency)
        url: Optional URL to include
        url_title: Optional URL title
        run_id: Optional run ID for tracking
        conversation_id: Optional conversation ID
        order_id: Optional order ID
        action: Action type (trade_placed, trade_failed, pending_confirm)
    
    Returns:
        True if notification sent successfully, False otherwise
        
    Note: Never raises exceptions - logs errors and returns False
    """
    settings = get_settings()
    
    # Check if Pushover is enabled
    if not settings.pushover_enabled:
        logger.debug("Pushover notifications disabled")
        _record_notification_event(
            channel="pushover",
            status="skipped",
            action=action,
            run_id=run_id,
            conversation_id=conversation_id,
            order_id=order_id,
            payload_redacted={"reason": "PUSHOVER_ENABLED=false"},
            error=None
        )
        return False
    
    # Validate credentials
    if not settings.pushover_app_token or not settings.pushover_user_key:
        logger.warning("Pushover credentials not configured")
        _record_notification_event(
            channel="pushover",
            status="failed",
            action=action,
            run_id=run_id,
            conversation_id=conversation_id,
            order_id=order_id,
            error="Missing credentials"
        )
        return False
    
    # Build payload (NEVER log secrets)
    payload = {
        "token": settings.pushover_app_token,
        "user": settings.pushover_user_key,
        "message": message,
        "title": title,
        "priority": priority
    }
    
    if url:
        payload["url"] = url
    if url_title:
        payload["url_title"] = url_title
    
    # Retry logic
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"Sending Pushover notification (attempt {attempt}/{MAX_RETRIES}): {title}")
            
            response = requests.post(
                PUSHOVER_API_URL,
                data=payload,
                timeout=TIMEOUT_SECONDS
            )
            
            if response.status_code == 200:
                logger.info(f"Pushover notification sent successfully: {title}")
                _record_notification_event(
                    channel="pushover",
                    status="sent",
                    action=action,
                    run_id=run_id,
                    conversation_id=conversation_id,
                    order_id=order_id,
                    payload_redacted={"title": title, "message_length": len(message)}
                )
                return True
            else:
                last_error = f"HTTP {response.status_code}: {response.text}"
                logger.warning(f"Pushover API error (attempt {attempt}): {last_error}")
                
        except requests.exceptions.Timeout:
            last_error = f"Timeout after {TIMEOUT_SECONDS}s"
            logger.warning(f"Pushover timeout (attempt {attempt}): {last_error}")
            
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            logger.warning(f"Pushover request failed (attempt {attempt}): {last_error}")
            
        except Exception as e:
            last_error = f"Unexpected error: {str(e)}"
            logger.error(f"Pushover unexpected error (attempt {attempt}): {last_error}")
    
    # All retries failed
    logger.error(f"Pushover notification failed after {MAX_RETRIES} attempts: {last_error}")
    _record_notification_event(
        channel="pushover",
        status="failed",
        action=action,
        run_id=run_id,
        conversation_id=conversation_id,
        order_id=order_id,
        error=last_error
    )
    return False


def _record_notification_event(
    channel: str,
    status: str,
    action: str,
    run_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    order_id: Optional[str] = None,
    payload_redacted: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None
) -> None:
    """Record notification event in database."""
    try:
        import json
        from backend.core.ids import new_id
        
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO notification_events 
                (id, created_at, channel, status, action, run_id, conversation_id, order_id, payload_redacted, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("notif"),
                    datetime.utcnow().isoformat(),
                    channel,
                    status,
                    action,
                    run_id,
                    conversation_id,
                    order_id,
                    json.dumps(payload_redacted) if payload_redacted else None,
                    error
                )
            )
            conn.commit()
            
    except Exception as e:
        logger.error(f"Failed to record notification event: {e}")


def notify_trade_placed(
    mode: str,
    side: str,
    symbol: str,
    notional_usd: float,
    order_id: str,
    run_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> bool:
    """Notify on successful trade placement."""
    emoji = "⚠️" if mode == "LIVE" else "📄"
    title = f"{emoji} {mode} Trade Placed"
    message = f"{side.upper()} ${notional_usd:.2f} of {symbol}\nOrder ID: {order_id}"
    
    return send_pushover(
        message=message,
        title=title,
        priority=1 if mode == "LIVE" else 0,
        run_id=run_id,
        conversation_id=conversation_id,
        order_id=order_id,
        action="trade_placed"
    )


def notify_trade_failed(
    mode: str,
    symbol: str,
    notional_usd: float,
    error: str,
    run_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> bool:
    """Notify on trade failure."""
    title = f"❌ {mode} Trade Failed"
    message = f"{symbol} ${notional_usd:.2f}\nError: {error[:100]}"
    
    return send_pushover(
        message=message,
        title=title,
        priority=1,
        run_id=run_id,
        conversation_id=conversation_id,
        action="trade_failed"
    )


def notify_pending_confirmation(
    mode: str,
    side: str,
    symbol: str,
    notional_usd: float,
    conversation_id: Optional[str] = None
) -> bool:
    """Notify on pending trade confirmation."""
    title = f"⏳ Trade Pending CONFIRM"
    message = f"{mode} {side.upper()} ${notional_usd:.2f} of {symbol}\nReply CONFIRM to execute"
    
    return send_pushover(
        message=message,
        title=title,
        priority=0,
        conversation_id=conversation_id,
        action="pending_confirm"
    )


def notify_portfolio_analysis(
    mode: str,
    total_value_usd: float,
    cash_usd: float,
    holdings_count: int,
    risk_level: str = "UNKNOWN",
    run_id: Optional[str] = None
) -> bool:
    """Notify on portfolio analysis completion."""
    title = f"📊 Portfolio Analysis ({mode})"
    message = (
        f"Total Value: ${total_value_usd:,.2f}\n"
        f"Cash: ${cash_usd:,.2f}\n"
        f"Holdings: {holdings_count}\n"
        f"Risk Level: {risk_level}"
    )
    
    return send_pushover(
        message=message,
        title=title,
        priority=0,
        run_id=run_id,
        action="portfolio_analysis"
    )


def notify_agent_response(
    intent: str,
    summary: str,
    run_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> bool:
    """Notify on any agent response (general notification)."""
    # Map intent to emoji
    emoji_map = {
        "PORTFOLIO_ANALYSIS": "📊",
        "TRADE_EXECUTION": "💹",
        "PORTFOLIO": "📈",
        "FINANCE_ANALYSIS": "📉",
        "GREETING": "👋",
        "CAPABILITIES_HELP": "❓",
    }
    emoji = emoji_map.get(intent, "🤖")
    
    title = f"{emoji} Agent Response"
    # Truncate summary if too long (Pushover limit is 1024 chars)
    message = summary[:500] if len(summary) > 500 else summary
    
    return send_pushover(
        message=message,
        title=title,
        priority=-1,  # Low priority for general responses
        run_id=run_id,
        conversation_id=conversation_id,
        action=f"response_{intent.lower()}"
    )


def record_skipped_notification(
    action: str,
    reason: str,
    run_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> None:
    """
    Record when a notification was intentionally skipped.
    
    This ensures all notification decisions are auditable.
    
    Args:
        action: Action type (portfolio_snapshot, trade_placed, etc.)
        reason: Human-readable reason for skipping
        run_id: Optional run ID
        conversation_id: Optional conversation ID
    """
    _record_notification_event(
        channel="pushover",
        status="skipped",
        action=action,
        run_id=run_id,
        conversation_id=conversation_id,
        payload_redacted={"reason": reason},
        error=None
    )
    logger.debug(f"Notification skipped for {action}: {reason}")


def notify_portfolio_failure(
    mode: str,
    error: str,
    run_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> bool:
    """
    Notify on portfolio analysis failure.
    
    Only sends for LIVE mode failures.
    """
    if mode != "LIVE":
        record_skipped_notification(
            action="portfolio_failure",
            reason=f"PAPER mode - notifications only sent for LIVE mode failures",
            run_id=run_id,
            conversation_id=conversation_id
        )
        return False
    
    title = "❌ Portfolio Analysis Failed"
    message = f"Mode: {mode}\nError: {error[:200]}"
    
    return send_pushover(
        message=message,
        title=title,
        priority=1,  # High priority for failures
        run_id=run_id,
        conversation_id=conversation_id,
        action="portfolio_failure"
    )


def notify_stock_ticket_created(
    symbol: str,
    side: str,
    notional_usd: float,
    ticket_id: str,
    run_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> bool:
    """
    Notify when an ASSISTED_LIVE stock order ticket is created.
    
    This is a high-priority notification since it requires manual action.
    
    Args:
        symbol: Stock symbol (e.g., AAPL)
        side: BUY or SELL
        notional_usd: Dollar amount
        ticket_id: Trade ticket ID
        run_id: Optional run ID
        conversation_id: Optional conversation ID
        
    Returns:
        True if notification sent successfully
    """
    title = "🎫 Stock Order Ticket Created"
    message = (
        f"{side.upper()} ${notional_usd:.2f} of {symbol}\n"
        f"MANUAL EXECUTION REQUIRED\n"
        f"Ticket: {ticket_id}\n"
        f"Execute in your brokerage and mark complete in the app."
    )
    
    return send_pushover(
        message=message,
        title=title,
        priority=1,  # High priority - requires action
        run_id=run_id,
        conversation_id=conversation_id,
        order_id=ticket_id,
        action="stock_ticket_created"
    )


def notify_stock_ticket_executed(
    symbol: str,
    side: str,
    notional_usd: float,
    ticket_id: str,
    filled_qty: Optional[float] = None,
    avg_price: Optional[float] = None,
    run_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> bool:
    """
    Notify when an ASSISTED_LIVE stock order ticket is marked as executed.
    
    Args:
        symbol: Stock symbol
        side: BUY or SELL
        notional_usd: Dollar amount
        ticket_id: Trade ticket ID
        filled_qty: Optional actual quantity filled
        avg_price: Optional average fill price
        run_id: Optional run ID
        conversation_id: Optional conversation ID
        
    Returns:
        True if notification sent successfully
    """
    title = "✅ Stock Order Executed"
    message = f"{side.upper()} ${notional_usd:.2f} of {symbol}\nTicket: {ticket_id}"
    
    if filled_qty is not None and avg_price is not None:
        message += f"\nFilled: {filled_qty:.4f} @ ${avg_price:.2f}"
    
    return send_pushover(
        message=message,
        title=title,
        priority=0,
        run_id=run_id,
        conversation_id=conversation_id,
        order_id=ticket_id,
        action="stock_ticket_executed"
    )

