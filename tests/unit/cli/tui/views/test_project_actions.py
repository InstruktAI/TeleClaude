"""Tests for shared project action helpers."""
# guard: no-companion

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from teleclaude.cli.tui.views._project_actions import save_new_project


class _FakeApp:
    """Minimal app stub that captures notifications."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        """Record a notification call."""
        self.notifications.append((message, severity))


@pytest.mark.unit
def test_save_new_project_appends_trusted_dir_without_overwriting_existing_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Appending a trusted dir preserves existing entries and metadata."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
computer:
  trusted_dirs:
    - name: alpha
      desc: first project
      path: /work/alpha
      discord_forum: 123
    - name: beta
      path: /work/beta
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(config_path))
    app = _FakeApp()
    project_path = tmp_path / "work" / "gamma"

    result = SimpleNamespace(name="gamma", description="new project", path=str(project_path))

    assert save_new_project(app, result) is True

    updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert project_path.is_dir()
    assert updated["computer"]["trusted_dirs"] == [
        {
            "name": "alpha",
            "desc": "first project",
            "path": "/work/alpha",
            "discord_forum": 123,
        },
        {
            "name": "beta",
            "path": "/work/beta",
        },
        {
            "name": "gamma",
            "desc": "new project",
            "path": str(project_path.resolve()),
        },
    ]
    assert len(app.notifications) == 1
    assert app.notifications[0][1] == "information"


@pytest.mark.unit
def test_save_new_project_reports_invalid_trusted_dir_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid trusted_dirs shape is reported without mutating config."""
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
computer:
  trusted_dirs: invalid
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(config_path))
    app = _FakeApp()

    result = SimpleNamespace(name="gamma", description="", path="/work/gamma")

    assert save_new_project(app, result) is False
    assert config_path.read_text(encoding="utf-8") == "computer:\n  trusted_dirs: invalid\n"
    assert len(app.notifications) == 1
    assert app.notifications[0][1] == "error"


@pytest.mark.unit
def test_save_new_project_rejects_existing_file_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An existing file target is rejected without mutating config."""
    config_path = tmp_path / "config.yml"
    config_path.write_text("computer:\n  trusted_dirs: []\n", encoding="utf-8")
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(config_path))
    app = _FakeApp()

    target = tmp_path / "gamma"
    target.write_text("not a directory", encoding="utf-8")
    result = SimpleNamespace(name="gamma", description="", path=str(target))

    assert save_new_project(app, result) is False

    updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert updated == {"computer": {"trusted_dirs": []}}
    assert len(app.notifications) == 1
    assert app.notifications[0][1] == "error"
