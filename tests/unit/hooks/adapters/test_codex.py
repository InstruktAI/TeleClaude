"""Characterization tests for teleclaude.hooks.adapters.codex."""

from __future__ import annotations

import argparse

import pytest

from teleclaude.hooks.adapters.codex import CodexAdapter


class TestCodexAdapter:
    @pytest.mark.unit
    def test_parse_input_reads_json_from_event_type_and_forces_agent_stop(self) -> None:
        adapter = CodexAdapter()

        raw_input, event_type, raw_data = adapter.parse_input(
            argparse.Namespace(
                event_type='{"thread-id":"thread-1","input-messages":["hi","follow up"],"last-assistant-message":"done"}'
            )
        )

        assert (
            raw_input == '{"thread-id":"thread-1","input-messages":["hi","follow up"],"last-assistant-message":"done"}'
        )
        assert event_type == "agent_stop"
        assert raw_data == {
            "thread-id": "thread-1",
            "input-messages": ["hi", "follow up"],
            "last-assistant-message": "done",
        }

    @pytest.mark.unit
    def test_parse_input_rejects_non_object_json_payloads(self) -> None:
        adapter = CodexAdapter()

        with pytest.raises(ValueError, match="JSON object"):
            adapter.parse_input(argparse.Namespace(event_type='["not","an","object"]'))

    @pytest.mark.unit
    def test_normalize_payload_maps_kebab_case_fields_to_internal_names(self) -> None:
        adapter = CodexAdapter()

        normalized = adapter.normalize_payload(
            {
                "thread-id": "thread-1",
                "input-messages": ["hi", "follow up"],
                "last-assistant-message": "done",
                "workspace-id": "workspace-1",
            }
        )

        assert normalized == {
            "session_id": "thread-1",
            "prompt": "follow up",
            "message": "done",
            "workspace-id": "workspace-1",
        }

    @pytest.mark.unit
    def test_checkpoint_and_memory_formatters_return_empty_outputs(self) -> None:
        adapter = CodexAdapter()

        assert adapter.format_checkpoint_response("blocked") is None
        assert adapter.format_memory_injection("context") == ""
