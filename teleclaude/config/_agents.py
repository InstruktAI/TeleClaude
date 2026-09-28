"""Agents-block parsing, validation, and load-time observation.

Owns the ``config.yml:agents`` section end to end: reading operator
overrides, validating them against the canonical registry's protocol data,
constructing the typed ``AgentConfig`` registry, and emitting the closed
``agent_runtime.agent_config_validation`` observation record family this
delivery's observation map requires.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NamedTuple, cast

from pydantic import Field, ValidationError, create_model

from teleclaude.agent_registry import AgentName, AgentProtocolDict, registry_digest
from teleclaude.closed_model import ClosedModel
from teleclaude.config._coerce import FLAG, as_bool
from teleclaude.config._models import AgentConfig, ConfigValidationIssue, ModelChainEntry
from teleclaude.config.observation import (
    AgentConfigRefusalReason,
    AgentConfigValidationOutcome,
    AgentConfigValidationStage,
    log_agent_config_validation,
)
from teleclaude.config.tiers import Tier, effective_tier, in_public_sample, pydantic_field_tier
from teleclaude.constants import AGENT_PROTOCOL, GIT_AUTHOR_IDENTITIES
from teleclaude.runtime.binaries import resolve_agent_binary

_DEFAULT_KEY = "default"
_ENABLED_KEY = "enabled"
_AGENTS_KEY = "agents"
_PROFILES_KEY = "profiles"
_MODEL_CHAINS_KEY = "model_chains"
_AGENT_SETTINGS_MODEL_NAME = "AgentSettingsInput"
_EMPTY_TEXT = ""
_AGENTS_REQUIRED_ERROR = (
    "Missing required config key `config.yml:agents`. Add `agents:` with at least one configured agent entry."
)
_AGENTS_MAPPING_ERROR = "Invalid config key `config.yml:agents`: expected a mapping of agent names to settings."
_DEFAULT_REQUIRED_ERROR = "Missing required config key `config.yml:agents.default`. Set it to one of: {allowed}."
_DEFAULT_TYPE_ERROR = "Invalid config key `config.yml:agents.default`: expected a string ({allowed})."
_DEFAULT_UNKNOWN_ERROR = (
    "Invalid config key `config.yml:agents.default`: unknown agent '{agent}'. Allowed values: {allowed}."
)
_UNKNOWN_AGENT_KEY_ERROR = "Unknown key(s) under `config.yml:agents`: {key}. Allowed keys: {allowed}."
_AGENT_MAPPING_ERROR = "Invalid config key `config.yml:agents.{agent}`: expected a mapping of agent settings."
_UNKNOWN_AGENT_SETTING_ERROR = "Unknown key(s) under `config.yml:agents.{agent}`: {key}. Allowed keys: {allowed}."
_ALL_AGENTS_DISABLED_ERROR = "Invalid config at `config.yml:agents`: all known agents are disabled. Set `config.yml:agents.<agent>.enabled: true` for at least one configured agent."
_DEFAULT_DISABLED_ERROR = "Invalid config key `config.yml:agents.default`: '{agent}' is disabled. Enable `config.yml:agents.{agent}.enabled: true` or choose an enabled agent."
_VALUE_ERROR_CODE = "value_error"
_EXTRA_FORBIDDEN_CODE = "extra_forbidden"
_PROFILE_FIELD = "profiles"


class AgentEntryResult(NamedTuple):
    config: AgentConfig
    enabled: bool | None
    issues: list[ConfigValidationIssue]


def _read_enabled(value: object) -> bool | None:
    try:
        return as_bool(value)
    except ValueError:
        return None


def _resolve_default_agent(
    agents_raw: dict[object, object], section_valid: bool
) -> tuple[AgentName | None, list[ConfigValidationIssue], AgentConfigRefusalReason | None]:
    issues: list[ConfigValidationIssue] = []
    refusal_reason: AgentConfigRefusalReason | None = None
    default_agent_raw = agents_raw.pop(_DEFAULT_KEY, None)
    if not section_valid:
        return None, issues, refusal_reason
    if default_agent_raw is None:
        issues.append(
            ConfigValidationIssue(
                (_AGENTS_KEY, _DEFAULT_KEY),
                _DEFAULT_REQUIRED_ERROR.format(allowed=", ".join(AgentName.choices())),
                default_agent_raw,
            )
        )
        return None, issues, AgentConfigRefusalReason.MISSING_DEFAULT
    if not isinstance(default_agent_raw, str):
        issues.append(
            ConfigValidationIssue(
                (_AGENTS_KEY, _DEFAULT_KEY),
                _DEFAULT_TYPE_ERROR.format(allowed=", ".join(AgentName.choices())),
                default_agent_raw,
            )
        )
        return None, issues, AgentConfigRefusalReason.UNKNOWN_DEFAULT
    try:
        return AgentName.from_str(default_agent_raw), issues, refusal_reason
    except ValueError:
        issues.append(
            ConfigValidationIssue(
                (_AGENTS_KEY, _DEFAULT_KEY),
                _DEFAULT_UNKNOWN_ERROR.format(
                    agent=default_agent_raw,
                    allowed=", ".join(AgentName.choices()),
                ),
                default_agent_raw,
            )
        )
        return None, issues, AgentConfigRefusalReason.UNKNOWN_DEFAULT


def _validate_agent_settings(
    name: str, user_agent_config: dict[object, object]
) -> tuple[bool | None, list[ConfigValidationIssue]]:
    issues: list[ConfigValidationIssue] = []
    try:
        settings = _AGENT_SETTINGS_INPUT.model_validate(user_agent_config)
    except ValidationError as error:
        for line in sorted(error.errors(include_url=False), key=lambda item: tuple(str(part) for part in item["loc"])):
            if line["type"] == _EXTRA_FORBIDDEN_CODE:
                key_text = str(line["loc"][-1])
                message = _UNKNOWN_AGENT_SETTING_ERROR.format(
                    agent=name,
                    key=key_text,
                    allowed=", ".join(sorted(_agent_editable_keys())),
                )
                loc: tuple[str | int, ...] = (_AGENTS_KEY, name, key_text)
            else:
                message = line["msg"]
                loc = (_AGENTS_KEY, name, *line["loc"])
            issues.append(ConfigValidationIssue(loc, message, line["input"]))
        return _read_enabled(user_agent_config.get(_ENABLED_KEY, True)), issues
    return cast(bool, getattr(settings, _ENABLED_KEY)), issues


def _build_agent_entry(agent_name: AgentName, value: object) -> AgentEntryResult:
    name = agent_name.value
    protocol = AGENT_PROTOCOL[name]
    issues: list[ConfigValidationIssue] = []
    valid_mapping = value is None or isinstance(value, dict)
    if not valid_mapping:
        issues.append(
            ConfigValidationIssue(
                (_AGENTS_KEY, name),
                _AGENT_MAPPING_ERROR.format(agent=name),
                value,
            )
        )
    user_agent_config = dict(value) if isinstance(value, dict) else {}
    enabled, settings_issues = _validate_agent_settings(name, user_agent_config)
    if not valid_mapping:
        enabled = None
    issues.extend(settings_issues)
    try:
        profiles = _parse_profiles(name, user_agent_config.get(_PROFILE_FIELD), protocol)
    except ValueError as error:
        profiles = dict(protocol["profiles"])
        issues.append(
            ConfigValidationIssue(
                (_AGENTS_KEY, name, _PROFILE_FIELD),
                str(error),
                user_agent_config.get(_PROFILE_FIELD),
            )
        )
    try:
        model_chains = _parse_model_chains(name, user_agent_config.get(_MODEL_CHAINS_KEY), protocol)
    except ValueError as error:
        model_chains = {}
        issues.append(
            ConfigValidationIssue(
                (_AGENTS_KEY, name, _MODEL_CHAINS_KEY),
                str(error),
                user_agent_config.get(_MODEL_CHAINS_KEY),
            )
        )
    mode_chains = {
        mode: [
            ModelChainEntry(
                model=str(entry["model"]),
                flags=str(entry.get("flags", _EMPTY_TEXT)),
                patch=str(entry.get("patch", _EMPTY_TEXT)),
            )
            for entry in entries
        ]
        for mode, entries in protocol["mode_chains"].items()
    }
    config = AgentConfig(
        binary=resolve_agent_binary(name),
        profiles=profiles,
        session_dir=str(protocol["session_dir"]),
        log_pattern=str(protocol["log_pattern"]),
        mode_chains=mode_chains,
        model_chains=model_chains,
        exec_subcommand=str(protocol["exec_subcommand"]),
        interactive_flag=str(protocol["interactive_flag"]),
        non_interactive_flag=str(protocol["non_interactive_flag"]),
        resume_template=str(protocol["resume_template"]),
        continue_template=str(protocol.get("continue_template", _EMPTY_TEXT)),
        prompt_at_launch=bool(protocol.get("prompt_at_launch", False)),
        model_via_launch_patch=bool(protocol.get("model_via_launch_patch", False)),
        restricted_sandbox_mode=str(protocol.get("restricted_sandbox_mode", _EMPTY_TEXT)),
        enabled=enabled if enabled is not None else True,
        git_identity=GIT_AUTHOR_IDENTITIES.get(name),
    )
    return AgentEntryResult(config, enabled, issues)


class AgentRegistryResult(NamedTuple):
    registry: dict[AgentName, AgentConfig]
    default_agent: AgentName
    issues: list[ConfigValidationIssue]
    refusal_reason: AgentConfigRefusalReason | None


def _build_agent_settings_model() -> type[ClosedModel]:
    fields: dict[str, Any] = {}  # guard: loose-dict - create_model accepts dynamic field definitions from AgentConfig.
    for name, field_info in AgentConfig.model_fields.items():
        if not in_public_sample(effective_tier(pydantic_field_tier(field_info), Tier.INTERNAL)):
            continue
        annotation = FLAG if name == _ENABLED_KEY else object
        default = field_info.default if name == _ENABLED_KEY else None
        fields[name] = (annotation, Field(default=default, json_schema_extra=field_info.json_schema_extra))
    dynamic_model: type[ClosedModel] = create_model(_AGENT_SETTINGS_MODEL_NAME, __base__=ClosedModel, **fields)
    return dynamic_model


_AGENT_SETTINGS_INPUT = _build_agent_settings_model()


def _agent_editable_keys() -> frozenset[str]:
    """Return the declared operator keys from the tier-derived closed settings model."""
    return frozenset(_AGENT_SETTINGS_INPUT.model_fields)


def _parse_profiles(agent: str, raw: object, protocol: AgentProtocolDict) -> dict[str, str]:
    """Overlay operator-declared launch profiles onto the protocol defaults.

    A declared profile replaces that profile's flags outright; profiles the
    operator does not name keep the protocol value.
    """
    merged = dict(protocol["profiles"])
    if raw is None:
        return merged
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid config key `config.yml:agents.{agent}.profiles`: expected a mapping.")
    for profile_name, flags in raw.items():
        name = str(profile_name)
        if name not in merged:
            allowed = ", ".join(sorted(merged))
            raise ValueError(
                f"Unknown profile `config.yml:agents.{agent}.profiles.{name}`. Allowed profiles: {allowed}."
            )
        if not isinstance(flags, str):
            raise ValueError(f"Invalid config key `config.yml:agents.{agent}.profiles.{name}`: expected a string.")
        merged[name] = flags
    return merged


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
            unknown_keys = sorted(set(entry_raw) - {"model", "flags", "patch"})
            if unknown_keys:
                raise ValueError(f"Invalid config key `{entry_path}`: unknown key(s): {', '.join(unknown_keys)}.")
            model = entry_raw.get("model")
            flags = entry_raw.get("flags")
            patch = entry_raw.get("patch")
            if not isinstance(model, str) or not model.strip():
                raise ValueError(f"Invalid config key `{entry_path}.model`: expected a non-empty model identifier.")
            if not isinstance(flags, str) or not flags.strip():
                raise ValueError(f"Invalid config key `{entry_path}.flags`: expected a non-empty launch-flag string.")
            if patch is not None and (not isinstance(patch, str) or not patch.strip()):
                raise ValueError(f"Invalid config key `{entry_path}.patch`: expected a JSON parameter-map string.")
            entries.append(ModelChainEntry(model=model, flags=flags, patch=patch or ""))
        chains[str(mode)] = entries
    return chains


def build_agents_registry(raw_agents: object, *, load_id: str) -> AgentRegistryResult:
    """Validate agents independently and return a registry plus every rejection."""
    digest = registry_digest()
    log_agent_config_validation(load_id=load_id, digest=digest, stage=AgentConfigValidationStage.STARTED)
    issues: list[ConfigValidationIssue] = []
    refusal_reason: AgentConfigRefusalReason | None = None
    section_valid = isinstance(raw_agents, Mapping)
    if raw_agents is None:
        issues.append(ConfigValidationIssue((_AGENTS_KEY,), _AGENTS_REQUIRED_ERROR, raw_agents))
        refusal_reason = AgentConfigRefusalReason.MISSING_DEFAULT
        agents_raw: dict[object, object] = {}
    elif not isinstance(raw_agents, Mapping):
        issues.append(ConfigValidationIssue((_AGENTS_KEY,), _AGENTS_MAPPING_ERROR, raw_agents))
        refusal_reason = AgentConfigRefusalReason.UNKNOWN_AGENT_KEY
        agents_raw = {}
    else:
        agents_raw = dict(raw_agents)

    default_agent, default_issues, default_reason = _resolve_default_agent(agents_raw, section_valid)
    issues.extend(default_issues)
    refusal_reason = refusal_reason or default_reason
    known_agent_ids = frozenset(agent.value for agent in AgentName)
    unknown_agents = sorted((str(key), value) for key, value in agents_raw.items() if str(key) not in known_agent_ids)
    for key_text, value in unknown_agents:
        issues.append(
            ConfigValidationIssue(
                (_AGENTS_KEY, key_text),
                _UNKNOWN_AGENT_KEY_ERROR.format(key=key_text, allowed=", ".join(AgentName.choices())),
                value,
            )
        )
    if unknown_agents:
        refusal_reason = refusal_reason or AgentConfigRefusalReason.UNKNOWN_AGENT_KEY

    entries = {agent: _build_agent_entry(agent, agents_raw.get(agent.value)) for agent in AgentName}
    for entry in entries.values():
        issues.extend(entry.issues)
        if entry.issues:
            refusal_reason = refusal_reason or AgentConfigRefusalReason.UNKNOWN_AGENT_KEY
    registry = {agent: entry.config for agent, entry in entries.items()}
    enabled_values = {agent: entry.enabled for agent, entry in entries.items()}
    if section_valid and all(value is not None for value in enabled_values.values()):
        enabled_count = sum(value is True for value in enabled_values.values())
        if enabled_count == 0:
            issues.append(ConfigValidationIssue((_AGENTS_KEY,), _ALL_AGENTS_DISABLED_ERROR, raw_agents))
            refusal_reason = refusal_reason or AgentConfigRefusalReason.ALL_DISABLED
        if default_agent is not None and enabled_values[default_agent] is False:
            issues.append(
                ConfigValidationIssue(
                    (_AGENTS_KEY, _DEFAULT_KEY),
                    _DEFAULT_DISABLED_ERROR.format(agent=default_agent.value),
                    default_agent.value,
                )
            )
            refusal_reason = refusal_reason or AgentConfigRefusalReason.DEFAULT_DISABLED
    else:
        enabled_count = sum(entry.config.enabled for entry in entries.values())

    if default_agent is None:
        default_agent = AgentName.CLAUDE
    if issues:
        log_agent_config_validation(
            load_id=load_id,
            digest=digest,
            outcome=AgentConfigValidationOutcome.REFUSED,
            reason=refusal_reason,
        )
    else:
        log_agent_config_validation(
            load_id=load_id,
            digest=digest,
            outcome=AgentConfigValidationOutcome.ACCEPTED,
            default_agent=default_agent.value,
            enabled_count=enabled_count,
            registry_count=len(registry),
        )
    return AgentRegistryResult(registry, default_agent, issues, refusal_reason)
