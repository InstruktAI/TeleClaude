"""Characterization tests for teleclaude.hooks.adapters.codex."""

from __future__ import annotations

import argparse
import json
from unittest.mock import patch

import pytest

from teleclaude.hooks.adapters.codex import CodexAdapter


class TestCodexAdapter:
    @pytest.mark.unit
    def test_parse_input_reads_json_from_receiver_stdin_and_uses_hook_event_name(self) -> None:
        adapter = CodexAdapter()

        with patch(
            "teleclaude.hooks.adapters.base.read_stdin_payload",
            return_value=(
                '{"session_id":"thread-1","hook_event_name":"UserPromptSubmit","user_prompt":"follow up"}',
                {
                    "session_id": "thread-1",
                    "hook_event_name": "UserPromptSubmit",
                    "user_prompt": "follow up",
                },
            ),
        ):
            raw_input, event_type, raw_data = adapter.parse_input(argparse.Namespace(event_type=None))

        assert raw_input == '{"session_id":"thread-1","hook_event_name":"UserPromptSubmit","user_prompt":"follow up"}'
        assert event_type == "UserPromptSubmit"
        assert raw_data == {
            "session_id": "thread-1",
            "hook_event_name": "UserPromptSubmit",
            "user_prompt": "follow up",
        }

    @pytest.mark.unit
    def test_parse_input_rejects_non_object_json_payloads(self) -> None:
        adapter = CodexAdapter()

        with pytest.raises(ValueError, match="JSON object"):
            with patch(
                "teleclaude.hooks.adapters.base.read_stdin_payload",
                return_value=('["not","an","object"]', ["not", "an", "object"]),
            ):
                adapter.parse_input(argparse.Namespace(event_type=None))

    @pytest.mark.unit
    def test_normalize_payload_maps_common_hook_fields_to_internal_names(self) -> None:
        adapter = CodexAdapter()

        normalized = adapter.normalize_payload(
            {
                "session_id": "thread-1",
                "transcript_path": "/tmp/rollout.jsonl",
                "user_prompt": "follow up",
                "last_assistant_message": "done",
                "cwd": "/repo",
            }
        )

        assert normalized == {
            "session_id": "thread-1",
            "transcript_path": "/tmp/rollout.jsonl",
            "prompt": "follow up",
            "message": "done",
            "cwd": "/repo",
        }

    @pytest.mark.unit
    def test_checkpoint_and_additional_context_formatters_match_current_codex_behavior(self) -> None:
        adapter = CodexAdapter()

        assert json.loads(adapter.format_checkpoint_response("blocked") or "") == {
            "decision": "block",
            "reason": "blocked",
        }
        assert adapter.format_additional_context("UserPromptSubmit", "context") == ""
