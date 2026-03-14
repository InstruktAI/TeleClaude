"""Characterization tests for teleclaude.core.activity_contract."""

from __future__ import annotations

import pytest

from teleclaude.core.activity_contract import (
    ACTIVITY_DELIVERY_SCOPE,
    ACTIVITY_MESSAGE_INTENT,
    HOOK_TO_CANONICAL,
    CanonicalActivityEvent,
    serialize_activity_event,
)


class TestConstants:
    @pytest.mark.unit
    def test_activity_message_intent_value(self):
        assert ACTIVITY_MESSAGE_INTENT == "ctrl_activity"

    @pytest.mark.unit
    def test_activity_delivery_scope_value(self):
        assert ACTIVITY_DELIVERY_SCOPE == "CTRL"

    @pytest.mark.unit
    def test_hook_to_canonical_maps_user_prompt_submit(self):
        assert HOOK_TO_CANONICAL["user_prompt_submit"] == "user_prompt_submit"

    @pytest.mark.unit
    def test_hook_to_canonical_maps_tool_use_to_update(self):
        assert HOOK_TO_CANONICAL["tool_use"] == "agent_output_update"

    @pytest.mark.unit
    def test_hook_to_canonical_maps_tool_done_to_update(self):
        assert HOOK_TO_CANONICAL["tool_done"] == "agent_output_update"

    @pytest.mark.unit
    def test_hook_to_canonical_maps_agent_stop(self):
        assert HOOK_TO_CANONICAL["agent_stop"] == "agent_output_stop"


class TestSerializeActivityEvent:
    @pytest.mark.unit
    def test_valid_user_prompt_submit_returns_event(self):
        event = serialize_activity_event(
            session_id="sess-001",
            hook_event_type="user_prompt_submit",
            timestamp="2024-01-01T00:00:00Z",
        )
        assert event is not None
        assert event.canonical_type == "user_prompt_submit"
        assert event.session_id == "sess-001"

    @pytest.mark.unit
    def test_valid_tool_use_maps_to_update(self):
        event = serialize_activity_event(
            session_id="sess-001",
            hook_event_type="tool_use",
            timestamp="2024-01-01T00:00:00Z",
            tool_name="Bash",
        )
        assert event is not None
        assert event.canonical_type == "agent_output_update"
        assert event.tool_name == "Bash"

    @pytest.mark.unit
    def test_unknown_hook_event_returns_none(self):
        event = serialize_activity_event(
            session_id="sess-001",
            hook_event_type="unknown_event",
            timestamp="2024-01-01T00:00:00Z",
        )
        assert event is None

    @pytest.mark.unit
    def test_empty_session_id_returns_none(self):
        event = serialize_activity_event(
            session_id="",
            hook_event_type="agent_stop",
            timestamp="2024-01-01T00:00:00Z",
        )
        assert event is None

    @pytest.mark.unit
    def test_valid_agent_stop_event_has_correct_routing(self):
        event = serialize_activity_event(
            session_id="sess-001",
            hook_event_type="agent_stop",
            timestamp="2024-01-01T00:00:00Z",
            summary="Done",
        )
        assert event is not None
        assert event.message_intent == "ctrl_activity"
        assert event.delivery_scope == "CTRL"
        assert event.summary == "Done"

    @pytest.mark.unit
    def test_event_preserves_hook_event_type(self):
        event = serialize_activity_event(
            session_id="sess-001",
            hook_event_type="tool_done",
            timestamp="2024-01-01T00:00:00Z",
        )
        assert event is not None
        assert event.hook_event_type == "tool_done"

    @pytest.mark.unit
    def test_optional_fields_default_to_none(self):
        event = serialize_activity_event(
            session_id="sess-001",
            hook_event_type="user_prompt_submit",
            timestamp="2024-01-01T00:00:00Z",
        )
        assert event is not None
        assert event.tool_name is None
        assert event.tool_preview is None
        assert event.summary is None
        assert event.message is None


class TestCanonicalActivityEvent:
    @pytest.mark.unit
    def test_is_frozen_dataclass(self):
        event = CanonicalActivityEvent(
            session_id="s",
            canonical_type="user_prompt_submit",
            hook_event_type="user_prompt_submit",
            timestamp="2024-01-01T00:00:00Z",
            message_intent="ctrl_activity",
            delivery_scope="CTRL",
        )
        with pytest.raises((AttributeError, TypeError)):
            event.session_id = "modified"

    @pytest.mark.unit
    def test_fields_are_accessible(self):
        event = CanonicalActivityEvent(
            session_id="sess-xyz",
            canonical_type="agent_output_stop",
            hook_event_type="agent_stop",
            timestamp="2024-01-01T00:00:00Z",
            message_intent="ctrl_activity",
            delivery_scope="CTRL",
            tool_name="Read",
        )
        assert event.session_id == "sess-xyz"
        assert event.canonical_type == "agent_output_stop"
        assert event.tool_name == "Read"
