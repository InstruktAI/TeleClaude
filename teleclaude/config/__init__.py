"""Global configuration management.

Runtime configuration is loaded on first attribute access and available via:
    from teleclaude.config import config
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import yaml
from dotenv import dotenv_values

from teleclaude.config._bootstrap import resolve_runtime_config_path
from teleclaude.config._chiptunes import ChiptunesConfig as ChiptunesConfig
from teleclaude.config._defaults import DEFAULT_CONFIG as DEFAULT_CONFIG
from teleclaude.config._environment import expand_environment_references as expand_environment_references
from teleclaude.config._machine_build import (
    CONFIG_LOAD_ACCEPTED as CONFIG_LOAD_ACCEPTED,
)
from teleclaude.config._machine_build import (
    CONFIG_LOAD_BUILD as CONFIG_LOAD_BUILD,
)
from teleclaude.config._machine_build import (
    CONFIG_LOAD_EVENT as CONFIG_LOAD_EVENT,
)
from teleclaude.config._machine_build import (
    CONFIG_LOAD_FIELD_SOURCES as CONFIG_LOAD_FIELD_SOURCES,
)
from teleclaude.config._machine_build import (
    CONFIG_LOAD_ID as CONFIG_LOAD_ID,
)
from teleclaude.config._machine_build import (
    CONFIG_LOAD_OUTCOME as CONFIG_LOAD_OUTCOME,
)
from teleclaude.config._machine_build import (
    CONFIG_LOAD_REJECTED as CONFIG_LOAD_REJECTED,
)
from teleclaude.config._machine_build import (
    CONFIG_LOAD_RESOLVED as CONFIG_LOAD_RESOLVED,
)
from teleclaude.config._machine_build import (
    CONFIG_LOAD_SECTION_AVAILABILITY as CONFIG_LOAD_SECTION_AVAILABILITY,
)
from teleclaude.config._machine_build import (
    CONFIG_LOAD_STAGE as CONFIG_LOAD_STAGE,
)
from teleclaude.config._machine_build import (
    WORKING_DIR as WORKING_DIR,
)
from teleclaude.config._machine_build import (
    build_config_from_raw as build_config_from_raw,
)
from teleclaude.config._machine_build import (
    deep_merge as deep_merge,
)
from teleclaude.config._machine_build import (
    detect_lan_ip as detect_lan_ip,
)
from teleclaude.config._machine_build import (
    prune_defaults as prune_defaults,
)
from teleclaude.config._machine_build import (
    strip_unset_placeholders as strip_unset_placeholders,
)
from teleclaude.config._models import AgentConfig as AgentConfig
from teleclaude.config._models import BackupConfig as BackupConfig
from teleclaude.config._models import ComputerConfig as ComputerConfig
from teleclaude.config._models import CredsConfig as CredsConfig
from teleclaude.config._models import DaemonConfig as DaemonConfig
from teleclaude.config._models import DeploymentConfig as DeploymentConfig
from teleclaude.config._models import DiscordConfig as DiscordConfig
from teleclaude.config._models import DiscordQoSConfig as DiscordQoSConfig
from teleclaude.config._models import EmailConfig as EmailConfig
from teleclaude.config._models import EventReliabilityConfig as EventReliabilityConfig
from teleclaude.config._models import ExperimentConfig as ExperimentConfig
from teleclaude.config._models import ModelChainEntry as ModelChainEntry
from teleclaude.config._models import PollingConfig as PollingConfig
from teleclaude.config._models import ProcessJanitorConfig as ProcessJanitorConfig
from teleclaude.config._models import RedisConfig as RedisConfig
from teleclaude.config._models import ReleaseChannel as ReleaseChannel
from teleclaude.config._models import STTConfig as STTConfig
from teleclaude.config._models import STTServiceConfig as STTServiceConfig
from teleclaude.config._models import TeleclaudeConfig as TeleclaudeConfig
from teleclaude.config._models import TelegramConfig as TelegramConfig
from teleclaude.config._models import TelegramCredsConfig as TelegramCredsConfig
from teleclaude.config._models import TelegramQoSConfig as TelegramQoSConfig
from teleclaude.config._models import TerminalConfig as TerminalConfig
from teleclaude.config._models import TTSConfig as TTSConfig
from teleclaude.config._models import TTSEventConfig as TTSEventConfig
from teleclaude.config._models import TTSServiceConfig as TTSServiceConfig
from teleclaude.config._models import TTSServiceVoiceConfig as TTSServiceVoiceConfig
from teleclaude.config._models import WhatsAppConfig as WhatsAppConfig
from teleclaude.config._models import WhatsAppCredsConfig as WhatsAppCredsConfig
from teleclaude.config._models import WhatsAppQoSConfig as WhatsAppQoSConfig
from teleclaude.config._models import WorkflowAutostartConfig as WorkflowAutostartConfig
from teleclaude.config._models import WorkflowConfig as WorkflowConfig
from teleclaude.config._models import WorkflowRunnerMode as WorkflowRunnerMode
from teleclaude.config._remote_computers import RemoteComputerConfig as RemoteComputerConfig
from teleclaude.config._summarizer import SummarizerConfig as SummarizerConfig
from teleclaude.config._summarizer import SummarizerLocalConfig as SummarizerLocalConfig
from teleclaude.config.migrations._runner import upcast_for_read
from teleclaude.config.observation import credential_field_sources as credential_field_sources
from teleclaude.config.observation import credential_section_availability as credential_section_availability
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.constants import (
    DIRECTORY_CHECK_INTERVAL as DIRECTORY_CHECK_INTERVAL,
)
from teleclaude.constants import (
    OUTPUT_CADENCE_S as OUTPUT_CADENCE_S,
)
from teleclaude.constants import (
    REDIS_MAX_CONNECTIONS as REDIS_MAX_CONNECTIONS,
)
from teleclaude.constants import (
    REDIS_MESSAGE_STREAM_MAXLEN as REDIS_MESSAGE_STREAM_MAXLEN,
)
from teleclaude.constants import (
    REDIS_OUTPUT_STREAM_MAXLEN as REDIS_OUTPUT_STREAM_MAXLEN,
)
from teleclaude.constants import (
    REDIS_OUTPUT_STREAM_TTL as REDIS_OUTPUT_STREAM_TTL,
)
from teleclaude.constants import (
    REDIS_SOCKET_TIMEOUT as REDIS_SOCKET_TIMEOUT,
)
from teleclaude.constants import (
    WHATSAPP_API_VERSION as WHATSAPP_API_VERSION,
)
from teleclaude.paths import PROJECT_ENV_PATH
from teleclaude.paths import ConfigFileName as ConfigFileName
from teleclaude.runtime.binaries import resolve_tmux_binary as resolve_tmux_binary

_dotenv_path = PROJECT_ENV_PATH

# Variables present before any .env load are shell-provided and keep precedence;
# .env-sourced variables are refreshed from the file on every (re)load.
_PRE_DOTENV_ENV_KEYS = frozenset(os.environ)
# Keys currently sourced from .env, so a reload can drop ones deleted from the file.
_dotenv_managed_keys: set[str] = set()


def _refresh_dotenv() -> None:
    """Apply the .env file to os.environ so config reload observes out-of-process edits.

    Shell-provided variables (captured before the first load) keep precedence over .env.
    .env-sourced variables are refreshed each call, and ones removed from the file are
    dropped from os.environ — so reload_config() reflects both edits and deletions of
    the ${VAR}-backed values the TUI writes to .env (Redis creds, summarizer URL, keys).
    """
    values = dotenv_values(_dotenv_path)
    current = {k for k, v in values.items() if v is not None and k not in _PRE_DOTENV_ENV_KEYS}
    for key in _dotenv_managed_keys - current:
        os.environ.pop(key, None)
    for key in current:
        os.environ[key] = str(values[key])
    _dotenv_managed_keys.clear()
    _dotenv_managed_keys.update(current)


def machine_runtime_environment() -> Mapping[str, str]:
    """Expose the established machine runtime environment to config adapters."""
    return os.environ


_refresh_dotenv()
os.environ.setdefault("WORKING_DIR", WORKING_DIR)


# Sections whose consumers re-read config at call-time, so a reload applies live via
# in-place singleton mutation (tts additionally needs TTSManager.reload()). This is a
# safe allowlist: any changed section NOT listed requires a daemon restart, because its
# consumers captured the value at startup and would otherwise silently ignore the change.
HOT_RELOADABLE_SECTIONS = frozenset({"chiptunes", "summarizer", "stt", "tts"})


def restart_required_sections(changed: list[str]) -> list[str]:
    """Return the changed sections that need a daemon restart (everything not hot-reloadable)."""
    return [section for section in changed if section not in HOT_RELOADABLE_SECTIONS]


def _load_config_from_disk(path: Path) -> TeleclaudeConfig:
    """Read config.yml (and optional adjacent experiments.yml) and build a typed Config."""
    _refresh_dotenv()  # pick up out-of-process .env edits before expanding ${VAR} placeholders
    with open(path, encoding="utf-8") as f:
        parsed: object = yaml.safe_load(f)
    raw_user_config = parsed if isinstance(parsed, dict) else {}
    migrated = upcast_for_read(path, raw_user_config, subject=SubjectRef(ConfigSubjectKind.COMPUTER))
    return build_config_from_raw(migrated, path.parent, config_source=path)


# Runtime config lives at ~/.teleclaude/config.yml, seeded from the repo blueprint.
_config_path = resolve_runtime_config_path()
_config: TeleclaudeConfig | None = None
config_path = _config_path
dotenv_path = _dotenv_path  # public alias; the config watcher watches config_path + dotenv_path


def _runtime_config() -> TeleclaudeConfig:
    """Load the runtime aggregate only when a runtime consumer requests it."""
    global _config
    if _config is None:
        if not _config_path.exists():
            raise FileNotFoundError(f"Config file not found: {_config_path}. Run 'telec config wizard' to create it.")
        _config = _load_config_from_disk(_config_path)
    return _config


class _RuntimeConfigAccessor:
    """Delegate runtime configuration attribute access to the lazy aggregate."""

    def __getattr__(self, name: str) -> Any:
        return getattr(_runtime_config(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(_runtime_config(), name, value)

    def __delattr__(self, name: str) -> None:
        delattr(_runtime_config(), name)


# Keep the established import surface and aggregate type for consumers. Importing
# this binding is cheap; using an aggregate attribute is the resolution boundary.
config = cast(TeleclaudeConfig, _RuntimeConfigAccessor())


def reload_config() -> list[str]:
    """Re-read config from disk and apply it to the live ``config`` singleton in place.

    The singleton's identity is preserved, so every ``from teleclaude.config import config``
    holder observes the new values without re-importing. Returns the names of the top-level
    sections that changed. Changed sections in ``HOT_RELOADABLE_SECTIONS`` take effect live;
    any other changed section needs a daemon restart (see ``restart_required_sections``).
    """
    current = _runtime_config()
    fresh = _load_config_from_disk(_config_path)
    changed = [
        name
        for name in TeleclaudeConfig.model_fields
        if name != CONFIG_LOAD_ID and getattr(current, name) != getattr(fresh, name)
    ]
    for name in TeleclaudeConfig.model_fields:
        object.__setattr__(current, name, getattr(fresh, name))
    object.__setattr__(current, "__pydantic_fields_set__", set(fresh.__pydantic_fields_set__))
    return changed
