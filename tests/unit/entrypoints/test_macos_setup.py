"""Characterization tests for teleclaude.entrypoints.macos_setup."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

import teleclaude.entrypoints.macos_setup as macos_setup


def test_main_returns_zero_without_running_actions_on_non_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(macos_setup, "is_macos", lambda: False)
    install_launchers = Mock()
    run_permissions_probe = Mock()
    monkeypatch.setattr(macos_setup, "install_launchers", install_launchers)
    monkeypatch.setattr(macos_setup, "run_permissions_probe", run_permissions_probe)
    monkeypatch.setattr(sys, "argv", ["macos-setup", "run-all"])

    assert macos_setup.main() == 0
    install_launchers.assert_not_called()
    run_permissions_probe.assert_not_called()


def test_main_install_launchers_action_resolves_project_root_and_skip_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(macos_setup, "is_macos", lambda: True)
    install_launchers = Mock()
    run_permissions_probe = Mock()
    monkeypatch.setattr(macos_setup, "install_launchers", install_launchers)
    monkeypatch.setattr(macos_setup, "run_permissions_probe", run_permissions_probe)
    project_root = tmp_path / "project"
    monkeypatch.setattr(
        sys,
        "argv",
        ["macos-setup", "--project-root", str(project_root), "install-launchers", "--skip-build"],
    )

    assert macos_setup.main() == 0
    install_launchers.assert_called_once_with(project_root.resolve(), skip_build=True)
    run_permissions_probe.assert_not_called()


def test_main_run_all_invokes_launcher_install_and_permissions_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(macos_setup, "is_macos", lambda: True)
    install_launchers = Mock()
    run_permissions_probe = Mock()
    monkeypatch.setattr(macos_setup, "install_launchers", install_launchers)
    monkeypatch.setattr(macos_setup, "run_permissions_probe", run_permissions_probe)
    project_root = tmp_path / "project"
    monkeypatch.setattr(sys, "argv", ["macos-setup", "--project-root", str(project_root), "run-all"])

    assert macos_setup.main() == 0
    install_launchers.assert_called_once_with(project_root.resolve(), skip_build=False)
    run_permissions_probe.assert_called_once_with(project_root.resolve())
