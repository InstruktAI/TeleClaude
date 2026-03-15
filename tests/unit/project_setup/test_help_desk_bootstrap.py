"""Characterization tests for teleclaude.project_setup.help_desk_bootstrap."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import teleclaude.project_setup.help_desk_bootstrap as help_desk_bootstrap
import teleclaude.project_setup.init_flow as init_flow


def test_bootstrap_help_desk_skips_existing_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "help-desk"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep\n", encoding="utf-8")
    monkeypatch.setattr(help_desk_bootstrap, "_resolve_help_desk_dir", lambda: target)
    monkeypatch.setattr(
        help_desk_bootstrap.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("subprocess.run should not be called")),
    )

    help_desk_bootstrap.bootstrap_help_desk()

    assert marker.read_text(encoding="utf-8") == "keep\n"


def test_bootstrap_help_desk_copies_template_runs_init_and_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "help-desk"
    calls: list[list[str]] = []
    init_calls: list[object] = []
    monkeypatch.setattr(help_desk_bootstrap, "_resolve_help_desk_dir", lambda: target)
    monkeypatch.setattr(init_flow, "init_project", lambda project_root: init_calls.append(project_root))

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(help_desk_bootstrap.subprocess, "run", fake_run)

    help_desk_bootstrap.bootstrap_help_desk()

    assert (target / "README.md").exists()
    assert init_calls == [target]
    assert calls == [
        ["git", "init"],
        ["git", "add", "."],
        ["git", "commit", "-m", "Initial help desk scaffold"],
    ]


def test_bootstrap_help_desk_cleans_up_directory_when_bootstrap_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "help-desk"
    monkeypatch.setattr(help_desk_bootstrap, "_resolve_help_desk_dir", lambda: target)

    def fail_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(help_desk_bootstrap.subprocess, "run", fail_run)

    with pytest.raises(subprocess.CalledProcessError):
        help_desk_bootstrap.bootstrap_help_desk()

    assert not target.exists()
