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
    _post_commit_review_instruction,
    get_checkpoint_content,
    run_heuristics,
)
from teleclaude.session_scoping import ScopedPathsResult
from teleclaude.utils.transcript import ToolCallRecord


class TestGetCheckpointContent:
    @pytest.mark.unit
    def test_uses_shared_session_scoping_turn_delta_for_codex(self) -> None:
        timeline = TurnTimeline(
            has_data=True,
            tool_calls=[
                ToolCallRecord(
                    tool_name="apply_patch",
                    input_data={"paths": ["src/app.py"]},
                    had_error=False,
                )
            ],
        )
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
            scope="checkpoint",
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

    @pytest.mark.unit
    def test_checkpoint_cycle_without_file_mutations_does_not_reuse_turn_dirty_files(self) -> None:
        timeline = TurnTimeline(
            has_data=True,
            tool_calls=[
                ToolCallRecord(
                    tool_name="functions.exec_command",
                    input_data={"cmd": "pytest tests/unit/hooks/checkpoint/test__init__.py"},
                    had_error=False,
                )
            ],
        )
        scoped_paths = ScopedPathsResult(
            paths=("teleclaude/hooks/checkpoint/__init__.py",),
            scope_mode="turn_delta",
            workspace_kind="git_shared",
            strategy="codex_structured",
            ledger_updated=False,
        )

        with (
            patch("teleclaude.hooks.checkpoint._is_checkpoint_project_supported", return_value=True),
            patch("teleclaude.hooks.checkpoint.extract_effective_tool_calls", return_value=timeline),
            patch("teleclaude.hooks.checkpoint.resolve_scoped_paths", return_value=scoped_paths),
            patch("teleclaude.hooks.checkpoint.run_heuristics") as run_heuristics_mock,
        ):
            checkpoint_text = get_checkpoint_content(
                session_id="session-1",
                transcript_path="/tmp/parent.jsonl",
                agent_name=AgentName.CODEX,
                project_path="/repo",
                native_session_id="parent-thread",
                working_slug="demo-slug",
            )

        assert checkpoint_text is None
        run_heuristics_mock.assert_not_called()

    @pytest.mark.unit
    def test_checkpoint_cycle_emits_when_main_head_changed_without_dirty_files(self) -> None:
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        scoped_paths = ScopedPathsResult(
            paths=(),
            scope_mode="turn_delta",
            workspace_kind="git_shared",
            strategy="codex_structured+anchor_diff",
            ledger_updated=False,
        )
        result = CheckpointResult(
            required_actions=[_post_commit_review_instruction()],
            observations=[],
            is_all_clear=False,
            commit_action_required=False,
            on_main=True,
            git_head_changed_this_turn=True,
            post_commit_review_action_required=True,
        )

        with (
            patch("teleclaude.hooks.checkpoint._is_checkpoint_project_supported", return_value=True),
            patch("teleclaude.hooks.checkpoint.extract_effective_tool_calls", return_value=timeline),
            patch("teleclaude.hooks.checkpoint.resolve_scoped_paths", return_value=scoped_paths),
            patch("teleclaude.hooks.checkpoint._current_head_sha", return_value="new-head"),
            patch("teleclaude.hooks.checkpoint.has_post_commit_review_flag", return_value=False),
            patch("teleclaude.hooks.checkpoint.replace_post_commit_review_flag") as replace_flag_mock,
            patch("teleclaude.hooks.checkpoint._current_branch", return_value="main"),
            patch("teleclaude.hooks.checkpoint.run_heuristics", return_value=result) as run_heuristics_mock,
        ):
            checkpoint_text = get_checkpoint_content(
                session_id="session-1",
                transcript_path="/tmp/parent.jsonl",
                agent_name=AgentName.CODEX,
                project_path="/repo",
                native_session_id="parent-thread",
                working_slug="demo-slug",
                turn_anchor_sha="old-head",
            )

        assert checkpoint_text is not None
        assert run_heuristics_mock.call_args.kwargs["git_head_changed_this_turn"] is True
        assert run_heuristics_mock.call_args.kwargs["post_commit_review_already_seen"] is False
        replace_flag_mock.assert_called_once_with("session-1", "new-head")

    @pytest.mark.unit
    def test_checkpoint_cycle_suppresses_repeated_main_head_change_without_dirty_files(self) -> None:
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        scoped_paths = ScopedPathsResult(
            paths=(),
            scope_mode="turn_delta",
            workspace_kind="git_shared",
            strategy="codex_structured+anchor_diff",
            ledger_updated=False,
        )

        with (
            patch("teleclaude.hooks.checkpoint._is_checkpoint_project_supported", return_value=True),
            patch("teleclaude.hooks.checkpoint.extract_effective_tool_calls", return_value=timeline),
            patch("teleclaude.hooks.checkpoint.resolve_scoped_paths", return_value=scoped_paths),
            patch("teleclaude.hooks.checkpoint._current_head_sha", return_value="new-head"),
            patch("teleclaude.hooks.checkpoint.has_post_commit_review_flag", return_value=True),
            patch("teleclaude.hooks.checkpoint._current_branch", return_value="main"),
            patch("teleclaude.hooks.checkpoint.run_heuristics") as run_heuristics_mock,
        ):
            checkpoint_text = get_checkpoint_content(
                session_id="session-1",
                transcript_path="/tmp/parent.jsonl",
                agent_name=AgentName.CODEX,
                project_path="/repo",
                native_session_id="parent-thread",
                working_slug="demo-slug",
                turn_anchor_sha="old-head",
            )

        assert checkpoint_text is None
        run_heuristics_mock.assert_not_called()

    @pytest.mark.unit
    def test_checkpoint_cycle_passes_seen_post_commit_flag_for_other_dirty_work(self) -> None:
        timeline = TurnTimeline(
            has_data=True,
            tool_calls=[
                ToolCallRecord(
                    tool_name="apply_patch",
                    input_data={"paths": ["teleclaude/hooks/checkpoint/__init__.py"]},
                    had_error=False,
                )
            ],
        )
        scoped_paths = ScopedPathsResult(
            paths=("teleclaude/hooks/checkpoint/__init__.py",),
            scope_mode="turn_delta",
            workspace_kind="git_shared",
            strategy="codex_structured",
            ledger_updated=False,
        )
        result = CheckpointResult(
            categories=["hook runtime"],
            required_actions=[],
            observations=[],
            is_all_clear=True,
        )

        with (
            patch("teleclaude.hooks.checkpoint._is_checkpoint_project_supported", return_value=True),
            patch("teleclaude.hooks.checkpoint.extract_effective_tool_calls", return_value=timeline),
            patch("teleclaude.hooks.checkpoint.resolve_scoped_paths", return_value=scoped_paths),
            patch("teleclaude.hooks.checkpoint._current_head_sha", return_value="new-head"),
            patch("teleclaude.hooks.checkpoint.has_post_commit_review_flag", return_value=True),
            patch("teleclaude.hooks.checkpoint.run_heuristics", return_value=result) as run_heuristics_mock,
        ):
            checkpoint_text = get_checkpoint_content(
                session_id="session-1",
                transcript_path="/tmp/parent.jsonl",
                agent_name=AgentName.CODEX,
                project_path="/repo",
                native_session_id="parent-thread",
                working_slug="demo-slug",
                turn_anchor_sha="old-head",
            )

        assert checkpoint_text is not None
        assert run_heuristics_mock.call_args.kwargs["post_commit_review_already_seen"] is True

    @pytest.mark.unit
    def test_checkpoint_cycle_scopes_files_to_post_checkpoint_mutations(self) -> None:
        timeline = TurnTimeline(
            has_data=True,
            tool_calls=[
                ToolCallRecord(
                    tool_name="apply_patch",
                    input_data={"paths": ["teleclaude/hooks/checkpoint/__init__.py"]},
                    had_error=False,
                ),
                ToolCallRecord(
                    tool_name="functions.exec_command",
                    input_data={"cmd": "pytest tests/unit/hooks/checkpoint/test__init__.py"},
                    had_error=False,
                ),
            ],
        )
        scoped_paths = ScopedPathsResult(
            paths=(
                "teleclaude/hooks/checkpoint/__init__.py",
                "teleclaude/hooks/checkpoint/_evidence.py",
            ),
            scope_mode="turn_delta",
            workspace_kind="git_shared",
            strategy="codex_structured",
            ledger_updated=False,
        )
        result = CheckpointResult(
            categories=["hook runtime"],
            required_actions=[],
            observations=[],
            is_all_clear=True,
        )

        with (
            patch("teleclaude.hooks.checkpoint._is_checkpoint_project_supported", return_value=True),
            patch("teleclaude.hooks.checkpoint.extract_effective_tool_calls", return_value=timeline),
            patch("teleclaude.hooks.checkpoint.resolve_scoped_paths", return_value=scoped_paths),
            patch("teleclaude.hooks.checkpoint.run_heuristics", return_value=result) as run_heuristics_mock,
        ):
            checkpoint_text = get_checkpoint_content(
                session_id="session-1",
                transcript_path="/tmp/parent.jsonl",
                agent_name=AgentName.CODEX,
                project_path="/repo",
                native_session_id="parent-thread",
                working_slug="demo-slug",
            )

        assert checkpoint_text is not None
        assert run_heuristics_mock.call_args.args[0] == ["teleclaude/hooks/checkpoint/__init__.py"]

    @pytest.mark.unit
    def test_checkpoint_cycle_suppresses_docs_only_no_action_changes(self) -> None:
        timeline = TurnTimeline(
            has_data=True,
            tool_calls=[
                ToolCallRecord(
                    tool_name="apply_patch",
                    input_data={"paths": ["docs/explore/checkpoint-cycle-probe.md"]},
                    had_error=False,
                )
            ],
        )
        scoped_paths = ScopedPathsResult(
            paths=("docs/explore/checkpoint-cycle-probe.md",),
            scope_mode="turn_delta",
            workspace_kind="git_shared",
            strategy="codex_structured",
            ledger_updated=False,
        )

        with (
            patch("teleclaude.hooks.checkpoint._is_checkpoint_project_supported", return_value=True),
            patch("teleclaude.hooks.checkpoint.extract_effective_tool_calls", return_value=timeline),
            patch("teleclaude.hooks.checkpoint.resolve_scoped_paths", return_value=scoped_paths),
        ):
            checkpoint_text = get_checkpoint_content(
                session_id="session-1",
                transcript_path="/tmp/parent.jsonl",
                agent_name=AgentName.CODEX,
                project_path="/repo",
                native_session_id="parent-thread",
                working_slug="demo-slug",
            )

        assert checkpoint_text is None

    @pytest.mark.unit
    def test_checkpoint_cycle_does_not_suppress_markdown_agent_artifacts_as_docs_only(self) -> None:
        timeline = TurnTimeline(
            has_data=True,
            tool_calls=[
                ToolCallRecord(
                    tool_name="apply_patch",
                    input_data={"paths": ["agents/commands/next-work.md"]},
                    had_error=False,
                )
            ],
        )
        scoped_paths = ScopedPathsResult(
            paths=("agents/commands/next-work.md",),
            scope_mode="turn_delta",
            workspace_kind="git_shared",
            strategy="codex_structured",
            ledger_updated=False,
        )
        result = CheckpointResult(
            categories=["agent artifacts"],
            required_actions=["Reload artifacts: `telec sessions restart self`"],
            observations=[],
            is_all_clear=False,
        )

        with (
            patch("teleclaude.hooks.checkpoint._is_checkpoint_project_supported", return_value=True),
            patch("teleclaude.hooks.checkpoint.extract_effective_tool_calls", return_value=timeline),
            patch("teleclaude.hooks.checkpoint.resolve_scoped_paths", return_value=scoped_paths),
            patch("teleclaude.hooks.checkpoint.run_heuristics", return_value=result) as run_heuristics_mock,
        ):
            checkpoint_text = get_checkpoint_content(
                session_id="session-1",
                transcript_path="/tmp/parent.jsonl",
                agent_name=AgentName.CODEX,
                project_path="/repo",
                native_session_id="parent-thread",
                working_slug="demo-slug",
            )

        assert checkpoint_text is not None
        assert run_heuristics_mock.call_args.args[0] == ["agents/commands/next-work.md"]


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
    def test_main_head_change_adds_post_commit_review_action(self) -> None:
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        context = CheckpointContext(agent_name=AgentName.CODEX, project_path="/repo")

        with patch("teleclaude.hooks.checkpoint._current_branch", return_value="main"):
            result = run_heuristics([], timeline, context, git_head_changed_this_turn=True)

        assert result.git_head_changed_this_turn is True
        assert result.commit_action_required is False
        assert result.post_commit_review_action_required is True
        assert result.required_actions == [_post_commit_review_instruction()]

    @pytest.mark.unit
    def test_seen_main_head_change_suppresses_only_post_commit_review_action(self) -> None:
        timeline = TurnTimeline(has_data=True, tool_calls=[])
        context = CheckpointContext(agent_name=AgentName.CODEX, project_path="/repo")

        with patch("teleclaude.hooks.checkpoint._current_branch", return_value="main"):
            result = run_heuristics(
                [],
                timeline,
                context,
                git_head_changed_this_turn=True,
                post_commit_review_already_seen=True,
            )

        assert result.git_head_changed_this_turn is True
        assert result.post_commit_review_action_required is False
        assert result.required_actions == []

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

    @pytest.mark.unit
    def test_commit_classification_evidence_suppresses_commit_instruction(self) -> None:
        timeline = TurnTimeline(
            has_data=True,
            tool_calls=[
                ToolCallRecord(
                    tool_name="functions.exec_command",
                    input_data={"cmd": "telec code commit -m 'Fix checkpoint compliance scoping'"},
                    had_error=True,
                    result_snippet="ERROR: Commits on main require classification.",
                )
            ],
        )
        context = CheckpointContext(agent_name=AgentName.CODEX, project_path="/repo")

        with patch("teleclaude.hooks.checkpoint._current_branch", return_value="main"):
            result = run_heuristics(["teleclaude/hooks/checkpoint/__init__.py"], timeline, context)

        message = _compose_checkpoint_message(["teleclaude/hooks/checkpoint/__init__.py"], result)

        assert result.commit_action_required is False
        assert "telec code commit" not in message

    @pytest.mark.unit
    def test_commit_evidence_before_later_edit_does_not_suppress_commit_instruction(self) -> None:
        timeline = TurnTimeline(
            has_data=True,
            tool_calls=[
                ToolCallRecord(
                    tool_name="functions.exec_command",
                    input_data={"cmd": "telec code commit -m 'Fix checkpoint compliance scoping'"},
                ),
                ToolCallRecord(
                    tool_name="edit",
                    input_data={"file_path": "/repo/teleclaude/hooks/checkpoint/__init__.py"},
                ),
            ],
        )
        context = CheckpointContext(agent_name=AgentName.CODEX, project_path="/repo")

        with patch("teleclaude.hooks.checkpoint._current_branch", return_value="main"):
            result = run_heuristics(["teleclaude/hooks/checkpoint/__init__.py"], timeline, context)

        assert result.commit_action_required is True


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
    def test_compose_orders_docs_check_before_commit_instruction(self) -> None:
        result = CheckpointResult(
            categories=["python"],
            required_actions=["Run tests"],
            observations=[],
            is_all_clear=False,
            on_main=True,
        )

        message = _compose_checkpoint_message(["src/app.py"], result)

        docs_idx = message.index("Docs check:")
        commit_idx = message.index("telec code commit")
        assert docs_idx < commit_idx
        assert message.count("Docs check:") == 1

    @pytest.mark.unit
    def test_compose_observations_only_does_not_reference_missing_required_actions(self) -> None:
        result = CheckpointResult(
            categories=["hook runtime"],
            required_actions=[],
            observations=["A command returned errors — verify the issue is resolved"],
            is_all_clear=False,
            on_main=True,
        )

        message = _compose_checkpoint_message(["teleclaude/hooks/checkpoint/__init__.py"], result)

        assert "Required actions" not in message
        assert "Execute every required action above" not in message
        assert "Review and resolve the observations" in message

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
    def test_compose_on_main_empty_variant_emits_telec_code_commit(self) -> None:
        result = CheckpointResult(on_main=True)

        message = _compose_checkpoint_message([], result)

        assert "telec code commit" in message
