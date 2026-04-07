"""Path constants for TeleClaude filesystem layout."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TELECLAUDE_HOME = Path("~/.teleclaude").expanduser()
STATE_DIR = TELECLAUDE_HOME / "state"
GLOBAL_SNIPPETS_DIR = TELECLAUDE_HOME / "docs"
TUI_STATE_PATH = STATE_DIR / "tui_state.json"
CRON_STATE_PATH = STATE_DIR / "cron_state.json"
LOG_BUG_HUNTER_STATE_PATH = STATE_DIR / "log-bug-hunter-state.json"
SESSION_MAP_PATH = STATE_DIR / "session_map.json"
CHIPTUNES_FAVORITES_PATH = STATE_DIR / "chiptunes-favorites.json"
RUNTIME_SETTINGS_PATH = STATE_DIR / "runtime-settings.json"
MAIN_DB_PATH = TELECLAUDE_HOME / "teleclaude.db"
MIRRORS_DB_PATH = TELECLAUDE_HOME / "mirrors.db"
EVENTS_DB_PATH = TELECLAUDE_HOME / "events.db"
