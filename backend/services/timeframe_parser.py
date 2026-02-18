"""Enterprise-grade timeframe parser for natural language time expressions.

Supports:
- Relative: "last 10 minutes", "past 24 hours", "last 7 weeks", "last 3 months"
- Anchored: "since Monday", "since 2026-02-01", "YTD", "MTD", "QTD"
- Bounded: "between Jan 2 and Feb 5", "from 2025-12-01 to 2025-12-08"
- Defaults: if timeframe omitted -> default 24h with parse_notes

All timestamps are resolved using SERVER time (UTC).
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from enum import Enum

from backend.core.logging import get_logger

logger = get_logger(__name__)


class Granularity(str, Enum):
    """Candle granularity options."""
    ONE_MINUTE = "1m"
    FIVE_MINUTE = "5m"
    FIFTEEN_MINUTE = "15m"
    ONE_HOUR = "1h"
    FOUR_HOUR = "4h"
    ONE_DAY = "1d"


@dataclass
class TimeWindow:
    """Structured timeframe result."""
    start_ts_utc: str  # ISO format
    end_ts_utc: str    # ISO format
    label: str         # Human-readable label (e.g., "10m", "24h", "2026-01-02 to 2026-02-05")
    granularity: Granularity
    source: str = "server_time"
    parse_confidence: float = 1.0  # 0-1, lower if defaulted or ambiguous
    parse_notes: Optional[str] = None
    lookback_hours: float = 24.0  # For backward compatibility
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_ts_utc": self.start_ts_utc,
            "end_ts_utc": self.end_ts_utc,
            "label": self.label,
            "granularity": self.granularity.value,
            "source": self.source,
            "parse_confidence": self.parse_confidence,
            "parse_notes": self.parse_notes,
            "lookback_hours": self.lookback_hours,
        }


@dataclass
class ParseResult:
    """Result of timeframe parsing."""
    success: bool
    time_window: Optional[TimeWindow] = None
    error_message: Optional[str] = None
    raw_match: Optional[str] = None


# Day name mapping
WEEKDAY_MAP = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

# Month name mapping
MONTH_MAP = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def _get_granularity(hours: float) -> Granularity:
    """Determine optimal granularity based on time window."""
    if hours <= 1:
        return Granularity.ONE_MINUTE
    elif hours <= 6:
        return Granularity.FIVE_MINUTE
    elif hours <= 24:
        return Granularity.FIFTEEN_MINUTE
    elif hours <= 168:  # 1 week
        return Granularity.ONE_HOUR
    elif hours <= 720:  # 30 days
        return Granularity.FOUR_HOUR
    else:
        return Granularity.ONE_DAY


def _format_label(hours: float, start_dt: datetime, end_dt: datetime) -> str:
    """Generate human-readable label for time window."""
    if hours < 1:
        return f"{int(hours * 60)}m"
    elif hours < 24:
        return f"{int(hours)}h"
    elif hours < 168:
        days = hours / 24
        if days == int(days):
            return f"{int(days)}d"
        return f"{hours}h"
    elif hours < 720:
        weeks = hours / 168
        if weeks == int(weeks):
            return f"{int(weeks)}w"
        return f"{int(hours / 24)}d"
    else:
        # Show date range
        return f"{start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}"


def _parse_relative(text: str, now: datetime) -> Optional[Tuple[datetime, datetime, str, float]]:
    """Parse relative time expressions like 'last 10 minutes', 'past 24 hours'."""
    # Pattern: [last|past|previous] X [unit]
    pattern = r'(?:last|past|previous)\s+(\d+)\s*(min(?:ute)?s?|m|hours?|h|days?|d|weeks?|w|months?|mo|years?|y)\b'
    match = re.search(pattern, text.lower())
    
    if not match:
        # Try without prefix: "10 minutes ago", "24 hours"
        pattern2 = r'(\d+)\s*(min(?:ute)?s?|m|hours?|h|days?|d|weeks?|w|months?|mo|years?|y)\s*(?:ago)?\b'
        match = re.search(pattern2, text.lower())
    
    if match:
        value = int(match.group(1))
        unit = match.group(2).lower()
        
        # Convert to hours
        if unit.startswith('min') or unit == 'm':
            hours = max(0.1, value / 60.0)
        elif unit.startswith('hour') or unit == 'h':
            hours = float(value)
        elif unit.startswith('day') or unit == 'd':
            hours = float(value * 24)
        elif unit.startswith('week') or unit == 'w':
            hours = float(value * 24 * 7)
        elif unit.startswith('month') or unit == 'mo':
            hours = float(value * 24 * 30)  # Approximate
        elif unit.startswith('year') or unit == 'y':
            hours = float(value * 24 * 365)  # Approximate
        else:
            return None
        
        start = now - timedelta(hours=hours)
        return (start, now, match.group(0), hours)
    
    return None


def _parse_anchored(text: str, now: datetime) -> Optional[Tuple[datetime, datetime, str, float]]:
    """Parse anchored time expressions like 'since Monday', 'since 2026-02-01', 'YTD'."""
    text_lower = text.lower()
    
    # YTD (Year to Date)
    if 'ytd' in text_lower or 'year to date' in text_lower:
        start = datetime(now.year, 1, 1)
        hours = (now - start).total_seconds() / 3600
        return (start, now, "YTD", hours)
    
    # MTD (Month to Date)
    if 'mtd' in text_lower or 'month to date' in text_lower:
        start = datetime(now.year, now.month, 1)
        hours = (now - start).total_seconds() / 3600
        return (start, now, "MTD", hours)
    
    # QTD (Quarter to Date)
    if 'qtd' in text_lower or 'quarter to date' in text_lower:
        quarter_start_month = ((now.month - 1) // 3) * 3 + 1
        start = datetime(now.year, quarter_start_month, 1)
        hours = (now - start).total_seconds() / 3600
        return (start, now, "QTD", hours)
    
    # Since weekday: "since Monday", "since last Tuesday"
    since_weekday = re.search(r'since\s+(?:last\s+)?(\w+day|\w{3})\b', text_lower)
    if since_weekday:
        day_name = since_weekday.group(1).lower()
        if day_name in WEEKDAY_MAP:
            target_weekday = WEEKDAY_MAP[day_name]
            current_weekday = now.weekday()
            days_ago = (current_weekday - target_weekday) % 7
            if days_ago == 0:
                days_ago = 7  # "since Monday" on Monday means last Monday
            start = now - timedelta(days=days_ago)
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            hours = (now - start).total_seconds() / 3600
            return (start, now, f"since {day_name.capitalize()}", hours)
    
    # Since date: "since 2026-02-01", "since Feb 1", "since February 1"
    # ISO format
    since_iso = re.search(r'since\s+(\d{4})-(\d{1,2})-(\d{1,2})', text_lower)
    if since_iso:
        try:
            year = int(since_iso.group(1))
            month = int(since_iso.group(2))
            day = int(since_iso.group(3))
            start = datetime(year, month, day)
            hours = (now - start).total_seconds() / 3600
            return (start, now, f"since {year}-{month:02d}-{day:02d}", hours)
        except ValueError:
            pass
    
    # Since month day: "since Feb 1", "since February 1st"
    since_month_day = re.search(r'since\s+(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?', text_lower)
    if since_month_day:
        month_name = since_month_day.group(1).lower()
        day = int(since_month_day.group(2))
        if month_name in MONTH_MAP:
            month = MONTH_MAP[month_name]
            year = now.year
            # If the date is in the future, use last year
            try:
                start = datetime(year, month, day)
                if start > now:
                    start = datetime(year - 1, month, day)
                hours = (now - start).total_seconds() / 3600
                return (start, now, f"since {month_name.capitalize()} {day}", hours)
            except ValueError:
                pass
    
    return None


def _parse_bounded(text: str, now: datetime) -> Optional[Tuple[datetime, datetime, str, float]]:
    """Parse bounded time expressions like 'between Jan 2 and Feb 5', 'from 2025-12-01 to 2025-12-08'."""
    text_lower = text.lower()
    
    # Between pattern: "between Jan 2 and Feb 5"
    between_pattern = re.search(
        r'between\s+(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?\s+and\s+(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?',
        text_lower
    )
    if between_pattern:
        start_month_name = between_pattern.group(1).lower()
        start_day = int(between_pattern.group(2))
        end_month_name = between_pattern.group(3).lower()
        end_day = int(between_pattern.group(4))
        
        if start_month_name in MONTH_MAP and end_month_name in MONTH_MAP:
            start_month = MONTH_MAP[start_month_name]
            end_month = MONTH_MAP[end_month_name]
            year = now.year
            
            try:
                start = datetime(year, start_month, start_day)
                end = datetime(year, end_month, end_day, 23, 59, 59)
                
                # Handle year boundary
                if start > end:
                    start = datetime(year - 1, start_month, start_day)
                if end > now:
                    # If end is in future, adjust to now or use previous year
                    end = min(end, now)
                
                hours = (end - start).total_seconds() / 3600
                label = f"{start_month_name.capitalize()} {start_day} to {end_month_name.capitalize()} {end_day}"
                return (start, end, label, hours)
            except ValueError:
                pass
    
    # ISO date range: "from 2025-12-01 to 2025-12-08"
    from_to_iso = re.search(
        r'(?:from\s+)?(\d{4})-(\d{1,2})-(\d{1,2})\s+(?:to|through|until)\s+(\d{4})-(\d{1,2})-(\d{1,2})',
        text_lower
    )
    if from_to_iso:
        try:
            start = datetime(
                int(from_to_iso.group(1)),
                int(from_to_iso.group(2)),
                int(from_to_iso.group(3))
            )
            end = datetime(
                int(from_to_iso.group(4)),
                int(from_to_iso.group(5)),
                int(from_to_iso.group(6)),
                23, 59, 59
            )
            if end > now:
                end = now
            hours = (end - start).total_seconds() / 3600
            label = f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}"
            return (start, end, label, hours)
        except ValueError:
            pass
    
    # Between ISO dates: "between 2025-12-01 and 2025-12-08"
    between_iso = re.search(
        r'between\s+(\d{4})-(\d{1,2})-(\d{1,2})\s+and\s+(\d{4})-(\d{1,2})-(\d{1,2})',
        text_lower
    )
    if between_iso:
        try:
            start = datetime(
                int(between_iso.group(1)),
                int(between_iso.group(2)),
                int(between_iso.group(3))
            )
            end = datetime(
                int(between_iso.group(4)),
                int(between_iso.group(5)),
                int(between_iso.group(6)),
                23, 59, 59
            )
            if end > now:
                end = now
            hours = (end - start).total_seconds() / 3600
            label = f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}"
            return (start, end, label, hours)
        except ValueError:
            pass
    
    return None


def parse_timeframe(text: str, default_hours: float = 24.0) -> ParseResult:
    """
    Parse natural language timeframe into structured TimeWindow.
    
    Supports:
    - Relative: "last 10 minutes", "past 24 hours", "last 7 weeks", "last 3 months"
    - Anchored: "since Monday", "since 2026-02-01", "YTD", "MTD", "QTD"
    - Bounded: "between Jan 2 and Feb 5", "from 2025-12-01 to 2025-12-08"
    
    Args:
        text: User input text
        default_hours: Default lookback if no timeframe found (default 24h)
    
    Returns:
        ParseResult with TimeWindow or error
    """
    now = datetime.utcnow()
    
    # Try parsing in order of specificity
    # 1. Bounded (most specific)
    result = _parse_bounded(text, now)
    if result:
        start, end, raw_match, hours = result
        return ParseResult(
            success=True,
            time_window=TimeWindow(
                start_ts_utc=start.isoformat() + "Z",
                end_ts_utc=end.isoformat() + "Z",
                label=_format_label(hours, start, end),
                granularity=_get_granularity(hours),
                parse_confidence=1.0,
                lookback_hours=hours,
            ),
            raw_match=raw_match,
        )
    
    # 2. Anchored
    result = _parse_anchored(text, now)
    if result:
        start, end, raw_match, hours = result
        return ParseResult(
            success=True,
            time_window=TimeWindow(
                start_ts_utc=start.isoformat() + "Z",
                end_ts_utc=end.isoformat() + "Z",
                label=raw_match,
                granularity=_get_granularity(hours),
                parse_confidence=1.0,
                lookback_hours=hours,
            ),
            raw_match=raw_match,
        )
    
    # 3. Relative
    result = _parse_relative(text, now)
    if result:
        start, end, raw_match, hours = result
        return ParseResult(
            success=True,
            time_window=TimeWindow(
                start_ts_utc=start.isoformat() + "Z",
                end_ts_utc=end.isoformat() + "Z",
                label=_format_label(hours, start, end),
                granularity=_get_granularity(hours),
                parse_confidence=1.0,
                lookback_hours=hours,
            ),
            raw_match=raw_match,
        )
    
    # 4. Default fallback
    start = now - timedelta(hours=default_hours)
    return ParseResult(
        success=True,
        time_window=TimeWindow(
            start_ts_utc=start.isoformat() + "Z",
            end_ts_utc=now.isoformat() + "Z",
            label=_format_label(default_hours, start, now),
            granularity=_get_granularity(default_hours),
            parse_confidence=0.5,
            parse_notes=f"No timeframe specified, defaulted to {int(default_hours)}h",
            lookback_hours=default_hours,
        ),
        raw_match=None,
    )


def emit_timeframe_parse_telemetry(
    result: ParseResult,
    user_input: str,
) -> None:
    """Emit telemetry for timeframe parsing."""
    try:
        from backend.evals.runtime_evals import emit_runtime_metric
        
        metric_data = {
            "success": result.success,
            "raw_match": result.raw_match,
            "user_input_length": len(user_input),
        }
        
        if result.time_window:
            metric_data.update({
                "parse_confidence": result.time_window.parse_confidence,
                "lookback_hours": result.time_window.lookback_hours,
                "granularity": result.time_window.granularity.value,
                "defaulted": result.time_window.parse_notes is not None,
            })
        
        if result.success and result.time_window and result.time_window.parse_confidence >= 0.9:
            emit_runtime_metric("timeframe_parse_success", metric_data)
        elif result.success and result.time_window:
            emit_runtime_metric("timeframe_parse_defaulted", metric_data)
        else:
            emit_runtime_metric("timeframe_parse_failed", metric_data)
            
    except Exception as e:
        logger.debug(f"Failed to emit timeframe parse telemetry: {e}")
