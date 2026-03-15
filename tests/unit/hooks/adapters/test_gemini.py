"""Characterization tests for teleclaude.hooks.adapters.gemini."""

from __future__ import annotations

import argparse
import json
import sys
import types

import pytest

import teleclaude.hooks as hooks_package
from teleclaude.core.models import JsonDict
from teleclaude.hooks.adapters.gemini import GeminiAdapter


class TestGeminiAdapter:
    @pytest.mark.unit
    def test_parse_input_reads_json_from_receiver_stdin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = GeminiAdapter()
        receiver_stub = types.ModuleType("teleclaude.hooks.receiver")

        def _read_stdin() -> tuple[str, JsonDict]:
            return '{"session_id":"g1"}', {"session_id": "g1"}

        receiver_stub._read_stdin = _read_stdin
        monkeypatch.setitem(sys.modules, "teleclaude.hooks.receiver", receiver_stub)
        monkeypatch.setattr(hooks_package, "receiver", receiver_stub, raising=False)

        raw_input, event_type, raw_data = adapter.parse_input(argparse.Namespace(event_type="session_start"))

        assert raw_input == '{"session_id":"g1"}'
        assert event_type == "session_start"
        assert raw_data == {"session_id": "g1"}

    @pytest.mark.unit
    def test_normalize_payload_is_identity(self) -> None:
        adapter = GeminiAdapter()
        payload = {"session_id": "g1", "prompt": "hello"}

        assert adapter.normalize_payload(payload) is payload

    @pytest.mark.unit
    def test_checkpoint_response_formats_deny_decision_json(self) -> None:
        adapter = GeminiAdapter()

        assert json.loads(adapter.format_checkpoint_response("blocked") or "") == {
            "decision": "deny",
            "reason": "blocked",
        }

    @pytest.mark.unit
    def test_memory_injection_wraps_context_without_hook_event_name(self) -> None:
        adapter = GeminiAdapter()

        assert json.loads(adapter.format_memory_injection("remember this")) == {
            "hookSpecificOutput": {
                "additionalContext": "remember this",
            }
        }
