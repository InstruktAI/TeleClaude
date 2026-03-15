"""Characterization tests for teleclaude.utils.transcript._iterators."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

import teleclaude.utils.transcript._iterators as transcript_iterators
from teleclaude.core.agents import AgentName

pytestmark = pytest.mark.unit


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestJsonlIteration:
    def test_iter_jsonl_entries_skips_blank_and_invalid_lines(self, tmp_path: Path) -> None:
        transcript = tmp_path / "session.jsonl"
        transcript.write_text('{"id": 1}\n\nnot-json\n{"id": 2}\n', encoding="utf-8")

        entries = list(transcript_iterators._iter_jsonl_entries(transcript))

        assert entries == [{"id": 1}, {"id": 2}]

    def test_iter_jsonl_entries_tail_keeps_only_last_entries(self, tmp_path: Path) -> None:
        transcript = tmp_path / "session.jsonl"
        _write_lines(transcript, ['{"id": 1}', '{"id": 2}', '{"id": 3}'])

        entries = list(transcript_iterators._iter_jsonl_entries_tail(transcript, 2))

        assert entries == [{"id": 2}, {"id": 3}]

    def test_iter_jsonl_entries_tail_drops_partial_first_line(self, tmp_path: Path) -> None:
        transcript = tmp_path / "session.jsonl"
        content = '{"id": 1}\n{"id": 2}\n{"id": 3}\n'
        transcript.write_text(content, encoding="utf-8")
        start_index = content.index('{"id": 2}') + 4

        entries = list(
            transcript_iterators._iter_jsonl_entries_tail(
                transcript,
                5,
                max_bytes=len(content) - start_index,
            )
        )

        assert entries == [{"id": 3}]


class TestAgentSpecificIterators:
    def test_iter_codex_entries_skips_session_meta_rows(self, tmp_path: Path) -> None:
        transcript = tmp_path / "codex.jsonl"
        _write_lines(
            transcript,
            [
                '{"type": "session_meta", "payload": {"cwd": "/tmp/demo"}}',
                '{"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": []}}',
            ],
        )

        entries = list(transcript_iterators._iter_codex_entries(transcript))

        assert len(entries) == 1
        assert entries[0]["type"] == "response_item"

    def test_iter_gemini_entries_normalizes_user_assistant_and_tool_results(self, tmp_path: Path) -> None:
        transcript = tmp_path / "gemini.json"
        transcript.write_text(
            """
            {
              "messages": [
                {
                  "type": "user",
                  "timestamp": "2024-01-01T00:00:00Z",
                  "content": "Question"
                },
                {
                  "type": "gemini",
                  "timestamp": "2024-01-01T00:00:01Z",
                  "thoughts": [{"description": "Think"}],
                  "content": "Answer",
                  "toolCalls": [
                    {
                      "displayName": "search",
                      "args": {"q": "demo"},
                      "result": [{"functionResponse": {"response": {"output": "Hit"}}}]
                    },
                    {
                      "name": "fetch",
                      "args": {"url": "https://example.com"},
                      "resultDisplay": "Fallback"
                    }
                  ]
                }
              ]
            }
            """,
            encoding="utf-8",
        )

        entries = list(transcript_iterators._iter_gemini_entries(transcript))

        assert entries[0] == {
            "type": "user",
            "timestamp": "2024-01-01T00:00:00Z",
            "message": {"role": "user", "content": [{"type": "input_text", "text": "Question"}]},
        }
        assistant_message = cast(Mapping[str, object], entries[1]["message"])
        assistant_content = cast(list[Mapping[str, object]], assistant_message["content"])

        assert assistant_message["role"] == "assistant"
        assert [block["type"] for block in assistant_content] == [
            "thinking",
            "text",
            "tool_use",
            "tool_result",
            "tool_use",
            "tool_result",
        ]
        assert assistant_content[3]["content"] == "Hit"
        assert assistant_content[5]["content"] == "Fallback"


class TestStartIndexResolution:
    def test_returns_first_entry_after_timestamp(self) -> None:
        entries = [
            {"timestamp": "2024-01-01T00:00:00Z", "message": {"role": "assistant", "content": []}},
            {"timestamp": "2024-01-01T00:00:05Z", "message": {"role": "assistant", "content": []}},
        ]

        index = transcript_iterators._start_index_after_timestamp_or_rotation(
            entries,
            datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC),
            transcript_path="/tmp/demo.jsonl",
            agent_name=AgentName.CLAUDE,
            mode="render",
        )

        assert index == 1

    def test_uses_rotation_fallback_for_assistant_only_windows(self) -> None:
        entries = [
            {"timestamp": "2024-01-01T00:00:00Z", "message": {"role": "assistant", "content": []}},
            {"timestamp": "2024-01-01T00:00:05Z", "message": {"role": "assistant", "content": []}},
        ]

        index = transcript_iterators._start_index_after_timestamp_or_rotation(
            entries,
            datetime(2024, 1, 1, 1, 0, 0, tzinfo=UTC),
            transcript_path="/tmp/demo.jsonl",
            agent_name=AgentName.CODEX,
            mode="render",
        )

        assert index == 0
