"""Unit tests for the canonical outbound activity contract.

Covers:
- Serializer success/failure for all mapped hook event types
- Validation failure behavior (explicit errors, non-crashing)
- Routing metadata correctness (message_intent, delivery_scope)
- Event-type mapping (HOOK_TO_CANONICAL)
- Unknown hook type handling
"""

import pytest

from teleclaude.core.activity_contract import (
    ACTIVITY_DELIVERY_SCOPE,
    ACTIVITY_MESSAGE_INTENT,
    HOOK_TO_CANONICAL,
    CanonicalActivityEvent,
    serialize_activity_event,
)

# ---------------------------------------------------------------------------
# Serializer — success paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hook_type, expected_canonical",
    [
        ("user_prompt_submit", "user_prompt_submit"),
        ("tool_use", "agent_output_update"),
        ("tool_done", "agent_output_update"),
        ("agent_stop", "agent_output_stop"),
    ],
)
def test_serialize_activity_event_maps_to_canonical(hook_type: str, expected_canonical: str) -> None:
    """serialize_activity_event should map each hook type to the correct canonical type."""
    result = serialize_activity_event(
        session_id="sess-abc",
        hook_event_type=hook_type,
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert result is not None
    assert result.canonical_type == expected_canonical


def test_serialize_activity_event_returns_canonical_activity_event() -> None:
    """serialize_activity_event should return a CanonicalActivityEvent instance."""
    result = serialize_activity_event(
        session_id="sess-123",
        hook_event_type="tool_use",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert isinstance(result, CanonicalActivityEvent)


def test_serialize_activity_event_required_fields_populated() -> None:
    """All required identity/routing fields must be populated on success."""
    result = serialize_activity_event(
        session_id="sess-req",
        hook_event_type="agent_stop",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert result is not None
    assert result.session_id == "sess-req"
    assert result.canonical_type == "agent_output_stop"
    assert result.hook_event_type == "agent_stop"
    assert result.timestamp == "2024-01-01T00:00:00+00:00"
    assert result.message_intent == ACTIVITY_MESSAGE_INTENT
    assert result.delivery_scope == ACTIVITY_DELIVERY_SCOPE


def test_serialize_activity_event_preserves_hook_type() -> None:
    """hook_event_type must be preserved for consumer compatibility."""
    result = serialize_activity_event(
        session_id="sess-compat",
        hook_event_type="tool_done",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert result is not None
    assert result.hook_event_type == "tool_done"
    assert result.canonical_type == "agent_output_update"


def test_serialize_activity_event_with_tool_fields() -> None:
    """tool_name and tool_preview must be passed through."""
    result = serialize_activity_event(
        session_id="sess-tool",
        hook_event_type="tool_use",
        timestamp="2024-01-01T00:00:00+00:00",
        tool_name="Bash",
        tool_preview="Bash git status",
    )

    assert result is not None
    assert result.tool_name == "Bash"
    assert result.tool_preview == "Bash git status"


def test_serialize_activity_event_with_summary() -> None:
    """summary must be passed through for agent_stop events."""
    result = serialize_activity_event(
        session_id="sess-sum",
        hook_event_type="agent_stop",
        timestamp="2024-01-01T00:00:00+00:00",
        summary="Finished editing the file.",
    )

    assert result is not None
    assert result.summary == "Finished editing the file."


# ---------------------------------------------------------------------------
# Routing metadata
# ---------------------------------------------------------------------------


def test_activity_routing_is_always_ctrl() -> None:
    """All activity events use CTRL delivery scope."""
    for hook_type in HOOK_TO_CANONICAL:
        result = serialize_activity_event(
            session_id="sess-ctrl",
            hook_event_type=hook_type,
            timestamp="2024-01-01T00:00:00+00:00",
        )
        assert result is not None
        assert result.delivery_scope == "CTRL", f"Expected CTRL for {hook_type}"
        assert result.message_intent == "ctrl_activity", f"Expected ctrl_activity for {hook_type}"


# ---------------------------------------------------------------------------
# Serializer — failure paths
# ---------------------------------------------------------------------------


def test_serialize_activity_event_returns_none_for_unknown_hook_type() -> None:
    """Unknown hook event types should return None without raising."""
    result = serialize_activity_event(
        session_id="sess-unk",
        hook_event_type="before_model",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert result is None


def test_serialize_activity_event_returns_none_for_empty_hook_type() -> None:
    """Empty hook event type is not mapped and returns None."""
    result = serialize_activity_event(
        session_id="sess-empty",
        hook_event_type="",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert result is None


def test_serialize_activity_event_logs_warning_for_unknown_type(caplog: pytest.LogCaptureFixture) -> None:
    """Unknown hook type should produce a warning log, not an exception."""
    import logging

    with caplog.at_level(logging.WARNING, logger="teleclaude.core.activity_contract"):
        result = serialize_activity_event(
            session_id="sess-warn",
            hook_event_type="subagent_start",
            timestamp="2024-01-01T00:00:00+00:00",
        )

    assert result is None
    assert any("unknown hook event type" in r.message for r in caplog.records)


def test_serialize_activity_event_returns_none_on_empty_session_id() -> None:
    """Empty session_id should fail validation and return None (non-crashing)."""
    result = serialize_activity_event(
        session_id="",
        hook_event_type="tool_use",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert result is None


def test_serialize_activity_event_returns_none_on_empty_timestamp() -> None:
    """Empty timestamp should fail validation and return None (non-crashing)."""
    result = serialize_activity_event(
        session_id="sess-ts",
        hook_event_type="tool_use",
        timestamp="",
    )

    assert result is None


def test_serialize_activity_event_logs_error_on_validation_failure(caplog: pytest.LogCaptureFixture) -> None:
    """Validation failures should be logged as errors, not exceptions."""
    import logging

    with caplog.at_level(logging.ERROR, logger="teleclaude.core.activity_contract"):
        result = serialize_activity_event(
            session_id="",
            hook_event_type="tool_use",
            timestamp="2024-01-01T00:00:00+00:00",
        )

    assert result is None
    assert any("validation failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# HOOK_TO_CANONICAL mapping completeness
# ---------------------------------------------------------------------------


def test_hook_to_canonical_covers_all_expected_hook_types() -> None:
    """HOOK_TO_CANONICAL must cover all canonical activity hook types."""
    required_hook_types = {"user_prompt_submit", "tool_use", "tool_done", "agent_stop"}
    assert required_hook_types.issubset(set(HOOK_TO_CANONICAL.keys()))


def test_hook_to_canonical_all_values_are_valid_canonical_types() -> None:
    """All values in HOOK_TO_CANONICAL must be valid canonical activity types."""
    valid = {"user_prompt_submit", "agent_output_update", "agent_output_stop", "agent_notification"}
    for hook, canonical in HOOK_TO_CANONICAL.items():
        assert canonical in valid, f"{hook!r} maps to invalid canonical type {canonical!r}"


def test_hook_to_canonical_includes_agent_stop_to_output_stop() -> None:
    """agent_stop must map to agent_output_stop (turn complete signal)."""
    assert HOOK_TO_CANONICAL["agent_stop"] == "agent_output_stop"


def test_hook_to_canonical_tool_events_map_to_output_update() -> None:
    """tool_use and tool_done both map to agent_output_update."""
    assert HOOK_TO_CANONICAL["tool_use"] == "agent_output_update"
    assert HOOK_TO_CANONICAL["tool_done"] == "agent_output_update"


# ---------------------------------------------------------------------------
# Optional fields default to None
# ---------------------------------------------------------------------------


def test_serialize_activity_event_optional_fields_default_to_none() -> None:
    """Optional fields (tool_name, tool_preview, summary) default to None."""
    result = serialize_activity_event(
        session_id="sess-opt",
        hook_event_type="user_prompt_submit",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert result is not None
    assert result.tool_name is None
    assert result.tool_preview is None
    assert result.summary is None


# ---------------------------------------------------------------------------
# agent_notification — new canonical type
# ---------------------------------------------------------------------------


def test_serialize_notification_hook_maps_to_agent_notification() -> None:
    """notification hook must map to agent_notification canonical type."""
    result = serialize_activity_event(
        session_id="sess-notif",
        hook_event_type="notification",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert result is not None
    assert result.canonical_type == "agent_notification"
    assert result.hook_event_type == "notification"


def test_serialize_notification_hook_passes_message_through() -> None:
    """message field must be included in the canonical event for notification hooks."""
    result = serialize_activity_event(
        session_id="sess-notif-msg",
        hook_event_type="notification",
        timestamp="2024-01-01T00:00:00+00:00",
        message="Permission required for shell command",
    )

    assert result is not None
    assert result.message == "Permission required for shell command"


def test_serialize_notification_hook_message_defaults_to_none() -> None:
    """message defaults to None when not supplied (notification hook without message)."""
    result = serialize_activity_event(
        session_id="sess-notif-nomsg",
        hook_event_type="notification",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    assert result is not None
    assert result.message is None


def test_notification_in_hook_to_canonical() -> None:
    """notification must be present in HOOK_TO_CANONICAL mapping."""
    assert "notification" in HOOK_TO_CANONICAL
    assert HOOK_TO_CANONICAL["notification"] == "agent_notification"


def test_serialize_notification_uses_ctrl_routing() -> None:
    """agent_notification events use CTRL delivery scope like all activity events."""
    result = serialize_activity_event(
        session_id="sess-notif-ctrl",
        hook_event_type="notification",
        timestamp="2024-01-01T00:00:00+00:00",
        message="hello",
    )

    assert result is not None
    assert result.delivery_scope == "CTRL"
    assert result.message_intent == "ctrl_activity"
