"""Characterization tests for teleclaude.core.integration.events."""

from __future__ import annotations

from typing import cast

import pytest

from teleclaude.core.integration.events import (
    BranchPushedPayload,
    FinalizeReadyPayload,
    IntegrationBlockedPayload,
    IntegrationEvent,
    IntegrationEventValidationError,
    ReviewApprovedPayload,
    build_integration_event,
    compute_idempotency_key,
    integration_event_from_record,
    integration_event_to_record,
    parse_event_type,
    validate_event_payload,
)

_REVIEW_APPROVED_PAYLOAD: ReviewApprovedPayload = {
    "slug": "my-slug",
    "approved_at": "2024-01-01T12:00:00+00:00",
    "review_round": 1,
    "reviewer_session_id": "session-abc",
}

_FINALIZE_READY_PAYLOAD: FinalizeReadyPayload = {
    "slug": "my-slug",
    "branch": "my-branch",
    "sha": "abc123",
    "worker_session_id": "worker-1",
    "orchestrator_session_id": "orch-1",
    "ready_at": "2024-01-01T12:00:00+00:00",
}

_BRANCH_PUSHED_PAYLOAD: BranchPushedPayload = {
    "branch": "feature-branch",
    "sha": "deadbeef",
    "remote": "origin",
    "pushed_at": "2024-01-01T12:00:00+00:00",
    "pusher": "agent-1",
}

_INTEGRATION_BLOCKED_PAYLOAD: IntegrationBlockedPayload = {
    "slug": "blocked-slug",
    "branch": "blocked-branch",
    "sha": "cafebabe",
    "conflict_evidence": ["file.py"],
    "diagnostics": ["merge conflict"],
    "next_action": "resolve",
    "blocked_at": "2024-01-01T12:00:00+00:00",
}


# ---------------------------------------------------------------------------
# parse_event_type
# ---------------------------------------------------------------------------


def test_parse_event_type_accepts_valid_types():
    for et in ("review_approved", "finalize_ready", "branch_pushed", "integration_blocked"):
        assert parse_event_type(et) == et


def test_parse_event_type_rejects_unknown_type():
    with pytest.raises(IntegrationEventValidationError):
        parse_event_type("unknown_event")


# ---------------------------------------------------------------------------
# compute_idempotency_key
# ---------------------------------------------------------------------------


def test_compute_idempotency_key_is_deterministic():
    key1 = compute_idempotency_key("review_approved", _REVIEW_APPROVED_PAYLOAD)
    key2 = compute_idempotency_key("review_approved", _REVIEW_APPROVED_PAYLOAD)
    assert key1 == key2


def test_compute_idempotency_key_differs_for_different_payloads():
    p1: ReviewApprovedPayload = {**_REVIEW_APPROVED_PAYLOAD, "slug": "slug-a"}
    p2: ReviewApprovedPayload = {**_REVIEW_APPROVED_PAYLOAD, "slug": "slug-b"}
    assert compute_idempotency_key("review_approved", p1) != compute_idempotency_key("review_approved", p2)


def test_compute_idempotency_key_is_hex_string():
    key = compute_idempotency_key("review_approved", _REVIEW_APPROVED_PAYLOAD)
    int(key, 16)  # must parse as hex


# ---------------------------------------------------------------------------
# build_integration_event
# ---------------------------------------------------------------------------


def test_build_integration_event_review_approved_returns_event():
    event = build_integration_event("review_approved", _REVIEW_APPROVED_PAYLOAD)
    assert isinstance(event, IntegrationEvent)
    assert event.event_type == "review_approved"
    assert cast(ReviewApprovedPayload, event.payload)["slug"] == "my-slug"


def test_build_integration_event_finalize_ready_returns_event():
    event = build_integration_event("finalize_ready", _FINALIZE_READY_PAYLOAD)
    assert event.event_type == "finalize_ready"


