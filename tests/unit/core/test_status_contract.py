"""Characterization tests for teleclaude.core.status_contract."""

from __future__ import annotations

import pytest

from teleclaude.core.status_contract import (
    LIFECYCLE_STATUSES,
    STATUS_DELIVERY_SCOPE,
    STATUS_MESSAGE_INTENT,
    CanonicalStatusEvent,
    serialize_status_event,
)


class TestConstants:
    @pytest.mark.unit
    def test_status_message_intent_value(self):
        assert STATUS_MESSAGE_INTENT == "ctrl_status"

    @pytest.mark.unit
    def test_status_delivery_scope_value(self):
        assert STATUS_DELIVERY_SCOPE == "CTRL"

    @pytest.mark.unit
    def test_lifecycle_statuses_contains_expected_values(self):
        expected = {"accepted", "active", "active_output", "completed", "error", "closed"}
        assert LIFECYCLE_STATUSES == expected


class TestSerializeStatusEvent:
    @pytest.mark.unit
    def test_valid_active_status_returns_event(self):
        event = serialize_status_event(
            session_id="sess-001",
            status="active",
            reason="agent_session_started",
            timestamp="2024-01-01T00:00:00Z",
        )
        assert event is not None
        assert event.status == "active"
        assert event.session_id == "sess-001"

    @pytest.mark.unit
    def test_invalid_status_returns_none(self):
        event = serialize_status_event(
            session_id="sess-001",
            status="invalid_status",
            reason="some_reason",
            timestamp="2024-01-01T00:00:00Z",
        )
        assert event is None

    @pytest.mark.unit
    def test_empty_session_id_returns_none(self):
        event = serialize_status_event(
            session_id="",
            status="active",
            reason="agent_session_started",
            timestamp="2024-01-01T00:00:00Z",
        )
        assert event is None

    @pytest.mark.unit
    def test_empty_reason_returns_none(self):
        event = serialize_status_event(
            session_id="sess-001",
            status="active",
            reason="",
            timestamp="2024-01-01T00:00:00Z",
        )
        assert event is None

    @pytest.mark.unit
    def test_last_activity_at_propagated(self):
        event = serialize_status_event(
            session_id="sess-001",
            status="completed",
            reason="agent_turn_complete",
            timestamp="2024-01-01T00:00:00Z",
            last_activity_at="2024-01-01T00:01:00Z",
        )
        assert event is not None
        assert event.last_activity_at == "2024-01-01T00:01:00Z"

    @pytest.mark.unit
    def test_routing_metadata_set_correctly(self):
        event = serialize_status_event(
            session_id="sess-001",
            status="closed",
            reason="session_closed",
            timestamp="2024-01-01T00:00:00Z",
        )
        assert event is not None
        assert event.message_intent == "ctrl_status"
        assert event.delivery_scope == "CTRL"


class TestCanonicalStatusEvent:
    @pytest.mark.unit
    def test_is_frozen_dataclass(self):
        event = CanonicalStatusEvent(
            session_id="s",
            status="active",
            reason="r",
            timestamp="2024-01-01T00:00:00Z",
        )
        with pytest.raises((AttributeError, TypeError)):
            event.session_id = "modified"
