"""Path constants for TeleClaude filesystem layout."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from teleclaude.runtime.config import get_runtime_config


class ConfigFileName(StrEnum):
    """Closed vocabulary of well-known config filenames."""

    OVERLAY = "teleclaude.yml"
    MACHINE = "config.yml"
    ENV = ".env"


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TELECLAUDE_HOME = Path("~/.teleclaude").expanduser()

TELECLAUDE_HOME = get_runtime_config().home
STATE_DIR = TELECLAUDE_HOME / "state"
LOGS_DIR = TELECLAUDE_HOME / "logs"
GLOBAL_DOCS_DIR = TELECLAUDE_HOME / "docs"
GLOBAL_SNIPPETS_DIR = GLOBAL_DOCS_DIR / "snippets"
BIN_DIR = TELECLAUDE_HOME / "bin"
DEFAULT_BIN_DIR = DEFAULT_TELECLAUDE_HOME / "bin"
SHELL_DIR = TELECLAUDE_HOME / "shell"
PEOPLE_DIR = TELECLAUDE_HOME / "people"
INTEGRATION_DIR = TELECLAUDE_HOME / "integration"
TMP_SESSIONS_DIR = TELECLAUDE_HOME / "tmp" / "sessions"
SESSION_AUTH_DIR = TELECLAUDE_HOME / "session-auth"
COMMANDS_DIR = TELECLAUDE_HOME / "commands"
GLOBAL_SKILLS_DIR = TELECLAUDE_HOME / "skills"
SKILL_STORE_DIR = TELECLAUDE_HOME / "skill-store"
JOBS_DIR = TELECLAUDE_HOME / "jobs"
STORAGE_DIR = TELECLAUDE_HOME / "storage"
SANDBOX_CARTRIDGES_DIR = TELECLAUDE_HOME / "sandbox-cartridges"
COMPANIES_ROOT = TELECLAUDE_HOME / "companies"
PERSONAL_DIR = TELECLAUDE_HOME / "personal"
TUI_STATE_PATH = STATE_DIR / "tui_state.json"
TUI_PIDS_DIR = STATE_DIR / "tui-pids"
CRON_STATE_PATH = STATE_DIR / "cron_state.json"
LOG_BUG_HUNTER_STATE_DIR = STATE_DIR / "log-bug-hunter"
SESSION_MAP_PATH = STATE_DIR / "session_map.json"
CHIPTUNES_FAVORITES_PATH = STATE_DIR / "chiptunes-favorites.json"
CHIPTUNES_DISLIKES_PATH = STATE_DIR / "chiptunes-dislikes.json"
CHIPTUNES_STATE_PATH = STATE_DIR / "chiptunes_state.json"
RUNTIME_SETTINGS_PATH = STATE_DIR / "runtime-settings.json"
MIGRATION_STATE_PATH = STATE_DIR / "migration_state.json"
INVITATIONS_PATH = STATE_DIR / "invitations.json"
DEPLOYED_COMMANDS_MANIFEST_PATH = STATE_DIR / "deployed_commands.json"
CHIPTUNES_WORKER_LOG_PATH = LOGS_DIR / "chiptunes_worker.log"
MAIN_DB_PATH = TELECLAUDE_HOME / "teleclaude.db"
MIRRORS_DB_PATH = TELECLAUDE_HOME / "mirrors.db"
EVENTS_DB_PATH = TELECLAUDE_HOME / "events.db"
GIT_MAIN_LOCK_PATH = TELECLAUDE_HOME / "git-main.lock"
CRON_PID_PATH = TELECLAUDE_HOME / "cron_runner.pid"
CHIPTUNES_PID_PATH = TELECLAUDE_HOME / "chiptunes.pid"
CHIPTUNES_SOCKET_PATH = TELECLAUDE_HOME / "chiptunes.sock"
GLOBAL_CONFIG_PATH = TELECLAUDE_HOME / ConfigFileName.OVERLAY
MACHINE_CONFIG_PATH = TELECLAUDE_HOME / ConfigFileName.MACHINE
PROJECTS_MANIFEST_PATH = TELECLAUDE_HOME / "projects.yaml"
ENV_PATH = TELECLAUDE_HOME / ConfigFileName.ENV
PROJECT_ENV_PATH = REPO_ROOT / ConfigFileName.ENV
