"""Append-only durable event store for integration events."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from teleclaude.core.integration.events import (
    IntegrationEvent,
    IntegrationEventValidationError,
    compute_idempotency_key,
    integration_event_from_record,
    integration_event_to_record,
)


class IntegrationEventStoreError(RuntimeError):
    """Raised when the event store cannot preserve append-only guarantees."""


@dataclass(frozen=True)
class AppendResult:
    """Result of appending a candidate event."""

    status: Literal["appended", "duplicate"]
    event: IntegrationEvent


class IntegrationEventStore:
    """File-backed append-only event store with idempotency checks."""

    def __init__(self, event_log_path: Path) -> None:
        self._event_log_path = event_log_path
        self._events: list[IntegrationEvent] = []
        self._digest_by_idempotency_key: dict[str, str] = {}
        self._loaded = False

    @property
    def event_count(self) -> int:
        """Current number of persisted events."""
        self._ensure_loaded()
        return len(self._events)

    def replay(self) -> tuple[IntegrationEvent, ...]:
        """Return all events in append order."""
        self._ensure_loaded()
        return tuple(self._events)

    def append(self, event: IntegrationEvent) -> AppendResult:
        """Persist event to append-only log unless an idempotent duplicate exists."""
        self._ensure_loaded()
        event_digest = compute_idempotency_key(event.event_type, event.payload)
        existing_digest = self._digest_by_idempotency_key.get(event.idempotency_key)
        if existing_digest is not None:
            if existing_digest != event_digest:
                raise IntegrationEventStoreError(
                    f"idempotency key collision for {event.idempotency_key}: payload mismatch"
                )
            return AppendResult(status="duplicate", event=event)

        self._event_log_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(
            integration_event_to_record(event), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        with self._event_log_path.open("a", encoding="utf-8") as file_handle:
            file_handle.write(serialized)
            file_handle.write("\n")
            file_handle.flush()
            os.fsync(file_handle.fileno())

        self._events.append(event)
        self._digest_by_idempotency_key[event.idempotency_key] = event_digest
        return AppendResult(status="appended", event=event)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._event_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._event_log_path.touch(exist_ok=True)

        self._events.clear()
        self._digest_by_idempotency_key.clear()

        with self._event_log_path.open("r", encoding="utf-8") as file_handle:
            for line_number, raw_line in enumerate(file_handle, start=1):
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise IntegrationEventStoreError(
                        f"corrupt integration event log at line {line_number}: invalid JSON"
                    ) from exc
                if not isinstance(record, dict):
                    raise IntegrationEventStoreError(
                        f"corrupt integration event log at line {line_number}: expected object record"
                    )
                try:
                    event = integration_event_from_record(record)
                except IntegrationEventValidationError as exc:
                    raise IntegrationEventStoreError(
                        f"corrupt integration event log at line {line_number}: {'; '.join(exc.diagnostics)}"
                    ) from exc
                event_digest = compute_idempotency_key(event.event_type, event.payload)
                existing_digest = self._digest_by_idempotency_key.get(event.idempotency_key)
                if existing_digest is not None and existing_digest != event_digest:
                    raise IntegrationEventStoreError(
                        f"corrupt integration event log at line {line_number}: idempotency collision"
                    )
                self._events.append(event)
                self._digest_by_idempotency_key[event.idempotency_key] = event_digest
        self._loaded = True
