"""Date/time normalization helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


def ensure_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_iso_datetime(value: str) -> datetime | None:
    """Parse ISO datetime string, normalizing to UTC."""
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return ensure_utc(parsed)
    except ValueError:
        logger.warning("Failed to parse ISO datetime: %s", value)
        return None
