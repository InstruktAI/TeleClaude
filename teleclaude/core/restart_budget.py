"""Sliding-window restart budget shared by every component that restarts a long-lived unit."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RestartCharge:
    """One restart attempt charged against a budget window."""

    attempt: int
    within_budget: bool


class RestartBudget:
    """Counts restart attempts in a sliding window and reports when the window's allowance is spent.

    The window opens at the first attempt and resets once an attempt arrives after it has elapsed.
    An attempt is within budget while its count in the current window does not exceed the maximum.
    """

    def __init__(self, *, max_restarts: int, window_s: float, backoff_s: float) -> None:
        self.max_restarts = max_restarts
        self.window_s = window_s
        self.backoff_s = backoff_s
        self._window_start: float | None = None
        self._attempts = 0

    def charge(self, now: float) -> RestartCharge:
        """Charge one restart attempt at monotonic time `now`."""
        if self._window_start is None or (now - self._window_start) > self.window_s:
            self._window_start = now
            self._attempts = 0
        self._attempts += 1
        return RestartCharge(attempt=self._attempts, within_budget=self._attempts <= self.max_restarts)
