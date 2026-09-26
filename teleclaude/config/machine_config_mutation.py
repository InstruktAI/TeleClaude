"""Semantic, lock-scoped operations over the machine configuration document."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from io import StringIO

from teleclaude.agent_registry import AgentName
from teleclaude.config import DEFAULT_CONFIG, TeleclaudeConfig, build_config_from_raw, config_path
from teleclaude.config._file_io import FileTransaction, file_transaction
from teleclaude.config._file_migrations import (
    LegacyDiscordProviderIds,
    contains_legacy_discord_provider_fields,
    partition_legacy_discord_provider_ids,
)
from teleclaude.config._models import ReleaseChannel
from teleclaude.config._yaml import round_trip_yaml
from teleclaude.config.revision import StaleRevision, view_revision

_DOCUMENT_MAPPING_ERROR = "Machine configuration must be a YAML mapping."
_MISSING_CONFIG_ERROR = "Machine configuration does not exist."
_MISSING_FIELD_ERROR = "Machine configuration field does not exist."
_INVALID_FIELD_PATH_ERROR = "Machine configuration field path is invalid."
_COMPUTER = "computer"
_TRUSTED_DIRS = "trusted_dirs"
_NAME = "name"
_DESC = "desc"
_PATH = "path"
_DEPLOYMENT = "deployment"
_CHANNEL = "channel"
_PINNED_MINOR = "pinned_minor"
_AGENTS = "agents"
_DEFAULT = "default"
_ENABLED = "enabled"
_KIND = "kind"
_RETIRED_PROVIDER_FIELD_ERROR = "Retired Discord provider identifiers are not valid machine-config input."
_READ_ONLY_DECLARATION_ERROR = "Machine configuration `kind` is read-only; persisting it is outside this mutation path."


class ReadOnlyDeclaration(ValueError):
    """A mutation candidate changed, added or removed the machine file's `kind` declaration."""


class MachineConfigOperation(StrEnum):
    """Closed vocabulary for machine-config changes."""

    PATCH = "patch"
    REMOVE = "remove"
    FIELD = "field"
    TRUSTED_DIRECTORY = "trusted_directory"
    DEPLOYMENT = "deployment"
    AGENTS = "agents"
    LEGACY_DISCORD_CLEANUP = "legacy_discord_cleanup"


@dataclass(frozen=True)
class MachineConfigInspection:
    """Current-schema view of the committed machine-config document."""

    raw: Mapping[object, object]
    legacy_discord_provider_ids: LegacyDiscordProviderIds
    revision: str


@dataclass(frozen=True)
class MachineConfigMutationResult:
    """Validated raw document and effective aggregate returned after replacement."""

    operation: MachineConfigOperation
    raw: Mapping[object, object]
    resolved: TeleclaudeConfig
    revision: str


def _computed_revision(raw: Mapping[object, object]) -> str:
    """Compute the machine subject's revision over its raw document, excluding `kind`."""
    return view_revision({_COMPUTER: {key: value for key, value in raw.items() if key != "kind"}})


def inspect_machine_config() -> MachineConfigInspection:
    """Read the machine configuration without requiring effective-config construction."""
    with file_transaction(config_path) as transaction:
        raw = _read_mapping(transaction)
    projected, legacy = partition_legacy_discord_provider_ids(raw)
    return MachineConfigInspection(raw=projected, legacy_discord_provider_ids=legacy, revision=_computed_revision(raw))


def patch_machine_config(patch: Mapping[object, object]) -> MachineConfigMutationResult:
    """Merge a semantic patch into the latest committed machine configuration."""
    _reject_retired_provider_fields(patch)
    return _mutate(MachineConfigOperation.PATCH, lambda raw: _deep_merge(raw, patch))


def patch_machine_config_at(
    patch: Mapping[object, object],
    expected_revision: str,
) -> MachineConfigMutationResult:
    """Merge a semantic patch only when the committed document matches `expected_revision`."""
    _reject_retired_provider_fields(patch)
    return _mutate(
        MachineConfigOperation.PATCH,
        lambda raw: _deep_merge(raw, patch),
        expected_revision=expected_revision,
    )


def remove_machine_config_fields(field_paths: tuple[tuple[str, ...], ...]) -> MachineConfigMutationResult:
    """Remove declared field paths from the latest committed machine configuration."""
    return _mutate(MachineConfigOperation.REMOVE, lambda raw: _remove_fields(raw, field_paths))


