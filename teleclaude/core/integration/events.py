"""Canonical integration event contracts and validation."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal, Mapping, TypedDict, cast

IntegrationEventType = Literal["review_approved", "finalize_ready", "branch_pushed"]


class ReviewApprovedPayload(TypedDict):
    """Payload for `review_approved`."""

    slug: str
    approved_at: str
    review_round: int
    reviewer_session_id: str


class FinalizeReadyPayload(TypedDict):
    """Payload for `finalize_ready`."""

    slug: str
    branch: str
    sha: str
    worker_session_id: str
    orchestrator_session_id: str
    ready_at: str


class BranchPushedPayload(TypedDict):
    """Payload for `branch_pushed`."""

    branch: str
    sha: str
    remote: str
    pushed_at: str
    pusher: str


IntegrationEventPayload = ReviewApprovedPayload | FinalizeReadyPayload | BranchPushedPayload


class IntegrationEventRecord(TypedDict):
    """Serialized integration event record for durable storage."""

    event_id: str
    event_type: IntegrationEventType
    payload: IntegrationEventPayload
    received_at: str
    idempotency_key: str


_REQUIRED_FIELDS: Mapping[IntegrationEventType, tuple[str, ...]] = MappingProxyType(
    {
        "review_approved": ("slug", "approved_at", "review_round", "reviewer_session_id"),
        "finalize_ready": ("slug", "branch", "sha", "worker_session_id", "orchestrator_session_id", "ready_at"),
        "branch_pushed": ("branch", "sha", "remote", "pushed_at", "pusher"),
    }
)

_TIMESTAMP_FIELDS: Mapping[IntegrationEventType, str] = MappingProxyType(
    {"review_approved": "approved_at", "finalize_ready": "ready_at", "branch_pushed": "pushed_at"}
)


class IntegrationEventValidationError(ValueError):
    """Raised when a candidate integration event payload is invalid."""

    def __init__(self, event_type: str, diagnostics: list[str]) -> None:
        message = f"Invalid integration event '{event_type}': " + "; ".join(diagnostics)
        super().__init__(message)
        self.event_type = event_type
        self.diagnostics = tuple(diagnostics)


@dataclass(frozen=True)
class IntegrationEvent:
    """Canonical persisted integration event."""

    event_id: str
    event_type: IntegrationEventType
    payload: IntegrationEventPayload
    received_at: str
    idempotency_key: str


def parse_event_type(raw_event_type: str) -> IntegrationEventType:
    """Validate and narrow a raw event type to the canonical set."""
    if raw_event_type not in _REQUIRED_FIELDS:
        raise IntegrationEventValidationError(
            raw_event_type,
            [f"unsupported event_type '{raw_event_type}' (allowed: {sorted(_REQUIRED_FIELDS)})"],
        )
    return cast(IntegrationEventType, raw_event_type)


def compute_idempotency_key(event_type: IntegrationEventType, payload: IntegrationEventPayload) -> str:
    """Compute deterministic idempotency key from canonical event contents."""
    canonical = json.dumps(
        {"event_type": event_type, "payload": payload},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_integration_event(
    event_type: IntegrationEventType,
    payload: Mapping[str, object],
    *,
    idempotency_key: str | None = None,
    event_id: str | None = None,
    received_at: str | None = None,
) -> IntegrationEvent:
    """Validate raw input and produce a canonical integration event."""
    validated_payload = validate_event_payload(event_type, payload)

    resolved_received_at = (
        _normalize_iso8601(event_type, "received_at", received_at)
        if received_at is not None
        else datetime.now(tz=UTC).isoformat(timespec="seconds")
    )
    resolved_event_id = event_id if event_id is not None else str(uuid.uuid4())
    resolved_idempotency_key = (
        idempotency_key.strip()
        if idempotency_key is not None
        else compute_idempotency_key(event_type, validated_payload)
    )
    if not resolved_idempotency_key:
        raise IntegrationEventValidationError(event_type, ["idempotency_key must be a non-empty string"])
    if not resolved_event_id:
        raise IntegrationEventValidationError(event_type, ["event_id must be a non-empty string"])

    return IntegrationEvent(
        event_id=resolved_event_id,
        event_type=event_type,
        payload=validated_payload,
        received_at=resolved_received_at,
        idempotency_key=resolved_idempotency_key,
    )


def validate_event_payload(event_type: IntegrationEventType, payload: Mapping[str, object]) -> IntegrationEventPayload:
    """Validate canonical payload contract for one integration event."""
    diagnostics = _validate_field_set(event_type, payload)

    if event_type == "review_approved":
        return _validate_review_approved(payload, diagnostics)
    if event_type == "finalize_ready":
        return _validate_finalize_ready(payload, diagnostics)
    return _validate_branch_pushed(payload, diagnostics)


def integration_event_to_record(event: IntegrationEvent) -> IntegrationEventRecord:
    """Convert event to JSON-serializable record."""
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "payload": event.payload,
        "received_at": event.received_at,
        "idempotency_key": event.idempotency_key,
    }


def integration_event_from_record(record: Mapping[str, object]) -> IntegrationEvent:
    """Build canonical event from persisted record and validate integrity."""
    diagnostics: list[str] = []

    raw_event_type = record.get("event_type")
    if not isinstance(raw_event_type, str):
        diagnostics.append("event_type must be a string")
        raise IntegrationEventValidationError("unknown", diagnostics)
    event_type = parse_event_type(raw_event_type)

    payload_obj = record.get("payload")
    if not isinstance(payload_obj, Mapping):
        diagnostics.append("payload must be an object")
        raise IntegrationEventValidationError(event_type, diagnostics)
    payload = cast(Mapping[str, object], payload_obj)

    event_id = record.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        diagnostics.append("event_id must be a non-empty string")
    received_at = record.get("received_at")
    if not isinstance(received_at, str) or not received_at.strip():
        diagnostics.append("received_at must be a non-empty ISO8601 string")
    idempotency_key = record.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        diagnostics.append("idempotency_key must be a non-empty string")
    if diagnostics:
        raise IntegrationEventValidationError(event_type, diagnostics)

    resolved_event_id = cast(str, event_id)
    resolved_received_at = cast(str, received_at)
    resolved_idempotency_key = cast(str, idempotency_key)

    return build_integration_event(
        event_type,
        payload,
        idempotency_key=resolved_idempotency_key,
        event_id=resolved_event_id,
        received_at=resolved_received_at,
    )


def _validate_field_set(event_type: IntegrationEventType, payload: Mapping[str, object]) -> list[str]:
    required = set(_REQUIRED_FIELDS[event_type])
    present = set(payload.keys())

    missing = sorted(required - present)
    unexpected = sorted(present - required)

    diagnostics: list[str] = []
    if missing:
        diagnostics.append(f"missing required fields: {missing}")
    if unexpected:
        diagnostics.append(f"unexpected fields: {unexpected}")
    return diagnostics


def _validate_review_approved(payload: Mapping[str, object], diagnostics: list[str]) -> ReviewApprovedPayload:
    slug = _as_non_empty_str(payload, "slug", diagnostics)
    approved_at = _as_iso8601("review_approved", payload, "approved_at", diagnostics)
    review_round = _as_positive_int(payload, "review_round", diagnostics)
    reviewer_session_id = _as_non_empty_str(payload, "reviewer_session_id", diagnostics)
    if diagnostics:
        raise IntegrationEventValidationError("review_approved", diagnostics)
    return {
        "slug": slug,
        "approved_at": approved_at,
        "review_round": review_round,
        "reviewer_session_id": reviewer_session_id,
    }


def _validate_finalize_ready(payload: Mapping[str, object], diagnostics: list[str]) -> FinalizeReadyPayload:
    slug = _as_non_empty_str(payload, "slug", diagnostics)
    branch = _as_non_empty_str(payload, "branch", diagnostics)
    sha = _as_non_empty_str(payload, "sha", diagnostics)
    worker_session_id = _as_non_empty_str(payload, "worker_session_id", diagnostics)
    orchestrator_session_id = _as_non_empty_str(payload, "orchestrator_session_id", diagnostics)
    ready_at = _as_iso8601("finalize_ready", payload, "ready_at", diagnostics)
    if diagnostics:
        raise IntegrationEventValidationError("finalize_ready", diagnostics)
    return {
        "slug": slug,
        "branch": branch,
        "sha": sha,
        "worker_session_id": worker_session_id,
        "orchestrator_session_id": orchestrator_session_id,
        "ready_at": ready_at,
    }


def _validate_branch_pushed(payload: Mapping[str, object], diagnostics: list[str]) -> BranchPushedPayload:
    branch = _as_non_empty_str(payload, "branch", diagnostics)
    sha = _as_non_empty_str(payload, "sha", diagnostics)
    remote = _as_non_empty_str(payload, "remote", diagnostics)
    pushed_at = _as_iso8601("branch_pushed", payload, "pushed_at", diagnostics)
    pusher = _as_non_empty_str(payload, "pusher", diagnostics)
    if diagnostics:
        raise IntegrationEventValidationError("branch_pushed", diagnostics)
    return {"branch": branch, "sha": sha, "remote": remote, "pushed_at": pushed_at, "pusher": pusher}


def _as_non_empty_str(payload: Mapping[str, object], field_name: str, diagnostics: list[str]) -> str:
    raw = payload.get(field_name)
    if not isinstance(raw, str) or not raw.strip():
        diagnostics.append(f"{field_name} must be a non-empty string")
        return ""
    return raw.strip()


def _as_positive_int(payload: Mapping[str, object], field_name: str, diagnostics: list[str]) -> int:
    raw = payload.get(field_name)
    if not isinstance(raw, int):
        diagnostics.append(f"{field_name} must be an integer")
        return 0
    if raw < 1:
        diagnostics.append(f"{field_name} must be >= 1")
        return 0
    return raw


def _as_iso8601(
    event_type: IntegrationEventType, payload: Mapping[str, object], field_name: str, diagnostics: list[str]
) -> str:
    raw = payload.get(field_name)
    if not isinstance(raw, str) or not raw.strip():
        diagnostics.append(f"{field_name} must be a non-empty ISO8601 string")
        return ""
    try:
        return _normalize_iso8601(event_type, field_name, raw)
    except IntegrationEventValidationError as exc:
        diagnostics.extend(exc.diagnostics)
        return ""


def _normalize_iso8601(event_type: IntegrationEventType, field_name: str, raw_value: str) -> str:
    adjusted = raw_value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(adjusted)
    except ValueError as exc:
        raise IntegrationEventValidationError(
            event_type,
            [f"{field_name} must be valid ISO8601 (value={raw_value!r})"],
        ) from exc
    if parsed.tzinfo is None:
        raise IntegrationEventValidationError(event_type, [f"{field_name} must include timezone offset"])
    return parsed.astimezone(UTC).isoformat(timespec="seconds")
