"""Tests for shared project action helpers."""
# guard: no-companion

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from teleclaude.cli.tui.views._project_actions import save_new_project


class _FakeApp:  # pylint: disable=too-few-public-methods
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

    result = SimpleNamespace(name="gamma", description="new project", path="/work/gamma")

    assert save_new_project(app, result) is True

    updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
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
            "path": "/work/gamma",
        },
    ]
    assert app.notifications == [("Project 'gamma' added", "information")]


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
    assert app.notifications == [
        ("Failed to save project: Config key `computer.trusted_dirs` must be a YAML list.", "error")
    ]
