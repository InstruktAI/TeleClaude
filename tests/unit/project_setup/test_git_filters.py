"""Characterization tests for teleclaude.project_setup.git_filters."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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
    calls: list[tuple[Path, str, str]] = []
    rechecked: list[Path] = []

    monkeypatch.setattr(
        git_filters,
        "_run_git_config",
        lambda project_root, key, value: calls.append((project_root, key, value)),
    )
    monkeypatch.setattr(git_filters, "_recheckout_docs", lambda project_root: rechecked.append(project_root))

    git_filters.setup_git_filters(tmp_path)

    home = str(Path.home())
    assert calls == [
        (tmp_path, "filter.teleclaude-docs.smudge", f'sed "s|@~/.teleclaude|@{home}/.teleclaude|g"'),
        (tmp_path, "filter.teleclaude-docs.clean", f'sed "s|@{home}/.teleclaude|@~/.teleclaude|g"'),
        (tmp_path, "filter.teleclaude-docs.required", "true"),
    ]
    assert rechecked == [tmp_path]
    assert "git filters configured" in capsys.readouterr().out


def test_recheckout_docs_only_runs_checkout_for_existing_doc_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "docs").mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(git_filters.subprocess, "run", fake_run)

    git_filters._recheckout_docs(tmp_path)

    assert calls == [["git", "checkout", "--", "docs/"]]
