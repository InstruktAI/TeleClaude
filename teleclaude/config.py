"""Global configuration management.

Config is loaded at module import time and available globally via:
    from teleclaude.config import config
"""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

from teleclaude.utils import expand_env_vars

# Load .env BEFORE expanding config variables
load_dotenv()


@dataclass
class TrustedDir:
    """Represents a trusted directory with metadata for AI understanding.

    Attributes:
        name: Human-readable identifier (e.g., "development", "documents", "projects")
        desc: Purpose description for AI context (e.g., "dev projects", "personal docs"). Can be empty.
        path: Absolute file system path to the directory
    """

    name: str
    desc: str
    path: str


@dataclass
class DatabaseConfig:
    _configured_path: str

    @property
    def path(self) -> str:
        """Get database path (lazy-loaded from env var for test compatibility)."""
        # Allow tests to override via TELECLAUDE_DB_PATH env var
        env_path = os.getenv("TELECLAUDE_DB_PATH")
        if env_path:
            return env_path
        # Otherwise use configured path
        return self._configured_path


@dataclass
class ComputerConfig:
    name: str
    role: str
    timezone: str
    default_shell: str
    default_working_dir: str
    is_master: bool
    trusted_dirs: list[TrustedDir]
    host: str | None = None  # Optional hostname/IP for SSH remote execution

    def get_all_trusted_dirs(self) -> list[TrustedDir]:
        """Get all trusted directories including default_working_dir.

        Returns list with default_working_dir first (desc="TeleClaude folder"),
        followed by configured trusted_dirs. Deduplicates by location path.

        Returns:
            List of TrustedDir objects with default_working_dir merged in
        """
        # Start with default working dir
        all_dirs = [
            TrustedDir(
                name="teleclaude",
                desc="TeleClaude folder",
                path=self.default_working_dir,
            )
        ]

        # Add trusted_dirs, skipping duplicates (compare by path)
        seen_paths = {self.default_working_dir}
        for trusted_dir in self.trusted_dirs:
            if trusted_dir.path not in seen_paths:
                all_dirs.append(trusted_dir)
                seen_paths.add(trusted_dir.path)

        return all_dirs


@dataclass
class LoggingConfig:
    level: str
    file: str


@dataclass
class PollingConfig:
    idle_notification_seconds: int
    lpoll_extensions: list[str]


@dataclass
class MCPConfig:
    enabled: bool
    transport: str
    socket_path: str


@dataclass
class RedisConfig:
    enabled: bool
    url: str
    password: str | None
    max_connections: int
    socket_timeout: int
    message_stream_maxlen: int
    output_stream_maxlen: int
    output_stream_ttl: int


@dataclass
class TelegramConfig:
    trusted_bots: list[str]


@dataclass
class Config:
    database: DatabaseConfig
    computer: ComputerConfig
    logging: LoggingConfig
    polling: PollingConfig
    mcp: MCPConfig
    redis: RedisConfig
    telegram: TelegramConfig


# Default configuration values (single source of truth)
DEFAULT_CONFIG: dict[str, object] = {
    "database": {
        "path": "${WORKING_DIR}/teleclaude.db",
    },
    "computer": {
        "name": "unknown",
        "role": "general",
        "timezone": "Europe/Amsterdam",
        "default_shell": "bash",
        "default_working_dir": "~",
        "is_master": False,
        "trusted_dirs": [],
        "host": None,
    },
    "logging": {
        "level": "INFO",
        "file": "/var/log/teleclaude.log",
    },
    "polling": {
        "idle_notification_seconds": 60,
        "lpoll_extensions": [],
    },
    "mcp": {
        "enabled": True,
        "transport": "socket",
        "socket_path": "/tmp/teleclaude.sock",
    },
    "redis": {
        "enabled": False,
        "url": "redis://localhost:6379",
        "password": None,
        "max_connections": 10,
        "socket_timeout": 5,
        "message_stream_maxlen": 10000,
        "output_stream_maxlen": 10000,
        "output_stream_ttl": 3600,
    },
    "telegram": {
        "trusted_bots": [],
    },
}


