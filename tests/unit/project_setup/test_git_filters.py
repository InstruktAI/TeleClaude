"""Characterization tests for teleclaude.project_setup.git_filters."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import teleclaude.project_setup.git_filters as git_filters


def test_setup_git_filters_skips_when_git_directory_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git_filters.setup_git_filters(tmp_path)

    assert "not a git repository" in capsys.readouterr().out


def test_setup_git_filters_configures_expected_keys_and_rechecks_docs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".git").mkdir()
    calls: list[tuple[object, str, str]] = []
    rechecked: list[tuple[object, Path]] = []

    monkeypatch.setattr(
        git_filters,
        "_run_git_config",
        lambda repo, key, value: calls.append((repo, key, value)),
    )
    monkeypatch.setattr(
        git_filters, "_recheckout_docs", lambda repo, project_root: rechecked.append((repo, project_root))
    )

    mock_repo = MagicMock()
    with patch("teleclaude.project_setup.git_filters.Repo", return_value=mock_repo):
        git_filters.setup_git_filters(tmp_path)

    home = str(Path.home())
    assert [(r, k, v) for r, k, v in calls] == [
        (mock_repo, "filter.teleclaude-docs.smudge", f'sed "s|@~/.teleclaude|@{home}/.teleclaude|g"'),
        (mock_repo, "filter.teleclaude-docs.clean", f'sed "s|@{home}/.teleclaude|@~/.teleclaude|g"'),
        (mock_repo, "filter.teleclaude-docs.required", "true"),
    ]
    assert rechecked == [(mock_repo, tmp_path)]
    assert "git filters configured" in capsys.readouterr().out


def test_recheckout_docs_only_runs_checkout_for_existing_doc_roots(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs").mkdir(parents=True)

    mock_repo = MagicMock()
    git_filters._recheckout_docs(mock_repo, tmp_path)

    mock_repo.git.checkout.assert_called_once_with("--", "docs/")
