# guard: no-companion
"""Characterization tests for teleclaude.hooks.checkpoint public entrypoints.

This file intentionally stays narrow and focused for checkpoint coverage.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from teleclaude.core.agents import AgentName
from teleclaude.hooks.checkpoint import (
    CheckpointContext,
    CheckpointResult,
    TurnTimeline,
    get_checkpoint_content,
    run_heuristics,
)


class TestGetCheckpointContent:
    @pytest.mark.unit
    def test_uses_effective_turn_timeline_for_codex(self) -> None:
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        result = CheckpointResult(
            categories=["python"],
            required_actions=["Run targeted tests for changed behavior"],
            observations=[],
            is_all_clear=False,
        )

        with (
            patch("teleclaude.hooks.checkpoint._is_checkpoint_project_supported", return_value=True),
            patch(
                "teleclaude.hooks.checkpoint.extract_effective_tool_calls",
                return_value=timeline,
            ) as extract_effective_mock,
            patch(
                "teleclaude.hooks.checkpoint._extract_turn_file_signals",
                return_value=({"src/app.py"}, True),
            ) as extract_files_mock,
            patch("teleclaude.hooks.checkpoint.run_heuristics", return_value=result),
        ):
            checkpoint_text = get_checkpoint_content(
                transcript_path="/tmp/parent.jsonl",
                agent_name=AgentName.CODEX,
                project_path="/repo",
                native_session_id="parent-thread",
                working_slug="demo-slug",
                elapsed_since_turn_start_s=90,
            )

        extract_effective_mock.assert_called_once_with(
            "/tmp/parent.jsonl",
            AgentName.CODEX,
            native_session_id="parent-thread",
            scope="turn",
        )
        extract_files_mock.assert_called_once_with(timeline, "/repo")
        assert checkpoint_text is not None
        assert "Run targeted tests for changed behavior" in checkpoint_text


class TestRunHeuristics:
    @pytest.mark.unit
    def test_test_quality_review_gate_fires_for_test_only_diffs(self) -> None:
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path="/repo")

        result = run_heuristics(["tests/unit/test_foo.py"], timeline, context)

        assert any("test policy" in action for action in result.required_actions)
