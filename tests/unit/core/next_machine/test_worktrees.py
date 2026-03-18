"""Characterization tests for worktree preparation policy helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from git.exc import GitCommandError, InvalidGitRepositoryError

from teleclaude.core.next_machine._types import WorktreePrepDecision
from teleclaude.core.next_machine.worktrees import (
    _ensure_todo_on_remote_main,
    _read_worktree_prep_state,
    _write_worktree_prep_state,
    commit_bookkeeping_to_main,
    ensure_worktree_with_policy,
)


def test_worktree_prep_state_round_trips_valid_marker(tmp_path: Path) -> None:
    worktree = tmp_path / "trees" / "slug-a"
    worktree.mkdir(parents=True)

    _write_worktree_prep_state(str(tmp_path), "slug-a", "digest-123")

    assert _read_worktree_prep_state(str(tmp_path), "slug-a") == {"inputs_digest": "digest-123"}


def test_ensure_worktree_with_policy_prepares_when_decision_requires_it(tmp_path: Path) -> None:
    decision = WorktreePrepDecision(should_prepare=True, reason="prep_state_missing", inputs_digest="abc")

    with (
        patch("teleclaude.core.next_machine.worktrees._create_or_attach_worktree", return_value=True),
        patch("teleclaude.core.next_machine.worktrees._decide_worktree_prep", return_value=decision),
        patch("teleclaude.core.next_machine.worktrees._prepare_worktree") as prepare,
        patch("teleclaude.core.next_machine.worktrees._write_worktree_prep_state") as write_state,
    ):
        result = ensure_worktree_with_policy(str(tmp_path), "slug-b")

    assert result.created is True
    assert result.prepared is True
    assert result.prep_reason == "prep_state_missing"
    prepare.assert_called_once_with(str(tmp_path), "slug-b")
    write_state.assert_called_once_with(str(tmp_path), "slug-b", "abc")


def test_ensure_worktree_with_policy_skips_prep_when_inputs_are_unchanged(tmp_path: Path) -> None:
    decision = WorktreePrepDecision(should_prepare=False, reason="unchanged_known_good", inputs_digest="abc")

    with (
        patch("teleclaude.core.next_machine.worktrees._create_or_attach_worktree", return_value=False),
        patch("teleclaude.core.next_machine.worktrees._decide_worktree_prep", return_value=decision),
        patch("teleclaude.core.next_machine.worktrees._prepare_worktree") as prepare,
        patch("teleclaude.core.next_machine.worktrees._write_worktree_prep_state") as write_state,
    ):
        result = ensure_worktree_with_policy(str(tmp_path), "slug-c")

    assert result.created is False
    assert result.prepared is False
    assert result.prep_reason == "unchanged_known_good"
    prepare.assert_not_called()
    write_state.assert_not_called()


def test_ensure_todo_on_remote_main_returns_no_local_artifacts_when_folder_is_missing(tmp_path: Path) -> None:
    assert _ensure_todo_on_remote_main(str(tmp_path), "missing") == (False, "no_local_artifacts")


def test_ensure_todo_on_remote_main_skips_when_remote_already_has_the_todo(tmp_path: Path) -> None:
    todo_dir = tmp_path / "todos" / "slug-d"
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text("content", encoding="utf-8")
    repo = SimpleNamespace(
        git=SimpleNamespace(
            fetch=lambda *_args: None,
            ls_tree=lambda *_args: "100644 blob abc\ttodos/slug-d/requirements.md\n",
        )
    )

    with patch("teleclaude.core.next_machine.worktrees.Repo", return_value=repo):
        result = _ensure_todo_on_remote_main(str(tmp_path), "slug-d")

    assert result == (False, "already_on_remote")


# ---------------------------------------------------------------------------
# commit_bookkeeping_to_main
# ---------------------------------------------------------------------------

_PATCH_REPO = "teleclaude.core.next_machine.worktrees.Repo"
_PATCH_LOGGER = "teleclaude.core.next_machine.worktrees.logger"


def _make_bookkeeping_repo(
    *,
    branch: str = "main",
    detached: bool = False,
    status: str = "M  todos/roadmap.yaml",
) -> MagicMock:
    """Build a mock Repo with controllable branch, status, and git commands."""
    repo = MagicMock()
    if detached:

        def _raise_detached(_: object) -> None:
            raise TypeError("HEAD is a detached symbolic reference")

        type(repo).active_branch = property(_raise_detached)
    else:
        repo.active_branch.name = branch
    repo.git.status.return_value = status
    repo.git.update_environment.return_value = {
        "TELECLAUDE_ALLOW_MAIN_COMMIT": None,
        "TELECLAUDE_ALLOW_MAIN_PUSH": None,
    }
    return repo


class TestBookkeepingEarlyReturns:
    """Early returns must produce zero side effects — no env bypass, no git ops."""

    def test_not_a_repo_returns_and_does_nothing(self) -> None:
        mock_repo_cls = MagicMock(side_effect=InvalidGitRepositoryError("bad"))
        with patch(_PATCH_REPO, mock_repo_cls):
            result = commit_bookkeeping_to_main("/nonexistent", ["f"], "msg")

        assert result == (False, "not_a_repo")
        # Repo() was called but raised — no instance methods should exist
        mock_repo_cls.assert_called_once_with("/nonexistent")

    def test_not_on_main_returns_without_staging_or_committing(self) -> None:
        repo = _make_bookkeeping_repo(branch="feature-x")
        with patch(_PATCH_REPO, return_value=repo):
            result = commit_bookkeeping_to_main("/tmp", ["f"], "msg")

        assert result == (False, "not_on_main")
        repo.git.update_environment.assert_not_called()
        repo.git.add.assert_not_called()
        repo.git.commit.assert_not_called()
        repo.git.push.assert_not_called()

    def test_detached_head_returns_without_staging_or_committing(self) -> None:
        repo = _make_bookkeeping_repo(detached=True)
        with patch(_PATCH_REPO, return_value=repo):
            result = commit_bookkeeping_to_main("/tmp", ["f"], "msg")

        assert result == (False, "detached_head")
        repo.git.update_environment.assert_not_called()
        repo.git.add.assert_not_called()
        repo.git.commit.assert_not_called()

    def test_nothing_to_commit_checks_exact_paths_then_exits(self) -> None:
        repo = _make_bookkeeping_repo(status="")
        with patch(_PATCH_REPO, return_value=repo):
            result = commit_bookkeeping_to_main("/tmp", ["todos/my-slug", "todos/roadmap.yaml"], "msg")

        assert result == (False, "nothing_to_commit")
        # Verify status was called with --porcelain and the exact paths
        repo.git.status.assert_called_once_with("--porcelain", "--", "todos/my-slug", "todos/roadmap.yaml")
        # Must not proceed to env bypass or git ops
        repo.git.update_environment.assert_not_called()
        repo.git.add.assert_not_called()
        repo.git.commit.assert_not_called()


class TestBookkeepingCommitContract:
    """Verify the exact git commands, flags, and message structure."""

    def test_happy_path_verifies_full_command_sequence(self) -> None:
        """End-to-end: status check → env bypass → add → commit → push → env restore."""
        repo = _make_bookkeeping_repo()
        paths = ["todos/my-slug", "todos/roadmap.yaml"]

        with patch(_PATCH_REPO, return_value=repo):
            result = commit_bookkeeping_to_main("/proj", paths, "chore(todos): scaffold my-slug")

        assert result == (True, "committed_and_pushed")

        # Status check uses --porcelain with exact paths
        repo.git.status.assert_called_once_with("--porcelain", "--", "todos/my-slug", "todos/roadmap.yaml")

        # Env bypass set with string "1" values (not int)
        env_set_call = repo.git.update_environment.call_args_list[0]
        assert env_set_call == call(
            TELECLAUDE_ALLOW_MAIN_COMMIT="1",
            TELECLAUDE_ALLOW_MAIN_PUSH="1",
        )

        # Add uses "--" separator with exact paths
        repo.git.add.assert_called_once_with("--", "todos/my-slug", "todos/roadmap.yaml")

        # Commit has all required flags and message structure
        commit_args = repo.git.commit.call_args[0]
        assert commit_args[0] == "-m"
        assert isinstance(commit_args[1], str)  # message verified in dedicated test
        assert commit_args[2] == "--no-verify"
        assert commit_args[3] == "--only"
        assert commit_args[4] == "--"
        assert commit_args[5:] == ("todos/my-slug", "todos/roadmap.yaml")

        # Push to origin main
        repo.git.push.assert_called_once_with("origin", "main")

        # Env restored in finally block
        env_restore_call = repo.git.update_environment.call_args_list[1]
        assert env_restore_call == call(
            TELECLAUDE_ALLOW_MAIN_COMMIT=None,
            TELECLAUDE_ALLOW_MAIN_PUSH=None,
        )

    def test_commit_message_structure(self) -> None:
        """Subject line with [skip ci], TeleClaude link, Co-Authored-By trailer."""
        repo = _make_bookkeeping_repo()
        with patch(_PATCH_REPO, return_value=repo):
            commit_bookkeeping_to_main("/tmp", ["f"], "chore(todos): scaffold slug")

        msg = repo.git.commit.call_args[0][1]
        lines = msg.split("\n")

        # Subject line is first, contains [skip ci]
        assert lines[0] == "chore(todos): scaffold slug [skip ci]"
        # Co-Authored-By trailer present
        assert "Co-Authored-By: TeleClaude <noreply@instrukt.ai>" in msg
        # TeleClaude link present
        assert "Generated with [TeleClaude]" in msg

    def test_skip_ci_not_duplicated_when_already_present(self) -> None:
        repo = _make_bookkeeping_repo()
        with patch(_PATCH_REPO, return_value=repo):
            commit_bookkeeping_to_main("/tmp", ["f"], "chore: test [skip ci]")

        msg = repo.git.commit.call_args[0][1]
        assert msg.count("[skip ci]") == 1

    def test_commit_failure_does_not_push(self) -> None:
        repo = _make_bookkeeping_repo()
        repo.git.commit.side_effect = GitCommandError("commit", "failed")
        with patch(_PATCH_REPO, return_value=repo):
            result = commit_bookkeeping_to_main("/tmp", ["f"], "chore: test")

        assert result == (False, "commit_failed")
        repo.git.push.assert_not_called()
        repo.git.pull.assert_not_called()


class TestBookkeepingPushRecovery:
    """Push recovery: direct push → rebase recovery → abort on stuck rebase."""

    def test_rebase_recovery_after_non_fast_forward(self) -> None:
        repo = _make_bookkeeping_repo()
        repo.git.push.side_effect = [
            GitCommandError("push", "non-fast-forward"),
            None,
        ]
        with patch(_PATCH_REPO, return_value=repo):
            result = commit_bookkeeping_to_main("/tmp", ["f"], "chore: test")

        assert result == (True, "rebased_and_pushed")
        # Verify exact rebase recovery sequence
        repo.git.pull.assert_called_once_with("--rebase", "origin", "main")
        assert repo.git.push.call_count == 2
        assert repo.git.push.call_args_list[1] == call("origin", "main")

    def test_rebase_conflict_defers_push_and_aborts_rebase(self) -> None:
        repo = _make_bookkeeping_repo()
        repo.git.push.side_effect = GitCommandError("push", "failed")
        repo.git.pull.side_effect = GitCommandError("pull", "conflict")
        with patch(_PATCH_REPO, return_value=repo):
            result = commit_bookkeeping_to_main("/tmp", ["f"], "chore: test")

        # Committed locally (True) but push deferred
        assert result == (True, "committed_push_deferred")
        repo.git.rebase.assert_called_once_with("--abort")

    def test_rebase_abort_failure_swallowed_gracefully(self) -> None:
        repo = _make_bookkeeping_repo()
        repo.git.push.side_effect = GitCommandError("push", "failed")
        repo.git.pull.side_effect = GitCommandError("pull", "conflict")
        repo.git.rebase.side_effect = GitCommandError("rebase", "no rebase in progress")
        with patch(_PATCH_REPO, return_value=repo):
            result = commit_bookkeeping_to_main("/tmp", ["f"], "chore: test")

        assert result == (True, "committed_push_deferred")


class TestBookkeepingEnvBypassContract:
    """Environment bypass must be set before ops and restored in ALL code paths."""

    def test_env_set_before_add_restored_after_push(self) -> None:
        repo = _make_bookkeeping_repo()
        call_order: list[str] = []

        original_update_env = repo.git.update_environment

        def _track_update_env(**kwargs: object) -> dict[str, None]:
            if "TELECLAUDE_ALLOW_MAIN_COMMIT" in kwargs:
                val = kwargs["TELECLAUDE_ALLOW_MAIN_COMMIT"]
                call_order.append("env_set" if val == "1" else "env_restore")
            return original_update_env.return_value

        repo.git.update_environment = _track_update_env
        repo.git.add.side_effect = lambda *_: call_order.append("add")
        repo.git.commit.side_effect = lambda *_: call_order.append("commit")
        repo.git.push.side_effect = lambda *_: call_order.append("push")

        with patch(_PATCH_REPO, return_value=repo):
            commit_bookkeeping_to_main("/tmp", ["f"], "chore: test")

        assert call_order == ["env_set", "add", "commit", "push", "env_restore"]

    def test_env_restored_even_when_commit_fails(self) -> None:
        repo = _make_bookkeeping_repo()
        repo.git.commit.side_effect = GitCommandError("commit", "index lock")
        with patch(_PATCH_REPO, return_value=repo):
            commit_bookkeeping_to_main("/tmp", ["f"], "chore: test")

        assert repo.git.update_environment.call_count == 2
        restore_call = repo.git.update_environment.call_args_list[1]
        assert restore_call == call(TELECLAUDE_ALLOW_MAIN_COMMIT=None, TELECLAUDE_ALLOW_MAIN_PUSH=None)

    def test_env_restored_even_when_push_and_rebase_both_fail(self) -> None:
        repo = _make_bookkeeping_repo()
        repo.git.push.side_effect = GitCommandError("push", "auth failed")
        repo.git.pull.side_effect = GitCommandError("pull", "auth failed")
        with patch(_PATCH_REPO, return_value=repo):
            commit_bookkeeping_to_main("/tmp", ["f"], "chore: test")

        assert repo.git.update_environment.call_count == 2
        restore_call = repo.git.update_environment.call_args_list[1]
        assert restore_call == call(TELECLAUDE_ALLOW_MAIN_COMMIT=None, TELECLAUDE_ALLOW_MAIN_PUSH=None)


class TestBookkeepingDiagnostics:
    """Finding #3: first push error preserved at debug level."""

    def test_first_push_error_logged_at_debug_with_original_exception(self) -> None:
        repo = _make_bookkeeping_repo()
        push_error = GitCommandError("push", "non-fast-forward")
        repo.git.push.side_effect = [push_error, None]
        with (
            patch(_PATCH_REPO, return_value=repo),
            patch(_PATCH_LOGGER) as mock_logger,
        ):
            commit_bookkeeping_to_main("/tmp", ["f"], "chore: test")

        # The original exception object — not a string — must be passed
        mock_logger.debug.assert_any_call("First push attempt failed: %s", push_error)

    def test_commit_failure_logged_at_warning(self) -> None:
        repo = _make_bookkeeping_repo()
        commit_error = GitCommandError("commit", "index.lock exists")
        repo.git.commit.side_effect = commit_error
        with (
            patch(_PATCH_REPO, return_value=repo),
            patch(_PATCH_LOGGER) as mock_logger,
        ):
            commit_bookkeeping_to_main("/tmp", ["f"], "chore: test")

        mock_logger.warning.assert_called_once()
        warning_args = mock_logger.warning.call_args[0]
        assert "Bookkeeping commit failed" in warning_args[0]
        assert warning_args[2] is commit_error
