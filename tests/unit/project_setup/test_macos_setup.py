"""Characterization tests for teleclaude.project_setup.macos_setup."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import teleclaude.project_setup.macos_setup as macos_setup


def test_install_launchers_copies_existing_bundles_into_home_applications(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_root = tmp_path / "project"
    tmux_source = project_root / "bin" / "TmuxLauncher.app" / "Contents"
    codex_source = project_root / "bin" / "CodexLauncher.app" / "Contents"
    tmux_source.mkdir(parents=True, exist_ok=True)
    codex_source.mkdir(parents=True, exist_ok=True)
    (tmux_source / "Info.plist").write_text("tmux\n", encoding="utf-8")
    (codex_source / "Info.plist").write_text("codex\n", encoding="utf-8")

    home_dir = tmp_path / "home"
    stale_target = home_dir / "Applications" / "TmuxLauncher.app"
    stale_target.mkdir(parents=True, exist_ok=True)
    (stale_target / "stale.txt").write_text("old\n", encoding="utf-8")

    monkeypatch.setattr(macos_setup, "is_macos", lambda: True)
    monkeypatch.setattr(macos_setup.Path, "home", classmethod(lambda cls: home_dir))

    macos_setup.install_launchers(project_root, skip_build=True)

    tmux_target = home_dir / "Applications" / "TmuxLauncher.app"
    codex_target = home_dir / "Applications" / "CodexLauncher.app"
    assert (tmux_target / "Contents" / "Info.plist").read_text(encoding="utf-8") == "tmux\n"
    assert not (tmux_target / "stale.txt").exists()
    assert (codex_target / "Contents" / "Info.plist").read_text(encoding="utf-8") == "codex\n"
    assert "skipping launcher build" in capsys.readouterr().out


def test_run_permissions_probe_returns_true_outside_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(macos_setup, "is_macos", lambda: False)

    assert macos_setup.run_permissions_probe(macos_setup.Path("/unused")) is True


def test_run_permissions_probe_detects_denials_in_captured_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tmux_wrapper = tmp_path / "tmux"
    tmux_wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "capture-pane" in cmd:
            return SimpleNamespace(returncode=0, stdout="PermissionError: denied\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(macos_setup, "is_macos", lambda: True)
    monkeypatch.setattr(macos_setup, "resolve_tmux_binary", lambda: str(tmux_wrapper))
    monkeypatch.setattr(macos_setup.subprocess, "run", fake_run)
    monkeypatch.setattr(macos_setup.time, "sleep", lambda seconds: None)

    assert macos_setup.run_permissions_probe(tmp_path) is False
    assert any("capture-pane" in cmd for cmd in calls)
    assert "permission probe found denied paths" in capsys.readouterr().out
