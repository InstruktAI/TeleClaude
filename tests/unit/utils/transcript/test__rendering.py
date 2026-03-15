"""Characterization tests for teleclaude.utils.transcript._rendering."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import teleclaude.utils.transcript._rendering as transcript_rendering
from teleclaude.core.agents import AgentName

pytestmark = pytest.mark.unit


class TestRenderTranscriptFromEntries:
    def test_hides_thinking_and_tool_blocks_when_disabled(self) -> None:
        entries = [
            {
                "timestamp": "2024-01-01T12:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Answer"},
                        {"type": "thinking", "thinking": "Plan"},
                        {"type": "tool_use", "name": "bash", "input": {"command": "ls"}},
                        {"type": "tool_result", "content": "output"},
                    ],
                },
            }
        ]

        rendered = transcript_rendering._render_transcript_from_entries(
            entries,
            "Demo",
            None,
            None,
            0,
            include_thinking=False,
            include_tools=False,
        )

        assert rendered.startswith("# Demo")
        assert "Answer" in rendered
        assert "Plan" not in rendered
        assert "TOOL RESPONSE" not in rendered
        assert "**`bash`**" not in rendered


class TestRenderCleanAgentOutput:
    def test_starts_after_last_user_boundary_and_hides_tool_results(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        entries = [
            {
                "timestamp": "2024-01-01T11:59:59Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "Stale"}]},
            },
            {
                "timestamp": "2024-01-01T12:00:00Z",
                "message": {"role": "user", "content": [{"type": "input_text", "text": "Prompt"}]},
            },
            {
                "timestamp": "2024-01-01T12:00:01Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Answer"},
                        {"type": "thinking", "thinking": "Plan"},
                        {"type": "tool_use", "name": "bash", "input": {"command": "ls"}},
                        {"type": "tool_result", "content": "Hidden"},
                    ],
                },
            },
        ]
        monkeypatch.setattr(transcript_rendering, "_get_entries_for_agent", lambda transcript_path, agent_name: entries)

        rendered, last_entry_dt = transcript_rendering.render_clean_agent_output("/tmp/demo.jsonl", AgentName.CLAUDE)

        assert rendered is not None
        assert "Stale" not in rendered
        assert "Answer" in rendered
        assert "*Plan*" in rendered
        assert "**`bash`**: `ls`" in rendered
        assert "Hidden" not in rendered
        assert last_entry_dt == datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC)


class TestRenderAgentOutput:
    def test_includes_timestamps_tools_and_tool_results(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        entries = [
            {
                "timestamp": "2024-01-01T12:00:00Z",
                "message": {"role": "user", "content": [{"type": "input_text", "text": "Prompt"}]},
            },
            {
                "timestamp": "2024-01-01T12:00:01Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Answer"},
                        {"type": "thinking", "thinking": "Plan"},
                        {"type": "tool_use", "name": "bash", "input": {"command": "ls"}},
                        {"type": "tool_result", "content": "Output"},
                    ],
                },
            },
        ]
        monkeypatch.setattr(transcript_rendering, "_get_entries_for_agent", lambda transcript_path, agent_name: entries)

        rendered, last_entry_dt = transcript_rendering.render_agent_output(
            "/tmp/demo.jsonl",
            AgentName.CLAUDE,
            include_tools=True,
            include_tool_results=True,
            include_timestamps=True,
        )

        assert rendered is not None
        assert "[12:00:01] Answer" in rendered
        assert "[12:00:01] *Plan*" in rendered
        assert "[12:00:01] **`bash`**: `ls`" in rendered
        assert "[12:00:01] ✅ **TOOL RESPONSE:**" in rendered
        assert last_entry_dt == datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC)