def set_machine_field(field_path: tuple[str, ...], value: object) -> MachineConfigMutationResult:
    """Set one typed field through the config-owned transaction."""
    if _is_retired_provider_field(field_path):
        raise ValueError(_RETIRED_PROVIDER_FIELD_ERROR)
    return _mutate(MachineConfigOperation.FIELD, lambda raw: _set_sparse_field(raw, field_path, value))


def add_trusted_directory(name: str, path: str, description: str = "") -> MachineConfigMutationResult:
    """Register one trusted directory without exposing backing-document ownership."""
    return _mutate(
        MachineConfigOperation.TRUSTED_DIRECTORY,
        lambda raw: _add_trusted_directory(raw, name, path, description),
    )


def set_deployment(channel: ReleaseChannel, pinned_minor: str) -> MachineConfigMutationResult:
    """Set the typed machine deployment selection."""
    deployment: dict[object, object] = {_CHANNEL: channel.value, _PINNED_MINOR: pinned_minor}
    patch: dict[object, object] = {_DEPLOYMENT: deployment}
    return _mutate(MachineConfigOperation.DEPLOYMENT, lambda raw: _deep_merge(raw, patch))


def configure_agents(
    enabled: Mapping[AgentName, bool],
    default_agent: AgentName,
) -> MachineConfigMutationResult:
    """Converge agent enablement and default selection through the semantic owner."""
    return _mutate(MachineConfigOperation.AGENTS, lambda raw: _configure_agents(raw, enabled, default_agent))


def legacy_discord_provider_ids() -> LegacyDiscordProviderIds:
    """Expose retained legacy provider identifiers for the integration migration."""
    return inspect_machine_config().legacy_discord_provider_ids


def clear_legacy_discord_provider_ids() -> MachineConfigMutationResult:
    """Remove retired provider identifiers after the integration owner reports durable import."""
    return _mutate(MachineConfigOperation.LEGACY_DISCORD_CLEANUP, lambda raw: _clear_legacy_discord_provider_ids(raw))


def _mutate(
    operation: MachineConfigOperation,
    mutation: Callable[[dict[object, object]], dict[object, object]],
    *,
    expected_revision: str | None = None,
) -> MachineConfigMutationResult:
    """Apply one mutation under the stable file lock and validate before replacement."""
    with file_transaction(config_path) as transaction:
        committed = _read_mapping(transaction)
        if expected_revision is not None:
            actual_revision = _computed_revision(committed)
            if actual_revision != expected_revision:
                raise StaleRevision(expected=expected_revision, actual=actual_revision)
        candidate = mutation(deepcopy(committed))
        if candidate.get(_KIND) != committed.get(_KIND):
            raise ReadOnlyDeclaration(_READ_ONLY_DECLARATION_ERROR)
        projected, _ = partition_legacy_discord_provider_ids(candidate)
        resolved = build_config_from_raw(projected, config_path.parent, config_source=config_path)
        _write_mapping(transaction, candidate)
    return MachineConfigMutationResult(
        operation=operation, raw=candidate, resolved=resolved, revision=_computed_revision(candidate)
    )


def _reject_retired_provider_fields(patch: Mapping[object, object]) -> None:
    """Keep current-schema mutation candidates distinct from retained stored legacy state."""
    if contains_legacy_discord_provider_fields(patch):
        raise ValueError(_RETIRED_PROVIDER_FIELD_ERROR)


def _is_retired_provider_field(field_path: tuple[str, ...]) -> bool:
    """Return whether a direct field operation targets a retired provider identifier."""
    patch: dict[object, object] = {}
    _set_field(patch, field_path, None)
    return contains_legacy_discord_provider_fields(patch)


def _read_mapping(transaction: FileTransaction) -> dict[object, object]:
    """Parse the latest document under the active config transaction."""
    content = transaction.read_text()
    if not content:
        raise FileNotFoundError(_MISSING_CONFIG_ERROR)
    document = round_trip_yaml().load(content)
    if not isinstance(document, dict):
        raise ValueError(_DOCUMENT_MAPPING_ERROR)
    return document


def _write_mapping(transaction: FileTransaction, document: Mapping[object, object]) -> None:
    """Serialize one validated document through the active atomic transaction."""
    buffer = StringIO()
    round_trip_yaml().dump(dict(document), buffer)
    transaction.replace_text(buffer.getvalue())


def _deep_merge(base: Mapping[object, object], patch: Mapping[object, object]) -> dict[object, object]:
    """Merge-patch (RFC 7386): mapping keys merge, a `None` leaf value removes the key."""
    result = deepcopy(dict(base))
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
            continue
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = deepcopy(value)
    return result


