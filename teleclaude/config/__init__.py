"""Global configuration management.

Config is loaded at module import time and available globally via:
    from teleclaude.config import config
"""

import getpass
import os
import socket
from dataclasses import fields
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values

from teleclaude.config._bootstrap import resolve_runtime_config_path
from teleclaude.config._chiptunes import ChiptunesConfig as ChiptunesConfig
from teleclaude.config._chiptunes import parse_chiptunes_config as _parse_chiptunes_config
from teleclaude.config._coerce import as_bool as _as_bool
from teleclaude.config._defaults import DEFAULT_CONFIG as DEFAULT_CONFIG
from teleclaude.config._models import AgentConfig as AgentConfig
from teleclaude.config._models import ComputerConfig as ComputerConfig
from teleclaude.config._models import CredsConfig as CredsConfig
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
from teleclaude.config._models import TrustedDir as TrustedDir
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
from teleclaude.config._remote_computers import parse_remote_computers as _parse_remote_computers
from teleclaude.config._summarizer import SummarizerConfig as SummarizerConfig
from teleclaude.config._summarizer import SummarizerLocalConfig as SummarizerLocalConfig
from teleclaude.config._summarizer import parse_summarizer_config as _parse_summarizer_config
from teleclaude.constants import (
    AGENT_PROTOCOL,
    DIRECTORY_CHECK_INTERVAL,
    GIT_AUTHOR_IDENTITIES,
    HELP_DESK_SUBDIR,
    OUTPUT_CADENCE_S,
    REDIS_MAX_CONNECTIONS,
    REDIS_MESSAGE_STREAM_MAXLEN,
    REDIS_OUTPUT_STREAM_MAXLEN,
    REDIS_OUTPUT_STREAM_TTL,
    REDIS_SOCKET_TIMEOUT,
    WHATSAPP_API_VERSION,
    AgentProtocolDict,
)
from teleclaude.paths import PROJECT_ENV_PATH, ConfigFileName
from teleclaude.runtime.binaries import resolve_agent_binary, resolve_tmux_binary
from teleclaude.utils import expand_env_vars

# Project root (relative to this file)
_project_root = Path(__file__).parent.parent.parent

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


_refresh_dotenv()
WORKING_DIR = str(_project_root)
os.environ.setdefault("WORKING_DIR", WORKING_DIR)


