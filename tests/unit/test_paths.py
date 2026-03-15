"""Characterization tests for teleclaude.paths."""

from __future__ import annotations

from pathlib import Path

from teleclaude import paths


def test_repo_root_is_derived_from_module_location() -> None:
    assert paths.REPO_ROOT == Path(paths.__file__).resolve().parents[1]


def test_home_relative_paths_share_expected_bases() -> None:
    assert paths.TELECLAUDE_HOME == Path("~/.teleclaude").expanduser()
    assert paths.STATE_DIR == paths.TELECLAUDE_HOME / "state"
    assert paths.GLOBAL_SNIPPETS_DIR == paths.TELECLAUDE_HOME / "docs"
    assert paths.TUI_STATE_PATH == paths.STATE_DIR / "tui_state.json"
    assert paths.CRON_STATE_PATH == paths.STATE_DIR / "cron_state.json"
    assert paths.SESSION_MAP_PATH == paths.STATE_DIR / "session_map.json"
    assert paths.CHIPTUNES_FAVORITES_PATH == paths.STATE_DIR / "chiptunes-favorites.json"
    assert paths.RUNTIME_SETTINGS_PATH == paths.STATE_DIR / "runtime-settings.json"
