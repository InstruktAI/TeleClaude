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
    _commit_instruction,
    _compose_checkpoint_message,
    get_checkpoint_content,
    run_heuristics,
)
from teleclaude.session_scoping import ScopedPathsResult


class TestGetCheckpointContent:
    @pytest.mark.unit
    def test_uses_shared_session_scoping_turn_delta_for_codex(self) -> None:
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        result = CheckpointResult(
            categories=["python"],
            required_actions=["stub action"],
            observations=[],
            is_all_clear=False,
        )
        scoped_paths = ScopedPathsResult(
            paths=("src/app.py",),
            scope_mode="turn_delta",
            workspace_kind="git_shared",
            strategy="codex_structured",
            ledger_updated=False,
        )

        with (
            patch("teleclaude.hooks.checkpoint._is_checkpoint_project_supported", return_value=True),
            patch(
                "teleclaude.hooks.checkpoint.extract_effective_tool_calls",
                return_value=timeline,
            ) as extract_effective_mock,
            patch(
                "teleclaude.hooks.checkpoint.resolve_scoped_paths",
                return_value=scoped_paths,
            ) as resolve_scoped_mock,
            patch("teleclaude.hooks.checkpoint.run_heuristics", return_value=result),
        ):
            checkpoint_text = get_checkpoint_content(
                session_id="session-1",
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
        resolve_scoped_mock.assert_called_once_with(
            session_id="session-1",
            workspace_root="/repo",
            agent_name="codex",
            scope_mode="turn_delta",
            transcript_path="/tmp/parent.jsonl",
            native_session_id="parent-thread",
            turn_anchor_sha=None,
        )
        assert checkpoint_text is not None


class TestRunHeuristics:
    @pytest.mark.unit
    def test_test_quality_review_gate_fires_for_test_only_diffs(self) -> None:
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path="/repo")

        with patch("teleclaude.hooks.checkpoint._current_branch", return_value="feature"):
            result = run_heuristics(["tests/unit/test_foo.py"], timeline, context)

        assert any("test policy" in action for action in result.required_actions)

    @pytest.mark.unit
    def test_on_main_flag_set_when_branch_is_main(self) -> None:
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path="/repo")

        with patch("teleclaude.hooks.checkpoint._current_branch", return_value="main"):
            result = run_heuristics(["src/app.py"], timeline, context)

        assert result.on_main is True

    @pytest.mark.unit
    def test_on_main_flag_false_off_main(self) -> None:
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path="/repo")

        with patch("teleclaude.hooks.checkpoint._current_branch", return_value="feature-x"):
            result = run_heuristics(["src/app.py"], timeline, context)

        assert result.on_main is False

    @pytest.mark.unit
    def test_on_main_flag_false_when_branch_detection_fails(self) -> None:
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path="/repo")

        with patch("teleclaude.hooks.checkpoint._current_branch", return_value=None):
            result = run_heuristics(["src/app.py"], timeline, context)

        assert result.on_main is False

    @pytest.mark.unit
    def test_daemon_code_off_main_suppresses_make_restart(self) -> None:
        """Workers on branch/worktree must not be told to restart the daemon.

        The running daemon is installed from main; worktree edits do not affect
        it until integration. Restart is the integrator's concern.
        """
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path="/repo")

        with patch("teleclaude.hooks.checkpoint._current_branch", return_value="feature-x"):
            result = run_heuristics(["teleclaude/core/daemon.py"], timeline, context)

        assert not any("make restart" in action for action in result.required_actions)
        assert not any("make status" in action for action in result.required_actions)

    @pytest.mark.unit
    def test_config_off_main_suppresses_make_restart(self) -> None:
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path="/repo")

        with patch("teleclaude.hooks.checkpoint._current_branch", return_value="feature-x"):
            result = run_heuristics(["config.yml"], timeline, context)

        assert not any("make restart" in action for action in result.required_actions)

    @pytest.mark.unit
    def test_setup_off_main_suppresses_make_install(self) -> None:
        """Setup changes in worktrees don't affect the running system."""
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path="/repo")

        with patch("teleclaude.hooks.checkpoint._current_branch", return_value="feature-x"):
            result = run_heuristics(["templates/foo.j2"], timeline, context)

        assert not any("make install" in action for action in result.required_actions)

    @pytest.mark.unit
    def test_deps_off_main_suppresses_uv_sync(self) -> None:
        """Dependency changes in worktrees don't affect the running virtualenv."""
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path="/repo")

        with patch("teleclaude.hooks.checkpoint._current_branch", return_value="feature-x"):
            result = run_heuristics(["pyproject.toml"], timeline, context)

        assert not any("uv sync" in action for action in result.required_actions)

    @pytest.mark.unit
    def test_daemon_code_on_main_still_requires_make_restart(self) -> None:
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path="/repo")

        with patch("teleclaude.hooks.checkpoint._current_branch", return_value="main"):
            result = run_heuristics(["teleclaude/core/daemon.py"], timeline, context)

        assert any("make restart" in action for action in result.required_actions)

    @pytest.mark.unit
    def test_setup_on_main_still_requires_make_install(self) -> None:
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path="/repo")

        with patch("teleclaude.hooks.checkpoint._current_branch", return_value="main"):
            result = run_heuristics(["templates/foo.j2"], timeline, context)

        assert any("make install" in action for action in result.required_actions)

    @pytest.mark.unit
    def test_tui_reload_instruction_still_fires_off_main(self) -> None:
        """TUI reload is not main-gated; it applies regardless of branch."""
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        context = CheckpointContext(agent_name=AgentName.CLAUDE, project_path="/repo")

        with patch("teleclaude.hooks.checkpoint._current_branch", return_value="feature-x"):
            result = run_heuristics(["teleclaude/cli/tui/app.py"], timeline, context)

        assert any("SIGUSR2" in action or "USR2" in action for action in result.required_actions)


class TestCommitInstruction:
    @pytest.mark.unit
    def test_on_main_references_telec_code_commit(self) -> None:
        instruction = _commit_instruction(on_main=True)
        assert "telec code commit" in instruction

    @pytest.mark.unit
    def test_off_main_references_telec_code_commit(self) -> None:
        instruction = _commit_instruction(on_main=False)
        assert "telec code commit" in instruction


class TestComposeBranchAware:
    @pytest.mark.unit
    def test_compose_on_main_emits_telec_code_commit(self) -> None:
        result = CheckpointResult(
            categories=["python"],
            required_actions=["Run tests"],
            observations=[],
            is_all_clear=False,
            on_main=True,
        )

        message = _compose_checkpoint_message(["src/app.py"], result)

        assert "telec code commit" in message

    @pytest.mark.unit
    def test_compose_off_main_emits_telec_code_commit(self) -> None:
        result = CheckpointResult(
            categories=["python"],
            required_actions=["Run tests"],
            observations=[],
            is_all_clear=False,
            on_main=False,
        )

        message = _compose_checkpoint_message(["src/app.py"], result)

        assert "telec code commit" in message

    @pytest.mark.unit
    def test_compose_on_main_all_clear_variant_emits_telec_code_commit(self) -> None:
        result = CheckpointResult(is_all_clear=True, on_main=True)

        message = _compose_checkpoint_message(["src/app.py"], result)

        assert "telec code commit" in message

    @pytest.mark.unit
    def test_compose_on_main_docs_only_variant_emits_telec_code_commit(self) -> None:
        result = CheckpointResult(on_main=True)

        message = _compose_checkpoint_message([], result)

        assert "telec code commit" in message
