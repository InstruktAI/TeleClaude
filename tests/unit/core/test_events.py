"""Characterization tests for teleclaude.core.events."""

from __future__ import annotations

from typing import get_args

import pytest

from teleclaude.core.events import (
    AgentHookEvents,
    AgentOutputPayload,
    AgentStopPayload,
    EventType,
    TeleClaudeEvents,
    build_agent_payload,
    parse_command_string,
)


class TestAgentHookEvents:
    @pytest.mark.unit
    def test_user_prompt_submit_value(self):
        assert AgentHookEvents.USER_PROMPT_SUBMIT == "user_prompt_submit"

    @pytest.mark.unit
    def test_agent_stop_value(self):
        assert AgentHookEvents.AGENT_STOP == "agent_stop"

    @pytest.mark.unit
    def test_tool_use_value(self):
        assert AgentHookEvents.TOOL_USE == "tool_use"

    @pytest.mark.unit
    def test_hook_event_map_contains_claude(self):
        assert "claude" in AgentHookEvents.HOOK_EVENT_MAP

    @pytest.mark.unit
    def test_hook_event_map_contains_codex(self):
        assert "codex" in AgentHookEvents.HOOK_EVENT_MAP

    @pytest.mark.unit
    def test_hook_event_map_contains_gemini(self):
        assert "gemini" in AgentHookEvents.HOOK_EVENT_MAP

    @pytest.mark.unit
    def test_claude_stop_maps_to_agent_stop(self):
        claude_map = AgentHookEvents.HOOK_EVENT_MAP["claude"]
        assert claude_map["Stop"] == "agent_stop"

    @pytest.mark.unit
    def test_codex_stop_maps_to_agent_stop(self):
        codex_map = AgentHookEvents.HOOK_EVENT_MAP["codex"]
        assert codex_map["Stop"] == "agent_stop"

    @pytest.mark.unit
    def test_codex_pre_tool_use_maps_to_tool_use(self):
        codex_map = AgentHookEvents.HOOK_EVENT_MAP["codex"]
        assert codex_map["PreToolUse"] == AgentHookEvents.TOOL_USE

    @pytest.mark.unit
    def test_codex_post_tool_use_cataloged_but_not_ingested(self):
        codex_map = AgentHookEvents.HOOK_EVENT_MAP["codex"]
        assert "PostToolUse" in codex_map
        assert codex_map["PostToolUse"] is None

    @pytest.mark.unit
    def test_codex_permission_request_cataloged_but_not_ingested(self):
        codex_map = AgentHookEvents.HOOK_EVENT_MAP["codex"]
        assert "PermissionRequest" in codex_map
        assert codex_map["PermissionRequest"] is None


class TestBuildAgentPayload:
    @pytest.mark.unit
    def test_tool_use_returns_agent_output_payload(self):
        data = {"session_id": "sess-001", "transcript_path": "/tmp/t.json"}
        payload = build_agent_payload(AgentHookEvents.TOOL_USE, data)
        assert isinstance(payload, AgentOutputPayload)
        assert payload.session_id == "sess-001"
        assert payload.transcript_path == "/tmp/t.json"

    @pytest.mark.unit
    def test_agent_stop_returns_agent_stop_payload(self):
        data = {"session_id": "sess-002", "prompt": "last prompt"}
        payload = build_agent_payload(AgentHookEvents.AGENT_STOP, data)
        assert isinstance(payload, AgentStopPayload)
        assert payload.session_id == "sess-002"
        assert payload.prompt == "last prompt"

    @pytest.mark.unit
    def test_unsupported_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported agent hook event_type"):
            build_agent_payload("before_model", {})


class TestParseCommandString:
    @pytest.mark.unit
    def test_simple_command_parses(self):
        name, args = parse_command_string("message hello world")
        assert name == "message"
        assert args == ["hello", "world"]

    @pytest.mark.unit
    def test_command_with_no_args(self):
        name, args = parse_command_string("new_session")
        assert name == "new_session"
        assert args == []

    @pytest.mark.unit
    def test_quoted_args_preserved(self):
        name, args = parse_command_string('message "hello world"')
        assert name == "message"
        assert args == ["hello world"]

    @pytest.mark.unit
    def test_empty_string_parsed(self):
        name, args = parse_command_string("")
        assert name is None
        assert args == []


class TestEventsReadinessSpec:
    """Test that new readiness event types are correctly defined."""

    def test_teleclaude_events_has_readiness_types(self):
        """TeleClaudeEvents must have AGENT_READY and AGENT_READINESS_TIMEOUT."""
        assert getattr(TeleClaudeEvents, "AGENT_READY", None) == "agent_ready"
        assert getattr(TeleClaudeEvents, "AGENT_READINESS_TIMEOUT", None) == "agent_readiness_timeout"

    def test_event_type_includes_readiness_types(self):
        """EventType literal must include readiness types for type-safety."""
        allowed_types = get_args(EventType)
        assert "agent_ready" in allowed_types
        assert "agent_readiness_timeout" in allowed_types
