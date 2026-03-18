"""Characterization tests for teleclaude.project_setup.help_desk_bootstrap."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import teleclaude.project_setup.help_desk_bootstrap as help_desk_bootstrap
import teleclaude.project_setup.init_flow as init_flow


def test_bootstrap_help_desk_skips_existing_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "help-desk"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep\n", encoding="utf-8")
    monkeypatch.setattr(help_desk_bootstrap, "_resolve_help_desk_dir", lambda: target)

    help_desk_bootstrap.bootstrap_help_desk()

    assert marker.read_text(encoding="utf-8") == "keep\n"


def test_bootstrap_help_desk_copies_template_runs_init_and_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "help-desk"
    init_calls: list[object] = []
    monkeypatch.setattr(help_desk_bootstrap, "_resolve_help_desk_dir", lambda: target)
    monkeypatch.setattr(init_flow, "init_project", lambda project_root: init_calls.append(project_root))

    mock_repo = MagicMock()
    mock_index = MagicMock()
    mock_repo.index = mock_index

    with patch("teleclaude.git.Repo") as mock_repo_cls:
        mock_repo_cls.init.return_value = mock_repo
        help_desk_bootstrap.bootstrap_help_desk()

    assert (target / "README.md").exists()
    assert init_calls == [target]
    mock_repo_cls.init.assert_called_once_with(target)
    mock_repo.git.add.assert_called_once_with(".")
    mock_index.commit.assert_called_once_with("Initial help desk scaffold")


def test_bootstrap_help_desk_cleans_up_directory_when_bootstrap_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "help-desk"
    monkeypatch.setattr(help_desk_bootstrap, "_resolve_help_desk_dir", lambda: target)

    with patch("teleclaude.git.Repo") as mock_repo_cls:
        mock_repo_cls.init.side_effect = Exception("git init failed")

        with pytest.raises(Exception, match="git init failed"):
            help_desk_bootstrap.bootstrap_help_desk()

    assert not target.exists()