def detect_lan_ip() -> str:
    """Return this host's primary LAN IPv4, falling back to loopback.

    Opens a UDP socket toward a public address and reads the local endpoint the
    OS would route through; no packets are sent.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


# Default configuration values (single source of truth for user-configurable keys)
def deep_merge(
    base: dict[str, object],  # guard: loose-dict - YAML config merge
    override: dict[str, object],  # guard: loose-dict - YAML config merge
) -> dict[str, object]:  # guard: loose-dict - YAML config merge
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
            result[key] = deep_merge(result[key], value)  # type: ignore[arg-type]
        else:
            result[key] = value
    return result


def strip_unset_placeholders(data: object) -> object:
    """Drop config keys whose value is an unexpanded ``${VAR}`` placeholder.

    After :func:`expand_env_vars`, a value still shaped like ``${VAR}`` means the
    environment variable was unset. Dropping the key lets the ``DEFAULT_CONFIG``
    value win in :func:`deep_merge`, so the Python default applies instead of a
    literal ``"${VAR}"`` string silently overriding it.
    """
    if isinstance(data, dict):
        cleaned: dict[str, object] = {}  # guard: loose-dict - YAML config tree
        for key, value in data.items():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                continue
            cleaned[key] = strip_unset_placeholders(value)
        return cleaned
    if isinstance(data, list):
        return [strip_unset_placeholders(item) for item in data]
    return data


def prune_defaults(
    data: dict[str, object],  # guard: loose-dict - YAML config tree
    defaults: dict[str, object],  # guard: loose-dict - YAML config tree
) -> dict[str, object]:  # guard: loose-dict - YAML config tree
    """Return ``data`` with every leaf equal to its default removed.

    The inverse of :func:`deep_merge` against ``DEFAULT_CONFIG``: values matching
    the default are dropped so the persisted config carries only deviations. The
    loader re-fills defaults on read, so a pruned file loads identically.
    """
    pruned: dict[str, object] = {}  # guard: loose-dict - YAML config tree
    for key, value in data.items():
        default = defaults.get(key)
        if isinstance(value, dict) and isinstance(default, dict):
            nested = prune_defaults(value, default)
            if nested:
                pruned[key] = nested
        elif value != default:
            pruned[key] = value
    return pruned


def _require_agents_section(raw_config: dict[str, object]) -> dict[str, object]:  # guard: loose-dict
    """Require an explicit top-level `agents` mapping in config.yml."""
    agents_raw = raw_config.get("agents")
    if agents_raw is None:
        raise ValueError(
            "Missing required config key `config.yml:agents`. Add `agents:` with at least one configured agent entry."
        )
    if not isinstance(agents_raw, dict):
        raise ValueError("Invalid config key `config.yml:agents`: expected a mapping of agent names to settings.")
    return agents_raw


def _validate_known_agent_keys(
    agents_raw: dict[str, object],  # guard: loose-dict
    known_agents: tuple[str, ...],
) -> None:
    """Reject unknown agent keys under config.yml:agents."""
    unknown = sorted(str(name) for name in agents_raw.keys() if str(name) not in known_agents)
    if unknown:
        raise ValueError(
            f"Unknown key(s) under `config.yml:agents`: {', '.join(unknown)}. Allowed keys: {', '.join(known_agents)}."
        )


def _parse_model_chains(agent: str, raw: object, protocol: AgentProtocolDict) -> dict[str, list[ModelChainEntry]]:
    """Validate the operator-owned per-mode fallback chains for one agent.

    Each chain entry is a mapping carrying the model identity and its complete,
    opaque launch flags; the platform never derives flags from a template.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid config key `config.yml:agents.{agent}.model_chains`: expected a mapping.")
    mode_chains = protocol["mode_chains"]
    chains: dict[str, list[ModelChainEntry]] = {}
    for mode, entries_raw in raw.items():
        path = f"config.yml:agents.{agent}.model_chains.{mode}"
        if mode not in mode_chains:
            raise ValueError(f"Invalid config key `{path}`: unknown thinking mode.")
        if mode == "default":
            raise ValueError(f"Invalid config key `{path}`: default mode does not accept a model chain.")
        if not isinstance(entries_raw, list) or not entries_raw:
            raise ValueError(f"Invalid config key `{path}`: expected a non-empty list of {{model, flags}} entries.")
        entries: list[ModelChainEntry] = []
        for index, entry_raw in enumerate(entries_raw):
            entry_path = f"{path}[{index}]"
            if not isinstance(entry_raw, dict):
                raise ValueError(f"Invalid config key `{entry_path}`: expected a {{model, flags}} mapping.")
            unknown_keys = sorted(set(entry_raw) - {"model", "flags"})
            if unknown_keys:
                raise ValueError(f"Invalid config key `{entry_path}`: unknown key(s): {', '.join(unknown_keys)}.")
            model = entry_raw.get("model")
            flags = entry_raw.get("flags")
            if not isinstance(model, str) or not model.strip():
                raise ValueError(f"Invalid config key `{entry_path}.model`: expected a non-empty model identifier.")
            if not isinstance(flags, str) or not flags.strip():
                raise ValueError(f"Invalid config key `{entry_path}.flags`: expected a non-empty launch-flag string.")
            entries.append(ModelChainEntry(model=model, flags=flags))
        chains[str(mode)] = entries
    return chains


def _parse_categories(raw: object) -> dict[str, int] | None:
    """Parse Discord categories dict from config (name -> channel ID)."""
    if not isinstance(raw, dict):
        return None
    result: dict[str, int] = {}
    for key, val in raw.items():
        parsed = _parse_optional_int(val)
        if parsed is not None:
            result[str(key)] = parsed
    return result or None


