"""Unit tests for worktree preparation functionality."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from teleclaude.core.next_machine import _prepare_worktree, ensure_worktree, ensure_worktree_with_policy
from teleclaude.core.next_machine.core import WorktreePrepDecision


class TestEnsureWorktreePrepPolicy:
    """Tests for conditional prep policy in ensure_worktree."""

    @patch("teleclaude.core.next_machine.core._prepare_worktree")
    @patch("teleclaude.core.next_machine.core._decide_worktree_prep")
    def test_skips_preparation_when_worktree_is_unchanged(
        self,
        mock_decide: Mock,
        mock_prepare: Mock,
        tmp_path: Path,
    ) -> None:
        """Existing worktree should skip prep when policy says known-good."""
        worktree_dir = tmp_path / "trees" / "test-slug"
        worktree_dir.mkdir(parents=True)
        mock_decide.return_value = WorktreePrepDecision(
            should_prepare=False,
            reason="unchanged_known_good",
            inputs_digest="abc",
        )

        result = ensure_worktree(str(tmp_path), "test-slug")

        assert result is False
        mock_prepare.assert_not_called()

    @patch("teleclaude.core.next_machine.core._write_worktree_prep_state")
    @patch("teleclaude.core.next_machine.core._prepare_worktree")
    @patch("teleclaude.core.next_machine.core._decide_worktree_prep")
    def test_runs_preparation_when_policy_detects_stale_inputs(
        self,
        mock_decide: Mock,
        mock_prepare: Mock,
        mock_write_state: Mock,
        tmp_path: Path,
    ) -> None:
        """Existing worktree should prepare when prep inputs changed."""
        worktree_dir = tmp_path / "trees" / "test-slug"
        worktree_dir.mkdir(parents=True)
        mock_decide.return_value = WorktreePrepDecision(
            should_prepare=True,
            reason="prep_inputs_changed",
            inputs_digest="new-digest",
        )

        result = ensure_worktree_with_policy(str(tmp_path), "test-slug")

        assert result.created is False
        assert result.prepared is True
        assert result.prep_reason == "prep_inputs_changed"
        assert mock_prepare.call_args == ((str(tmp_path), "test-slug"), {})
        assert mock_write_state.call_args == ((str(tmp_path), "test-slug", "new-digest"), {})

    @patch("teleclaude.core.next_machine.core._write_worktree_prep_state")
    @patch("teleclaude.core.next_machine.core._prepare_worktree")
    @patch("teleclaude.core.next_machine.core.Repo")
    def test_new_worktree_is_created_and_prepared(
        self,
        mock_repo_cls: Mock,
        mock_prepare: Mock,
        mock_write_state: Mock,
        tmp_path: Path,
    ) -> None:
        """New worktrees should always run prep and return created=True."""
        repo = MagicMock()
        mock_repo_cls.return_value = repo

        result = ensure_worktree_with_policy(str(tmp_path), "test-slug")

        assert result.created is True
        assert result.prepared is True
        assert result.prep_reason == "worktree_created"
        assert repo.git.worktree.call_args is not None
        assert mock_prepare.call_args == ((str(tmp_path), "test-slug"), {})
        assert mock_write_state.call_args is not None


class TestPrepareWorktreeConventions:
    """Tests for _prepare_worktree with convention-based projects."""

    @patch("teleclaude.core.next_machine.core.subprocess.run")
    def test_calls_make_install_when_target_exists(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test that make install is called when Makefile has install target."""
        worktree_dir = tmp_path / "trees" / "test-slug"
        worktree_dir.mkdir(parents=True)
        (worktree_dir / "Makefile").write_text("install:\n\t@echo ok\n", encoding="utf-8")
        mock_run.return_value = MagicMock(returncode=0, stdout="Prepared")

        _prepare_worktree(str(tmp_path), "test-slug")

        actual_call = mock_run.call_args_list[0]
        assert actual_call[0][0] == ["make", "install"]
        assert actual_call[1]["cwd"] == str(worktree_dir)
        assert actual_call[1]["check"] is True

    @patch("teleclaude.core.next_machine.core.subprocess.run")
    def test_calls_npm_install_when_package_json_exists(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test that npm install is called when package.json exists and pnpm is unavailable."""
        worktree_dir = tmp_path / "trees" / "test-slug"
        worktree_dir.mkdir(parents=True)
        (worktree_dir / "package.json").write_text("{}", encoding="utf-8")
        mock_run.return_value = MagicMock(returncode=0, stdout="Prepared")

        with patch("teleclaude.core.next_machine.core.shutil.which", return_value=None):
            _prepare_worktree(str(tmp_path), "test-slug")

        actual_call = mock_run.call_args_list[0]
        assert actual_call[0][0] == ["npm", "install"]
        assert actual_call[1]["cwd"] == str(worktree_dir)
        assert actual_call[1]["check"] is True

    @patch("teleclaude.core.next_machine.core.subprocess.run")
    def test_raises_when_preparation_fails(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test that RuntimeError is raised when preparation fails."""
        worktree_dir = tmp_path / "trees" / "test-slug"
        worktree_dir.mkdir(parents=True)
        (worktree_dir / "Makefile").write_text("install:\n\t@echo ok\n", encoding="utf-8")

        error = subprocess.CalledProcessError(1, "make", output="", stderr="Failed!")
        error.stdout = ""
        error.stderr = "Failed!"
        mock_run.side_effect = error

        with pytest.raises(RuntimeError, match="Worktree preparation failed"):
            _prepare_worktree(str(tmp_path), "test-slug")


class TestPrepareWorktreeNoTargets:
    """Tests for _prepare_worktree when no preparation targets exist."""

    def test_noop_when_no_targets(self, tmp_path: Path) -> None:
        """Test that no error is raised when no targets exist."""
        worktree_dir = tmp_path / "trees" / "test-slug"
        worktree_dir.mkdir(parents=True)
        _prepare_worktree(str(tmp_path), "test-slug")
