"""Characterization tests for teleclaude.hooks.adapters.gemini."""

from __future__ import annotations

import argparse
import json
from unittest.mock import patch

import pytest

from teleclaude.hooks.adapters.gemini import GeminiAdapter


class TestGeminiAdapter:
    @pytest.mark.unit
    def test_parse_input_reads_json_from_receiver_stdin(self) -> None:
        adapter = GeminiAdapter()

        with patch(
            "teleclaude.hooks.adapters.base.read_stdin_payload",
            return_value=('{"session_id":"g1"}', {"session_id": "g1"}),
        ):
            raw_input, event_type, raw_data = adapter.parse_input(argparse.Namespace(event_type="session_start"))

        assert raw_input == '{"session_id":"g1"}'
        assert event_type == "session_start"
        assert raw_data == {"session_id": "g1"}

    @pytest.mark.unit
    def test_normalize_payload_is_identity(self) -> None:
        adapter = GeminiAdapter()
        payload = {"session_id": "g1", "prompt": "hello"}

        assert adapter.normalize_payload(payload) == payload

    @pytest.mark.unit
    def test_checkpoint_response_formats_deny_decision_json(self) -> None:
        adapter = GeminiAdapter()

        assert json.loads(adapter.format_checkpoint_response("blocked") or "") == {
            "decision": "deny",
            "reason": "blocked",
        }

    @pytest.mark.unit
    def test_additional_context_wraps_context_without_hook_event_name(self) -> None:
        adapter = GeminiAdapter()

        assert json.loads(adapter.format_additional_context("SessionStart", "remember this")) == {
            "hookSpecificOutput": {
                "additionalContext": "remember this",
            }
        }