def _parse_trusted_dirs(
    raw_dirs: list[object],
) -> list[TrustedDir]:
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
            # New format: dict with name, desc, path, optional discord_forum
            trusted_dirs.append(
                TrustedDir(
                    name=str(item["name"]),
                    desc=str(item.get("desc", "")),
                    path=str(item["path"]),
                    discord_forum=_parse_optional_int(item.get("discord_forum")),
                )
            )
        else:
            raise ValueError(f"Invalid trusted_dirs entry type: {type(item)}")

    return trusted_dirs


def parse_tts_config(
    raw_tts: dict[str, object] | None,  # guard: loose-dict - YAML config value
) -> TTSConfig | None:  # guard: loose-dict
    """Parse TTS config from raw dict.

    Args:
        raw_tts: Raw TTS dict from YAML

    Returns:
        TTSConfig object or None if not configured
    """
    if not raw_tts:
        return None

    return TTSConfig(
        enabled=_as_bool(raw_tts.get("enabled", False)),
        service_priority=_parse_service_priority(raw_tts.get("service_priority", [])),
        events=_parse_tts_events(raw_tts.get("events", {})),
        services=_parse_tts_services(raw_tts.get("services", {})),
    )


def _parse_service_priority(raw_value: object) -> list[str] | None:
    if not isinstance(raw_value, list):
        return None
    return [str(item) for item in raw_value]


def _parse_tts_events(raw_events: object) -> dict[str, TTSEventConfig]:
    events: dict[str, TTSEventConfig] = {}
    if not isinstance(raw_events, dict):
        return events
    for event_name, event_data in raw_events.items():
        if isinstance(event_data, dict):
            events[event_name] = TTSEventConfig(
                enabled=_as_bool(event_data.get("enabled", False)),
                messages=_parse_tts_event_messages(event_data.get("messages"), event_data.get("message")),
            )
    return events


def _parse_tts_event_messages(raw_messages: object, legacy_message: object = None) -> list[str] | None:
    """Parse the messages pool, folding a legacy single ``message`` into the list."""
    messages = [str(item) for item in raw_messages if item] if isinstance(raw_messages, list) else []
    if not messages and legacy_message:
        messages = [str(legacy_message)]
    return messages or None


def _parse_tts_voices(raw_voices: object) -> list[TTSServiceVoiceConfig]:
    voices: list[TTSServiceVoiceConfig] = []
    if not isinstance(raw_voices, list):
        return voices
    for voice_data in raw_voices:
        if isinstance(voice_data, dict):
            voices.append(
                TTSServiceVoiceConfig(
                    name=str(voice_data.get("name", "")),
                    voice_id=str(voice_data.get("voice_id", "")) if voice_data.get("voice_id") else None,
                )
            )
    return voices


def _parse_tts_service(service_data: object) -> TTSServiceConfig | None:
    if not isinstance(service_data, dict):
        return None
    voices = _parse_tts_voices(service_data.get("voices", []))
    raw_params = service_data.get("params")
    params = dict(raw_params) if isinstance(raw_params, dict) else None
    return TTSServiceConfig(
        enabled=_as_bool(service_data.get("enabled", False)),
        voices=voices if voices else None,
        model=str(service_data.get("model")) if service_data.get("model") else None,
        params=params,
    )


def _parse_tts_services(raw_services: object) -> dict[str, TTSServiceConfig]:
    services: dict[str, TTSServiceConfig] = {}
    if not isinstance(raw_services, dict):
        return services
    for service_name, service_data in raw_services.items():
        parsed = _parse_tts_service(service_data)
        if parsed is not None:
            services[service_name] = parsed
    return services


def _parse_process_janitor_config(raw: dict[str, object] | None) -> ProcessJanitorConfig:  # guard: loose-dict
    """Parse process janitor config from raw dict."""
    if not raw:
        return ProcessJanitorConfig()
    return ProcessJanitorConfig(
        scan_interval_seconds=_parse_process_janitor_seconds(raw, "scan_interval_seconds", 300),
        default_signature_ttl_seconds=_parse_process_janitor_seconds(raw, "default_signature_ttl_seconds", 3600),
        lease_ttl_seconds=_parse_process_janitor_seconds(raw, "lease_ttl_seconds", 1800),
        dry_run_default=_as_bool(raw.get("dry_run_default", True)),
        reap_revalidation_seconds=_parse_process_janitor_seconds(raw, "reap_revalidation_seconds", 3600),
    )


