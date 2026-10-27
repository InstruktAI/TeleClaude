"""Read what GitHub's response headers say about the request budget."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

_LIMIT_HEADER = "x-ratelimit-limit"
_REMAINING_HEADER = "x-ratelimit-remaining"
_RESET_HEADER = "x-ratelimit-reset"
_RETRY_AFTER_HEADER = "retry-after"
_EXHAUSTED = "0"


@dataclass(frozen=True)
class RateReading:
    """The budget an installation's latest response left, and when it was read."""

    limit: int | None
    remaining: int
    reset_at: datetime | None
    observed_at: datetime


def read_rate_reading(headers: Mapping[str, str], observed_at: datetime) -> RateReading | None:
    """Read the remaining count, limit and reset time a response names; None when it names no remaining count."""
    remaining = _integer(headers.get(_REMAINING_HEADER))
    if remaining is None:
        return None
    reset = _integer(headers.get(_RESET_HEADER))
    return RateReading(
        limit=_integer(headers.get(_LIMIT_HEADER)),
        remaining=remaining,
        reset_at=datetime.fromtimestamp(reset, UTC) if reset is not None else None,
        observed_at=observed_at,
    )


def named_resume_time(headers: Mapping[str, str], now: datetime) -> datetime | None:
    """The time a limit response says requests may resume: its retry delay, else its reset when exhausted.

    None when the response names no time; callers then apply their own waiting rule.
    """
    retry_after = headers.get(_RETRY_AFTER_HEADER)
    if retry_after is not None:
        seconds = _integer(retry_after)
        if seconds is not None:
            return now + timedelta(seconds=seconds)
        try:
            return parsedate_to_datetime(retry_after).astimezone(UTC)
        except (TypeError, ValueError):
            return None
    if headers.get(_REMAINING_HEADER) == _EXHAUSTED:
        reset = _integer(headers.get(_RESET_HEADER))
        return datetime.fromtimestamp(reset, UTC) if reset is not None else None
    return None


def _integer(value: str | None) -> int | None:
    if value is None or not value.isascii() or not value.isdecimal():
        return None
    return int(value)
