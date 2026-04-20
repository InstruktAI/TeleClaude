"""Characterization tests for teleclaude.project_setup.sync."""

from __future__ import annotations

from pathlib import Path

import pytest

import teleclaude.project_setup.sync as project_sync
import teleclaude.sync as teleclaude_sync


def test_sync_project_artifacts_runs_sync_in_warn_only_mode_when_sync_reports_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, bool]] = []

    def fake_sync(project_root: Path, warn_only: bool) -> bool:
        calls.append((project_root, warn_only))
        return False

    monkeypatch.setattr(teleclaude_sync, "sync", fake_sync)

    project_sync.sync_project_artifacts(tmp_path)

    assert calls == [(tmp_path, True)]
