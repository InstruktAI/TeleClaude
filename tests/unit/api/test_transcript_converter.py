"""Characterization tests for transcript SSE conversion helpers."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from teleclaude.api import transcript_converter
from teleclaude.core.models import JsonDict


def _parse_sse_payload(event: str) -> JsonDict:
    prefix = "data: "
    assert event.startswith(prefix)
    payload = event.removeprefix(prefix).strip()
    loaded = json.loads(payload)
    assert isinstance(loaded, dict)
    return loaded


class TestTranscriptConverter:
    @pytest.mark.unit
    def test_message_lifecycle_helpers_preserve_explicit_message_id(self) -> None:
        """Message lifecycle helpers keep a caller-supplied message identifier."""
        start_payload = _parse_sse_payload(transcript_converter.message_start("msg-123"))
        finish_payload = _parse_sse_payload(transcript_converter.message_finish("msg-123"))

        assert start_payload == {"type": "start", "messageId": "msg-123"}
        assert finish_payload == {"type": "finish", "messageId": "msg-123"}

    @pytest.mark.unit
    def test_convert_text_block_emits_delta_between_start_and_end(self) -> None:
        """Text blocks become ordered start, delta, and end SSE events."""
        events = list(transcript_converter.convert_text_block({"text": "hello"}))
        payloads = [_parse_sse_payload(event) for event in events]

        assert [payload["type"] for payload in payloads] == ["text-start", "text-delta", "text-end"]
        assert payloads[1]["delta"] == "hello"
        assert payloads[0]["id"] == payloads[1]["id"] == payloads[2]["id"]

    @pytest.mark.unit
    def test_convert_projected_block_ignores_unknown_block_types(self) -> None:
        """Projected blocks with unsupported types do not emit SSE events."""
        projected = SimpleNamespace(block_type="compaction", block={"text": "ignored"})

        assert list(transcript_converter.convert_projected_block(projected)) == []

    @pytest.mark.unit
    def test_convert_entry_serializes_only_assistant_content_blocks(self) -> None:
        """Entry conversion skips non-assistant messages and emits assistant block events."""
        assistant_entry = {
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "hi"},
                    {"type": "tool_result", "tool_use_id": "tool-1", "content": {"ok": True}},
                ],
            }
        }
        user_entry = {"message": {"role": "user", "content": [{"type": "text", "text": "skip"}]}}

        payloads = [_parse_sse_payload(event) for event in transcript_converter.convert_entry(assistant_entry)]

        assert list(transcript_converter.convert_entry(user_entry)) == []
        assert [payload["type"] for payload in payloads] == [
            "text-start",
            "text-delta",
            "text-end",
            "tool-output-available",
        ]
        assert payloads[-1]["toolCallId"] == "tool-1"
