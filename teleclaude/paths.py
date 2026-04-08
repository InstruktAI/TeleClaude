"""Path constants for TeleClaude filesystem layout."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TELECLAUDE_HOME = Path("~/.teleclaude").expanduser()
STATE_DIR = TELECLAUDE_HOME / "state"
LOGS_DIR = TELECLAUDE_HOME / "logs"
GLOBAL_SNIPPETS_DIR = TELECLAUDE_HOME / "docs"
BIN_DIR = TELECLAUDE_HOME / "bin"
PEOPLE_DIR = TELECLAUDE_HOME / "people"
INTEGRATION_DIR = TELECLAUDE_HOME / "integration"
TUI_STATE_PATH = STATE_DIR / "tui_state.json"
CRON_STATE_PATH = STATE_DIR / "cron_state.json"
LOG_BUG_HUNTER_STATE_PATH = STATE_DIR / "log-bug-hunter-state.json"
SESSION_MAP_PATH = STATE_DIR / "session_map.json"
CHIPTUNES_FAVORITES_PATH = STATE_DIR / "chiptunes-favorites.json"
CHIPTUNES_STATE_PATH = STATE_DIR / "chiptunes_state.json"
RUNTIME_SETTINGS_PATH = STATE_DIR / "runtime-settings.json"
MIGRATION_STATE_PATH = STATE_DIR / "migration_state.json"
CHIPTUNES_WORKER_LOG_PATH = LOGS_DIR / "chiptunes_worker.log"
MAIN_DB_PATH = TELECLAUDE_HOME / "teleclaude.db"
MIRRORS_DB_PATH = TELECLAUDE_HOME / "mirrors.db"
EVENTS_DB_PATH = TELECLAUDE_HOME / "events.db"
GIT_MAIN_LOCK_PATH = TELECLAUDE_HOME / "git-main.lock"
CRON_PID_PATH = TELECLAUDE_HOME / "cron_runner.pid"
GLOBAL_CONFIG_PATH = TELECLAUDE_HOME / "teleclaude.yml"
ENV_PATH = TELECLAUDE_HOME / ".env"
