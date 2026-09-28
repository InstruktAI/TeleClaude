"""Schema-owned absent-only machine configuration generation."""

from __future__ import annotations

from collections.abc import MutableMapping
from copy import deepcopy
from pathlib import Path

import yaml

from teleclaude.agent_registry import AgentName
from teleclaude.config._defaults import DEFAULT_CONFIG
from teleclaude.config.schema import CURRENT_SCHEMA_VERSION
from teleclaude.config.surface import machine_config_surface
from teleclaude.config.tiers import in_public_sample
from teleclaude.file_transaction import file_transaction

_AGENTS_KEY = "agents"
_KIND_KEY = "kind"
_SCHEMA_VERSION_KEY = "schema_version"
_DEFAULT_AGENT_KEY = "default"
_ENABLED_KEY = "enabled"
_DEFAULT_AGENT_PATH = ("default_agent",)
_AGENTS_PATH = (_AGENTS_KEY,)


def ensure_machine_config(path: Path) -> str:
    """Create a schema-derived machine config only when the target is absent."""
    with file_transaction(path) as transaction:
        if path.exists():
            return "existing"
        document: dict[str, object] = {  # guard: loose-dict - YAML configuration tree
            _KIND_KEY: "computer",
            _SCHEMA_VERSION_KEY: CURRENT_SCHEMA_VERSION,
        }
        for descriptor in machine_config_surface():
            if descriptor.path == _DEFAULT_AGENT_PATH or descriptor.path[:1] == _AGENTS_PATH:
                continue
            if not in_public_sample(descriptor.tier):
                continue
            value = f"${{{descriptor.environment_name}}}" if descriptor.sensitive else _default_value(descriptor.path)
            _set_path(document, descriptor.path, value)
        document[_AGENTS_KEY] = {
            _DEFAULT_AGENT_KEY: AgentName.CLAUDE.value,
            **{agent.value: {_ENABLED_KEY: agent is AgentName.CLAUDE} for agent in AgentName},
        }
        transaction.replace_text(yaml.safe_dump(document, sort_keys=False))
    return "created"


def _set_path(document: MutableMapping[str, object], path: tuple[str, ...], value: object) -> None:
    """Write one schema leaf into a nested document."""
    current = document
    for part in path[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, MutableMapping):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[path[-1]] = value


def _default_value(path: tuple[str, ...]) -> object:
    """Return a copy of the declared default for one generated schema leaf."""
    current: object = DEFAULT_CONFIG
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return deepcopy(current)
