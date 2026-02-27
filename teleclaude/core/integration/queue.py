"""Durable FIFO queue for integration readiness candidates."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict

from teleclaude.core.integration.readiness_projection import CandidateKey

QueueStatus = Literal["queued", "in_progress", "integrated", "blocked", "superseded"]
_RECOVERY_REQUEUE_REASON = "requeued after runtime restart"
_ALLOWED_STATUS_TRANSITIONS: dict[QueueStatus, frozenset[QueueStatus]] = {
    "queued": frozenset({"in_progress"}),
    "in_progress": frozenset({"queued", "integrated", "blocked", "superseded"}),
    "integrated": frozenset(),
    "blocked": frozenset({"queued"}),
    "superseded": frozenset(),
}


class IntegrationQueueError(RuntimeError):
    """Raised when queue state cannot be loaded or persisted."""


@dataclass(frozen=True)
class QueueItem:
    """Current queue state for one candidate."""

    key: CandidateKey
    ready_at: str
    status: QueueStatus
    status_updated_at: str
    status_reason: str | None


@dataclass(frozen=True)
class QueueTransition:
    """Auditable queue status transition."""

    key: CandidateKey
    from_status: QueueStatus | None
    to_status: QueueStatus
    transitioned_at: str
    reason: str | None


class _QueueItemPayload(TypedDict):
    slug: str
    branch: str
    sha: str
    ready_at: str
    status: QueueStatus
    status_updated_at: str
    status_reason: str | None


class _QueueTransitionPayload(TypedDict):
    slug: str
    branch: str
    sha: str
    from_status: QueueStatus | None
    to_status: QueueStatus
    transitioned_at: str
    reason: str | None


class _QueueStatePayload(TypedDict):
    version: int
    items: list[_QueueItemPayload]
    transitions: list[_QueueTransitionPayload]


class IntegrationQueue:
    """File-backed candidate queue with durable transition audit log."""

    def __init__(self, *, state_path: Path) -> None:
        self._state_path = state_path
        self._items_by_key: dict[CandidateKey, QueueItem] = {}
        self._transitions: list[QueueTransition] = []
        self._load_state()
        self._recover_in_progress_items()

    @property
    def state_path(self) -> Path:
        """Return durable queue state path."""
        return self._state_path

    def enqueue(self, *, key: CandidateKey, ready_at: str, now: datetime | None = None) -> QueueItem:
        """Enqueue candidate when absent; preserves first-seen FIFO ordering input."""
        self._validate_iso8601(ready_at)
        existing = self._items_by_key.get(key)
        if existing is not None:
            return existing

        changed_at = _format_timestamp(_resolve_now(now))
        queued = QueueItem(
            key=key,
            ready_at=ready_at,
            status="queued",
            status_updated_at=changed_at,
            status_reason="candidate became READY",
        )
        self._items_by_key[key] = queued
        self._transitions.append(
            QueueTransition(
                key=key,
                from_status=None,
                to_status="queued",
                transitioned_at=changed_at,
                reason="candidate became READY",
            )
        )
        self._persist_state()
        return queued

    def pop_next(self, *, now: datetime | None = None) -> QueueItem | None:
        """Mark the next FIFO candidate as in-progress and return it."""
        queued = [item for item in self._items_by_key.values() if item.status == "queued"]
        if not queued:
            return None

        queued.sort(
            key=lambda item: (
                _parse_timestamp(item.ready_at),
                item.key.slug,
                item.key.branch,
                item.key.sha,
            )
        )
        target = queued[0]
        updated = self._set_status(
            key=target.key,
            to_status="in_progress",
            reason="dequeued for processing",
            now=now,
        )
        return updated

    def mark_integrated(
        self, *, key: CandidateKey, reason: str = "shadow integration simulated", now: datetime | None = None
    ) -> None:
        """Mark candidate as integrated by shadow simulation."""
        self._set_status(key=key, to_status="integrated", reason=reason, now=now)

    def mark_blocked(self, *, key: CandidateKey, reason: str, now: datetime | None = None) -> None:
        """Mark candidate as blocked during processing."""
        self._set_status(key=key, to_status="blocked", reason=reason, now=now)

    def mark_superseded(self, *, key: CandidateKey, reason: str, now: datetime | None = None) -> None:
        """Mark candidate as superseded by newer readiness."""
        self._set_status(key=key, to_status="superseded", reason=reason, now=now)

    def resume_blocked(self, *, key: CandidateKey, reason: str, now: datetime | None = None) -> None:
        """Re-queue a blocked candidate after remediation and readiness re-check."""
        self._set_status(key=key, to_status="queued", reason=reason, now=now)

    def get(self, *, key: CandidateKey) -> QueueItem | None:
        """Get queue state for one candidate key."""
        return self._items_by_key.get(key)

    def items(self) -> tuple[QueueItem, ...]:
        """Return all queue items in stable sort order."""
        return tuple(
            sorted(
                self._items_by_key.values(),
                key=lambda item: (
                    _parse_timestamp(item.ready_at),
                    item.key.slug,
                    item.key.branch,
                    item.key.sha,
                ),
            )
        )

    def transitions(self) -> tuple[QueueTransition, ...]:
        """Return transition history in append order."""
        return tuple(self._transitions)

    def _set_status(
        self,
        *,
        key: CandidateKey,
        to_status: QueueStatus,
        reason: str,
        now: datetime | None,
    ) -> QueueItem:
        item = self._items_by_key.get(key)
        if item is None:
            raise IntegrationQueueError(
                f"cannot transition unknown candidate {key.slug}/{key.branch}@{key.sha} to {to_status}"
            )

        if item.status == to_status and item.status_reason == reason:
            return item

        allowed_targets = _ALLOWED_STATUS_TRANSITIONS[item.status]
        if to_status not in allowed_targets:
            raise IntegrationQueueError(
                f"invalid queue transition {item.status}->{to_status} for candidate {key.slug}/{key.branch}@{key.sha}"
            )
        if item.status == "in_progress" and to_status == "queued" and reason != _RECOVERY_REQUEUE_REASON:
            raise IntegrationQueueError(f"invalid queue transition reason for in_progress->queued: {reason!r}")

        changed_at = _format_timestamp(_resolve_now(now))
        updated = QueueItem(
            key=item.key,
            ready_at=item.ready_at,
            status=to_status,
            status_updated_at=changed_at,
            status_reason=reason,
        )
        self._items_by_key[key] = updated
        self._transitions.append(
            QueueTransition(
                key=key,
                from_status=item.status,
                to_status=to_status,
                transitioned_at=changed_at,
                reason=reason,
            )
        )
        self._persist_state()
        return updated

    def _recover_in_progress_items(self) -> None:
        """Re-queue interrupted in-progress items after restart."""
        in_progress_keys = [key for key, item in self._items_by_key.items() if item.status == "in_progress"]
        if not in_progress_keys:
            return

        resumed_at = _format_timestamp(datetime.now(tz=UTC))
        for key in in_progress_keys:
            item = self._items_by_key[key]
            queued = QueueItem(
                key=item.key,
                ready_at=item.ready_at,
                status="queued",
                status_updated_at=resumed_at,
                status_reason=_RECOVERY_REQUEUE_REASON,
            )
            self._items_by_key[key] = queued
            self._transitions.append(
                QueueTransition(
                    key=key,
                    from_status="in_progress",
                    to_status="queued",
                    transitioned_at=resumed_at,
                    reason=_RECOVERY_REQUEUE_REASON,
                )
            )

        self._persist_state()

    def _load_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._state_path.exists():
            return

        raw_text = self._state_path.read_text(encoding="utf-8")
        if not raw_text.strip():
            return

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise IntegrationQueueError(f"invalid queue state JSON: {self._state_path}") from exc

        if not isinstance(payload, dict):
            raise IntegrationQueueError("queue state payload must be an object")

        raw_items = payload.get("items")
        raw_transitions = payload.get("transitions")
        if raw_items is None:
            raw_items = []
        if raw_transitions is None:
            raw_transitions = []
        if not isinstance(raw_items, list):
            raise IntegrationQueueError("queue state field 'items' must be a list")
        if not isinstance(raw_transitions, list):
            raise IntegrationQueueError("queue state field 'transitions' must be a list")

        self._items_by_key.clear()
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise IntegrationQueueError("queue item must be an object")
            item = _item_from_payload(raw_item)
            self._items_by_key[item.key] = item

        self._transitions.clear()
        for raw_transition in raw_transitions:
            if not isinstance(raw_transition, dict):
                raise IntegrationQueueError("queue transition must be an object")
            transition = _transition_from_payload(raw_transition)
            self._transitions.append(transition)

    def _persist_state(self) -> None:
        payload: _QueueStatePayload = {
            "version": 1,
            "items": [_item_to_payload(item) for item in self.items()],
            "transitions": [_transition_to_payload(item) for item in self._transitions],
        }
        serialized = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
        temp_path = self._state_path.with_suffix(f"{self._state_path.suffix}.tmp")

        with temp_path.open("w", encoding="utf-8") as file_handle:
            file_handle.write(serialized)
            file_handle.flush()
            os.fsync(file_handle.fileno())

        os.replace(temp_path, self._state_path)

    def _validate_iso8601(self, value: str) -> None:
        _parse_timestamp(value)


def _item_from_payload(payload: dict[object, object]) -> QueueItem:
    key = _candidate_key_from_payload(payload)
    ready_at = _required_str(payload, "ready_at")
    status = _status_from_value(payload.get("status"))
    status_updated_at = _required_str(payload, "status_updated_at")
    status_reason = _optional_str(payload.get("status_reason"), field_name="status_reason")
    _parse_timestamp(ready_at)
    _parse_timestamp(status_updated_at)
    return QueueItem(
        key=key,
        ready_at=ready_at,
        status=status,
        status_updated_at=status_updated_at,
        status_reason=status_reason,
    )


def _transition_from_payload(payload: dict[object, object]) -> QueueTransition:
    key = _candidate_key_from_payload(payload)
    from_status = _optional_status_from_value(payload.get("from_status"))
    to_status = _status_from_value(payload.get("to_status"))
    transitioned_at = _required_str(payload, "transitioned_at")
    reason = _optional_str(payload.get("reason"), field_name="reason")
    _parse_timestamp(transitioned_at)
    return QueueTransition(
        key=key,
        from_status=from_status,
        to_status=to_status,
        transitioned_at=transitioned_at,
        reason=reason,
    )


def _item_to_payload(item: QueueItem) -> _QueueItemPayload:
    return {
        "slug": item.key.slug,
        "branch": item.key.branch,
        "sha": item.key.sha,
        "ready_at": item.ready_at,
        "status": item.status,
        "status_updated_at": item.status_updated_at,
        "status_reason": item.status_reason,
    }


def _transition_to_payload(item: QueueTransition) -> _QueueTransitionPayload:
    return {
        "slug": item.key.slug,
        "branch": item.key.branch,
        "sha": item.key.sha,
        "from_status": item.from_status,
        "to_status": item.to_status,
        "transitioned_at": item.transitioned_at,
        "reason": item.reason,
    }


def _candidate_key_from_payload(payload: dict[object, object]) -> CandidateKey:
    slug = _required_str(payload, "slug")
    branch = _required_str(payload, "branch")
    sha = _required_str(payload, "sha")
    return CandidateKey(slug=slug, branch=branch, sha=sha)


def _required_str(payload: dict[object, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise IntegrationQueueError(f"field {field_name!r} must be a non-empty string")
    return value


def _optional_str(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise IntegrationQueueError(f"field {field_name!r} must be a string or null")
    return value


def _status_from_value(value: object) -> QueueStatus:
    allowed: tuple[QueueStatus, ...] = ("queued", "in_progress", "integrated", "blocked", "superseded")
    if value not in allowed:
        raise IntegrationQueueError(f"invalid queue status {value!r}")
    return value


def _optional_status_from_value(value: object) -> QueueStatus | None:
    if value is None:
        return None
    return _status_from_value(value)


def _resolve_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(tz=UTC)
    if now.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return now.astimezone(UTC)


def _parse_timestamp(raw_value: str) -> datetime:
    normalized = raw_value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise IntegrationQueueError(f"timestamp must include timezone offset: {raw_value!r}")
    return parsed.astimezone(UTC)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")
