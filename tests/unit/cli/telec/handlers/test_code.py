"""Tests for telec code commit classification and staging logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.cli.telec.handlers.code import (
    _classify_main_commit,
    _current_branch,
    _get_staged_files,
    _stage_files,
)
from teleclaude.git import GitCommandError


class TestClassifyMainCommit:
    """Path A/B/C classification for commits on main."""

    @pytest.mark.unit
    def test_path_a_passes_for_non_functional_with_skip_ci(self) -> None:
        """Non-functional files with [skip ci] in message proceed silently."""
        _classify_main_commit(["-m", "chore: update docs [skip ci]"], ["README.md", "docs/guide.yaml"])

    @pytest.mark.unit
    def test_path_a_blocks_non_functional_without_skip_ci(self) -> None:
        """Non-functional files without [skip ci] still require classification."""
        with pytest.raises(SystemExit, match="1"):
            _classify_main_commit(["-m", "chore: update docs"], ["README.md"])

    @pytest.mark.unit
    def test_functional_files_require_classification(self) -> None:
        """Functional files trigger the classification gate."""
        with pytest.raises(SystemExit, match="1"):
            _classify_main_commit(["-m", "fix: something"], ["teleclaude/foo.py"])

    @pytest.mark.unit
    def test_functional_with_skip_ci_still_requires_classification(self) -> None:
        """Functional files are not bypassed by [skip ci]."""
        with pytest.raises(SystemExit, match="1"):
            _classify_main_commit(["-m", "fix: something [skip ci]"], ["teleclaude/foo.py"])

    @pytest.mark.unit
    def test_makefile_is_functional(self) -> None:
        """Makefile is classified as functional."""
        with pytest.raises(SystemExit, match="1"):
            _classify_main_commit(["-m", "chore: update [skip ci]"], ["Makefile"])

    @pytest.mark.unit
    def test_dockerfile_is_functional(self) -> None:
        """Dockerfile is classified as functional."""
        with pytest.raises(SystemExit, match="1"):
            _classify_main_commit(["-m", "chore: update [skip ci]"], ["Dockerfile"])


class TestGitHelpers:
    """Verify git helpers use Repo with correct project_root."""

    @pytest.mark.unit
    def test_stage_files_calls_repo_git_add(self, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        with patch("teleclaude.cli.telec.handlers.code.Repo", return_value=mock_repo):
            _stage_files(["a.py", "b.py"], tmp_path)
        mock_repo.git.add.assert_called_once_with("--", "a.py", "b.py")

    @pytest.mark.unit
    def test_get_staged_files_parses_diff_output(self, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = "a.py\nb.py\n"
        with patch("teleclaude.cli.telec.handlers.code.Repo", return_value=mock_repo):
            result = _get_staged_files(tmp_path)
        assert result == ["a.py", "b.py"]
        mock_repo.git.diff.assert_called_once_with("--cached", "--name-only", "--diff-filter=ACM")

    @pytest.mark.unit
    def test_get_staged_files_returns_empty_for_no_output(self, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = ""
        with patch("teleclaude.cli.telec.handlers.code.Repo", return_value=mock_repo):
            result = _get_staged_files(tmp_path)
        assert result == []

    @pytest.mark.unit
    def test_current_branch_returns_branch_name(self, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        mock_repo.git.rev_parse.return_value = "feature-branch\n"
        with patch("teleclaude.cli.telec.handlers.code.Repo", return_value=mock_repo):
            result = _current_branch(tmp_path)
        assert result == "feature-branch"

    @pytest.mark.unit
    def test_current_branch_propagates_git_error(self, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        mock_repo.git.rev_parse.side_effect = GitCommandError("git", "rev-parse failed")
        with (
            patch("teleclaude.cli.telec.handlers.code.Repo", return_value=mock_repo),
            pytest.raises(GitCommandError),
        ):
            _current_branch(tmp_path)
