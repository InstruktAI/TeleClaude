"""Characterization tests for teleclaude.paths."""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

from teleclaude import paths


def test_repo_root_is_derived_from_module_location() -> None:
    assert paths.REPO_ROOT == Path(paths.__file__).resolve().parents[1]


def test_home_relative_paths_share_expected_bases() -> None:
    assert paths.TELECLAUDE_HOME == Path(os.environ["TELECLAUDE_HOME"])
    assert paths.STATE_DIR == paths.TELECLAUDE_HOME / "state"
    assert paths.GLOBAL_SNIPPETS_DIR == paths.TELECLAUDE_HOME / "docs"
    assert paths.TUI_STATE_PATH == paths.STATE_DIR / "tui_state.json"
    assert paths.CRON_STATE_PATH == paths.STATE_DIR / "cron_state.json"
    assert paths.SESSION_MAP_PATH == paths.STATE_DIR / "session_map.json"
    assert paths.CHIPTUNES_FAVORITES_PATH == paths.STATE_DIR / "chiptunes-favorites.json"
    assert paths.RUNTIME_SETTINGS_PATH == paths.STATE_DIR / "runtime-settings.json"


def test_home_defaults_to_user_teleclaude_dir_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When TELECLAUDE_HOME env is absent, TELECLAUDE_HOME resolves to ``~/.teleclaude``.

    Verified via in-process reimport with the env var cleared — no subprocess
    needed. ``teleclaude.paths`` resolves its constants at module-import time,
    so ``importlib.reload`` reruns that resolution against the patched env.
    """
    monkeypatch.delenv("TELECLAUDE_HOME", raising=False)
    reloaded = importlib.reload(paths)
    try:
        assert reloaded.TELECLAUDE_HOME == reloaded.DEFAULT_TELECLAUDE_HOME
    finally:
        # Restore the suite-level env binding by reloading once more.
        monkeypatch.setenv("TELECLAUDE_HOME", str(reloaded.TELECLAUDE_HOME))
        importlib.reload(paths)
