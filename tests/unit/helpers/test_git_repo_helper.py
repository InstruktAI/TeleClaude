"""Characterization tests for teleclaude.helpers.git_repo_helper."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.git import GitCommandError
from teleclaude.helpers import git_repo_helper

pytestmark = pytest.mark.unit


class TestParseUrl:
    @pytest.mark.parametrize(
        ("repo_url", "expected"),
        [
            ("https://github.com/openai/teleclaude.git", ("github.com", "openai", "teleclaude")),
            ("git@github.com:openai/teleclaude.git", ("github.com", "openai", "teleclaude")),
        ],
    )
    def test_parses_common_url_forms(self, repo_url: str, expected: tuple[str, str, str]) -> None:
        assert git_repo_helper._parse_url(repo_url) == expected


class TestDefaultBranch:
    def test_falls_back_to_remote_head_output(self, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        # First two rev-parse calls raise GitCommandError, then remote show returns HEAD branch
        mock_repo.git.rev_parse.side_effect = GitCommandError("rev-parse", 1)
        mock_repo.git.remote.return_value = "  HEAD branch: trunk"

        assert git_repo_helper._default_branch(mock_repo) == "trunk"


class TestEnsureRepo:
    def test_returns_dirty_changes_without_fetching(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        repo_path = tmp_path / "repo"
        (repo_path / ".git").mkdir(parents=True)
        mock_repo = MagicMock()
        monkeypatch.setattr(git_repo_helper, "_ensure_on_branch", lambda repo: None)
        monkeypatch.setattr(git_repo_helper, "_dirty_worktree", lambda repo: [" M tracked.txt"])

        with patch.object(git_repo_helper, "Repo", return_value=mock_repo):
            changes, dirty = git_repo_helper._ensure_repo("https://github.com/openai/repo.git", repo_path)

        assert changes == []
        assert dirty == [" M tracked.txt"]
        mock_repo.git.fetch.assert_not_called()

    def test_clones_when_repository_is_missing(self, tmp_path: Path) -> None:
        repo_path = tmp_path / "github.com" / "openai" / "repo"

        with patch.object(git_repo_helper, "Repo") as mock_repo_cls:
            changes, dirty = git_repo_helper._ensure_repo("https://github.com/openai/repo.git", repo_path)

        assert changes == []
        assert dirty == []
        mock_repo_cls.clone_from.assert_called_once_with("https://github.com/openai/repo.git", str(repo_path))
        assert repo_path.parent.exists()


class TestLoadCheckoutRoot:
    def test_uses_default_checkout_root_when_config_value_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            git_repo_helper,
            "load_global_config",
            lambda: SimpleNamespace(git=SimpleNamespace(checkout_root=None)),
        )

        assert git_repo_helper._load_checkout_root() == git_repo_helper.DEFAULT_CHECKOUT_ROOT
