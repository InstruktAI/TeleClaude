"""Unit tests for worktree preparation functionality."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from teleclaude.core.next_machine import _prepare_worktree, ensure_worktree
from teleclaude.paths import REPO_ROOT


class TestEnsureWorktreeAlwaysPrepares:
    """Tests for ensure_worktree always running preparation."""

    @patch("teleclaude.core.next_machine.core._prepare_worktree")
    def test_always_runs_preparation_when_worktree_exists(self, mock_prepare: Mock, tmp_path: Path) -> None:
        """Test that preparation always runs when worktree exists (idempotent)."""
        # Setup - create worktree dir
        worktree_dir = tmp_path / "trees" / "test-slug"
        worktree_dir.mkdir(parents=True)

        # Execute
        result = ensure_worktree(str(tmp_path), "test-slug")

        # Verify - preparation always runs (idempotent, catches drift)
        assert result is False  # Worktree already existed
        mock_prepare.assert_called_once_with(str(tmp_path), "test-slug")


class TestPrepareWorktreeScript:
    """Tests for _prepare_worktree with script-based projects."""

    @patch("teleclaude.core.next_machine.core.subprocess.run")
    def test_calls_worktree_prepare_script_with_slug(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test that bin/worktree-prepare.sh is called with correct slug."""
        worktree_script = REPO_ROOT / "bin" / "worktree-prepare.sh"
        mock_run.return_value = MagicMock(returncode=0, stdout="Prepared")

        # Execute
        _prepare_worktree(str(tmp_path), "test-slug")

        # Verify script was called with slug
        assert mock_run.call_count == 1
        actual_call = mock_run.call_args_list[0]
        assert actual_call[0][0] == [str(worktree_script), "test-slug"]
        assert actual_call[1]["cwd"] == str(tmp_path)
        assert actual_call[1]["check"] is True

    @patch("teleclaude.core.next_machine.core.subprocess.run")
    def test_raises_when_worktree_prepare_target_missing(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test that RuntimeError is raised when script is missing."""
        with patch("teleclaude.core.next_machine.core.Path.exists", return_value=False):
            with pytest.raises(
                RuntimeError,
                match="Worktree preparation script not found",
            ):
                _prepare_worktree(str(tmp_path), "test-slug")

    @patch("teleclaude.core.next_machine.core.subprocess.run")
    def test_raises_when_preparation_fails(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test that RuntimeError is raised when worktree preparation fails."""
        worktree_script = REPO_ROOT / "bin" / "worktree-prepare.sh"

        # Script execution fails
        error = subprocess.CalledProcessError(1, str(worktree_script), output="", stderr="Failed!")
        error.stdout = ""
        error.stderr = "Failed!"
        mock_run.side_effect = error

        # Execute & Verify
        with pytest.raises(RuntimeError, match="Worktree preparation failed"):
            _prepare_worktree(str(tmp_path), "test-slug")


class TestPrepareWorktreeNoHook:
    """Tests for _prepare_worktree when no preparation hook exists."""

    def test_raises_when_no_makefile_or_package_json(self, tmp_path: Path) -> None:
        """Test that RuntimeError is raised when no preparation hook found."""
        with patch("teleclaude.core.next_machine.core.Path.exists", return_value=False):
            with pytest.raises(
                RuntimeError,
                match="Worktree preparation script not found",
            ):
                _prepare_worktree(str(tmp_path), "test-slug")
