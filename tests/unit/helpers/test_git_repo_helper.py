"""Characterization tests for teleclaude.helpers.git_repo_helper."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    def test_falls_back_to_remote_head_output(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        error = subprocess.CalledProcessError(1, "git")
        responses = iter([error, error, "  HEAD branch: trunk"])

        def fake_git_output(cmd: list[str], cwd: Path | None) -> str:
            result = next(responses)
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(git_repo_helper, "_git_output", fake_git_output)

        assert git_repo_helper._default_branch(repo_path) == "trunk"


class TestEnsureRepo:
    def test_returns_dirty_changes_without_fetching(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        repo_path = tmp_path / "repo"
        (repo_path / ".git").mkdir(parents=True)
        calls: list[list[str]] = []
        monkeypatch.setattr(git_repo_helper, "_ensure_on_branch", lambda path: None)
        monkeypatch.setattr(git_repo_helper, "_dirty_worktree", lambda path: [" M tracked.txt"])
        monkeypatch.setattr(git_repo_helper, "_run", lambda cmd, cwd=None: calls.append(cmd))

        changes, dirty = git_repo_helper._ensure_repo("https://github.com/openai/repo.git", repo_path)

        assert changes == []
        assert dirty == [" M tracked.txt"]
        assert calls == []

    def test_clones_when_repository_is_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        repo_path = tmp_path / "github.com" / "openai" / "repo"
        calls: list[list[str]] = []
        monkeypatch.setattr(git_repo_helper, "_run", lambda cmd, cwd=None: calls.append(cmd))

        changes, dirty = git_repo_helper._ensure_repo("https://github.com/openai/repo.git", repo_path)

        assert changes == []
        assert dirty == []
        assert calls == [["git", "clone", "https://github.com/openai/repo.git", str(repo_path)]]
        assert repo_path.parent.exists()


class TestLoadCheckoutRoot:
    def test_uses_default_checkout_root_when_config_value_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            git_repo_helper,
            "load_global_config",
            lambda: SimpleNamespace(git=SimpleNamespace(checkout_root=None)),
        )

        assert git_repo_helper._load_checkout_root() == git_repo_helper.DEFAULT_CHECKOUT_ROOT
