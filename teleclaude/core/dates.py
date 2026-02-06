"""Date/time normalization helpers."""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


def get_local_timezone() -> tzinfo:
    """Get system's local timezone."""
    local_tz = datetime.now().astimezone().tzinfo
    assert local_tz is not None  # Always set by astimezone()
    return local_tz


def format_local_datetime(dt: datetime, *, include_date: bool = False) -> str:
    """Format datetime for user display in local timezone.

    Args:
        dt: datetime (UTC or timezone-aware)
        include_date: Include date if True, otherwise just time

    Returns:
        Formatted string like "14:25:33" or "2025-02-03 14:25:33"
    """
    # Ensure timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    local_tz = get_local_timezone()
    local_dt = dt.astimezone(local_tz)

    if include_date:
        return local_dt.strftime("%Y-%m-%d %H:%M:%S")
    return local_dt.strftime("%H:%M:%S")


def ensure_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_iso_datetime(value: object) -> datetime | None:
    """Parse ISO datetime string, normalizing to UTC.

    Handles string inputs, datetime objects (normalized to UTC),
    and returns None for other types.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return ensure_utc(value)

    if not isinstance(value, str):
        logger.warning("Attempted to parse non-string datetime: %s (type: %s)", value, type(value))
        return None

    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return ensure_utc(parsed)
    except ValueError:
        logger.warning("Failed to parse ISO datetime string: %s", value)
        return None
