"""Characterization tests for teleclaude.hooks.checkpoint._evidence.

Patches _evidence.get_todos_db_sync (consumer-module local).
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.constants import CHECKPOINT_FILE_CATEGORIES
from teleclaude.hooks.checkpoint._evidence import (
    _check_edit_hygiene,
    _check_error_state,
    _check_slug_alignment,
    _compute_log_since_window,
    _dedupe_strings,
    _extract_plan_file_paths,
    _has_commit_evidence,
    _has_commit_evidence_after_last_mutation,
    _has_evidence,
    _has_status_evidence,
    _segment_matches_evidence,
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

        assert not _check_error_state(timeline)

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

    @pytest.mark.unit
    def test_check_error_state_clears_failed_tests_after_later_successful_test_run(self) -> None:
        timeline = TurnTimeline(
            tool_calls=[
                _shell_record(
                    "pytest tests/unit/hooks/checkpoint/test__init__.py tests/unit/utils/transcript/test__tool_calls.py",
                    had_error=True,
                    result_snippet="FAILED tests/unit/hooks/checkpoint/test__init__.py",
                ),
                _shell_record(
                    "pytest tests/unit/hooks/checkpoint/test__init__.py::TestGetCheckpointContent::"
                    "test_checkpoint_cycle_suppresses_docs_only_no_action_changes "
                    "tests/unit/utils/transcript/test__tool_calls.py::TestEffectiveToolCallExtraction::"
                    "test_extract_effective_tool_calls_filters_codex_children_before_checkpoint",
                    result_snippet="2 passed",
                ),
            ]
        )

        assert _check_error_state(timeline) == []

    @pytest.mark.unit
    def test_check_error_state_does_not_clear_failed_tests_with_unrelated_test_run(self) -> None:
        timeline = TurnTimeline(
            tool_calls=[
                _shell_record(
                    "pytest tests/unit/a_test.py",
                    had_error=True,
                    result_snippet="FAILED tests/unit/a_test.py",
                ),
                _shell_record("pytest tests/unit/b_test.py", result_snippet="1 passed"),
            ]
        )

        assert _check_error_state(timeline) == ["Test failures remain — re-run tests after fixes"]

    @pytest.mark.unit
    def test_check_error_state_clears_failed_tests_with_broader_later_test_run(self) -> None:
        timeline = TurnTimeline(
            tool_calls=[
                _shell_record(
                    "pytest tests/unit/hooks/checkpoint/test__init__.py",
                    had_error=True,
                    result_snippet="FAILED tests/unit/hooks/checkpoint/test__init__.py",
                ),
                _shell_record("pytest tests/unit/hooks", result_snippet="10 passed"),
            ]
        )

        assert _check_error_state(timeline) == []

    @pytest.mark.unit
    def test_check_error_state_clears_failed_typecheck_after_later_successful_typecheck(self) -> None:
        timeline = TurnTimeline(
            tool_calls=[
                _shell_record("pyright teleclaude/hooks/checkpoint/__init__.py", had_error=True),
                _shell_record(
                    "pyright teleclaude/hooks/checkpoint/__init__.py teleclaude/utils/transcript/_tool_calls.py",
                    result_snippet="0 errors, 0 warnings",
                ),
            ]
        )

        assert _check_error_state(timeline) == []

    @pytest.mark.unit
    def test_check_error_state_ignores_user_aborted_commands(self) -> None:
        timeline = TurnTimeline(
            tool_calls=[
                _shell_record(
                    "instrukt-ai-logs teleclaude --since 2m --grep Checkpoint",
                    had_error=True,
                    result_snippet="aborted by user after 2.2s",
                )
            ]
        )

        assert _check_error_state(timeline) == []

    @pytest.mark.unit
    def test_check_error_state_clears_commit_error_after_classification_gate(self) -> None:
        timeline = TurnTimeline(
            tool_calls=[
                _shell_record(
                    "telec code commit -m 'Fix checkpoint message ordering'",
                    had_error=True,
                    result_snippet="ERROR: partially staged files detected.",
                ),
                _shell_record(
                    "telec code commit -m 'Fix checkpoint message ordering'",
                    had_error=True,
                    result_snippet="ERROR: Commits on main require classification.",
                ),
            ]
        )

        assert _check_error_state(timeline) == []

    @pytest.mark.unit
    def test_telec_code_test_counts_as_test_evidence_and_failed_test_command(self) -> None:
        successful_timeline = TurnTimeline(tool_calls=[_shell_record("telec code test tests/unit/demo.py")])
        failed_timeline = TurnTimeline(
            tool_calls=[
                _shell_record(
                    "telec code test tests/unit/demo.py",
                    had_error=True,
                    result_snippet="failed",
                )
            ]
        )

        assert _has_evidence(successful_timeline, ["telec code test"]) is True
        assert _check_error_state(failed_timeline) == ["Test failures remain — re-run tests after fixes"]

    @pytest.mark.unit
    def test_commit_classification_gate_counts_as_commit_evidence_not_error(self) -> None:
        timeline = TurnTimeline(
            tool_calls=[
                _shell_record(
                    "telec code commit -m 'Fix checkpoint compliance scoping'",
                    had_error=True,
                    result_snippet="ERROR: Commits on main require classification.",
                )
            ]
        )

        assert _has_commit_evidence(timeline) is True
        assert _check_error_state(timeline) == []

    @pytest.mark.unit
    def test_commit_evidence_must_follow_last_relevant_mutation(self) -> None:
        timeline = TurnTimeline(
            has_data=True,
            tool_calls=[
                _shell_record("telec code commit -m 'checkpoint'"),
                ToolCallRecord(
                    tool_name="edit",
                    input_data={"file_path": "/repo/teleclaude/hooks/checkpoint/__init__.py"},
                ),
            ],
        )

        assert (
            _has_commit_evidence_after_last_mutation(
                timeline,
                ["teleclaude/hooks/checkpoint/__init__.py"],
                "/repo",
            )
            is False
        )

    @pytest.mark.unit
    def test_commit_evidence_after_last_relevant_mutation_counts(self) -> None:
        timeline = TurnTimeline(
            has_data=True,
            tool_calls=[
                ToolCallRecord(
                    tool_name="edit",
                    input_data={"file_path": "/repo/teleclaude/hooks/checkpoint/__init__.py"},
                ),
                _shell_record("telec code commit -m 'checkpoint'"),
            ],
        )

        assert (
            _has_commit_evidence_after_last_mutation(
                timeline,
                ["teleclaude/hooks/checkpoint/__init__.py"],
                "/repo",
            )
            is True
        )

    @pytest.mark.unit
    def test_global_python_stdin_probe_error_is_not_counted(self) -> None:
        timeline = TurnTimeline(
            tool_calls=[
                _shell_record(
                    "python - <<'PY'\nprint('ok')\nPY",
                    had_error=True,
                    result_snippet="ModuleNotFoundError: No module named 'instrukt_ai_logging'",
                ),
            ]
        )

        assert _check_error_state(timeline) == []

    @pytest.mark.unit
    def test_venv_python_stdin_probe_error_is_counted(self) -> None:
        timeline = TurnTimeline(
            tool_calls=[
                _shell_record(
                    ".venv/bin/python - <<'PY'\nprint('ok')\nPY",
                    had_error=True,
                    result_snippet="Traceback (most recent call last)",
                ),
            ]
        )

        assert _check_error_state(timeline) == ["Python errors remain unresolved — verify they are fixed"]


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
        plan_text = (
            "# Implementation Plan\n\n"
            "## Files to Change\n"
            "| File | Change |\n"
            "| --- | --- |\n"
            "| `teleclaude/hooks/inbound.py` | Add tests |\n"
            "| `tests/unit/hooks/test_inbound.py` | Add coverage |\n"
        )
        mock_db = MagicMock()
        mock_db.read_artifact_sync.return_value = plan_text
        context = CheckpointContext(
            agent_name="claude",
            project_path=str(tmp_path),
            working_slug="chartest-hooks",
        )

        assert _extract_plan_file_paths(plan_text) == {
            "teleclaude/hooks/inbound.py",
            "tests/unit/hooks/test_inbound.py",
        }
        with patch("teleclaude.hooks.checkpoint._evidence.get_todos_db_sync", return_value=mock_db):
            assert len(_check_slug_alignment(["docs/guide.md"], context)) == 1
            assert not _check_slug_alignment(["tests/unit/hooks/test_inbound.py"], context)


class TestEvidenceUtilities:
    @pytest.mark.unit
    def test_dedupe_strings_preserves_first_seen_order(self) -> None:
        assert _dedupe_strings(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]

    @pytest.mark.unit
    def test_compute_log_since_window_uses_two_minute_floor_and_rounds_up(self) -> None:
        assert _compute_log_since_window(None) == "2m"
        assert _compute_log_since_window(61) == "2m"
        assert _compute_log_since_window(121) == "3m"

    @pytest.mark.unit
    def test_tui_checkpoint_reload_instruction_matches_console_script_process_shape(self) -> None:
        tui_category = next(category for category in CHECKPOINT_FILE_CATEGORIES if category.name == "TUI code")
        match = re.search(r"pkill -SIGUSR2 -f -- '([^']+)'", tui_category.instruction)

        assert match is not None
        pattern = match.group(1)
        command_line = (
            "/Users/Morriz/Workspace/InstruktAI/TeleClaude/.venv/bin/python3 "
            "/Users/Morriz/Workspace/InstruktAI/TeleClaude/.venv/bin/telec"
        )

        assert re.search(pattern, command_line) is not None


class TestProjectsInitEvidence:
    """Regression tests for the `telec projects init` evidence matcher.

    After the rename from `telec init`, the matcher must accept the new
    exact command shape and reject everything else, including the legacy
    `telec init` form and spurious `telec foo init` shapes.
    """

    @pytest.mark.unit
    def test_accepts_exact_projects_init_shape(self) -> None:
        assert _segment_matches_evidence("telec projects init", "telec projects init") is True

    @pytest.mark.unit
    def test_accepts_projects_init_with_trailing_args(self) -> None:
        assert _segment_matches_evidence("telec projects init --foo", "telec projects init") is True

    @pytest.mark.unit
    def test_rejects_legacy_top_level_init(self) -> None:
        assert _segment_matches_evidence("telec init", "telec projects init") is False

    @pytest.mark.unit
    def test_rejects_spurious_intermediate_subcommand(self) -> None:
        assert _segment_matches_evidence("telec foo init", "telec projects init") is False
        assert _segment_matches_evidence("telec sessions init", "telec projects init") is False

    @pytest.mark.unit
    def test_rejects_init_before_projects(self) -> None:
        assert _segment_matches_evidence("telec init projects", "telec projects init") is False
