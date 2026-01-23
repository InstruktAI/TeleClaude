"""Global configuration management.

Config is loaded at module import time and available globally via:
    from teleclaude.config import config
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

import yaml
from dotenv import load_dotenv

from teleclaude.constants import (
    REDIS_MAX_CONNECTIONS,
    REDIS_MESSAGE_STREAM_MAXLEN,
    REDIS_OUTPUT_STREAM_MAXLEN,
    REDIS_OUTPUT_STREAM_TTL,
    REDIS_SOCKET_TIMEOUT,
)
from teleclaude.utils import expand_env_vars

# Project root (relative to this file)
_project_root = Path(__file__).parent.parent

# Load .env (allow override for tests)
_env_path = os.getenv("TELECLAUDE_ENV_PATH")
_dotenv_path = Path(_env_path).expanduser() if _env_path else _project_root / ".env"
if not _dotenv_path.is_absolute():
    _dotenv_path = (_project_root / _dotenv_path).resolve()

load_dotenv(_dotenv_path)
WORKING_DIR = str(_project_root)
os.environ.setdefault("WORKING_DIR", WORKING_DIR)


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
class ComputerConfig:  # pylint: disable=too-many-instance-attributes  # Config classes naturally have many fields
    name: str
    user: str
    role: str
    timezone: str
    default_working_dir: str
    is_master: bool
    trusted_dirs: list[TrustedDir]
    host: str | None = None  # Optional hostname/IP for SSH remote execution
    tmux_binary: str = "tmux"  # Path to tmux binary or wrapper

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
class AgentConfig:
    """Configuration for a specific AI agent."""

    command: str  # The full base command string, including fixed flags
    session_dir: str
    log_pattern: str
    model_flags: dict[str, str]
    exec_subcommand: str
    interactive_flag: str  # Flag to add before prompt for interactive mode (e.g., "-i")
    non_interactive_flag: str  # Flag for non-interactive/pipe mode (e.g., "-p")
    resume_template: str
    continue_template: str = ""


@dataclass
class RedisConfig:
    """Redis configuration with user-configurable and internal settings."""

    enabled: bool
    url: str
    password: str | None

    # Internal settings exposed as properties (not configurable by user)
    @property
    def max_connections(self) -> int:
        return REDIS_MAX_CONNECTIONS

    @property
    def socket_timeout(self) -> int:
        return REDIS_SOCKET_TIMEOUT

    @property
    def message_stream_maxlen(self) -> int:
        return REDIS_MESSAGE_STREAM_MAXLEN

    @property
    def output_stream_maxlen(self) -> int:
        return REDIS_OUTPUT_STREAM_MAXLEN

    @property
    def output_stream_ttl(self) -> int:
        return REDIS_OUTPUT_STREAM_TTL


@dataclass
class TelegramConfig:
    trusted_bots: list[str]


@dataclass
class UIConfig:
    """TUI display settings."""

    animations_enabled: bool
    animations_periodic_interval: int
    animations_subset: List[str]  # Empty list means all animations enabled


@dataclass
class TTSServiceVoiceConfig:
    """Voice configuration for a TTS service."""

    name: str
    voice_id: str | None = None  # For services like ElevenLabs that need IDs


@dataclass
class TTSServiceConfig:
    """Configuration for a single TTS service."""

    enabled: bool
    voices: list[TTSServiceVoiceConfig] | None = None


@dataclass
class TTSEventConfig:
    """Configuration for a TTS event.

    Supports either a single message or a list of messages (picks randomly).
    """

    enabled: bool
    message: str | None = None
    messages: list[str] | None = None  # For random selection (e.g., startup greetings)


@dataclass
class TTSConfig:
    """Text-to-speech configuration."""

    enabled: bool
    service_priority: list[str] | None = None
    events: Dict[str, TTSEventConfig] | None = None
    services: Dict[str, TTSServiceConfig] | None = None


@dataclass
class SummarizerConfig:
    """Summarizer configuration.

    Controls whether TTS and UI display use the LLM-generated summary
    or the raw agent output.

    Attributes:
        use_summary: If True, use last_feedback_summary. If False, use last_feedback_received.
    """

    use_summary: bool = True


@dataclass
class Config:
    database: DatabaseConfig
    computer: ComputerConfig
    redis: RedisConfig
    telegram: TelegramConfig
    agents: Dict[str, AgentConfig]
    ui: UIConfig
    tts: TTSConfig | None = None
    summarizer: SummarizerConfig = field(default_factory=SummarizerConfig)


# Default configuration values (single source of truth)
DEFAULT_CONFIG: dict[str, object] = {  # noqa: loose-dict - YAML configuration structure
    "database": {
        "path": f"{WORKING_DIR}/teleclaude.db",
    },
    "computer": {
        "name": "unknown",
        "user": "unknown",
        "role": "general",
        "timezone": "Europe/Amsterdam",
        "default_working_dir": "~",
        "is_master": False,
        "trusted_dirs": [],
        "host": None,
        "tmux_binary": "tmux",
    },
    "redis": {
        "enabled": False,
        "url": "redis://localhost:6379",
        "password": None,
    },
    "telegram": {
        "trusted_bots": [],
    },
    "agents": {
        "claude": {
            "command": 'claude --dangerously-skip-permissions --settings \'{"forceLoginMethod": "claudeai"}\'',
        },
        "gemini": {
            "command": "gemini --yolo",
        },
        "codex": {
            "command": "codex --dangerously-bypass-approvals-and-sandbox --search",
        },
    },
    "ui": {
        "animations_enabled": True,
        "animations_periodic_interval": 60,
        "animations_subset": [],  # Empty list = all animations enabled
    },
    "tts": {
        "enabled": False,
        "events": {
            "session_start": {
                "enabled": False,
                "message": None,
            },
            "agent_stop": {
                "enabled": False,
                "message": None,
            },
        },
        "services": {
            "pyttsx3": {
                "enabled": True,
                "voices": [],
            },
            "macos": {
                "enabled": False,
                "voices": [],
            },
            "openai": {
                "enabled": False,
                "voices": [],
            },
            "elevenlabs": {
                "enabled": False,
                "voices": [],
            },
        },
    },
    "summarizer": {
        "use_summary": True,
    },
}


def _deep_merge(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:  # noqa: loose-dict - YAML config merge
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


def _parse_trusted_dirs(raw_dirs: list[object]) -> list[TrustedDir]:
    """Parse trusted_dirs from config.

    Expects list[dict] entries with name/desc/path.

    Args:
        raw_dirs: List of dicts with trusted dir metadata

    Returns:
        List of TrustedDir objects
    """
    trusted_dirs = []
    for item in raw_dirs:
        if isinstance(item, dict):
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


def _parse_tts_config(raw_tts: dict[str, object] | None) -> TTSConfig | None:  # noqa: loose-dict
    """Parse TTS config from raw dict.

    Args:
        raw_tts: Raw TTS dict from YAML

    Returns:
        TTSConfig object or None if not configured
    """
    if not raw_tts:
        return None

    tts_enabled = bool(raw_tts.get("enabled", False))
    service_priority_raw = raw_tts.get("service_priority", [])
    events_raw = raw_tts.get("events", {})
    services_raw = raw_tts.get("services", {})

    # Parse service priority
    service_priority = None
    if isinstance(service_priority_raw, list):
        service_priority = [str(s) for s in service_priority_raw]

    # Parse events
    events = {}
    if isinstance(events_raw, dict):
        for event_name, event_data in events_raw.items():
            if isinstance(event_data, dict):
                events[event_name] = TTSEventConfig(
                    enabled=bool(event_data.get("enabled", False)),
                    message=str(event_data.get("message", "")) if event_data.get("message") else None,
                )

    # Parse services
    services = {}
    if isinstance(services_raw, dict):
        for service_name, service_data in services_raw.items():
            if isinstance(service_data, dict):
                voices_raw = service_data.get("voices", [])
                voices = []
                if isinstance(voices_raw, list):
                    for voice_data in voices_raw:
                        if isinstance(voice_data, dict):
                            voices.append(
                                TTSServiceVoiceConfig(
                                    name=str(voice_data.get("name", "")),
                                    voice_id=str(voice_data.get("voice_id", ""))
                                    if voice_data.get("voice_id")
                                    else None,
                                )
                            )

                services[service_name] = TTSServiceConfig(
                    enabled=bool(service_data.get("enabled", False)),
                    voices=voices if voices else None,
                )

    return TTSConfig(enabled=tts_enabled, service_priority=service_priority, events=events, services=services)


def _build_config(raw: dict[str, object]) -> Config:  # noqa: loose-dict - YAML deserialization input
    """Build typed Config from raw dict with proper type conversion."""
    db_raw = raw["database"]
    comp_raw = raw["computer"]
    redis_raw = raw["redis"]
    tg_raw = raw["telegram"]
    ui_raw = raw["ui"]
    agents_raw = raw.get("agents", {})
    tts_raw = raw.get("tts", None)
    summarizer_raw = raw.get("summarizer", {})

    # Import AGENT_METADATA from constants
    from teleclaude.constants import AGENT_METADATA

    agents_registry: Dict[str, AgentConfig] = {}
    if isinstance(agents_raw, dict):
        for name, agent_data in agents_raw.items():
            if isinstance(agent_data, dict):
                # Get metadata from constants
                metadata = AGENT_METADATA.get(name, {})
                if not metadata:
                    raise ValueError(f"Unknown agent '{name}' - no metadata in constants.AGENT_METADATA")

                # Build AgentConfig from constants + user's command
                agents_registry[name] = AgentConfig(
                    command=str(agent_data["command"]),
                    session_dir=str(metadata["session_dir"]),
                    log_pattern=str(metadata["log_pattern"]),
                    model_flags=dict(metadata["model_flags"]),  # type: ignore[arg-type]
                    exec_subcommand=str(metadata["exec_subcommand"]),
                    interactive_flag=str(metadata["interactive_flag"]),
                    non_interactive_flag=str(metadata["non_interactive_flag"]),
                    resume_template=str(metadata["resume_template"]),
                    continue_template=str(metadata.get("continue_template", "")),  # Optional field
                )

    return Config(
        database=DatabaseConfig(
            _configured_path=str(db_raw["path"]),  # type: ignore[index,misc]
        ),
        computer=ComputerConfig(
            name=str(comp_raw["name"]),  # type: ignore[index,misc]
            user=str(comp_raw["user"]),  # type: ignore[index,misc]
            role=str(comp_raw["role"]),  # type: ignore[index,misc]
            timezone=str(comp_raw["timezone"]),  # type: ignore[index,misc]
            default_working_dir=str(comp_raw["default_working_dir"]),  # type: ignore[index,misc]
            is_master=bool(comp_raw["is_master"]),  # type: ignore[index,misc]
            trusted_dirs=_parse_trusted_dirs(list(comp_raw["trusted_dirs"])),  # type: ignore[index,misc]
            host=str(comp_raw["host"]) if comp_raw["host"] else None,  # type: ignore[index,misc]
            tmux_binary=str(comp_raw["tmux_binary"]),  # type: ignore[index,misc]
        ),
        redis=RedisConfig(
            enabled=bool(redis_raw["enabled"]),  # type: ignore[index,misc]
            url=str(redis_raw["url"]),  # type: ignore[index,misc]
            password=str(redis_raw["password"]) if redis_raw["password"] else None,  # type: ignore[index,misc]
        ),
        telegram=TelegramConfig(
            trusted_bots=list(tg_raw["trusted_bots"]),  # type: ignore[index,misc]
        ),
        agents=agents_registry,
        ui=UIConfig(
            animations_enabled=bool(ui_raw["animations_enabled"]),  # type: ignore[index,misc]
            animations_periodic_interval=int(ui_raw["animations_periodic_interval"]),  # type: ignore[index,misc]
            animations_subset=list(ui_raw.get("animations_subset", [])),  # type: ignore[index,misc]
        ),
        tts=_parse_tts_config(tts_raw),  # type: ignore[arg-type]
        summarizer=SummarizerConfig(
            use_summary=bool(summarizer_raw.get("use_summary", True)) if isinstance(summarizer_raw, dict) else True,
        ),
    )


# Load config.yml from project root (required)
_config_env_path = os.getenv("TELECLAUDE_CONFIG_PATH")
_config_path = Path(_config_env_path).expanduser() if _config_env_path else _project_root / "config.yml"
if not _config_path.is_absolute():
    _config_path = (_project_root / _config_path).resolve()

if not _config_path.exists():
    raise FileNotFoundError(
        f"Config file not found: {_config_path}. "
        "Set TELECLAUDE_CONFIG_PATH to a valid config (e.g., tests/integration/config.yml) or run 'make init' to create it."
    )

with open(_config_path, encoding="utf-8") as f:
    _user_config = yaml.safe_load(f)  # type: ignore[misc]

# Expand environment variables
_user_config = expand_env_vars(_user_config)  # type: ignore[misc]

# Merge with defaults and build typed config
_merged = _deep_merge(DEFAULT_CONFIG, _user_config)  # type: ignore[arg-type]

config = _build_config(_merged)