def _parse_process_janitor_seconds(raw: dict[str, object], key: str, default: int) -> int:  # guard: loose-dict
    """Parse a process janitor duration and enforce the schema floor."""
    value = raw.get(key)
    if value is None:
        return default
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise ValueError(f"process_janitor.{key} must be an integer")
    if parsed < 60:
        raise ValueError(f"process_janitor.{key} must be greater than or equal to 60")
    return parsed


def _parse_workflow_config(raw: dict[str, object] | None) -> WorkflowConfig:  # guard: loose-dict
    """Parse the daemon-runtime workflow control-plane config from raw dict."""
    if not raw:
        return WorkflowConfig()
    autostart_raw = raw.get("autostart")
    autostart = WorkflowAutostartConfig()
    if isinstance(autostart_raw, dict):
        autostart = WorkflowAutostartConfig(
            feature=_as_bool(autostart_raw.get("feature", False)),
            change=_as_bool(autostart_raw.get("change", False)),
            bug=_as_bool(autostart_raw.get("bug", False)),
            task=_as_bool(autostart_raw.get("task", False)),
        )
    runner_raw = raw.get("runner", "autostart")
    if not isinstance(runner_raw, str):
        raise ValueError(f"workflow.runner must be one of {[mode.value for mode in WorkflowRunnerMode]}")
    try:
        runner = WorkflowRunnerMode(runner_raw)
    except ValueError:
        raise ValueError(f"workflow.runner must be one of {[mode.value for mode in WorkflowRunnerMode]}") from None
    max_dispatch_raw = raw.get("max_todo_dispatch", 5)
    if isinstance(max_dispatch_raw, bool) or not isinstance(max_dispatch_raw, int):
        if isinstance(max_dispatch_raw, str) and max_dispatch_raw.strip().isdigit():
            max_todo_dispatch = int(max_dispatch_raw.strip())
        else:
            raise ValueError("workflow.max_todo_dispatch must be an integer")
    else:
        max_todo_dispatch = max_dispatch_raw
    if max_todo_dispatch < 1:
        raise ValueError("workflow.max_todo_dispatch must be greater than or equal to 1")
    return WorkflowConfig(autostart=autostart, runner=runner, max_todo_dispatch=max_todo_dispatch)


def _parse_deployment_config(raw: dict[str, object] | None) -> DeploymentConfig:  # guard: loose-dict
    """Parse the machine self-update release-channel config from raw dict.

    Enforces the stable-channel-requires-pinned_minor rule (via the dataclass
    ``__post_init__``) so an invalid ``config.yml:deployment`` block fails loudly at
    load instead of silently shipping the wrong channel.
    """
    if not raw:
        return DeploymentConfig()
    channel_raw = raw.get("channel", "alpha")
    try:
        channel = ReleaseChannel(str(channel_raw))
    except ValueError:
        raise ValueError(f"deployment.channel must be one of {[c.value for c in ReleaseChannel]}") from None
    pinned_minor = str(raw.get("pinned_minor", "") or "")
    return DeploymentConfig(channel=channel, pinned_minor=pinned_minor)


def parse_stt_config(raw_stt: dict[str, object] | None) -> STTConfig | None:  # guard: loose-dict
    """Parse STT config from raw dict."""
    if not raw_stt:
        return None

    stt_enabled = _as_bool(raw_stt.get("enabled", False))
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
                    enabled=_as_bool(service_data.get("enabled", False)),
                    model=str(service_data.get("model")) if service_data.get("model") else None,
                )

    return STTConfig(enabled=stt_enabled, service_priority=service_priority, services=services)


def _parse_optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return None


