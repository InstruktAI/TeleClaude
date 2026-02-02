"""Unit tests for worktree preparation functionality."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from teleclaude.core.next_machine import _prepare_worktree, ensure_worktree


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
        assert mock_prepare.call_args == ((str(tmp_path), "test-slug"), {})


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