def _deep_merge(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    """Deep merge override dict into base dict.

    Args:
        base: Base dictionary with defaults
        override: Dictionary with overrides from user config

    Returns:
        Merged dictionary
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)  # type: ignore[arg-type]
        else:
            result[key] = value
    return result


def _parse_trusted_dirs(raw_dirs: list[str | dict[str, str]]) -> list[TrustedDir]:
    """Parse trusted_dirs from config, handling both old and new formats.

    Supports backward compatibility:
    - Old format: list[str] - converts to TrustedDir with name=basename, desc=""
    - New format: list[dict] - creates TrustedDir from dict fields

    Args:
        raw_dirs: List of strings (old format) or dicts (new format)

    Returns:
        List of TrustedDir objects
    """
    trusted_dirs = []
    for item in raw_dirs:
        if isinstance(item, str):
            # Old format: just a path string
            # Convert to new format with auto-generated name
            trusted_dirs.append(
                TrustedDir(
                    name=os.path.basename(item.rstrip("/")),
                    desc="",
                    path=item,
                )
            )
        elif isinstance(item, dict):
            # New format: dict with name, desc, path
            trusted_dirs.append(
                TrustedDir(
                    name=str(item["name"]),
                    desc=str(item.get("desc", "")),
                    path=str(item["path"]),
                )
            )
        else:
            raise ValueError(f"Invalid trusted_dirs entry type: {type(item)}")

    return trusted_dirs


def _build_config(raw: dict[str, object]) -> Config:
    """Build typed Config from raw dict with proper type conversion."""
    db = raw["database"]
    comp = raw["computer"]
    log = raw["logging"]
    poll = raw["polling"]
    mcp = raw["mcp"]
    redis = raw["redis"]
    tg = raw["telegram"]

    return Config(
        database=DatabaseConfig(
            _configured_path=str(db["path"]),  # type: ignore[index]
        ),
        computer=ComputerConfig(
            name=str(comp["name"]),  # type: ignore[index]
            role=str(comp["role"]),  # type: ignore[index]
            timezone=str(comp["timezone"]),  # type: ignore[index]
            default_shell=str(comp["default_shell"]),  # type: ignore[index]
            default_working_dir=str(comp["default_working_dir"]),  # type: ignore[index]
            is_master=bool(comp["is_master"]),  # type: ignore[index]
            trusted_dirs=_parse_trusted_dirs(list(comp["trusted_dirs"])),  # type: ignore[index]
            host=str(comp["host"]) if comp["host"] else None,  # type: ignore[index]
        ),
        logging=LoggingConfig(
            level=str(log["level"]),  # type: ignore[index]
            file=str(log["file"]),  # type: ignore[index]
        ),
        polling=PollingConfig(
            idle_notification_seconds=int(poll["idle_notification_seconds"]),  # type: ignore[index]
            lpoll_extensions=list(poll["lpoll_extensions"]),  # type: ignore[index]
        ),
        mcp=MCPConfig(
            enabled=bool(mcp["enabled"]),  # type: ignore[index]
            transport=str(mcp["transport"]),  # type: ignore[index]
            socket_path=str(mcp["socket_path"]),  # type: ignore[index]
        ),
        redis=RedisConfig(
            enabled=bool(redis["enabled"]),  # type: ignore[index]
            url=str(redis["url"]),  # type: ignore[index]
            password=str(redis["password"]) if redis["password"] else None,  # type: ignore[index]
            max_connections=int(redis["max_connections"]),  # type: ignore[index]
            socket_timeout=int(redis["socket_timeout"]),  # type: ignore[index]
            message_stream_maxlen=int(redis["message_stream_maxlen"]),  # type: ignore[index]
            output_stream_maxlen=int(redis["output_stream_maxlen"]),  # type: ignore[index]
            output_stream_ttl=int(redis["output_stream_ttl"]),  # type: ignore[index]
        ),
        telegram=TelegramConfig(
            trusted_bots=list(tg["trusted_bots"]),  # type: ignore[index]
        ),
    )


# Load config.yml from project root or TELECLAUDE_CONFIG_PATH env var (falls back to defaults if not found)
_project_root = Path(__file__).parent.parent
_config_path_env = os.getenv("TELECLAUDE_CONFIG_PATH")
_config_path = Path(_config_path_env) if _config_path_env else _project_root / "config.yml"

try:
    with open(_config_path, encoding="utf-8") as f:
        _user_config = yaml.safe_load(f)

    # Expand environment variables
    _user_config = expand_env_vars(_user_config)

    # Merge with defaults and build typed config
    _merged = _deep_merge(DEFAULT_CONFIG, _user_config)  # type: ignore[arg-type]
except FileNotFoundError:
    # Config file not found (e.g., in CI or fresh install) - use defaults
    _merged = DEFAULT_CONFIG

config = _build_config(_merged)
