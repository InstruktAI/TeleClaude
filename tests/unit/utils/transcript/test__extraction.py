"""Characterization tests for teleclaude.utils.transcript._extraction."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import teleclaude.utils.transcript._extraction as transcript_extraction
from teleclaude.core.agents import AgentName

pytestmark = pytest.mark.unit


class TestAssistantMessages:
    def test_get_assistant_messages_since_defaults_to_last_user_boundary(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        entries = [
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "old"}]}},
            {"message": {"role": "user", "content": [{"type": "input_text", "text": "prompt"}]}},
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "new"}]}},
        ]
        monkeypatch.setattr(
            transcript_extraction, "_get_entries_for_agent", lambda transcript_path, agent_name: entries
        )

        messages = transcript_extraction.get_assistant_messages_since("/tmp/demo.jsonl", AgentName.CLAUDE)

        assert messages == [{"role": "assistant", "content": [{"type": "text", "text": "new"}]}]

    def test_count_renderable_assistant_blocks_respects_tool_flags(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            transcript_extraction,
            "get_assistant_messages_since",
            lambda transcript_path, agent_name, since_timestamp=None: [
                {
                    "content": [
                        {"type": "text", "text": "Answer"},
                        {"type": "thinking", "thinking": "Plan"},
                        {"type": "tool_use", "name": "bash"},
                        {"type": "tool_result", "content": "Output"},
                    ]
                }
            ],
        )

        assert transcript_extraction.count_renderable_assistant_blocks("/tmp/demo.jsonl", AgentName.CLAUDE) == 2
        assert (
            transcript_extraction.count_renderable_assistant_blocks(
                "/tmp/demo.jsonl",
                AgentName.CLAUDE,
                include_tools=True,
                include_tool_results=True,
            )
            == 4
        )


class TestLastMessageExtraction:
    def test_extracts_last_messages_and_user_timestamp(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        entries = [
            {"timestamp": "2024-01-01T12:00:00Z", "message": {"role": "user", "content": "First prompt"}},
            {
                "timestamp": "2024-01-01T12:00:01Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "First answer"}]},
            },
            {"timestamp": "2024-01-01T12:00:02Z", "message": {"role": "user", "content": "Latest prompt"}},
            {
                "timestamp": "2024-01-01T12:00:03Z",
                "message": {"role": "assistant", "content": [{"type": "output_text", "text": "Latest answer"}]},
            },
        ]
        monkeypatch.setattr(
            transcript_extraction, "_get_entries_for_agent", lambda transcript_path, agent_name: entries
        )

        assert transcript_extraction.extract_last_user_message("/tmp/demo.jsonl", AgentName.CLAUDE) == "Latest prompt"
        assert (
            transcript_extraction.extract_last_agent_message("/tmp/demo.jsonl", AgentName.CLAUDE, count=2)
            == "First answer\n\nLatest answer"
        )
        assert transcript_extraction.extract_last_user_message_with_timestamp("/tmp/demo.jsonl", AgentName.CLAUDE) == (
            "Latest prompt",
            datetime(2024, 1, 1, 12, 0, 2, tzinfo=UTC),
        )

    def test_extract_recent_transcript_turns_limits_each_role_and_preserves_order(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            transcript_extraction,
            "collect_transcript_messages",
            lambda transcript_path, agent_name: [
                ("user", "u1"),
                ("assistant", "a1"),
                ("user", "u2"),
                ("assistant", "a2"),
                ("user", "u3"),
                ("assistant", "a3"),
            ],
        )

        turns = transcript_extraction.extract_recent_transcript_turns(
            "/tmp/demo.jsonl",
            AgentName.CLAUDE,
            max_turns_per_role=2,
        )

        assert turns == [("user", "u2"), ("assistant", "a2"), ("user", "u3"), ("assistant", "a3")]


class TestSessionParsing:
    def test_parse_session_transcript_uses_codex_tail_limit_and_escapes_backticks(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        transcript = tmp_path / "session.jsonl"
        transcript.write_text("{}", encoding="utf-8")
        captured: dict[str, Any] = {}  # guard: loose-dict - Test helper payloads intentionally vary by scenario.
        monkeypatch.setattr(transcript_extraction, "_iter_codex_entries", lambda path: iter(()))

        def fake_render(
            entries: object,
            title: str,
            since_timestamp: datetime | None,
            until_timestamp: datetime | None,
            tail_chars: int | None,
            **kwargs: object,
        ) -> str:
            captured["tail_limit_fn"] = kwargs["tail_limit_fn"]
            return "```demo```"

        monkeypatch.setattr(transcript_extraction, "_render_transcript_from_entries", fake_render)

        rendered = transcript_extraction.parse_session_transcript(
            str(transcript),
            "Demo",
            agent_name=AgentName.CODEX,
            escape_triple_backticks=True,
        )

        assert captured["tail_limit_fn"] is transcript_extraction._apply_tail_limit_codex
        assert rendered == "`\u200b``demo`\u200b``"


class TestWorkdirExtraction:
    def test_extract_workdir_from_transcript_prefers_explicit_jsonl_metadata(self, tmp_path: Path) -> None:
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(
            '{"type": "session_meta", "payload": {"environment": {"workingDirectory": "/tmp/project"}}}\n',
            encoding="utf-8",
        )

        assert transcript_extraction.extract_workdir_from_transcript(str(transcript)) == "/tmp/project"

    def test_extract_workdir_from_transcript_derives_common_path_from_json(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        transcript = tmp_path / "session.json"
        transcript.write_text(
            (f'{{"entries": ["{project_root / "src" / "a.py"}", "{project_root / "tests" / "test_a.py"}"]}}'),
            encoding="utf-8",
        )

        assert transcript_extraction.extract_workdir_from_transcript(str(transcript)) == str(project_root)