def _remove_fields(raw: dict[object, object], field_paths: tuple[tuple[str, ...], ...]) -> dict[object, object]:
    """Remove declared paths, rejecting absent or malformed paths before validation."""
    for field_path in field_paths:
        if not field_path:
            raise ValueError(_INVALID_FIELD_PATH_ERROR)
        target: dict[object, object] = raw
        for segment in field_path[:-1]:
            nested = target.get(segment)
            if not isinstance(nested, dict):
                raise KeyError(_MISSING_FIELD_ERROR)
            target = nested
        if field_path[-1] not in target:
            raise KeyError(_MISSING_FIELD_ERROR)
        target.pop(field_path[-1])
    return raw


def _set_field(raw: dict[object, object], field_path: tuple[str, ...], value: object) -> dict[object, object]:
    """Set one nested field, creating only parent containers owned by the path."""
    if not field_path:
        raise ValueError(_INVALID_FIELD_PATH_ERROR)
    target = raw
    for segment in field_path[:-1]:
        nested = target.get(segment)
        if nested is None:
            nested = {}
            target[segment] = nested
        if not isinstance(nested, dict):
            raise ValueError(_INVALID_FIELD_PATH_ERROR)
        target = nested
    target[field_path[-1]] = deepcopy(value)
    return raw


def _set_sparse_field(raw: dict[object, object], field_path: tuple[str, ...], value: object) -> dict[object, object]:
    """Write a field or omit its stored representation when the schema default applies."""
    default = _default_for_field(field_path)
    if default is not _MISSING_DEFAULT and value == default:
        _remove_field_if_present(raw, field_path)
        return raw
    return _set_field(raw, field_path, value)


_MISSING_DEFAULT = object()


def _default_for_field(field_path: tuple[str, ...]) -> object:
    """Find a scalar default in the schema-owned defaults tree."""
    current: object = DEFAULT_CONFIG
    for segment in field_path:
        if not isinstance(current, Mapping) or segment not in current:
            return _MISSING_DEFAULT
        current = current[segment]
    return current


def _remove_field_if_present(raw: dict[object, object], field_path: tuple[str, ...]) -> None:
    """Omit a default-valued path and prune empty owned parent mappings."""
    if not field_path:
        return
    current = raw
    parents: list[tuple[dict[object, object], str]] = []
    for segment in field_path[:-1]:
        nested = current.get(segment)
        if not isinstance(nested, dict):
            return
        parents.append((current, segment))
        current = nested
    current.pop(field_path[-1], None)
    for parent, segment in reversed(parents):
        nested = parent.get(segment)
        if isinstance(nested, dict) and not nested:
            parent.pop(segment)


def _add_trusted_directory(raw: dict[object, object], name: str, path: str, description: str) -> dict[object, object]:
    """Add or replace a trusted directory by its stable path identity."""
    computer = raw.setdefault(_COMPUTER, {})
    if not isinstance(computer, dict):
        raise ValueError(_INVALID_FIELD_PATH_ERROR)
    directories = computer.setdefault(_TRUSTED_DIRS, [])
    if not isinstance(directories, list):
        raise ValueError(_INVALID_FIELD_PATH_ERROR)
    entry: dict[object, object] = {_NAME: name, _PATH: path}
    if description:
        entry[_DESC] = description
    for index, existing in enumerate(directories):
        if isinstance(existing, dict) and existing.get(_PATH) == path:
            directories[index] = entry
            return raw
    directories.append(entry)
    return raw


def _configure_agents(
    raw: dict[object, object],
    enabled: Mapping[AgentName, bool],
    default_agent: AgentName,
) -> dict[object, object]:
    """Update only agent enablement and the declared default agent."""
    agents = raw.setdefault(_AGENTS, {})
    if not isinstance(agents, dict):
        raise ValueError(_INVALID_FIELD_PATH_ERROR)
    agents[_DEFAULT] = default_agent.value
    for agent, is_enabled in enabled.items():
        entry = agents.setdefault(agent.value, {})
        if not isinstance(entry, dict):
            raise ValueError(_INVALID_FIELD_PATH_ERROR)
        entry[_ENABLED] = is_enabled
    return raw


def _clear_legacy_discord_provider_ids(raw: dict[object, object]) -> dict[object, object]:
    """Persist the projected current-schema document after durable reflection import."""
    projected, _ = partition_legacy_discord_provider_ids(raw)
    return projected
