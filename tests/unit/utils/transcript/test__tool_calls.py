# pyright: reportUnknownLambdaType=false
"""Characterization tests for teleclaude.utils.transcript._tool_calls."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

import teleclaude.utils.transcript._tool_calls as transcript_tool_calls
from teleclaude.core.agents import AgentName
from teleclaude.core.codex_transcript import CodexTranscriptMeta

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

    def test_extract_tool_calls_current_turn_maps_codex_patch_apply_end_to_apply_patch(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        entries = [
            {"message": {"role": "user", "content": [{"type": "input_text", "text": "Prompt"}]}},
            {
                "timestamp": "2024-01-01T12:00:03Z",
                "type": "event_msg",
                "payload": {
                    "type": "patch_apply_end",
                    "success": True,
                    "stdout": "Success. Updated the following files:\nM src/kept.py\n",
                    "changes": {
                        "/repo/src/kept.py": {"type": "update"},
                        "/repo/tests/test_kept.py": {"type": "update"},
                    },
                },
            },
        ]
        monkeypatch.setattr(
            transcript_tool_calls,
            "_get_entries_for_agent",
            lambda transcript_path, agent_name, tail_entries=None: entries,
        )

        timeline = transcript_tool_calls.extract_tool_calls_current_turn("/tmp/demo.jsonl", AgentName.CODEX)

        assert timeline.tool_calls == [
            transcript_tool_calls.ToolCallRecord(
                tool_name="apply_patch",
                input_data={"paths": ["/repo/src/kept.py", "/repo/tests/test_kept.py"]},
                had_error=False,
                result_snippet="Success. Updated the following files:\nM src/kept.py\n",
                timestamp=datetime(2024, 1, 1, 12, 0, 3, tzinfo=UTC),
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


class TestEffectiveToolCallExtraction:
    def test_extract_effective_tool_calls_unions_codex_family_for_session_scope(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        parent_meta = CodexTranscriptMeta(
            transcript_path="/tmp/parent.jsonl",
            thread_id="parent-thread",
            parent_thread_id=None,
            session_started_at=datetime(2026, 3, 20, 7, 0, tzinfo=UTC),
        )
        child_meta = CodexTranscriptMeta(
            transcript_path="/tmp/child.jsonl",
            thread_id="child-thread",
            parent_thread_id="parent-thread",
            session_started_at=datetime(2026, 3, 20, 7, 1, tzinfo=UTC),
        )

        timelines = {
            ("/tmp/parent.jsonl", True): transcript_tool_calls.TurnTimeline(
                tool_calls=[
                    transcript_tool_calls.ToolCallRecord(
                        tool_name="read_file",
                        input_data={"path": "parent.py"},
                        timestamp=datetime(2026, 3, 20, 7, 0, 10, tzinfo=UTC),
                    )
                ],
                has_data=True,
            ),
            ("/tmp/child.jsonl", True): transcript_tool_calls.TurnTimeline(
                tool_calls=[
                    transcript_tool_calls.ToolCallRecord(
                        tool_name="apply_patch",
                        input_data={"path": "child.py"},
                        timestamp=datetime(2026, 3, 20, 7, 1, 10, tzinfo=UTC),
                    )
                ],
                has_data=True,
            ),
        }

        monkeypatch.setattr(
            transcript_tool_calls,
            "discover_codex_transcript_family_meta",
            lambda **kwargs: [parent_meta, child_meta],
        )
        monkeypatch.setattr(
            transcript_tool_calls,
            "_extract_tool_calls_for_scope",
            lambda transcript_path, agent_name, full_session=False: timelines[(transcript_path, full_session)],
        )

        timeline = transcript_tool_calls.extract_effective_tool_calls(
            "/tmp/parent.jsonl",
            AgentName.CODEX,
            native_session_id="parent-thread",
            scope="session",
        )

        assert [record.input_data for record in timeline.tool_calls] == [{"path": "parent.py"}, {"path": "child.py"}]
        assert timeline.has_data is True

    def test_extract_effective_tool_calls_filters_codex_children_before_parent_turn(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        parent_turn_start = datetime(2026, 3, 20, 7, 5, tzinfo=UTC)
        parent_meta = CodexTranscriptMeta(
            transcript_path="/tmp/parent.jsonl",
            thread_id="parent-thread",
            parent_thread_id=None,
            session_started_at=datetime(2026, 3, 20, 7, 0, tzinfo=UTC),
        )
        old_child_meta = CodexTranscriptMeta(
            transcript_path="/tmp/old-child.jsonl",
            thread_id="old-child-thread",
            parent_thread_id="parent-thread",
            session_started_at=datetime(2026, 3, 20, 7, 4, 59, tzinfo=UTC),
        )
        new_child_meta = CodexTranscriptMeta(
            transcript_path="/tmp/new-child.jsonl",
            thread_id="new-child-thread",
            parent_thread_id="parent-thread",
            session_started_at=datetime(2026, 3, 20, 7, 5, 1, tzinfo=UTC),
        )

        timelines = {
            ("/tmp/parent.jsonl", False): transcript_tool_calls.TurnTimeline(
                tool_calls=[
                    transcript_tool_calls.ToolCallRecord(
                        tool_name="spawn_agent",
                        input_data={"path": "parent.py"},
                        timestamp=datetime(2026, 3, 20, 7, 5, 2, tzinfo=UTC),
                    )
                ],
                has_data=True,
                turn_start_at=parent_turn_start,
            ),
            ("/tmp/new-child.jsonl", True): transcript_tool_calls.TurnTimeline(
                tool_calls=[
                    transcript_tool_calls.ToolCallRecord(
                        tool_name="apply_patch",
                        input_data={"path": "new-child.py"},
                        timestamp=datetime(2026, 3, 20, 7, 5, 3, tzinfo=UTC),
                    )
                ],
                has_data=True,
            ),
        }

        monkeypatch.setattr(
            transcript_tool_calls,
            "discover_codex_transcript_family_meta",
            lambda **kwargs: [parent_meta, old_child_meta, new_child_meta],
        )
        monkeypatch.setattr(
            transcript_tool_calls,
            "_extract_tool_calls_for_scope",
            lambda transcript_path, agent_name, full_session=False: timelines[(transcript_path, full_session)],
        )

        timeline = transcript_tool_calls.extract_effective_tool_calls(
            "/tmp/parent.jsonl",
            AgentName.CODEX,
            native_session_id="parent-thread",
            scope="turn",
        )

        assert [record.input_data for record in timeline.tool_calls] == [
            {"path": "parent.py"},
            {"path": "new-child.py"},
        ]
        assert timeline.turn_start_at == parent_turn_start


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
