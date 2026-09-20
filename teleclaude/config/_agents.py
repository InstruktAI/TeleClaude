"""Agents-block parsing, validation, and load-time observation.

Owns the ``config.yml:agents`` section end to end: reading operator
overrides, validating them against the canonical registry's protocol data,
constructing the typed ``AgentConfig`` registry, and emitting the closed
``agent_runtime.agent_config_validation`` observation record family this
delivery's observation map requires.
"""

from __future__ import annotations

from dataclasses import fields

from teleclaude.agent_registry import AgentName, AgentProtocolDict, registry_digest
from teleclaude.config._coerce import as_bool
from teleclaude.config._models import AgentConfig, ModelChainEntry
from teleclaude.config.observation import (
    AgentConfigRefusalReason,
    AgentConfigValidationOutcome,
    AgentConfigValidationStage,
    log_agent_config_validation,
)
from teleclaude.config.tiers import Tier, dataclass_field_tier, effective_tier, in_public_sample
from teleclaude.constants import AGENT_PROTOCOL, GIT_AUTHOR_IDENTITIES
from teleclaude.runtime.binaries import resolve_agent_binary


def require_agents_section(raw_config: dict[str, object]) -> dict[str, object]:  # guard: loose-dict
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
    known_agents: tuple[AgentName, ...],
    *,
    load_id: str,
    digest: str,
) -> None:
    """Reject unknown agent keys under config.yml:agents."""
    known_agent_ids = frozenset(agent.value for agent in known_agents)
    unknown = sorted(str(name) for name in agents_raw.keys() if str(name) not in known_agent_ids)
    if unknown:
        log_agent_config_validation(
            load_id=load_id,
            digest=digest,
            outcome=AgentConfigValidationOutcome.REFUSED,
            reason=AgentConfigRefusalReason.UNKNOWN_AGENT_KEY,
        )
        raise ValueError(
            f"Unknown key(s) under `config.yml:agents`: {', '.join(unknown)}. Allowed keys: {', '.join(AgentName.choices())}."
        )


def _agent_editable_keys() -> frozenset[str]:
    """Return the agent settings an operator may declare, read from the field tiers.

    The tier markers on ``AgentConfig`` are the single authority: a leaf marked
    ``public`` or ``tui`` is an operator surface, everything else is runtime
    policy. Adding a marker is therefore the whole change needed to expose a new
    setting — this loader never carries its own list.
    """
    return frozenset(
        f.name for f in fields(AgentConfig) if in_public_sample(effective_tier(dataclass_field_tier(f), Tier.INTERNAL))
    )


def _validate_agent_setting_keys(
    agent: str,
    user_agent_config: dict[str, object],  # guard: loose-dict - YAML deserialization input
) -> None:
    """Reject agent settings the loader cannot honor rather than discarding them."""
    editable = _agent_editable_keys()
    unknown = sorted(str(key) for key in user_agent_config if str(key) not in editable)
    if unknown:
        raise ValueError(
            f"Unknown key(s) under `config.yml:agents.{agent}`: {', '.join(unknown)}. "
            f"Allowed keys: {', '.join(sorted(editable))}."
        )


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


