"""Characterization tests for teleclaude.project_setup.sync."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import teleclaude.project_setup.sync as project_sync
import teleclaude.sync as teleclaude_sync


def test_project_label_slugifies_names_and_falls_back_when_empty() -> None:
    assert project_sync._project_label(project_sync.Path("/tmp/My Project!!")) == "my-project"
    assert project_sync._project_label(project_sync.Path("/tmp/---")) == "teleclaude"


def test_sync_project_artifacts_prints_warning_when_sync_reports_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(teleclaude_sync, "sync", lambda project_root, warn_only: False)

    project_sync.sync_project_artifacts(tmp_path)

    assert "sync completed with warnings" in capsys.readouterr().out


def test_install_docs_watch_dispatches_to_launchd_on_macos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(project_sync.sys, "platform", "darwin")
    monkeypatch.setattr(project_sync, "_install_launchd_watch", lambda project_root: calls.append(project_root))

    project_sync.install_docs_watch(tmp_path)

    assert calls == [tmp_path]


def test_remove_stale_launchd_plists_only_deletes_other_watchers_for_same_project(tmp_path: Path) -> None:
    launchd_dir = tmp_path / "LaunchAgents"
    launchd_dir.mkdir()
    current = launchd_dir / "ai.instrukt.teleclaude.docs.my-project.plist"
    stale = launchd_dir / "ai.instrukt.teleclaude.docs.other.plist"
    unrelated = launchd_dir / "ai.instrukt.teleclaude.docs.unrelated.plist"
    project_root = tmp_path / "My Project"
    current.write_text(f"<string>{project_root}</string>\n", encoding="utf-8")
    stale.write_text(f"<string>{project_root}</string>\n", encoding="utf-8")
    unrelated.write_text("<string>/another/project</string>\n", encoding="utf-8")

    project_sync._remove_stale_launchd_plists(launchd_dir, project_root)

    assert current.exists()
    assert not stale.exists()
    assert unrelated.exists()


def test_install_systemd_watch_writes_units_and_reports_missing_user_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_root = tmp_path / "Project Root"
    project_root.mkdir()
    home_dir = tmp_path / "home"

    def fake_run(cmd, **kwargs):
        if cmd == ["systemctl", "--user", "daemon-reload"]:
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(project_sync.Path, "home", classmethod(lambda cls: home_dir))
    monkeypatch.setattr(project_sync.subprocess, "run", fake_run)

    project_sync._install_systemd_watch(project_root)

    service_path = home_dir / ".config" / "systemd" / "user" / "teleclaude-docs-project-root.service"
    path_path = home_dir / ".config" / "systemd" / "user" / "teleclaude-docs-project-root.path"
    assert service_path.exists()
    assert path_path.exists()
    assert str(project_root) in service_path.read_text(encoding="utf-8")
    assert str(project_root) in path_path.read_text(encoding="utf-8")
    assert "systemd user services unavailable" in capsys.readouterr().out
