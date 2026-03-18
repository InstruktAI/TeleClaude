"""Characterization tests for teleclaude.project_setup.git_repo."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import teleclaude.project_setup.git_repo as git_repo
from teleclaude.git import InvalidGitRepositoryError


def test_ensure_git_repo_initializes_when_not_inside_worktree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with patch("teleclaude.project_setup.git_repo.Repo") as mock_repo_cls:
        # First call (check existing) raises InvalidGitRepositoryError
        mock_repo_cls.side_effect = [InvalidGitRepositoryError("not a repo"), None]
        mock_repo_cls.init = MagicMock()
        # Reset side_effect for init call
        mock_repo_cls.side_effect = InvalidGitRepositoryError("not a repo")

    # Re-approach: Repo(path, search_parent_directories=True) raises, then Repo.init(path) succeeds
    with patch("teleclaude.project_setup.git_repo.Repo") as mock_repo_cls:
        mock_repo_cls.side_effect = InvalidGitRepositoryError("not a repo")
        mock_repo_cls.init = MagicMock()

        git_repo.ensure_git_repo(tmp_path)

    mock_repo_cls.init.assert_called_once_with(tmp_path)
    assert "initialized git repository" in capsys.readouterr().out


def test_ensure_hooks_path_unsets_core_hookspath_and_copies_executable_hooks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_dir = tmp_path / ".githooks"
    source_dir.mkdir()
    source_hook = source_dir / "pre-commit"
    source_hook.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    git_hooks_dir = tmp_path / ".git" / "hooks"
    git_hooks_dir.mkdir(parents=True)

    mock_repo = MagicMock()
    # git config --local --get core.hooksPath succeeds (value exists)
    # git config --local --unset core.hooksPath succeeds
    mock_repo.git.config = MagicMock()

    with patch("teleclaude.project_setup.git_repo.Repo", return_value=mock_repo):
        git_repo.ensure_hooks_path(tmp_path)

    dest_hook = git_hooks_dir / "pre-commit"
    # Verify config calls: first --get, then --unset
    config_calls = mock_repo.git.config.call_args_list
    assert config_calls[0].args == ("--local", "--get", "core.hooksPath")
    assert config_calls[1].args == ("--local", "--unset", "core.hooksPath")
    assert dest_hook.read_text(encoding="utf-8") == "#!/bin/sh\necho hi\n"
    assert dest_hook.stat().st_mode & 0o111
    assert "installed project hooks" in capsys.readouterr().out
