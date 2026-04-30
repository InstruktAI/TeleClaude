"""Characterization tests for teleclaude.hooks.adapters.codex."""

from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from teleclaude.hooks.adapters.codex import CodexAdapter


class TestCodexAdapter:
    @pytest.mark.unit
    def test_parse_input_falls_back_to_hook_event_name_from_stdin(self) -> None:
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
            _raw_input, event_type, _raw_data = adapter.parse_input(argparse.Namespace(event_type=None))

        assert event_type == "UserPromptSubmit"

    @pytest.mark.unit
    def test_normalize_payload_maps_codex_aliases_to_internal_names(self) -> None:
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

        assert normalized["prompt"] == "follow up"
        assert normalized["message"] == "done"
        assert "user_prompt" not in normalized
        assert "last_assistant_message" not in normalized
