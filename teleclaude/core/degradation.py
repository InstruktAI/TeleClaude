"""The daemon's record of optional components that are not serving.

An optional component that fails keeps the daemon running without it. Its owner marks it here with the
reason and the act that resolves it, and clears the mark when the component serves again; the health
endpoint publishes the current marks so the daemon's status reports it degraded rather than healthy.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class DegradedComponent(StrEnum):
    """Optional daemon components whose failure degrades the daemon instead of stopping it."""

    WORKFLOW_STORE = "workflow-store"
    CHIPTUNES = "chiptunes"


@dataclass(frozen=True)
class Degradation:
    """One component, or one subject of it such as a project, that is not serving, and why."""

    component: DegradedComponent
    subject: str | None
    reason: str
    since: datetime


class DegradationRecord:
    """Current degradations, keyed by component and subject; safe to mark from worker threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[DegradedComponent, str | None], Degradation] = {}

    def mark(self, component: DegradedComponent, reason: str, *, subject: str | None = None) -> bool:
        """Record the component (or subject) as degraded; True when it was not degraded for this reason before.

        A repeated mark keeps its original time, so callers that meet the same failure on every pass log it once.
        """
        key = (component, subject)
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None and existing.reason == reason:
                return False
            since = existing.since if existing is not None else datetime.now(UTC)
            self._entries[key] = Degradation(component=component, subject=subject, reason=reason, since=since)
            return True

    def clear(self, component: DegradedComponent, *, subject: str | None = None) -> bool:
        """Remove the mark once the component (or subject) serves again; True when it had been degraded."""
        with self._lock:
            return self._entries.pop((component, subject), None) is not None

    def snapshot(self) -> tuple[Degradation, ...]:
        """The current degradations, oldest first."""
        with self._lock:
            return tuple(sorted(self._entries.values(), key=lambda entry: entry.since))


_record = DegradationRecord()


def get_degradations() -> DegradationRecord:
    """The process-wide degradation record."""
    return _record
