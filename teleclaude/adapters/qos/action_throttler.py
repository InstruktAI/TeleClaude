"""Lightweight throttling for adapter control actions."""

from __future__ import annotations


class AdapterActionThrottler:
    """Track the last attempt time for adapter control actions.

    The throttler is intentionally state-light: callers provide a stable action
    key, and repeated attempts inside the configured interval are dropped.
    """

    def __init__(self) -> None:
        self._last_attempt_at: dict[str, float] = {}

    def allow(self, key: str, *, min_interval_s: float, now: float) -> bool:
        """Return True when the action should be attempted now."""
        if min_interval_s <= 0:
            self._last_attempt_at[key] = now
            return True

        previous = self._last_attempt_at.get(key)
        if previous is not None and (now - previous) < min_interval_s:
            return False

        self._last_attempt_at[key] = now
        return True

    def clear(self) -> None:
        """Drop all recorded action timestamps."""
        self._last_attempt_at.clear()