def build_agents_registry(
    raw: dict[str, object],  # guard: loose-dict - YAML deserialization input
    *,
    load_id: str,
) -> tuple[dict[AgentName, AgentConfig], AgentName]:
    """Validate `config.yml:agents` and construct the typed per-agent registry.

    Emits the closed agent-config-validation observation record family as a
    side effect (one ``started`` record, then exactly one terminal
    ``accepted`` or ``refused`` record per call) and raises ``ValueError``
    with the operator-facing message on any refusal. Returns the constructed
    registry and the validated default agent key.
    """
    agents_raw = dict(require_agents_section(raw))

    known_agents = tuple(AgentName)
    digest = registry_digest()
    log_agent_config_validation(load_id=load_id, digest=digest, stage=AgentConfigValidationStage.STARTED)

    default_agent_raw = agents_raw.pop("default", None)
    if default_agent_raw is None:
        log_agent_config_validation(
            load_id=load_id,
            digest=digest,
            outcome=AgentConfigValidationOutcome.REFUSED,
            reason=AgentConfigRefusalReason.MISSING_DEFAULT,
        )
        raise ValueError(
            f"Missing required config key `config.yml:agents.default`. Set it to one of: {', '.join(AgentName.choices())}."
        )
    if not isinstance(default_agent_raw, str):
        raise ValueError(
            f"Invalid config key `config.yml:agents.default`: expected a string ({', '.join(AgentName.choices())})."
        )
    try:
        default_agent = AgentName.from_str(default_agent_raw)
    except ValueError as exc:
        log_agent_config_validation(
            load_id=load_id,
            digest=digest,
            outcome=AgentConfigValidationOutcome.REFUSED,
            reason=AgentConfigRefusalReason.UNKNOWN_DEFAULT,
        )
        raise ValueError(
            f"Invalid config key `config.yml:agents.default`: unknown agent '{default_agent_raw}'. "
            f"Allowed values: {', '.join(AgentName.choices())}."
        ) from exc

    _validate_known_agent_keys(agents_raw, known_agents, load_id=load_id, digest=digest)

    agents_registry: dict[AgentName, AgentConfig] = {}
    for agent_name in AgentName:
        name = agent_name.value
        protocol = AGENT_PROTOCOL[name]
        # Get user overrides for this agent if any
        val = agents_raw.get(name)
        if val is not None and not isinstance(val, dict):
            raise ValueError(f"Invalid config key `config.yml:agents.{name}`: expected a mapping of agent settings.")
        user_agent_config = val if isinstance(val, dict) else {}
        _validate_agent_setting_keys(name, user_agent_config)
        model_chains = _parse_model_chains(name, user_agent_config.get("model_chains"), protocol)

        agents_registry[agent_name] = AgentConfig(
            binary=resolve_agent_binary(name),
            profiles=_parse_profiles(name, user_agent_config.get("profiles"), protocol),
            session_dir=str(protocol["session_dir"]),
            log_pattern=str(protocol["log_pattern"]),
            mode_chains={
                mode: [
                    ModelChainEntry(
                        model=str(entry["model"]),
                        flags=str(entry.get("flags", "")),
                        patch=str(entry.get("patch", "")),
                    )
                    for entry in entries
                ]
                for mode, entries in protocol["mode_chains"].items()
            },
            model_chains=model_chains,
            exec_subcommand=str(protocol["exec_subcommand"]),
            interactive_flag=str(protocol["interactive_flag"]),
            non_interactive_flag=str(protocol["non_interactive_flag"]),
            resume_template=str(protocol["resume_template"]),
            continue_template=str(protocol.get("continue_template", "")),  # Optional field
            prompt_at_launch=bool(protocol.get("prompt_at_launch", False)),
            model_via_launch_patch=bool(protocol.get("model_via_launch_patch", False)),
            restricted_sandbox_mode=str(protocol.get("restricted_sandbox_mode", "")),
            enabled=as_bool(user_agent_config.get("enabled", True)),
            git_identity=GIT_AUTHOR_IDENTITIES.get(name),
        )

    enabled_count = sum(1 for agent_cfg in agents_registry.values() if agent_cfg.enabled)
    if enabled_count == 0:
        log_agent_config_validation(
            load_id=load_id,
            digest=digest,
            outcome=AgentConfigValidationOutcome.REFUSED,
            reason=AgentConfigRefusalReason.ALL_DISABLED,
        )
        raise ValueError(
            "Invalid config at `config.yml:agents`: all known agents are disabled. "
            "Set `config.yml:agents.<agent>.enabled: true` for at least one configured agent."
        )
    if not agents_registry[default_agent].enabled:
        log_agent_config_validation(
            load_id=load_id,
            digest=digest,
            outcome=AgentConfigValidationOutcome.REFUSED,
            reason=AgentConfigRefusalReason.DEFAULT_DISABLED,
        )
        raise ValueError(
            f"Invalid config key `config.yml:agents.default`: '{default_agent}' is disabled. "
            f"Enable `config.yml:agents.{default_agent}.enabled: true` or choose an enabled agent."
        )
    log_agent_config_validation(
        load_id=load_id,
        digest=digest,
        outcome=AgentConfigValidationOutcome.ACCEPTED,
        default_agent=default_agent.value,
        enabled_count=enabled_count,
        registry_count=len(agents_registry),
    )
    return agents_registry, default_agent
