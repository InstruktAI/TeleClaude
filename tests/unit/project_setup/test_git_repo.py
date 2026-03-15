"""Characterization tests for teleclaude.project_setup.git_repo."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import teleclaude.project_setup.git_repo as git_repo


def test_ensure_git_repo_initializes_when_not_inside_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["git", "rev-parse"]:
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(git_repo.subprocess, "run", fake_run)

    git_repo.ensure_git_repo(tmp_path)

    assert calls == [["git", "rev-parse", "--is-inside-work-tree"], ["git", "init"]]
    assert "initialized git repository" in capsys.readouterr().out


def test_ensure_hooks_path_unsets_core_hookspath_and_copies_executable_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_dir = tmp_path / ".githooks"
    source_dir.mkdir()
    source_hook = source_dir / "pre-commit"
    source_hook.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    git_hooks_dir = tmp_path / ".git" / "hooks"
    git_hooks_dir.mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(git_repo.subprocess, "run", fake_run)

    git_repo.ensure_hooks_path(tmp_path)

    dest_hook = git_hooks_dir / "pre-commit"
    assert ["git", "config", "--local", "--get", "core.hooksPath"] in calls
    assert ["git", "config", "--local", "--unset", "core.hooksPath"] in calls
    assert dest_hook.read_text(encoding="utf-8") == "#!/bin/sh\necho hi\n"
    assert dest_hook.stat().st_mode & 0o111
    assert "installed project hooks" in capsys.readouterr().out
