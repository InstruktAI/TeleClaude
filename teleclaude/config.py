"""Global configuration management.

Config is loaded at module import time and available globally via:
    from teleclaude.config import config
"""

from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Load .env BEFORE expanding config variables
load_dotenv()

from teleclaude.utils import expand_env_vars


@dataclass
class DatabaseConfig:
    _configured_path: str

    @property
    def path(self) -> str:
        """Get database path (lazy-loaded from env var for test compatibility)."""
        import os

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
    trusted_dirs: list[str]


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
class RestAPIConfig:
    port: int


@dataclass
class Config:
    database: DatabaseConfig
    computer: ComputerConfig
    logging: LoggingConfig
    polling: PollingConfig
    mcp: MCPConfig
    redis: RedisConfig
    telegram: TelegramConfig
    rest_api: RestAPIConfig


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
    "rest_api": {
        "port": 6666,
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


def _build_config(raw: dict[str, object]) -> Config:
    """Build typed Config from raw dict with proper type conversion."""
    db = raw["database"]
    comp = raw["computer"]
    log = raw["logging"]
    poll = raw["polling"]
    mcp = raw["mcp"]
    redis = raw["redis"]
    tg = raw["telegram"]
    api = raw["rest_api"]

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
            trusted_dirs=list(comp["trusted_dirs"]),  # type: ignore[index]
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
        rest_api=RestAPIConfig(
            port=int(api["port"]),  # type: ignore[index]
        ),
    )


# Load config.yml from project root (falls back to defaults if not found)
_project_root = Path(__file__).parent.parent
_config_path = _project_root / "config.yml"

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
