"""Unit tests for worktree preparation functionality."""

import json
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
        mock_prepare.assert_called_once_with(str(tmp_path), "test-slug")


class TestPrepareWorktreeMakefile:
    """Tests for _prepare_worktree with Makefile projects."""

    @patch("teleclaude.core.next_machine.core.subprocess.run")
    def test_calls_make_worktree_prepare_with_slug(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test that make worktree-prepare is called with correct SLUG parameter."""
        # Setup
        makefile = tmp_path / "Makefile"
        makefile.write_text("worktree-prepare:\n\techo 'preparing'")

        mock_run.side_effect = [
            MagicMock(returncode=0),  # make -n check
            MagicMock(returncode=0, stdout="Prepared"),  # actual prep
        ]

        # Execute
        _prepare_worktree(str(tmp_path), "test-slug")

        # Verify make worktree-prepare was called with SLUG
        assert mock_run.call_count == 2
        actual_call = mock_run.call_args_list[1]
        assert actual_call[0][0] == ["make", "worktree-prepare", "SLUG=test-slug"]
        assert actual_call[1]["cwd"] == str(tmp_path)
        assert actual_call[1]["check"] is True

    @patch("teleclaude.core.next_machine.core.subprocess.run")
    def test_raises_when_worktree_prepare_target_missing(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test that RuntimeError is raised when worktree-prepare target doesn't exist."""
        # Setup
        makefile = tmp_path / "Makefile"
        makefile.write_text("other-target:\n\techo 'other'")

        # make -n should fail
        mock_run.side_effect = subprocess.CalledProcessError(2, "make")

        # Execute & Verify
        with pytest.raises(
            RuntimeError,
            match="Makefile exists but 'worktree-prepare' target not found",
        ):
            _prepare_worktree(str(tmp_path), "test-slug")

    @patch("teleclaude.core.next_machine.core.subprocess.run")
    def test_raises_when_preparation_fails(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test that RuntimeError is raised when worktree preparation fails."""
        # Setup
        makefile = tmp_path / "Makefile"
        makefile.write_text("worktree-prepare:\n\techo 'preparing'")

        # make -n succeeds, but actual prep fails
        error = subprocess.CalledProcessError(1, "make", output="", stderr="Failed!")
        error.stdout = ""
        error.stderr = "Failed!"
        mock_run.side_effect = [
            MagicMock(returncode=0),  # make -n check
            error,  # actual prep fails
        ]

        # Execute & Verify
        with pytest.raises(RuntimeError, match="Worktree preparation failed"):
            _prepare_worktree(str(tmp_path), "test-slug")


class TestPrepareWorktreePackageJson:
    """Tests for _prepare_worktree with Node.js projects."""

    @patch("teleclaude.core.next_machine.core.subprocess.run")
    def test_calls_npm_run_worktree_prepare_with_slug(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test that npm run worktree:prepare is called with slug parameter."""
        # Setup
        package_json = tmp_path / "package.json"
        package_json.write_text(json.dumps({"scripts": {"worktree:prepare": "node prepare.js"}}))

        mock_run.return_value = MagicMock(returncode=0, stdout="Prepared")

        # Execute
        _prepare_worktree(str(tmp_path), "test-slug")

        # Verify npm run was called correctly
        assert mock_run.call_count == 1
        actual_call = mock_run.call_args_list[0]
        assert actual_call[0][0] == ["npm", "run", "worktree:prepare", "--", "test-slug"]
        assert actual_call[1]["cwd"] == str(tmp_path)

    def test_raises_when_worktree_prepare_script_missing(self, tmp_path: Path) -> None:
        """Test that RuntimeError is raised when worktree:prepare script doesn't exist."""
        # Setup
        package_json = tmp_path / "package.json"
        package_json.write_text(json.dumps({"scripts": {"other": "echo 'other'"}}))

        # Execute & Verify
        with pytest.raises(
            RuntimeError,
            match="package.json exists but 'worktree:prepare' script not found",
        ):
            _prepare_worktree(str(tmp_path), "test-slug")

    def test_raises_when_package_json_invalid(self, tmp_path: Path) -> None:
        """Test that RuntimeError is raised when package.json is invalid JSON."""
        # Setup
        package_json = tmp_path / "package.json"
        package_json.write_text("{invalid json")

        # Execute & Verify
        with pytest.raises(RuntimeError, match="Failed to parse package.json"):
            _prepare_worktree(str(tmp_path), "test-slug")


class TestPrepareWorktreeNoHook:
    """Tests for _prepare_worktree when no preparation hook exists."""

    def test_raises_when_no_makefile_or_package_json(self, tmp_path: Path) -> None:
        """Test that RuntimeError is raised when no preparation hook found."""
        # Execute & Verify
        with pytest.raises(
            RuntimeError,
            match="No worktree preparation hook found",
        ):
            _prepare_worktree(str(tmp_path), "test-slug")
