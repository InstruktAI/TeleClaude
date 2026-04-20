"""Characterization tests for teleclaude.utils.transcript._parsers."""

from __future__ import annotations

import pytest

import teleclaude.utils.transcript._parsers as transcript_parsers

pytestmark = pytest.mark.unit


class TestExtractCodexReasoningText:
    def test_extracts_text_and_content_skipping_dict_summary_items(self) -> None:
        payload = {
            "summary": [{"text": "Summary noise"}],  # dict items (API-native format) are skipped
            "text": "Direct text",
            "content": [{"text": "Content block"}],
        }

        # Dict-style summary items are skipped; string summary items, text, and content are extracted.
        assert transcript_parsers._extract_codex_reasoning_text(payload) == "Direct text\n\nContent block"

    def test_deduplicates_chunks_while_preserving_source_order(self) -> None:
        payload = {
            "text": "Second",
            "content": [{"text": "Third"}, {"text": "Second"}],
        }

        assert transcript_parsers._extract_codex_reasoning_text(payload) == "Second\n\nThird"


class TestNormalizeTranscriptEntryMessage:
    def test_returns_native_message_payload_unchanged(self) -> None:
        entry = {"message": {"role": "assistant", "content": "hello"}}

        assert transcript_parsers.normalize_transcript_entry_message(entry) == entry["message"]

    def test_maps_reasoning_with_text_to_thinking_block(self) -> None:
        entry = {"type": "response_item", "payload": {"type": "reasoning", "text": "Plan"}}

        assert transcript_parsers.normalize_transcript_entry_message(entry) == {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": "Plan"}],
        }

    def test_reasoning_with_only_summary_returns_none(self) -> None:
        """Summary-only reasoning payloads are noise — no displayable text."""
        entry = {"type": "response_item", "payload": {"type": "reasoning", "summary": [{"text": "Plan"}]}}

        assert transcript_parsers.normalize_transcript_entry_message(entry) is None

    def test_accepts_message_like_payloads_without_explicit_message_type(self) -> None:
        payload = {"role": "assistant", "content": [{"type": "text", "text": "hello"}]}

        assert (
            transcript_parsers.normalize_transcript_entry_message({"type": "response_item", "payload": payload})
            == payload
        )

    def test_returns_none_for_empty_reasoning_or_unknown_entries(self) -> None:
        empty_reasoning = {"type": "response_item", "payload": {"type": "reasoning"}}
        unknown = {"type": "response_item", "payload": {"type": "other"}}

        assert transcript_parsers.normalize_transcript_entry_message(empty_reasoning) is None
        assert transcript_parsers.normalize_transcript_entry_message(unknown) is None
