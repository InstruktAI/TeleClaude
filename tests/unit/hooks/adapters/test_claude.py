"""Characterization tests for teleclaude.hooks.adapters.claude."""

from __future__ import annotations

import argparse
import json
import sys
import types

import pytest

import teleclaude.hooks as hooks_package
from teleclaude.core.models import JsonDict
from teleclaude.hooks.adapters.claude import ClaudeAdapter


class TestClaudeAdapter:
    @pytest.mark.unit
    def test_parse_input_reads_json_from_receiver_stdin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = ClaudeAdapter()
        receiver_stub = types.ModuleType("teleclaude.hooks.receiver")

        def _read_stdin() -> tuple[str, JsonDict]:
            return '{"session_id":"s1"}', {"session_id": "s1"}

        receiver_stub._read_stdin = _read_stdin

        monkeypatch.setitem(sys.modules, "teleclaude.hooks.receiver", receiver_stub)
        monkeypatch.setattr(hooks_package, "receiver", receiver_stub, raising=False)

        raw_input, event_type, raw_data = adapter.parse_input(argparse.Namespace(event_type="session_start"))

        assert raw_input == '{"session_id":"s1"}'
        assert event_type == "session_start"
        assert raw_data == {"session_id": "s1"}

    @pytest.mark.unit
    def test_normalize_payload_is_identity(self) -> None:
        adapter = ClaudeAdapter()
        payload = {"session_id": "s1", "prompt": "hello"}

        assert adapter.normalize_payload(payload) is payload

    @pytest.mark.unit
    def test_checkpoint_response_formats_block_decision_json(self) -> None:
        adapter = ClaudeAdapter()

        assert json.loads(adapter.format_checkpoint_response("blocked") or "") == {
            "decision": "block",
            "reason": "blocked",
        }

    @pytest.mark.unit
    def test_memory_injection_wraps_context_for_session_start(self) -> None:
        adapter = ClaudeAdapter()

        assert json.loads(adapter.format_memory_injection("remember this")) == {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "remember this",
            }
        }