def _build_config(
    raw: dict[str, object],  # guard: loose-dict - YAML deserialization input
) -> TeleclaudeConfig:
    """Build typed TeleclaudeConfig from raw dict with proper type conversion."""
    comp_raw = raw["computer"]
    if not isinstance(comp_raw, dict):
        raise ValueError("Invalid config key `config.yml:computer`: expected a mapping.")
    redis_raw = raw["redis"]
    if not isinstance(redis_raw, dict):
        raise ValueError("Invalid config key `config.yml:redis`: expected a mapping.")
    discord_raw = raw.get("discord", {})
    telegram_raw = raw.get("telegram", {})
    whatsapp_raw = raw.get("whatsapp", {})
    creds_raw = raw.get("creds", {})
    terminal_raw = raw.get("terminal", {})
    tts_raw = raw.get("tts", None)
    stt_raw = raw.get("stt", None)
    chiptunes_raw = raw.get("chiptunes", None)
    process_janitor_raw = raw.get("process_janitor", None)
    workflow_raw = raw.get("workflow", None)
    deployment_raw = raw.get("deployment", None)
    summarizer_raw = raw.get("summarizer", None)
    experiments_raw = raw.get("experiments", [])
    agents_raw = dict(_require_agents_section(raw))

    known_agents = tuple(AGENT_PROTOCOL.keys())

    default_agent_raw = agents_raw.pop("default", None)
    if default_agent_raw is None:
        raise ValueError(
            f"Missing required config key `config.yml:agents.default`. Set it to one of: {', '.join(known_agents)}."
        )
    if not isinstance(default_agent_raw, str):
        raise ValueError(
            f"Invalid config key `config.yml:agents.default`: expected a string ({', '.join(known_agents)})."
        )
    default_agent = default_agent_raw.strip().lower()
    if default_agent not in known_agents:
        raise ValueError(
            f"Invalid config key `config.yml:agents.default`: unknown agent '{default_agent_raw}'. "
            f"Allowed values: {', '.join(known_agents)}."
        )

    _validate_known_agent_keys(agents_raw, known_agents)

    agents_registry: dict[str, AgentConfig] = {}
    for name, protocol in AGENT_PROTOCOL.items():
        # Get user overrides for this agent if any
        val = agents_raw.get(name)
        if val is not None and not isinstance(val, dict):
            raise ValueError(f"Invalid config key `config.yml:agents.{name}`: expected a mapping of agent settings.")
        user_agent_config = val if isinstance(val, dict) else {}
        model_chains = _parse_model_chains(name, user_agent_config.get("model_chains"), protocol)

        agents_registry[name] = AgentConfig(
            binary=resolve_agent_binary(name),
            profiles=dict(protocol["profiles"]),
            session_dir=str(protocol["session_dir"]),
            log_pattern=str(protocol["log_pattern"]),
            mode_chains={
                mode: [ModelChainEntry(model=str(entry["model"]), flags=str(entry["flags"])) for entry in entries]
                for mode, entries in protocol["mode_chains"].items()
            },
            model_chains=model_chains,
            exec_subcommand=str(protocol["exec_subcommand"]),
            interactive_flag=str(protocol["interactive_flag"]),
            non_interactive_flag=str(protocol["non_interactive_flag"]),
            resume_template=str(protocol["resume_template"]),
            continue_template=str(protocol.get("continue_template", "")),  # Optional field
            enabled=_as_bool(user_agent_config.get("enabled", True)),
            git_identity=GIT_AUTHOR_IDENTITIES.get(name),
        )

    if not any(agent_cfg.enabled for agent_cfg in agents_registry.values()):
        raise ValueError(
            "Invalid config at `config.yml:agents`: all known agents are disabled. "
            "Set `config.yml:agents.<agent>.enabled: true` for at least one configured agent."
        )
    if not agents_registry[default_agent].enabled:
        raise ValueError(
            f"Invalid config key `config.yml:agents.default`: '{default_agent}' is disabled. "
            f"Enable `config.yml:agents.{default_agent}.enabled: true` or choose an enabled agent."
        )

    experiments = []
    if isinstance(experiments_raw, list):
        for exp_data in experiments_raw:
            if isinstance(exp_data, dict):
                experiments.append(
                    ExperimentConfig(
                        name=str(exp_data["name"]),
                        agents=list(exp_data["agents"]) if exp_data.get("agents") else None,
                        adapters=list(exp_data["adapters"]) if exp_data.get("adapters") else None,
                    )
                )

    tg_creds = None
    whatsapp_creds = None
    if isinstance(creds_raw, dict):
        tg_creds_raw = creds_raw.get("telegram")
        if isinstance(tg_creds_raw, dict):
            tg_creds = TelegramCredsConfig(
                user_name=str(tg_creds_raw["user_name"]),
                user_id=int(tg_creds_raw["user_id"]),
            )
        whatsapp_creds_raw = creds_raw.get("whatsapp")
        if isinstance(whatsapp_creds_raw, dict) and whatsapp_creds_raw.get("phone_number"):
            whatsapp_creds = WhatsAppCredsConfig(phone_number=str(whatsapp_creds_raw["phone_number"]))

    whatsapp_phone_number_id = None
    whatsapp_access_token = None
    whatsapp_webhook_secret = None
    whatsapp_verify_token = None
    whatsapp_template_name = None
    whatsapp_template_language = "en_US"
    whatsapp_enabled_flag = False

    if isinstance(whatsapp_raw, dict):
        whatsapp_phone_number_id = (
            str(whatsapp_raw.get("phone_number_id")) if whatsapp_raw.get("phone_number_id") else None
        )
        whatsapp_access_token = str(whatsapp_raw.get("access_token")) if whatsapp_raw.get("access_token") else None
        whatsapp_webhook_secret = (
            str(whatsapp_raw.get("webhook_secret")) if whatsapp_raw.get("webhook_secret") else None
        )
        whatsapp_verify_token = str(whatsapp_raw.get("verify_token")) if whatsapp_raw.get("verify_token") else None
        whatsapp_template_name = str(whatsapp_raw.get("template_name")) if whatsapp_raw.get("template_name") else None
        whatsapp_template_language = str(whatsapp_raw.get("template_language") or "en_US")
        whatsapp_enabled_flag = _as_bool(whatsapp_raw.get("enabled", False))

    whatsapp_phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID") or whatsapp_phone_number_id
    whatsapp_access_token = os.getenv("WHATSAPP_ACCESS_TOKEN") or whatsapp_access_token
    whatsapp_webhook_secret = os.getenv("WHATSAPP_WEBHOOK_SECRET") or whatsapp_webhook_secret
    whatsapp_verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN") or whatsapp_verify_token
    whatsapp_template_name = os.getenv("WHATSAPP_TEMPLATE_NAME") or whatsapp_template_name
    whatsapp_template_language = os.getenv("WHATSAPP_TEMPLATE_LANGUAGE") or whatsapp_template_language

    # The explicit `enabled` flag is authoritative. Presence of credentials must
    # never force-enable the adapter — config-shipped ${VAR} placeholders are
    # non-empty strings, so an `or credentials` clause would enable WhatsApp
    # regardless of `enabled: false`. Credential sufficiency is enforced at adapter
    # start, not here.
    whatsapp_enabled = whatsapp_enabled_flag

    remote_computers = _parse_remote_computers(raw.get("remote_computers"))

    email_raw = raw.get("email")
    email_enabled = _as_bool(email_raw.get("enabled", False)) if isinstance(email_raw, dict) else False

    return TeleclaudeConfig(
        computer=ComputerConfig(
            name=str(comp_raw["name"]),  # type: ignore[index]
            # Derived, not user-editable: system login, project dir, and the
            # detected LAN address (host is required by get_computer_info).
            user=str(comp_raw["user"] or getpass.getuser()),  # type: ignore[index]
            role=str(comp_raw["role"]),  # type: ignore[index]
            timezone=str(comp_raw["timezone"]),  # type: ignore[index]
            default_working_dir=str(comp_raw["default_working_dir"] or WORKING_DIR),  # type: ignore[index]
            help_desk_dir=str(Path.home() / HELP_DESK_SUBDIR),
            is_master=bool(comp_raw["is_master"]),  # type: ignore[index]
            trusted_dirs=_parse_trusted_dirs(
                list(comp_raw["trusted_dirs"]),  # type: ignore[index]
            ),
            host=str(comp_raw["host"] or detect_lan_ip()),  # type: ignore[index]
            tmux_binary=resolve_tmux_binary(),
            is_ingress_node=bool(comp_raw["is_ingress_node"]),  # type: ignore[index]
        ),
        polling=PollingConfig(
            directory_check_interval=DIRECTORY_CHECK_INTERVAL,
            output_cadence_s=OUTPUT_CADENCE_S,
        ),
        redis=RedisConfig(
            url=str(redis_raw["url"]),
            password=str(redis_raw["password"]) if redis_raw["password"] else None,
            max_connections=int(redis_raw.get("max_connections", REDIS_MAX_CONNECTIONS)),
            socket_timeout=int(redis_raw.get("socket_timeout", REDIS_SOCKET_TIMEOUT)),
            message_stream_maxlen=int(redis_raw.get("message_stream_maxlen", REDIS_MESSAGE_STREAM_MAXLEN)),
            output_stream_maxlen=int(redis_raw.get("output_stream_maxlen", REDIS_OUTPUT_STREAM_MAXLEN)),
            output_stream_ttl=int(redis_raw.get("output_stream_ttl", REDIS_OUTPUT_STREAM_TTL)),
        ),
        event_reliability=EventReliabilityConfig(
            idle_threshold_ms=30_000,
            max_attempts=3,
            sweep_interval_ms=5_000,
            dlq_destination="teleclaude:events:dlq",
        ),
        telegram=TelegramConfig(
            enabled=_as_bool(telegram_raw.get("enabled", False)) if isinstance(telegram_raw, dict) else False,
            qos=TelegramQoSConfig(),
        ),
        discord=DiscordConfig(
            enabled=_as_bool(discord_raw.get("enabled", False)) if isinstance(discord_raw, dict) else False,
            token=(
                str(discord_raw.get("token")) if isinstance(discord_raw, dict) and discord_raw.get("token") else None
            ),
            guild_id=(_parse_optional_int(discord_raw.get("guild_id")) if isinstance(discord_raw, dict) else None),
            help_desk_channel_id=(
                _parse_optional_int(discord_raw.get("help_desk_channel_id")) if isinstance(discord_raw, dict) else None
            ),
            escalation_channel_id=(
                _parse_optional_int(discord_raw.get("escalation_channel_id")) if isinstance(discord_raw, dict) else None
            ),
            all_sessions_channel_id=(
                _parse_optional_int(discord_raw.get("all_sessions_channel_id"))
                if isinstance(discord_raw, dict)
                else None
            ),
            operator_chat_channel_id=(
                _parse_optional_int(discord_raw.get("operator_chat_channel_id"))
                if isinstance(discord_raw, dict)
                else None
            ),
            announcements_channel_id=(
                _parse_optional_int(discord_raw.get("announcements_channel_id"))
                if isinstance(discord_raw, dict)
                else None
            ),
            general_channel_id=(
                _parse_optional_int(discord_raw.get("general_channel_id")) if isinstance(discord_raw, dict) else None
            ),
            categories=(_parse_categories(discord_raw.get("categories")) if isinstance(discord_raw, dict) else None),
            qos=DiscordQoSConfig(),
        ),
        creds=CredsConfig(telegram=tg_creds, whatsapp=whatsapp_creds),
        agents=agents_registry,
        default_agent=default_agent,
        terminal=TerminalConfig(
            strip_ansi=bool(terminal_raw.get("strip_ansi", True))  # type: ignore[attr-defined]
        ),
        whatsapp=WhatsAppConfig(
            enabled=whatsapp_enabled,
            phone_number_id=whatsapp_phone_number_id,
            access_token=whatsapp_access_token,
            webhook_secret=whatsapp_webhook_secret,
            verify_token=whatsapp_verify_token,
            api_version=WHATSAPP_API_VERSION,
            template_name=whatsapp_template_name,
            template_language=whatsapp_template_language,
            qos=WhatsAppQoSConfig(),
        ),
        email=EmailConfig(enabled=email_enabled),
        tts=parse_tts_config(tts_raw),  # type: ignore[arg-type]
        stt=parse_stt_config(stt_raw),  # type: ignore[arg-type]
        chiptunes=_parse_chiptunes_config(chiptunes_raw),  # type: ignore[arg-type]
        process_janitor=_parse_process_janitor_config(process_janitor_raw),  # type: ignore[arg-type]
        workflow=_parse_workflow_config(workflow_raw),  # type: ignore[arg-type]
        deployment=_parse_deployment_config(deployment_raw),  # type: ignore[arg-type]
        summarizer=_parse_summarizer_config(summarizer_raw),  # type: ignore[arg-type]
        experiments=experiments,
        remote_computers=remote_computers,
    )


