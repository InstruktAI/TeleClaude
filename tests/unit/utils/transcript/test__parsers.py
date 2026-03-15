"""Characterization tests for teleclaude.utils.transcript._parsers."""

from __future__ import annotations

import pytest

import teleclaude.utils.transcript._parsers as transcript_parsers

pytestmark = pytest.mark.unit


class TestExtractCodexReasoningText:
    def test_deduplicates_chunks_while_preserving_source_order(self) -> None:
        payload = {
            "summary": [{"text": "First"}, "Second", {"text": "First"}],
            "text": "Second",
            "content": [{"text": "Third"}, {"text": "First"}],
        }

        assert transcript_parsers._extract_codex_reasoning_text(payload) == "First\n\nSecond\n\nThird"


class TestNormalizeTranscriptEntryMessage:
    def test_returns_native_message_payload_unchanged(self) -> None:
        entry = {"message": {"role": "assistant", "content": "hello"}}

        assert transcript_parsers.normalize_transcript_entry_message(entry) == entry["message"]

    def test_maps_reasoning_payload_to_assistant_thinking_block(self) -> None:
        entry = {"type": "response_item", "payload": {"type": "reasoning", "summary": [{"text": "Plan"}]}}

        assert transcript_parsers.normalize_transcript_entry_message(entry) == {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": "Plan"}],
        }

    def test_accepts_message_like_payloads_without_explicit_message_type(self) -> None:
        payload = {"role": "assistant", "content": [{"type": "text", "text": "hello"}]}

        assert (
            transcript_parsers.normalize_transcript_entry_message({"type": "response_item", "payload": payload})
            == payload
        )

    def test_returns_none_for_empty_reasoning_or_unknown_entries(self) -> None:
        empty_reasoning = {"type": "response_item", "payload": {"type": "reasoning", "summary": []}}
        unknown = {"type": "response_item", "payload": {"type": "other"}}

        assert transcript_parsers.normalize_transcript_entry_message(empty_reasoning) is None
        assert transcript_parsers.normalize_transcript_entry_message(unknown) is None
