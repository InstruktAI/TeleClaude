"""Machine runtime configuration build pipeline."""

from __future__ import annotations

import getpass
import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast
from uuid import uuid4

import yaml
from instrukt_ai_logging import get_logger
from pydantic import Field, TypeAdapter, ValidationError

from teleclaude.agent_registry import AgentName
from teleclaude.closed_model import ClosedModel
from teleclaude.config._agents import _agent_editable_keys, build_agents_registry
from teleclaude.config._coerce import SCALAR_INPUT
from teleclaude.config._defaults import DEFAULT_CONFIG
from teleclaude.config._environment import expand_environment_references
from teleclaude.config._models import (
    AgentConfig,
    ComputerConfig,
    ConfigValidationIssue,
    EventReliabilityConfig,
    ExperimentConfig,
    PollingConfig,
    TeleclaudeConfig,
    TTSConfig,
    TTSEventConfig,
    VoxCPMVoiceConfig,
    tts_service_model,
)
from teleclaude.config._remote_computers import RemoteComputerConfig
from teleclaude.config._unresolved import (
    DROP,
    FieldOverrides,
    drop_unresolved,
    drop_unresolved_fields,
    drop_unresolved_untyped,
    is_unresolved,
)
from teleclaude.config.errors import ConfigLoadError
from teleclaude.config.machine_environment import machine_runtime_environment
from teleclaude.config.observation import credential_field_sources, credential_section_availability
from teleclaude.constants import (
    DIRECTORY_CHECK_INTERVAL,
    OUTPUT_CADENCE_S,
    WHATSAPP_API_VERSION,
)
from teleclaude.paths import ConfigFileName
from teleclaude.runtime.binaries import resolve_tmux_binary

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent
WORKING_DIR = str(_PROJECT_ROOT)

CONFIG_LOAD_EVENT = "config_load_observation"
CONFIG_LOAD_ACCEPTED = "accepted"
CONFIG_LOAD_RESOLVED = "resolved"
CONFIG_LOAD_REJECTED = "rejected"
CONFIG_LOAD_STAGE = "stage"
CONFIG_LOAD_BUILD = "build"
CONFIG_LOAD_ID = "load_id"
CONFIG_LOAD_OUTCOME = "outcome"
CONFIG_LOAD_FIELD_SOURCES = "field_sources"
CONFIG_LOAD_SECTION_AVAILABILITY = "section_availability"
_KIND_FIELD = "kind"
_SCHEMA_VERSION_FIELD = "schema_version"

_EXTRA_FORBIDDEN = "extra_forbidden"
_EXTRA_FORBIDDEN_MESSAGE = "Extra inputs are not permitted."
_SCALAR_INPUT_ADAPTER = TypeAdapter(SCALAR_INPUT)
_EVENT_DLQ_DESTINATION = "teleclaude:events:dlq"
_CONFIG_VALIDATION_ERROR = "Failed to validate config file {path}: {error}"
_CONFIG_READ_ERROR = "Failed to read config file {path}: {error}"
_KIND_MISMATCH_ERROR = "Machine configuration at {path} declares kind '{kind}', expected 'computer'"
_REMOTE_ENTRY_MAPPING_ERROR = "Invalid remote_computers entry '{name}': expected a mapping, got {actual}."
_SCALAR_INPUT_ERROR = "Expected a scalar configuration value."
EXPERIMENTS_FILE_NAME = "experiments.yml"
_UTF8_ENCODING = "utf-8"


class _MachineField(StrEnum):
    AGENTS = "agents"
    API = "api"
    API_VERSION = "api_version"
    BACKUP = "backup"
    CHIPTUNES = "chiptunes"
    COMPUTER = "computer"
    CREDS = "creds"
    DEFAULT = "default"
    DEFAULT_AGENT = "default_agent"
    DEFAULT_WORKING_DIR = "default_working_dir"
    DEPLOYMENT = "deployment"
    DISCORD = "discord"
    EMAIL = "email"
    EVENT_RELIABILITY = "event_reliability"
    EXPERIMENTS = "experiments"
    HOST = "host"
    LOAD_ID = "load_id"
    MESSAGE = "message"
    NAME = "name"
    POLLING = "polling"
    PARAMS = "params"
    PROCESS_JANITOR = "process_janitor"
    REMOTE_COMPUTERS = "remote_computers"
    REDIS = "redis"
    SUMMARIZER = "summarizer"
    TERMINAL = "terminal"
    TMUX_BINARY = "tmux_binary"
    TTS = "tts"
    STT = "stt"
    SERVICES = "services"
    USER = "user"
    VOLUME = "volume"
    WHATSAPP = "whatsapp"


