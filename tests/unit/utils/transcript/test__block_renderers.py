"""Characterization tests for teleclaude.utils.transcript._block_renderers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import teleclaude.utils.transcript._block_renderers as block_renderers

pytestmark = pytest.mark.unit


class TestIterAssistantBlocks:
    def test_yields_only_assistant_blocks_with_entry_timestamps(self) -> None:
        entries = [
            {
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "skip"}]},
            },
            {
                "timestamp": "2024-01-01T00:00:01Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "answer"}, {"type": "thinking", "thinking": "plan"}, "skip"],
                },
            },
        ]

        blocks = list(block_renderers.iter_assistant_blocks(entries))

        assert [block["type"] for block, _ in blocks] == ["text", "thinking"]
        assert all(timestamp == datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC) for _, timestamp in blocks)


class TestSkipFiltering:
    def test_should_skip_entry_honors_summary_and_timestamp_filters(self) -> None:
        since_dt = datetime(2024, 1, 1, 0, 0, 5, tzinfo=UTC)
        until_dt = datetime(2024, 1, 1, 0, 0, 10, tzinfo=UTC)

        assert block_renderers._should_skip_entry({"type": "summary"}, None, None) is True
        assert block_renderers._should_skip_entry({"timestamp": "2024-01-01T00:00:01Z"}, since_dt, None) is True
        assert block_renderers._should_skip_entry({"timestamp": "2024-01-01T00:00:11Z"}, None, until_dt) is True
        assert (
            block_renderers._should_skip_entry({"message": {"role": "assistant", "content": []}}, since_dt, None)
            is True
        )
        assert block_renderers._should_skip_entry({"timestamp": "2024-01-01T00:00:08Z"}, since_dt, until_dt) is False


class TestEntryProcessing:
    def test_process_entry_hides_thinking_and_tools_when_disabled(self) -> None:
        entry = {
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Answer"},
                    {"type": "thinking", "thinking": "Plan"},
                    {"type": "tool_use", "name": "bash", "input": {"command": "ls"}},
                    {"type": "tool_result", "content": "output"},
                ],
            }
        }
        lines: list[str] = []

        last_section = block_renderers._process_entry(
            entry,
            lines,
            None,
            collapse_tool_results=False,
            include_thinking=False,
            include_tools=False,
        )

        assert last_section == "assistant"
        assert lines == ["", "## 🤖 Assistant", "", "Answer"]

    def test_process_tool_use_block_sanitizes_name_and_subject(self) -> None:
        lines: list[str] = []
        block = {
            "name": "shell(run){payload}\nignored",
            "input": {"command": ("x" * 80) + "\nsecond-line"},
        }

        block_renderers._process_tool_use_block(block, "[12:00] ", lines)

        assert lines[-1].startswith("[12:00] **`shell`**: `")
        assert "ignored" not in lines[-1]
        assert "second-line" not in lines[-1]
        assert "…`" in lines[-1]

    @pytest.mark.parametrize(
        ("collapse_tool_results", "expected_lines"),
        [
            (
                True,
                ["T ✅ **TOOL RESPONSE (tap to reveal):**", "||line 1||", "|| ||", "||line 2||"],
            ),
            (
                False,
                ["T ✅ **TOOL RESPONSE:**", "> line 1", ">", "> line 2"],
            ),
        ],
    )
    def test_process_tool_result_block_renders_collapsed_or_expanded_forms(
        self,
        collapse_tool_results: bool,
        expected_lines: list[str],
    ) -> None:
        lines: list[str] = []

        block_renderers._process_tool_result_block(
            {"content": "line 1\n\nline 2"},
            "T ",
            lines,
            collapse_tool_results=collapse_tool_results,
        )

        assert all(line in lines for line in expected_lines)
