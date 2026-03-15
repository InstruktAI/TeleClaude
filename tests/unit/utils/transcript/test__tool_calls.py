"""Characterization tests for teleclaude.utils.transcript._tool_calls."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

import teleclaude.utils.transcript._tool_calls as transcript_tool_calls
from teleclaude.core.agents import AgentName

pytestmark = pytest.mark.unit


class TestFunctionCallParsing:
    @pytest.mark.parametrize(
        ("raw_arguments", "expected"),
        [
            ({"path": "/tmp/demo"}, {"path": "/tmp/demo"}),
            ('{"path": "/tmp/demo"}', {"path": "/tmp/demo"}),
            ("not-json", {"raw_arguments": "not-json"}),
        ],
    )
    def test_parse_function_call_arguments_normalizes_supported_shapes(
        self,
        raw_arguments: object,
        expected: dict[str, Any],  # guard: loose-dict - Test helper payloads intentionally vary by scenario.
    ) -> None:
        assert dict(transcript_tool_calls._parse_function_call_arguments(raw_arguments)) == expected

    def test_find_turn_start_idx_skips_user_tool_result_only_messages(self) -> None:
        entries = [
            {"message": {"role": "user", "content": [{"type": "input_text", "text": "Prompt"}]}},
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "Answer"}]}},
            {"message": {"role": "user", "content": [{"type": "tool_result", "content": "Output"}]}},
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "Later"}]}},
        ]

        assert transcript_tool_calls._is_user_tool_result_only_message(entries[2]["message"]) is True
        assert transcript_tool_calls._find_turn_start_idx(entries, full_session=False) == 1


class TestCurrentTurnExtraction:
    def test_extract_tool_calls_current_turn_matches_function_call_with_output(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        entries = [
            {"message": {"role": "user", "content": [{"type": "input_text", "text": "Prompt"}]}},
            {
                "timestamp": "2024-01-01T12:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "read_file",
                    "call_id": "call-1",
                    "arguments": '{"path": "/tmp/demo.txt"}',
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": "completed successfully",
                },
            },
        ]
        monkeypatch.setattr(
            transcript_tool_calls,
            "_get_entries_for_agent",
            lambda transcript_path, agent_name, tail_entries=None: entries,
        )

        timeline = transcript_tool_calls.extract_tool_calls_current_turn("/tmp/demo.jsonl", AgentName.CODEX)

        assert timeline.has_data is True
        assert timeline.tool_calls == [
            transcript_tool_calls.ToolCallRecord(
                tool_name="read_file",
                input_data={"path": "/tmp/demo.txt"},
                had_error=False,
                result_snippet="completed successfully",
                timestamp=datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC),
            )
        ]

    def test_extract_tool_calls_current_turn_flushes_pending_tool_use_without_result(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        entries = [
            {"message": {"role": "user", "content": [{"type": "input_text", "text": "Prompt"}]}},
            {
                "timestamp": "2024-01-01T12:00:02Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "name": "bash", "input": {"command": "ls"}}],
                },
            },
        ]
        monkeypatch.setattr(
            transcript_tool_calls,
            "_get_entries_for_agent",
            lambda transcript_path, agent_name, tail_entries=None: entries,
        )

        timeline = transcript_tool_calls.extract_tool_calls_current_turn("/tmp/demo.jsonl", AgentName.CLAUDE)

        assert timeline.tool_calls == [
            transcript_tool_calls.ToolCallRecord(
                tool_name="bash",
                input_data={"command": "ls"},
                had_error=False,
                result_snippet="",
                timestamp=datetime(2024, 1, 1, 12, 0, 2, tzinfo=UTC),
            )
        ]

    def test_extract_tool_calls_current_turn_fails_open_when_loading_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def raise_error(
            transcript_path: str, agent_name: AgentName, tail_entries: int | None = None
        ) -> list[dict[str, Any]]:  # guard: loose-dict - Test helper payloads intentionally vary by scenario.
            raise RuntimeError("boom")

        monkeypatch.setattr(transcript_tool_calls, "_get_entries_for_agent", raise_error)

        timeline = transcript_tool_calls.extract_tool_calls_current_turn("/tmp/demo.jsonl", AgentName.CODEX)

        assert timeline == transcript_tool_calls.TurnTimeline(tool_calls=[], has_data=False)


class TestStructuredMessageExtraction:
    def test_extract_structured_messages_emits_compaction_and_visible_blocks(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        entries = [
            {"timestamp": "2024-01-01T12:00:00Z", "message": {"role": "user", "content": "Prompt"}},
            {
                "timestamp": "2024-01-01T12:00:01Z",
                "parentUuid": "parent-1",
                "message": {"role": "system", "content": []},
            },
            {
                "timestamp": "2024-01-01T12:00:02Z",
                "message": {"role": "user", "content": [{"type": "tool_result", "content": "Tool output"}]},
            },
            {
                "timestamp": "2024-01-01T12:00:03Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "Plan"},
                        {"type": "text", "text": "Answer"},
                        {"type": "tool_use", "name": "search", "input": {"q": "demo"}},
                    ],
                },
            },
        ]
        monkeypatch.setattr(
            transcript_tool_calls, "_get_entries_for_agent", lambda transcript_path, agent_name: entries
        )

        messages = transcript_tool_calls.extract_structured_messages(
            "/tmp/demo.jsonl",
            AgentName.CLAUDE,
            include_tools=True,
            include_thinking=True,
        )

        assert [(message.role, message.type, message.text) for message in messages] == [
            ("user", "text", "Prompt"),
            ("system", "compaction", "Context compacted"),
            ("assistant", "tool_result", "Tool output"),
            ("assistant", "thinking", "Plan"),
            ("assistant", "text", "Answer"),
            ("assistant", "tool_use", 'search: {"q": "demo"}'),
        ]

    def test_extract_messages_from_chain_adds_file_index(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            transcript_tool_calls,
            "extract_structured_messages",
            lambda file_path, agent_name, since=None, include_tools=False, include_thinking=False: [
                transcript_tool_calls.StructuredMessage(
                    role="assistant",
                    type="text",
                    text=file_path,
                )
            ],
        )

        messages = transcript_tool_calls.extract_messages_from_chain(
            ["/tmp/one.jsonl", "/tmp/two.jsonl"],
            AgentName.CLAUDE,
        )

        assert messages == [
            {
                "role": "assistant",
                "type": "text",
                "text": "/tmp/one.jsonl",
                "timestamp": None,
                "entry_index": 0,
                "file_index": 0,
            },
            {
                "role": "assistant",
                "type": "text",
                "text": "/tmp/two.jsonl",
                "timestamp": None,
                "entry_index": 0,
                "file_index": 1,
            },
        ]