_DERIVED_ROOT_FIELDS = frozenset(
    {
        _MachineField.POLLING,
        _MachineField.EVENT_RELIABILITY,
        _MachineField.DEFAULT_AGENT,
        _MachineField.LOAD_ID,
    }
)
_KNOWN_AGENT_IDS = frozenset(agent.value for agent in AgentName)


def detect_lan_ip() -> str:
    """Return this host's primary LAN IPv4, falling back to loopback."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


# guard: loose-dict-func - Recursive merge of raw YAML configuration trees.
def deep_merge(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    """Deep merge override dict into base dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(cast(dict[str, object], result[key]), value)
        else:
            result[key] = value
    return result


# guard: loose-dict-func - Recursive comparison of raw YAML configuration trees.
def prune_defaults(data: dict[str, object], defaults: dict[str, object]) -> dict[str, object]:
    """Return ``data`` with every leaf equal to its default removed."""
    pruned: dict[str, object] = {}
    for key, value in data.items():
        default = defaults.get(key)
        if isinstance(value, dict) and isinstance(default, dict):
            nested = prune_defaults(value, default)
            if nested:
                pruned[key] = nested
        elif value != default:
            pruned[key] = value
    return pruned


def _clean_computer_input(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    model_type = ComputerConfig
    cleaned: dict[object, object] = {}
    for key, item in value.items():
        if key == _MachineField.TMUX_BINARY:
            cleaned[key] = item
            continue
        if isinstance(key, str) and key in model_type.model_fields:
            result = drop_unresolved_machine(item, model_type.model_fields[key].annotation)
            if result is not DROP:
                cleaned[key] = result
        else:
            cleaned[key] = item
    return cleaned


def _clean_agent_input(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    allowed = _agent_editable_keys()
    cleaned: dict[object, object] = {}
    for agent_key, agent_value in value.items():
        agent_name = str(agent_key)
        if agent_name == _MachineField.DEFAULT:
            if not is_unresolved(agent_value):
                cleaned[agent_key] = agent_value
            continue
        if agent_name in _KNOWN_AGENT_IDS and is_unresolved(agent_value):
            continue
        if agent_name not in _KNOWN_AGENT_IDS or not isinstance(agent_value, Mapping):
            cleaned[agent_key] = agent_value
            continue
        settings: dict[object, object] = {}
        for key, item in agent_value.items():
            key_text = str(key)
            if key_text in allowed:
                field_info = AgentConfig.model_fields[key_text]
                result = drop_unresolved_machine(item, field_info.annotation)
                if result is not DROP:
                    settings[key] = result
            else:
                settings[key] = item
        cleaned[agent_key] = settings
    return cleaned


def _clean_remote_input(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    field_model = RemoteComputerConfig
    cleaned: dict[object, object] = {}
    for name, properties in value.items():
        if is_unresolved(properties):
            continue
        if not isinstance(properties, Mapping):
            cleaned[name] = properties
            continue
        entry: dict[object, object] = {}
        for key, item in properties.items():
            if key == _MachineField.NAME:
                entry[key] = item
            elif isinstance(key, str) and key in field_model.model_fields:
                result = drop_unresolved_machine(item, field_model.model_fields[key].annotation)
                if result is not DROP:
                    entry[key] = result
            else:
                entry[key] = item
        cleaned[name] = entry
    return cleaned


def _keep_unless_unresolved(value: object) -> object:
    return DROP if is_unresolved(value) else value


def _keep(value: object) -> object:
    return value


def _clean_tts_services(value: object) -> object:
    """Resolve each service's model while removing unresolved parameter leaves."""
    if is_unresolved(value):
        return DROP
    if not isinstance(value, Mapping):
        return value
    return {
        name: drop_unresolved_machine_fields(settings, tts_service_model(str(name)))
        for name, settings in value.items()
        if not is_unresolved(settings)
    }


# Fields whose shape the model annotations cannot describe, cleaned by their own rules.
_MACHINE_OVERRIDES: FieldOverrides = {
    **{(TeleclaudeConfig, field): _keep for field in _DERIVED_ROOT_FIELDS},
    (TeleclaudeConfig, _MachineField.AGENTS): _clean_agent_input,
    (TeleclaudeConfig, _MachineField.REMOTE_COMPUTERS): _clean_remote_input,
    (TeleclaudeConfig, _MachineField.COMPUTER): _clean_computer_input,
    (TTSEventConfig, _MachineField.MESSAGE): _keep_unless_unresolved,
    (VoxCPMVoiceConfig, _MachineField.PARAMS): drop_unresolved_untyped,
    (TTSConfig, _MachineField.SERVICES): _clean_tts_services,
}


def drop_unresolved_machine(value: object, annotation: object) -> object:
    """Remove unresolved leaves from a machine-document value destined for ``annotation``."""
    return drop_unresolved(value, annotation, _MACHINE_OVERRIDES)


def drop_unresolved_machine_fields(value: object, model_type: type[ClosedModel]) -> object:
    """Remove unresolved leaves from a machine-document mapping destined for ``model_type``."""
    return drop_unresolved_fields(value, model_type, _MACHINE_OVERRIDES)


def _scalar_input_issue(value: object, path: tuple[str | int, ...], issues: list[ConfigValidationIssue]) -> None:
    try:
        _SCALAR_INPUT_ADAPTER.validate_python(value)
    except ValidationError as error:
        line = error.errors(include_url=False)[0]
        issues.append(ConfigValidationIssue(path, line["msg"], value, line["type"]))


def _derived_text(
    value: object,
    fallback: str,
    path: tuple[str | int, ...],
    issues: list[ConfigValidationIssue],
) -> str:
    if not value:
        return fallback
    try:
        _SCALAR_INPUT_ADAPTER.validate_python(value)
    except ValidationError as error:
        line = error.errors(include_url=False)[0]
        issues.append(ConfigValidationIssue(path, line["msg"], value, line["type"]))
        return fallback
    return str(value)


@dataclass(frozen=True)
class _MachineConfigDerivation:
    load_id: str
    login: str
    lan_ip: str
    working_dir: str
    tmux_binary: str
    whatsapp_api_version: str
    initial_issues: tuple[ConfigValidationIssue, ...] = ()

    def prepare(self, data: object) -> tuple[object, list[ConfigValidationIssue]]:
        if not isinstance(data, Mapping):
            return data, list(self.initial_issues)
        prepared = dict(data)
        issues = list(self.initial_issues)
        for field in _DERIVED_ROOT_FIELDS:
            if field in prepared:
                issues.append(
                    ConfigValidationIssue(
                        (field.value,), _EXTRA_FORBIDDEN_MESSAGE, prepared.pop(field), _EXTRA_FORBIDDEN
                    )
                )
        computer = prepared.get(_MachineField.COMPUTER)
        if isinstance(computer, Mapping):
            computer_data = dict(computer)
            if _MachineField.TMUX_BINARY in computer_data:
                issues.append(
                    ConfigValidationIssue(
                        (_MachineField.COMPUTER.value, _MachineField.TMUX_BINARY.value),
                        _EXTRA_FORBIDDEN_MESSAGE,
                        computer_data.pop(_MachineField.TMUX_BINARY),
                        _EXTRA_FORBIDDEN,
                    )
                )
            for field, provider in (
                (_MachineField.USER, self.login),
                (_MachineField.HOST, self.lan_ip),
                (_MachineField.DEFAULT_WORKING_DIR, self.working_dir),
            ):
                computer_data[field] = _derived_text(
                    computer_data.get(field),
                    provider,
                    (_MachineField.COMPUTER.value, field.value),
                    issues,
                )
            computer_data[_MachineField.TMUX_BINARY] = self.tmux_binary
            prepared[_MachineField.COMPUTER] = computer_data

        whatsapp = prepared.get(_MachineField.WHATSAPP)
        if whatsapp is None:
            prepared[_MachineField.WHATSAPP] = {_MachineField.API_VERSION: self.whatsapp_api_version}
        elif isinstance(whatsapp, Mapping):
            whatsapp_data = dict(whatsapp)
            if _MachineField.API_VERSION in whatsapp_data:
                _scalar_input_issue(
                    whatsapp_data[_MachineField.API_VERSION],
                    (_MachineField.WHATSAPP.value, _MachineField.API_VERSION.value),
                    issues,
                )
            whatsapp_data[_MachineField.API_VERSION] = self.whatsapp_api_version
            prepared[_MachineField.WHATSAPP] = whatsapp_data

        if _MachineField.CREDS not in prepared or prepared[_MachineField.CREDS] is None:
            prepared[_MachineField.CREDS] = {}
        if _MachineField.TERMINAL not in prepared:
            prepared[_MachineField.TERMINAL] = {}
        if prepared.get(_MachineField.CHIPTUNES) is None:
            prepared[_MachineField.CHIPTUNES] = {_MachineField.VOLUME: 0.5}
        if prepared.get(_MachineField.SUMMARIZER) is not None and not prepared[_MachineField.SUMMARIZER]:
            prepared[_MachineField.SUMMARIZER] = None
        if prepared.get(_MachineField.EXPERIMENTS) is None:
            prepared[_MachineField.EXPERIMENTS] = []
        prepared[_MachineField.REMOTE_COMPUTERS] = self._remote_computers(
            prepared.get(_MachineField.REMOTE_COMPUTERS),
            issues,
        )
        agent_result = build_agents_registry(prepared.get(_MachineField.AGENTS), load_id=self.load_id)
        prepared[_MachineField.AGENTS] = agent_result.registry
        prepared[_MachineField.DEFAULT_AGENT] = agent_result.default_agent
        issues.extend(agent_result.issues)
        prepared[_MachineField.POLLING] = PollingConfig(
            directory_check_interval=DIRECTORY_CHECK_INTERVAL,
            output_cadence_s=OUTPUT_CADENCE_S,
        )
        prepared[_MachineField.EVENT_RELIABILITY] = EventReliabilityConfig(
            idle_threshold_ms=30_000,
            max_attempts=3,
            sweep_interval_ms=5_000,
            dlq_destination=_EVENT_DLQ_DESTINATION,
        )
        prepared[_MachineField.LOAD_ID] = self.load_id
        return prepared, issues

    def _remote_computers(
        self,
        value: object,
        issues: list[ConfigValidationIssue],
    ) -> list[RemoteComputerConfig] | object:
        if value is None or (isinstance(value, Mapping) and not value):
            return []
        if not isinstance(value, Mapping):
            return value
        result: list[RemoteComputerConfig] = []
        allowed = set(RemoteComputerConfig.model_fields)
        allowed.discard(_MachineField.NAME.value)
        for name, properties in value.items():
            if not isinstance(properties, Mapping):
                message = _REMOTE_ENTRY_MAPPING_ERROR.format(name=name, actual=type(properties).__name__)
                issues.append(
                    ConfigValidationIssue((_MachineField.REMOTE_COMPUTERS.value, str(name)), message, properties)
                )
                continue
            entry = dict(properties)
            if _MachineField.NAME in entry:
                issues.append(
                    ConfigValidationIssue(
                        (_MachineField.REMOTE_COMPUTERS.value, str(name), _MachineField.NAME.value),
                        _EXTRA_FORBIDDEN_MESSAGE,
                        entry.pop(_MachineField.NAME),
                        _EXTRA_FORBIDDEN,
                    )
                )
            model_input = {_MachineField.NAME: str(name), **entry}
            try:
                result.append(RemoteComputerConfig.model_validate(model_input))
            except ValidationError as error:
                for line in error.errors(include_url=False):
                    field_path = tuple(str(part) for part in line["loc"])
                    if field_path and field_path[-1] not in allowed:
                        issues.append(
                            ConfigValidationIssue(
                                (_MachineField.REMOTE_COMPUTERS.value, str(name), field_path[-1]),
                                _EXTRA_FORBIDDEN_MESSAGE,
                                line["input"],
                                _EXTRA_FORBIDDEN,
                            )
                        )
                    else:
                        issues.append(
                            ConfigValidationIssue(
                                (_MachineField.REMOTE_COMPUTERS.value, str(name), *line["loc"]),
                                line["msg"],
                                line["input"],
                                line["type"],
                            )
                        )
        return result


class _ExperimentsFileInput(ClosedModel):
    experiments: list[ExperimentConfig] = Field(default_factory=list)


def build_config_from_raw(
    raw_user_config: object,
    sibling_dir: Path,
    *,
    config_source: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> TeleclaudeConfig:
    """Build the typed config from raw YAML and adjacent machine-config files."""
    source = config_source or sibling_dir / ConfigFileName.MACHINE
    field_sources_input = raw_user_config
    if isinstance(raw_user_config, Mapping):
        raw_document = dict(raw_user_config)
        declared_kind = raw_document.get(_KIND_FIELD)
        if declared_kind is not None and declared_kind != "computer":
            raise ConfigLoadError(_KIND_MISMATCH_ERROR.format(path=source, kind=declared_kind), document=source)
        initial_issues: list[ConfigValidationIssue] = []
        schema_version = raw_document.get(_SCHEMA_VERSION_FIELD)
        if isinstance(schema_version, (Mapping, list)):
            initial_issues.append(
                ConfigValidationIssue(
                    (_SCHEMA_VERSION_FIELD,),
                    _SCALAR_INPUT_ERROR,
                    schema_version,
                )
            )
        raw_document.pop(_KIND_FIELD, None)
        raw_document.pop(_SCHEMA_VERSION_FIELD, None)
        field_sources_input = raw_document
        user_config: object = expand_environment_references(
            raw_document,
            machine_runtime_environment() if environment is None else environment,
            preserve_unresolved=True,
        )
        if isinstance(user_config, Mapping):
            user_config = drop_unresolved_machine_fields(user_config, TeleclaudeConfig)
    else:
        initial_issues = []
        user_config = raw_user_config

    load_id = str(uuid4())
    field_sources = credential_field_sources(field_sources_input)
    logger.debug(
        CONFIG_LOAD_EVENT,
        **{CONFIG_LOAD_ID: load_id, CONFIG_LOAD_OUTCOME: CONFIG_LOAD_ACCEPTED, CONFIG_LOAD_STAGE: CONFIG_LOAD_BUILD},
    )

    experiments_path = sibling_dir / EXPERIMENTS_FILE_NAME
    try:
        if experiments_path.exists():
            with open(experiments_path, encoding=_UTF8_ENCODING) as stream:
                raw_experiments = yaml.safe_load(stream) or {}
            expanded_experiments = expand_environment_references(
                raw_experiments,
                os.environ,
                preserve_unresolved=True,
            )
            if isinstance(expanded_experiments, Mapping):
                expanded_experiments = drop_unresolved_machine_fields(expanded_experiments, _ExperimentsFileInput)
            try:
                experiments_input = _ExperimentsFileInput.model_validate(expanded_experiments)
            except ValidationError as error:
                raise ConfigLoadError(
                    _CONFIG_VALIDATION_ERROR.format(path=experiments_path, error=error), document=experiments_path
                ) from error
            if _MachineField.EXPERIMENTS in experiments_input.model_fields_set and isinstance(user_config, Mapping):
                merged_experiments = dict(user_config)
                current = merged_experiments.get(_MachineField.EXPERIMENTS, [])
                if isinstance(current, list):
                    merged_experiments[_MachineField.EXPERIMENTS] = [*current, *experiments_input.experiments]
                else:
                    merged_experiments[_MachineField.EXPERIMENTS] = experiments_input.experiments
                user_config = merged_experiments

        merged = (
            deep_merge(
                DEFAULT_CONFIG,
                cast(dict[str, object], user_config),  # guard: loose-dict - Expanded raw YAML configuration tree.
            )
            if isinstance(user_config, Mapping)
            else user_config
        )
        computer_values = merged.get(_MachineField.COMPUTER) if isinstance(merged, Mapping) else None
        computer_user = computer_values.get(_MachineField.USER) if isinstance(computer_values, Mapping) else None
        computer_host = computer_values.get(_MachineField.HOST) if isinstance(computer_values, Mapping) else None
        derivation = _MachineConfigDerivation(
            load_id=load_id,
            login=getpass.getuser() if not computer_user else str(computer_user),
            lan_ip=detect_lan_ip() if not computer_host else str(computer_host),
            working_dir=WORKING_DIR,
            tmux_binary=resolve_tmux_binary(),
            whatsapp_api_version=WHATSAPP_API_VERSION,
            initial_issues=tuple(initial_issues),
        )
        resolved = TeleclaudeConfig.model_validate(merged, context=derivation)
    except Exception as error:
        logger.info(
            CONFIG_LOAD_EVENT,
            **{
                CONFIG_LOAD_ID: load_id,
                CONFIG_LOAD_OUTCOME: CONFIG_LOAD_REJECTED,
                CONFIG_LOAD_STAGE: CONFIG_LOAD_BUILD,
            },
        )
        if isinstance(error, ValidationError):
            raise ConfigLoadError(_CONFIG_VALIDATION_ERROR.format(path=source, error=error), document=source) from error
        if isinstance(error, (OSError, yaml.YAMLError)):
            raise ConfigLoadError(
                _CONFIG_READ_ERROR.format(path=experiments_path, error=error), document=experiments_path
            ) from error
        raise

    logger.info(
        CONFIG_LOAD_EVENT,
        **{
            CONFIG_LOAD_ID: load_id,
            CONFIG_LOAD_OUTCOME: CONFIG_LOAD_RESOLVED,
            CONFIG_LOAD_FIELD_SOURCES: field_sources,
            CONFIG_LOAD_SECTION_AVAILABILITY: credential_section_availability(resolved),
        },
    )
    return resolved
