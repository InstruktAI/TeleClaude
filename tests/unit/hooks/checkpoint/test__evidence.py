"""Characterization tests for teleclaude.hooks.checkpoint._evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.hooks.checkpoint._evidence import (
    _check_edit_hygiene,
    _check_error_state,
    _check_slug_alignment,
    _compute_log_since_window,
    _dedupe_strings,
    _extract_plan_file_paths,
    _has_evidence,
    _has_status_evidence,
)
from teleclaude.hooks.checkpoint._models import CheckpointContext
from teleclaude.utils.transcript import ToolCallRecord, TurnTimeline


def _shell_record(command: str, *, had_error: bool = False, result_snippet: str = "") -> ToolCallRecord:
    return ToolCallRecord(
        tool_name="functions.exec_command",
        input_data={"cmd": command},
        had_error=had_error,
        result_snippet=result_snippet,
    )


class TestEvidenceChecks:
    @pytest.mark.unit
    def test_has_evidence_only_counts_successful_shell_commands(self) -> None:
        failed_timeline = TurnTimeline(tool_calls=[_shell_record("pytest tests/unit/hooks/test_x.py", had_error=True)])
        successful_timeline = TurnTimeline(tool_calls=[_shell_record("uv run pytest tests/unit/hooks/test_x.py")])

        assert _has_evidence(failed_timeline, ["pytest"]) is False
        assert _has_evidence(successful_timeline, ["pytest"]) is True

    @pytest.mark.unit
    def test_status_evidence_requires_make_status_after_make_restart(self) -> None:
        restart_after_status = TurnTimeline(tool_calls=[_shell_record("make status"), _shell_record("make restart")])
        status_after_restart = TurnTimeline(tool_calls=[_shell_record("make restart"), _shell_record("make status")])

        assert _has_status_evidence(restart_after_status) is False
        assert _has_status_evidence(status_after_restart) is True

    @pytest.mark.unit
    def test_check_error_state_ignores_search_commands_that_exit_with_no_matches(self) -> None:
        timeline = TurnTimeline(
            tool_calls=[
                _shell_record(
                    "rg missing-pattern teleclaude/hooks",
                    had_error=True,
                    result_snippet="Process exited with code 1",
                )
            ]
        )

        assert _check_error_state(timeline) == []

    @pytest.mark.unit
    def test_check_error_state_reports_unresolved_failed_test_commands(self) -> None:
        timeline = TurnTimeline(
            tool_calls=[
                _shell_record(
                    "pytest tests/unit/hooks/test_inbound.py",
                    had_error=True,
                    result_snippet="assert 0",
                )
            ]
        )

        assert len(_check_error_state(timeline)) == 1


class TestEditHygieneAndSlugAlignment:
    @pytest.mark.unit
    def test_check_edit_hygiene_flags_edits_without_reads_and_wide_blast_radius(self) -> None:
        timeline = TurnTimeline(
            tool_calls=[
                ToolCallRecord(tool_name="edit", input_data={"file_path": "teleclaude/hooks/inbound.py"}),
            ]
        )
        git_files = [
            "teleclaude/hooks/inbound.py",
            "tests/unit/hooks/test_inbound.py",
            "docs/guide.md",
            "frontend/src/App.tsx",
        ]

        assert len(_check_edit_hygiene(timeline, git_files)) == 2

    @pytest.mark.unit
    def test_check_slug_alignment_uses_files_from_the_plan_table(self, tmp_path: Path) -> None:
        plan_path = tmp_path / "todos" / "chartest-hooks" / "implementation-plan.md"
        plan_path.parent.mkdir(parents=True)
        plan_text = (
            "# Implementation Plan\n\n"
            "## Files to Change\n"
            "| File | Change |\n"
            "| --- | --- |\n"
            "| `teleclaude/hooks/inbound.py` | Add tests |\n"
            "| `tests/unit/hooks/test_inbound.py` | Add coverage |\n"
        )
        plan_path.write_text(plan_text, encoding="utf-8")
        context = CheckpointContext(
            agent_name="claude",
            project_path=str(tmp_path),
            working_slug="chartest-hooks",
        )

        assert _extract_plan_file_paths(plan_text) == {
            "teleclaude/hooks/inbound.py",
            "tests/unit/hooks/test_inbound.py",
        }
        assert len(_check_slug_alignment(["docs/guide.md"], context)) == 1
        assert _check_slug_alignment(["tests/unit/hooks/test_inbound.py"], context) == []


class TestEvidenceUtilities:
    @pytest.mark.unit
    def test_dedupe_strings_preserves_first_seen_order(self) -> None:
        assert _dedupe_strings(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]

    @pytest.mark.unit
    def test_compute_log_since_window_uses_two_minute_floor_and_rounds_up(self) -> None:
        assert _compute_log_since_window(None) == "2m"
        assert _compute_log_since_window(61) == "2m"
        assert _compute_log_since_window(121) == "3m"
