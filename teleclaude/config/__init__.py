"""Global configuration management.

Config is loaded at module import time and available globally via:
    from teleclaude.config import config
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml
from dotenv import load_dotenv

from teleclaude.constants import (
    DIRECTORY_CHECK_INTERVAL,
    REDIS_MAX_CONNECTIONS,
    REDIS_MESSAGE_STREAM_MAXLEN,
    REDIS_OUTPUT_STREAM_MAXLEN,
    REDIS_OUTPUT_STREAM_TTL,
    REDIS_SOCKET_TIMEOUT,
)
from teleclaude.runtime.binaries import resolve_agent_binary, resolve_tmux_binary
from teleclaude.utils import expand_env_vars

# Project root (relative to this file)
_project_root = Path(__file__).parent.parent.parent

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
class PollingConfig:
    directory_check_interval: int


@dataclass
class ComputerConfig:
    # pylint: disable=too-many-instance-attributes  # Config classes naturally have many fields
    name: str
    user: str
    role: str
    timezone: str
    default_working_dir: str
    is_master: bool
    trusted_dirs: list[TrustedDir]
    host: str | None = None  # Optional hostname/IP for SSH remote execution
    tmux_binary: str = "tmux"  # Resolved by runtime policy (not user-configurable)

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

    binary: str  # Resolved by runtime policy (not user-configurable)
    flags: str  # System-controlled flags, from AGENT_PROTOCOL
    session_dir: str
    log_pattern: str
    model_flags: dict[str, str]
    exec_subcommand: str
    interactive_flag: str  # Flag to add before prompt for interactive mode (e.g., "-i")
    non_interactive_flag: str  # Flag for non-interactive/pipe mode (e.g., "-p")
    resume_template: str
    continue_template: str = ""

    @property
    def command(self) -> str:
        """Assembled base command: binary + system flags."""
        return f"{self.binary} {self.flags}".strip()


@dataclass
class RedisConfig:
    """Redis configuration with user-configurable and internal settings."""

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
    model: str | None = None  # Optional local path or HF repo id
    params: dict[str, object] | None = None  # guard: loose-dict - Model-specific kwargs are dynamic.


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
class STTServiceConfig:
    """Configuration for a single STT service."""

    enabled: bool
    model: str | None = None  # HF repo id or local path (for parakeet)


@dataclass
class STTConfig:
    """Speech-to-text configuration."""

    enabled: bool
    service_priority: list[str] | None = None
    services: Dict[str, STTServiceConfig] | None = None


@dataclass
class SummarizerConfig:
    """Summarizer configuration.

    Controls whether the LLM summarizer runs and how feedback is displayed.

    Attributes:
        enabled: If True, run LLM summarizer. If False, skip summarization entirely.
        max_summary_words: Target maximum words for the summary output.
    """

    enabled: bool = True
    max_summary_words: int = 30


@dataclass
class TerminalConfig:
    """Terminal display settings."""

    strip_ansi: bool = True


@dataclass
class ExperimentConfig:
    """Configuration for a specific experiment.

    Attributes:
        name: Unique identifier for the experiment
        agents: Optional list of agents this experiment applies to.
               If None or empty, applies to all agents.
    """

    name: str
    agents: list[str] | None = None


@dataclass
class TelegramCredsConfig:
    user_name: str
    user_id: int


@dataclass
class CredsConfig:
    telegram: TelegramCredsConfig | None = None


@dataclass
class Config:
    database: DatabaseConfig
    computer: ComputerConfig
    polling: PollingConfig
    redis: RedisConfig
    telegram: TelegramConfig
    creds: CredsConfig
    agents: Dict[str, AgentConfig]
    ui: UIConfig
    terminal: TerminalConfig
    tts: TTSConfig | None = None
    stt: STTConfig | None = None
    summarizer: SummarizerConfig = field(default_factory=SummarizerConfig)
    experiments: list[ExperimentConfig] = field(default_factory=list)

    def is_experiment_enabled(self, name: str, agent: str | None = None) -> bool:
        """Check if an experiment is enabled, optionally for a specific agent.

        Args:
            name: Experiment name to check
            agent: Optional agent key to match against (e.g., "gemini")

        Returns:
            True if experiment is enabled and matches the agent (if provided)
        """
        for exp in self.experiments:
            if exp.name == name:
                # If agents list is empty or None, it applies to all agents
                if not exp.agents:
                    return True
                # Otherwise, agent must be in the list
                if agent and agent in exp.agents:
                    return True
        return False


# Default configuration values (single source of truth for user-configurable keys)
DEFAULT_CONFIG: dict[str, object] = {  # guard: loose-dict - YAML configuration structure
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
    },
    "polling": {
        "directory_check_interval": DIRECTORY_CHECK_INTERVAL,
    },
    "redis": {
        "enabled": False,
        "url": "redis://localhost:6379",
        "password": None,
        "max_connections": REDIS_MAX_CONNECTIONS,
        "socket_timeout": REDIS_SOCKET_TIMEOUT,
        "message_stream_maxlen": REDIS_MESSAGE_STREAM_MAXLEN,
        "output_stream_maxlen": REDIS_OUTPUT_STREAM_MAXLEN,
        "output_stream_ttl": REDIS_OUTPUT_STREAM_TTL,
    },
    "telegram": {
        "trusted_bots": [],
    },
    "creds": {
        "telegram": None,
    },
    "terminal": {
        "strip_ansi": True,
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
        "enabled": True,
        "max_summary_words": 30,
    },
    "experiments": [],
}


def _deep_merge(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:  # guard: loose-dict - YAML config merge
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


def _validate_disallowed_runtime_keys(user_config: dict[str, object]) -> None:  # guard: loose-dict
    """Reject config keys that must be runtime policy, not user configuration."""
    disallowed: list[str] = []

    if "agents" in user_config:
        disallowed.append("agents")

    computer = user_config.get("computer")
    if isinstance(computer, dict) and "tmux_binary" in computer:
        disallowed.append("computer.tmux_binary")

    if disallowed:
        joined = ", ".join(disallowed)
        raise ValueError(
            "config.yml contains disallowed runtime keys: "
            f"{joined}. "
            "Agent and tmux binaries are now hardcoded runtime policy and cannot be configured."
        )


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


def _parse_tts_config(raw_tts: dict[str, object] | None) -> TTSConfig | None:  # guard: loose-dict
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

                raw_params = service_data.get("params")
                params = dict(raw_params) if isinstance(raw_params, dict) else None

                services[service_name] = TTSServiceConfig(
                    enabled=bool(service_data.get("enabled", False)),
                    voices=voices if voices else None,
                    model=str(service_data.get("model")) if service_data.get("model") else None,
                    params=params,
                )

    return TTSConfig(enabled=tts_enabled, service_priority=service_priority, events=events, services=services)


def _parse_stt_config(raw_stt: dict[str, object] | None) -> STTConfig | None:  # guard: loose-dict
    """Parse STT config from raw dict."""
    if not raw_stt:
        return None

    stt_enabled = bool(raw_stt.get("enabled", False))
    service_priority_raw = raw_stt.get("service_priority", [])
    services_raw = raw_stt.get("services", {})

    service_priority = None
    if isinstance(service_priority_raw, list):
        service_priority = [str(s) for s in service_priority_raw]

    services: dict[str, STTServiceConfig] = {}
    if isinstance(services_raw, dict):
        for service_name, service_data in services_raw.items():
            if isinstance(service_data, dict):
                services[service_name] = STTServiceConfig(
                    enabled=bool(service_data.get("enabled", False)),
                    model=str(service_data.get("model")) if service_data.get("model") else None,
                )

    return STTConfig(enabled=stt_enabled, service_priority=service_priority, services=services)


def _build_config(raw: dict[str, object]) -> Config:  # guard: loose-dict - YAML deserialization input
    """Build typed Config from raw dict with proper type conversion."""
    db_raw = raw["database"]
    comp_raw = raw["computer"]
    polling_raw = raw.get("polling", {"directory_check_interval": DIRECTORY_CHECK_INTERVAL})
    redis_raw = raw["redis"]
    tg_raw = raw["telegram"]
    creds_raw = raw.get("creds", {})
    ui_raw = raw["ui"]
    terminal_raw = raw.get("terminal", {"strip_ansi": True})
    tts_raw = raw.get("tts", None)
    stt_raw = raw.get("stt", None)
    summarizer_raw = raw.get("summarizer", {})
    experiments_raw = raw.get("experiments", [])

    # Import AGENT_PROTOCOL from constants
    from teleclaude.constants import AGENT_PROTOCOL

    agents_registry: Dict[str, AgentConfig] = {}
    for name, protocol in AGENT_PROTOCOL.items():
        agents_registry[name] = AgentConfig(
            binary=resolve_agent_binary(name),
            flags=str(protocol["flags"]),
            session_dir=str(protocol["session_dir"]),
            log_pattern=str(protocol["log_pattern"]),
            model_flags=dict(protocol["model_flags"]),  # type: ignore[arg-type]
            exec_subcommand=str(protocol["exec_subcommand"]),
            interactive_flag=str(protocol["interactive_flag"]),
            non_interactive_flag=str(protocol["non_interactive_flag"]),
            resume_template=str(protocol["resume_template"]),
            continue_template=str(protocol.get("continue_template", "")),  # Optional field
        )

    experiments = []
    if isinstance(experiments_raw, list):
        for exp_data in experiments_raw:
            if isinstance(exp_data, dict):
                experiments.append(
                    ExperimentConfig(
                        name=str(exp_data["name"]),
                        agents=list(exp_data["agents"]) if exp_data.get("agents") else None,
                    )
                )

    tg_creds = None
    if isinstance(creds_raw, dict):
        tg_creds_raw = creds_raw.get("telegram")
        if isinstance(tg_creds_raw, dict):
            tg_creds = TelegramCredsConfig(
                user_name=str(tg_creds_raw["user_name"]),
                user_id=int(tg_creds_raw["user_id"]),
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
            tmux_binary=resolve_tmux_binary(),
        ),
        polling=PollingConfig(
            directory_check_interval=int(polling_raw["directory_check_interval"]),  # type: ignore[index,misc]
        ),
        redis=RedisConfig(
            enabled=bool(redis_raw["enabled"]),  # type: ignore[index,misc]
            url=str(redis_raw["url"]),  # type: ignore[index,misc]
            password=str(redis_raw["password"]) if redis_raw["password"] else None,  # type: ignore[index,misc]
            max_connections=int(redis_raw.get("max_connections", REDIS_MAX_CONNECTIONS)),  # type: ignore[index,misc]
            socket_timeout=int(redis_raw.get("socket_timeout", REDIS_SOCKET_TIMEOUT)),  # type: ignore[index,misc]
            message_stream_maxlen=int(redis_raw.get("message_stream_maxlen", REDIS_MESSAGE_STREAM_MAXLEN)),  # type: ignore[index,misc]
            output_stream_maxlen=int(redis_raw.get("output_stream_maxlen", REDIS_OUTPUT_STREAM_MAXLEN)),  # type: ignore[index,misc]
            output_stream_ttl=int(redis_raw.get("output_stream_ttl", REDIS_OUTPUT_STREAM_TTL)),  # type: ignore[index,misc]
        ),
        telegram=TelegramConfig(
            trusted_bots=list(tg_raw["trusted_bots"]),  # type: ignore[index,misc]
        ),
        creds=CredsConfig(telegram=tg_creds),
        agents=agents_registry,
        ui=UIConfig(
            animations_enabled=bool(ui_raw["animations_enabled"]),  # type: ignore[index,misc]
            animations_periodic_interval=int(ui_raw["animations_periodic_interval"]),  # type: ignore[index,misc]
            animations_subset=list(ui_raw.get("animations_subset", [])),  # type: ignore[index,misc]
        ),
        terminal=TerminalConfig(
            strip_ansi=bool(terminal_raw.get("strip_ansi", True))  # type: ignore[attr-defined]
        ),
        tts=_parse_tts_config(tts_raw),  # type: ignore[arg-type]
        stt=_parse_stt_config(stt_raw),  # type: ignore[arg-type]
        summarizer=SummarizerConfig(
            enabled=bool(summarizer_raw.get("enabled", True)) if isinstance(summarizer_raw, dict) else True,
            max_summary_words=int(summarizer_raw.get("max_summary_words", 30))
            if isinstance(summarizer_raw, dict)
            else 30,
        ),
        experiments=experiments,
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
    _raw_user_config = yaml.safe_load(f)  # type: ignore[misc]

# Expand environment variables
_user_config: Any = expand_env_vars(_raw_user_config) if isinstance(_raw_user_config, dict) else {}
if isinstance(_user_config, dict):
    _validate_disallowed_runtime_keys(_user_config)

# Load optional experiments.yml from same directory as config.yml
_experiments_path = _config_path.parent / "experiments.yml"
if _experiments_path.exists():
    with open(_experiments_path, encoding="utf-8") as f:
        _raw_experiments_config = yaml.safe_load(f)
    if isinstance(_raw_experiments_config, dict):
        # Expand env vars in experiments config too
        _experiments_config: Any = expand_env_vars(_raw_experiments_config)
        # Merge into user config (experiments leaf)
        if "experiments" in _experiments_config:
            if "experiments" not in _user_config:
                _user_config["experiments"] = []

            exp_list = _experiments_config["experiments"]
            if isinstance(exp_list, list):
                # Standard logger not yet available here, but we can add a log entry to DEFAULT_CONFIG or similar
                # Actually, config.py defines 'config' at the end.
                _user_config["experiments"].extend(exp_list)

if isinstance(_user_config, dict):
    _validate_disallowed_runtime_keys(_user_config)

# Merge with defaults and build typed config
_merged = _deep_merge(DEFAULT_CONFIG, _user_config)  # type: ignore[arg-type]

config = _build_config(_merged)
