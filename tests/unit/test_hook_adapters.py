"""Unit tests for hook adapters."""

import argparse
import json
import os

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.hooks.adapters import get_adapter
from teleclaude.hooks.adapters.claude import ClaudeAdapter
from teleclaude.hooks.adapters.codex import CodexAdapter
from teleclaude.hooks.adapters.gemini import GeminiAdapter


class TestClaudeAdapter:
    def test_normalize_payload_identity(self):
        adapter = ClaudeAdapter()
        data = {"session_id": "s1", "transcript_path": "/tmp/t.jsonl", "prompt": "hi"}
        assert adapter.normalize_payload(data) is data

    def test_format_checkpoint_response(self):
        adapter = ClaudeAdapter()
        result = adapter.format_checkpoint_response("test reason")
        assert json.loads(result) == {"decision": "block", "reason": "test reason"}

    def test_format_memory_injection(self):
        adapter = ClaudeAdapter()
        result = adapter.format_memory_injection("context text")
        parsed = json.loads(result)
        assert parsed == {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "context text",
            }
        }

    def test_parse_input_reads_stdin(self, monkeypatch):
        from teleclaude.hooks import receiver

        adapter = ClaudeAdapter()
        monkeypatch.setattr(
            receiver,
            "_read_stdin",
            lambda: ('{"session_id":"s1"}', {"session_id": "s1"}),
        )
        args = argparse.Namespace(event_type="SessionStart", agent="claude")
        raw_input, event_type, data = adapter.parse_input(args)
        assert raw_input == '{"session_id":"s1"}'
        assert event_type == "SessionStart"
        assert data == {"session_id": "s1"}

    def test_mint_events(self):
        adapter = ClaudeAdapter()
        assert adapter.mint_events == frozenset({"session_start"})

    def test_supports_hook_checkpoint(self):
        adapter = ClaudeAdapter()
        assert adapter.supports_hook_checkpoint is True


class TestGeminiAdapter:
    def test_normalize_payload_identity(self):
        adapter = GeminiAdapter()
        data = {"session_id": "s1", "prompt": "hi"}
        assert adapter.normalize_payload(data) is data

    def test_format_checkpoint_response(self):
        adapter = GeminiAdapter()
        result = adapter.format_checkpoint_response("deny reason")
        assert json.loads(result) == {"decision": "deny", "reason": "deny reason"}

    def test_format_memory_injection(self):
        adapter = GeminiAdapter()
        result = adapter.format_memory_injection("context text")
        parsed = json.loads(result)
        assert parsed == {
            "hookSpecificOutput": {
                "additionalContext": "context text",
            }
        }

    def test_parse_input_reads_stdin(self, monkeypatch):
        from teleclaude.hooks import receiver

        adapter = GeminiAdapter()
        monkeypatch.setattr(
            receiver,
            "_read_stdin",
            lambda: ('{"session_id":"s1"}', {"session_id": "s1"}),
        )
        args = argparse.Namespace(event_type="BeforeAgent", agent="gemini")
        raw_input, event_type, data = adapter.parse_input(args)
        assert raw_input == '{"session_id":"s1"}'
        assert event_type == "BeforeAgent"
        assert data == {"session_id": "s1"}

    def test_mint_events(self):
        adapter = GeminiAdapter()
        assert adapter.mint_events == frozenset({"session_start"})

    def test_supports_hook_checkpoint(self):
        adapter = GeminiAdapter()
        assert adapter.supports_hook_checkpoint is True


class TestCodexAdapter:
    def test_normalize_payload_maps_fields(self):
        adapter = CodexAdapter()
        data = {
            "type": "agent-turn-complete",
            "thread-id": "abc-123",
            "turn-id": "42",
            "input-messages": ["first prompt", "second prompt"],
            "last-assistant-message": "response text",
        }
        result = adapter.normalize_payload(data)
        assert result["session_id"] == "abc-123"
        assert result["prompt"] == "second prompt"
        assert result["message"] == "response text"
        assert "thread-id" not in result
        assert "input-messages" not in result
        assert "last-assistant-message" not in result
        # Non-mapped fields preserved
        assert result["type"] == "agent-turn-complete"
        assert result["turn-id"] == "42"

    def test_normalize_payload_string_input_messages(self):
        adapter = CodexAdapter()
        data = {"input-messages": "single prompt"}
        result = adapter.normalize_payload(data)
        assert result["prompt"] == "single prompt"

    def test_normalize_payload_empty_input_messages(self):
        adapter = CodexAdapter()
        data = {"input-messages": []}
        result = adapter.normalize_payload(data)
        assert "prompt" not in result

    def test_normalize_payload_no_mapped_fields(self):
        adapter = CodexAdapter()
        data = {"type": "agent-turn-complete", "other": "value"}
        result = adapter.normalize_payload(data)
        assert result == {"type": "agent-turn-complete", "other": "value"}

    def test_parse_input_parses_json_from_event_type(self):
        adapter = CodexAdapter()
        json_payload = json.dumps({"thread-id": "t-1", "type": "agent-turn-complete"})
        args = argparse.Namespace(event_type=json_payload, agent="codex")
        raw_input, event_type, data = adapter.parse_input(args)
        assert raw_input == json_payload
        assert event_type == "agent_stop"
        assert data["thread-id"] == "t-1"

    def test_parse_input_empty_event_type(self):
        adapter = CodexAdapter()
        args = argparse.Namespace(event_type="", agent="codex")
        raw_input, event_type, data = adapter.parse_input(args)
        assert raw_input == ""
        assert event_type == "agent_stop"
        assert data == {}

    def test_parse_input_none_event_type(self):
        adapter = CodexAdapter()
        args = argparse.Namespace(event_type=None, agent="codex")
        raw_input, event_type, data = adapter.parse_input(args)
        assert raw_input == ""
        assert event_type == "agent_stop"
        assert data == {}

    def test_parse_input_invalid_json(self):
        adapter = CodexAdapter()
        args = argparse.Namespace(event_type="not json", agent="codex")
        with pytest.raises(json.JSONDecodeError):
            adapter.parse_input(args)

    def test_parse_input_non_object_json(self):
        adapter = CodexAdapter()
        args = argparse.Namespace(event_type="[1,2,3]", agent="codex")
        with pytest.raises(ValueError, match="JSON object"):
            adapter.parse_input(args)

    def test_format_checkpoint_response_returns_none(self):
        adapter = CodexAdapter()
        assert adapter.format_checkpoint_response("reason") is None

    def test_format_memory_injection_returns_empty(self):
        adapter = CodexAdapter()
        assert adapter.format_memory_injection("context") == ""

    def test_mint_events(self):
        adapter = CodexAdapter()
        assert adapter.mint_events == frozenset({"session_start", "agent_stop"})

    def test_supports_hook_checkpoint(self):
        adapter = CodexAdapter()
        assert adapter.supports_hook_checkpoint is False


class TestAdapterFactory:
    def test_get_adapter_claude(self):
        adapter = get_adapter("claude")
        assert isinstance(adapter, ClaudeAdapter)

    def test_get_adapter_gemini(self):
        adapter = get_adapter("gemini")
        assert isinstance(adapter, GeminiAdapter)

    def test_get_adapter_codex(self):
        adapter = get_adapter("codex")
        assert isinstance(adapter, CodexAdapter)

    def test_get_adapter_unknown_raises(self):
        with pytest.raises(KeyError):
            get_adapter("unknown")
