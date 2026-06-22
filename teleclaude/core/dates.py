"""Date/time normalization helpers."""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo

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
        dt = dt.replace(tzinfo=UTC)

    local_tz = get_local_timezone()
    local_dt = dt.astimezone(local_tz)

    if include_date:
        return local_dt.strftime("%Y-%m-%d %H:%M:%S")
    return local_dt.strftime("%H:%M:%S")


def ensure_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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


def normalize_task_schedule(value: str | None) -> str | None:
    """Normalize a task schedule value at the API boundary."""
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.startswith("cron:"):
        _validate_cron_schedule(raw)
        return raw
    parsed = parse_iso_datetime(raw)
    if parsed is None:
        raise ValueError("schedule must be an ISO-8601 datetime or cron:<minute hour day month weekday>")
    return parsed.isoformat()


def task_schedule_due(schedule: str | None, *, now: datetime | None = None) -> bool:
    """Return whether a normalized task schedule is due at ``now``."""
    if not schedule:
        return True
    current = ensure_utc(now or datetime.now(UTC))
    if schedule.startswith("cron:"):
        return _cron_schedule_matches(schedule, current)
    parsed = parse_iso_datetime(schedule)
    return parsed is not None and parsed <= current


def _validate_cron_schedule(value: str) -> None:
    fields = value.removeprefix("cron:").strip().split()
    if len(fields) != 5:
        raise ValueError("cron schedule must have five fields")
    for field, minimum, maximum in zip(fields, (0, 0, 1, 1, 0), (59, 23, 31, 12, 7), strict=True):
        _parse_cron_field(field, minimum=minimum, maximum=maximum)


def _cron_schedule_matches(value: str, current: datetime) -> bool:
    fields = value.removeprefix("cron:").strip().split()
    if len(fields) != 5:
        return False
    minute, hour, day, month, weekday = fields
    # Standard cron numbers weekdays with Sunday as 0; accept 7 as Sunday too.
    cron_weekday = (current.weekday() + 1) % 7
    return (
        current.minute in _parse_cron_field(minute, minimum=0, maximum=59)
        and current.hour in _parse_cron_field(hour, minimum=0, maximum=23)
        and current.day in _parse_cron_field(day, minimum=1, maximum=31)
        and current.month in _parse_cron_field(month, minimum=1, maximum=12)
        and cron_weekday in _parse_cron_weekday_field(weekday)
    )


def _parse_cron_weekday_field(field: str) -> set[int]:
    return {0 if value == 7 else value for value in _parse_cron_field(field, minimum=0, maximum=7)}


def _parse_cron_field(field: str, *, minimum: int, maximum: int) -> set[int]:
    if field == "*":
        return set(range(minimum, maximum + 1))
    values: set[int] = set()
    for raw_part in field.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError("cron schedule fields cannot contain empty segments")
        if not part.isdigit():
            raise ValueError(f"unsupported cron field segment: {part!r}")
        value = int(part)
        if value < minimum or value > maximum:
            raise ValueError(f"cron field segment {value} outside {minimum}-{maximum}")
        values.add(value)
    return values
