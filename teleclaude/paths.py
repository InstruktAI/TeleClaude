"""Path constants for TeleClaude filesystem layout."""

from __future__ import annotations

import hashlib
import os
import re
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
HELP_DESK_DIRNAME = "help-desk"
VENDOR_DIRNAME = "instrukt-ai"
PLATFORM_DIRNAME = "teleclaude"
_DEFAULT_DATA_HOME = Path(".local") / "share"


def _xdg_data_home() -> Path:
    """The XDG data directory: ``$XDG_DATA_HOME`` when set to an absolute path, else ``~/.local/share``."""
    configured = os.environ.get("XDG_DATA_HOME")  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
    if configured and Path(configured).is_absolute():
        return Path(configured)
    return Path.home() / _DEFAULT_DATA_HOME


INSTALLATION_ROOT = _xdg_data_home() / VENDOR_DIRNAME / PLATFORM_DIRNAME
DAEMON_PID_PATH = INSTALLATION_ROOT / "teleclaude.pid"


def invocation_cwd() -> Path:
    """Return the shell directory captured by the telec wrapper, with direct-call fallbacks."""
    explicit = os.environ.get("TELEC_INVOCATION_CWD")  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
    if explicit:
        return Path(explicit)
    pwd = os.environ.get("PWD")  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
    if pwd:
        return Path(pwd)
    return Path.cwd()


TELECLAUDE_HOME = get_runtime_config().home


def is_platform_home(path: Path) -> bool:
    """Return whether a path resolves to this machine's platform home."""
    return path.expanduser().resolve() == TELECLAUDE_HOME.expanduser().resolve()


STATE_DIR = TELECLAUDE_HOME / "state"
JOB_RUNS_DIR = STATE_DIR / "runs"
LOGS_DIR = TELECLAUDE_HOME / "logs"
GLOBAL_DOCS_DIR = TELECLAUDE_HOME / "docs"
GLOBAL_DOCS_ROOTS = (DEFAULT_TELECLAUDE_HOME / "docs", GLOBAL_DOCS_DIR)
GLOBAL_SNIPPETS_DIR = GLOBAL_DOCS_DIR / "snippets"
BIN_DIR = TELECLAUDE_HOME / "bin"
DEFAULT_BIN_DIR = DEFAULT_TELECLAUDE_HOME / "bin"
SHELL_DIR = TELECLAUDE_HOME / "shell"
PEOPLE_DIR = TELECLAUDE_HOME / "people"
INTEGRATION_DIR = TELECLAUDE_HOME / "integration"
TMP_SESSIONS_DIR = TELECLAUDE_HOME / "tmp" / "sessions"
SESSION_AUTH_DIR = TELECLAUDE_HOME / "session-auth"
LAUNCHER_SIGNING_DIR = TELECLAUDE_HOME / "launcher-signing"
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
LAUNCHER_SIGNING_RECORD_PATH = STATE_DIR / "launcher_signing.json"
INVITATIONS_PATH = STATE_DIR / "invitations.json"
LEGACY_DISCORD_HANDOFF_PATH = STATE_DIR / "legacy_discord_provider_ids.json"
DEPLOYED_COMMANDS_MANIFEST_PATH = STATE_DIR / "deployed_commands.json"
SESSION_DECLARATIONS_FILENAME = "declarations.json"
DECLARATION_VIEWS_DIR = STATE_DIR / "declaration-views"
CHIPTUNES_WORKER_LOG_PATH = LOGS_DIR / "chiptunes_worker.log"
MAIN_DB_PATH = TELECLAUDE_HOME / "teleclaude.db"
MIRRORS_DB_PATH = TELECLAUDE_HOME / "mirrors.db"
MIRRORS_BACKUP_DIR = TELECLAUDE_HOME / "backups" / "mirrors"
EVENTS_DB_PATH = TELECLAUDE_HOME / "events.db"
GIT_MAIN_LOCK_PATH = TELECLAUDE_HOME / "git-main.lock"
DOCS_DEPLOYMENT_LOCK_PATH = TELECLAUDE_HOME / "docs-deployment.lock"
CRON_PID_PATH = TELECLAUDE_HOME / "cron_runner.pid"
CHIPTUNES_PID_PATH = TELECLAUDE_HOME / "chiptunes.pid"
CHIPTUNES_SOCKET_PATH = TELECLAUDE_HOME / "chiptunes.sock"
GLOBAL_CONFIG_PATH = TELECLAUDE_HOME / ConfigFileName.OVERLAY
MACHINE_CONFIG_PATH = TELECLAUDE_HOME / ConfigFileName.MACHINE
PROJECTS_MANIFEST_PATH = TELECLAUDE_HOME / "projects.yaml"
ENV_PATH = TELECLAUDE_HOME / ConfigFileName.ENV
HOME_RETAINED_SET_PATH = TELECLAUDE_HOME / ".gitignore"

_SAFE_PATH_COMPONENT_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")
_SAFE_PATH_COMPONENT_HASH_LENGTH = 32


def safe_path_component(value: str) -> str:
    """Convert an identifier into a filesystem-safe path component."""
    if _SAFE_PATH_COMPONENT_PATTERN.fullmatch(value):
        return value
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_SAFE_PATH_COMPONENT_HASH_LENGTH]


def session_tmp_dir(session_id: str) -> Path:
    """Return the temporary directory path owned by a session."""
    return TMP_SESSIONS_DIR / safe_path_component(session_id)
