"""Characterization tests for teleclaude.project_setup.git_filters."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.project_setup import git_filters


def test_setup_git_filters_skips_when_git_directory_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Print a clear message when filter setup runs outside a git repo."""
    git_filters.setup_git_filters(tmp_path)

    assert "not a git repository" in capsys.readouterr().out


def test_setup_git_filters_configures_expected_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Install the @-scoped clean/smudge filters without rewriting docs."""
    (tmp_path / ".git").mkdir()
    calls: list[tuple[object, str, str]] = []

    def _fake_config(repo: object, key: str, value: str) -> None:
        calls.append((repo, key, value))

    monkeypatch.setattr(git_filters, "_run_git_config", _fake_config)

    mock_repo = MagicMock()
    with patch("teleclaude.project_setup.git_filters.Repo", return_value=mock_repo):
        git_filters.setup_git_filters(tmp_path)

    home = str(Path.home())
    assert calls == [
        (mock_repo, "filter.teleclaude-docs.smudge", f'sed "s|@~/.teleclaude|@{home}/.teleclaude|g"'),
        (mock_repo, "filter.teleclaude-docs.clean", f'sed "s|@{home}/.teleclaude|@~/.teleclaude|g"'),
        (mock_repo, "filter.teleclaude-docs.required", "true"),
    ]
    assert "git filters configured" in capsys.readouterr().out