# Sections whose consumers re-read config at call-time, so a reload applies live via
# in-place singleton mutation (tts additionally needs TTSManager.reload()). This is a
# safe allowlist: any changed section NOT listed requires a daemon restart, because its
# consumers captured the value at startup and would otherwise silently ignore the change.
HOT_RELOADABLE_SECTIONS = frozenset({"chiptunes", "summarizer", "stt", "tts"})


def restart_required_sections(changed: list[str]) -> list[str]:
    """Return the changed sections that need a daemon restart (everything not hot-reloadable)."""
    return [section for section in changed if section not in HOT_RELOADABLE_SECTIONS]


def build_config_from_raw(raw_user_config: object, sibling_dir: Path) -> TeleclaudeConfig:
    """Build the typed config from raw YAML and adjacent machine-config files."""
    user_config: Any = (
        strip_unset_placeholders(expand_env_vars(raw_user_config)) if isinstance(raw_user_config, dict) else {}
    )

    experiments_path = sibling_dir / "experiments.yml"
    if experiments_path.exists():
        with open(experiments_path, encoding="utf-8") as f:
            raw_experiments_config = yaml.safe_load(f)
        if isinstance(raw_experiments_config, dict) and isinstance(user_config, dict):
            experiments_config: Any = strip_unset_placeholders(expand_env_vars(raw_experiments_config))
            if "experiments" in experiments_config:
                user_config.setdefault("experiments", [])
                exp_list = experiments_config["experiments"]
                if isinstance(exp_list, list):
                    user_config["experiments"].extend(exp_list)

    if isinstance(user_config, dict):
        pass

    merged = deep_merge(DEFAULT_CONFIG, user_config)  # type: ignore[arg-type]
    return _build_config(merged)


