"""Unit tests for the canonical lifecycle status contract.

Covers:
- Serializer success/failure for all status vocabulary values
- Validation failure behavior (explicit errors, non-crashing)
- Routing metadata correctness (message_intent, delivery_scope)
- LIFECYCLE_STATUSES vocabulary completeness
- Optional field handling
"""

import pytest

from teleclaude.core.status_contract import (
    AWAITING_OUTPUT_THRESHOLD_SECONDS,
    LIFECYCLE_STATUSES,
    STALL_THRESHOLD_SECONDS,
    STATUS_DELIVERY_SCOPE,
    STATUS_MESSAGE_INTENT,
    CanonicalStatusEvent,
    serialize_status_event,
)

# ---------------------------------------------------------------------------
# Serializer — success paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [
        "accepted",
        "awaiting_output",
        "active_output",
        "stalled",
        "completed",
        "error",
        "closed",
    ],
)
def test_serialize_status_event_accepts_all_vocabulary_values(status: str) -> None:
    """serialize_status_event should accept every value in the canonical vocabulary."""
    result = serialize_status_event(
        session_id="sess-abc",
        status=status,
        reason="test_reason",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert result is not None
    assert result.status == status


def test_serialize_status_event_returns_canonical_status_event() -> None:
    """serialize_status_event should return a CanonicalStatusEvent instance."""
    result = serialize_status_event(
        session_id="sess-123",
        status="accepted",
        reason="user_prompt_accepted",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert isinstance(result, CanonicalStatusEvent)


def test_serialize_status_event_required_fields_populated() -> None:
    """All required identity/routing fields must be populated on success."""
    result = serialize_status_event(
        session_id="sess-req",
        status="completed",
        reason="agent_turn_complete",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert result is not None
    assert result.session_id == "sess-req"
    assert result.status == "completed"
    assert result.reason == "agent_turn_complete"
    assert result.timestamp == "2024-01-01T00:00:00+00:00"
    assert result.message_intent == STATUS_MESSAGE_INTENT
    assert result.delivery_scope == STATUS_DELIVERY_SCOPE


def test_serialize_status_event_with_last_activity_at() -> None:
    """last_activity_at is optional and should be passed through when provided."""
    result = serialize_status_event(
        session_id="sess-laa",
        status="active_output",
        reason="output_observed",
        timestamp="2024-01-01T00:00:00+00:00",
        last_activity_at="2024-01-01T00:00:01+00:00",
    )

    assert result is not None
    assert result.last_activity_at == "2024-01-01T00:00:01+00:00"


# ---------------------------------------------------------------------------
# Routing metadata
# ---------------------------------------------------------------------------


def test_status_routing_is_always_ctrl() -> None:
    """All status events use CTRL delivery scope."""
    for status in LIFECYCLE_STATUSES:
        result = serialize_status_event(
            session_id="sess-ctrl",
            status=status,
            reason="test",
            timestamp="2024-01-01T00:00:00+00:00",
        )
        assert result is not None
        assert result.delivery_scope == "CTRL", f"Expected CTRL for {status}"
        assert result.message_intent == "ctrl_status", f"Expected ctrl_status for {status}"


# ---------------------------------------------------------------------------
# Serializer — failure paths
# ---------------------------------------------------------------------------


def test_serialize_status_event_returns_none_for_invalid_status() -> None:
    """Unknown status values should return None without raising."""
    result = serialize_status_event(
        session_id="sess-bad",
        status="not_a_status",
        reason="test",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert result is None


def test_serialize_status_event_returns_none_on_empty_session_id() -> None:
    """Empty session_id should fail validation and return None (non-crashing)."""
    result = serialize_status_event(
        session_id="",
        status="accepted",
        reason="test",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert result is None


def test_serialize_status_event_returns_none_on_empty_timestamp() -> None:
    """Empty timestamp should fail validation and return None (non-crashing)."""
    result = serialize_status_event(
        session_id="sess-ts",
        status="accepted",
        reason="test",
        timestamp="",
    )

    assert result is None


def test_serialize_status_event_returns_none_on_empty_reason() -> None:
    """Empty reason should fail validation and return None (non-crashing)."""
    result = serialize_status_event(
        session_id="sess-reason",
        status="accepted",
        reason="",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert result is None


def test_serialize_status_event_logs_error_on_validation_failure(caplog: pytest.LogCaptureFixture) -> None:
    """Validation failures should be logged as errors, not exceptions."""
    import logging

    with caplog.at_level(logging.ERROR, logger="teleclaude.core.status_contract"):
        result = serialize_status_event(
            session_id="",
            status="accepted",
            reason="test",
            timestamp="2024-01-01T00:00:00+00:00",
        )

    assert result is None
    assert any("validation failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# LIFECYCLE_STATUSES vocabulary completeness
# ---------------------------------------------------------------------------


def test_lifecycle_statuses_contains_all_required_values() -> None:
    """LIFECYCLE_STATUSES must contain the full canonical vocabulary."""
    required = {"accepted", "awaiting_output", "active_output", "stalled", "completed", "error", "closed"}
    assert required == LIFECYCLE_STATUSES


def test_lifecycle_statuses_is_frozenset() -> None:
    """LIFECYCLE_STATUSES must be a frozenset for immutability and O(1) lookup."""
    assert isinstance(LIFECYCLE_STATUSES, frozenset)


# ---------------------------------------------------------------------------
# Stall timing thresholds
# ---------------------------------------------------------------------------


def test_awaiting_output_threshold_is_positive() -> None:
    """AWAITING_OUTPUT_THRESHOLD_SECONDS must be a positive float."""
    assert AWAITING_OUTPUT_THRESHOLD_SECONDS > 0


def test_stall_threshold_is_greater_than_awaiting_output() -> None:
    """STALL_THRESHOLD_SECONDS must exceed AWAITING_OUTPUT_THRESHOLD_SECONDS."""
    assert STALL_THRESHOLD_SECONDS > AWAITING_OUTPUT_THRESHOLD_SECONDS


# ---------------------------------------------------------------------------
# Optional fields default to None
# ---------------------------------------------------------------------------


def test_serialize_status_event_last_activity_at_defaults_to_none() -> None:
    """last_activity_at defaults to None when not provided."""
    result = serialize_status_event(
        session_id="sess-opt",
        status="accepted",
        reason="user_prompt_accepted",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert result is not None
    assert result.last_activity_at is None