def test_build_integration_event_normalizes_iso8601_to_utc():
    payload: ReviewApprovedPayload = {**_REVIEW_APPROVED_PAYLOAD, "approved_at": "2024-01-01T13:00:00+01:00"}
    event = build_integration_event("review_approved", payload)
    assert cast(ReviewApprovedPayload, event.payload)["approved_at"].endswith("+00:00")


def test_build_integration_event_invalid_payload_raises():
    with pytest.raises(IntegrationEventValidationError):
        build_integration_event("review_approved", {"slug": "x"})


def test_build_integration_event_custom_idempotency_key_preserved():
    event = build_integration_event("review_approved", _REVIEW_APPROVED_PAYLOAD, idempotency_key="my-key")
    assert event.idempotency_key == "my-key"


# ---------------------------------------------------------------------------
# validate_event_payload
# ---------------------------------------------------------------------------


def test_validate_event_payload_accepts_branch_pushed():
    result = validate_event_payload("branch_pushed", _BRANCH_PUSHED_PAYLOAD)
    assert cast(BranchPushedPayload, result)["branch"] == "feature-branch"


def test_validate_event_payload_accepts_integration_blocked():
    result = validate_event_payload("integration_blocked", _INTEGRATION_BLOCKED_PAYLOAD)
    assert result["slug"] == "blocked-slug"  # type: ignore[typeddict-item]


def test_validate_event_payload_rejects_missing_required_field():
    bad = {k: v for k, v in _REVIEW_APPROVED_PAYLOAD.items() if k != "slug"}
    with pytest.raises(IntegrationEventValidationError) as exc_info:
        validate_event_payload("review_approved", bad)
    assert "slug" in str(exc_info.value)


def test_validate_event_payload_rejects_unexpected_field():
    bad = {**_REVIEW_APPROVED_PAYLOAD, "extra": "field"}
    with pytest.raises(IntegrationEventValidationError):
        validate_event_payload("review_approved", bad)


def test_validate_event_payload_rejects_invalid_iso8601():
    bad = {**_REVIEW_APPROVED_PAYLOAD, "approved_at": "not-a-date"}
    with pytest.raises(IntegrationEventValidationError):
        validate_event_payload("review_approved", bad)


def test_validate_event_payload_integration_blocked_optional_follow_up_slug():
    payload = {**_INTEGRATION_BLOCKED_PAYLOAD, "follow_up_slug": "my-follow-up"}
    result = validate_event_payload("integration_blocked", payload)
    assert result.get("follow_up_slug") == "my-follow-up"


# ---------------------------------------------------------------------------
# integration_event_to_record / integration_event_from_record round-trip
# ---------------------------------------------------------------------------


def test_event_to_record_and_back_round_trips():
    event = build_integration_event("review_approved", _REVIEW_APPROVED_PAYLOAD)
    record = integration_event_to_record(event)
    restored = integration_event_from_record(record)
    assert restored.event_type == event.event_type
    assert restored.idempotency_key == event.idempotency_key
    assert cast(ReviewApprovedPayload, restored.payload)["slug"] == cast(ReviewApprovedPayload, event.payload)["slug"]


def test_event_from_record_rejects_missing_event_type():
    from teleclaude.core.integration.events import IntegrationEventRecord

    bad: IntegrationEventRecord = {
        "event_id": "x",
        "event_type": "",  # type: ignore[typeddict-item]
        "payload": {},  # type: ignore[typeddict-item]
        "received_at": "2024-01-01T12:00:00+00:00",
        "idempotency_key": "k",
    }
    with pytest.raises(IntegrationEventValidationError):
        integration_event_from_record(bad)


def test_integration_event_validation_error_has_diagnostics():
    with pytest.raises(IntegrationEventValidationError) as exc_info:
        validate_event_payload("review_approved", {})
    # Must report at least the missing required fields (slug, approved_at, etc.)
    assert len(exc_info.value.diagnostics) >= 3