def _load_config_from_disk(path: Path) -> TeleclaudeConfig:
    """Read config.yml (and optional adjacent experiments.yml) and build a typed Config."""
    _refresh_dotenv()  # pick up out-of-process .env edits before expanding ${VAR} placeholders
    with open(path, encoding="utf-8") as f:
        raw_user_config = yaml.safe_load(f)
    return build_config_from_raw(raw_user_config, path.parent)


# Runtime config lives at ~/.teleclaude/config.yml, seeded from the repo blueprint.
_config_path = resolve_runtime_config_path(_project_root / "templates" / ConfigFileName.MACHINE, deep_merge)

if not _config_path.exists():
    raise FileNotFoundError(f"Config file not found: {_config_path}. Run 'telec config wizard' to create it.")

config = _load_config_from_disk(_config_path)
config_path = _config_path
dotenv_path = _dotenv_path  # public alias; the config watcher watches config_path + dotenv_path


def reload_config() -> list[str]:
    """Re-read config from disk and apply it to the live ``config`` singleton in place.

    The singleton's identity is preserved, so every ``from teleclaude.config import config``
    holder observes the new values without re-importing. Returns the names of the top-level
    sections that changed. Changed sections in ``HOT_RELOADABLE_SECTIONS`` take effect live;
    any other changed section needs a daemon restart (see ``restart_required_sections``).
    """
    fresh = _load_config_from_disk(_config_path)
    changed = [f.name for f in fields(TeleclaudeConfig) if getattr(config, f.name) != getattr(fresh, f.name)]
    config.__dict__.update(fresh.__dict__)
    return changed
