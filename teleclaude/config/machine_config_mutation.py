"""Semantic, lock-scoped operations over the machine configuration document."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from teleclaude.agent_registry import AgentName
from teleclaude.config._defaults import DEFAULT_CONFIG
from teleclaude.config._machine_build import build_config_from_raw
from teleclaude.config._models import ReleaseChannel, TeleclaudeConfig
from teleclaude.config._yaml import round_trip_yaml
from teleclaude.config.declaration import render_machine_config
from teleclaude.config.machine import config_path
from teleclaude.config.migrations._carry import carry_pending
from teleclaude.config.migrations._chain import CURRENT_VERSION, Destination, upcast
from teleclaude.config.migrations.read import upcast_for_read
from teleclaude.config.revision import StaleRevision, view_revision
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.file_transaction import FileTransaction, file_transaction
from teleclaude.paths import MACHINE_CONFIG_PATH

_UTF8 = "utf-8"
_DOCUMENT_MAPPING_ERROR = "Machine configuration must be a YAML mapping."
_MISSING_CONFIG_ERROR = "Machine configuration does not exist."
_MISSING_FIELD_ERROR = "Machine configuration field does not exist."
_INVALID_FIELD_PATH_ERROR = "Machine configuration field path is invalid."
_COMPUTER = "computer"
_DEPLOYMENT = "deployment"
_CHANNEL = "channel"
_PINNED_MINOR = "pinned_minor"
_AGENTS = "agents"
_DEFAULT = "default"
_ENABLED = "enabled"
_KIND = "kind"
_SCHEMA_VERSION = "schema_version"
_READ_ONLY_SCHEMA_VERSION_ERROR = "Machine configuration `schema_version` is read-only."
_READ_ONLY_DECLARATION_ERROR = "Machine configuration `kind` is read-only; persisting it is outside this mutation path."
_COMPUTER_SUBJECT = SubjectRef(ConfigSubjectKind.COMPUTER)


class ReadOnlyDeclaration(ValueError):
    """A mutation candidate changed, added or removed the machine file's `kind` declaration."""


class MachineConfigOperation(StrEnum):
    """Closed vocabulary for machine-config changes."""

    PATCH = "patch"
    REMOVE = "remove"
    FIELD = "field"
    DEPLOYMENT = "deployment"
    AGENTS = "agents"


@dataclass(frozen=True)
class MachineConfigInspection:
    """Current-schema view of the committed machine-config document."""

    raw: Mapping[object, object]
    revision: str


@dataclass(frozen=True)
class MachineConfigMutationResult:
    """Validated raw document and effective aggregate returned after replacement."""

    operation: MachineConfigOperation
    raw: Mapping[object, object]
    resolved: TeleclaudeConfig
    revision: str


def _computed_revision(raw: Mapping[object, object]) -> str:
    """Compute the machine subject's revision over its read-only metadata-free view."""
    return view_revision({_COMPUTER: {key: value for key, value in raw.items() if key not in {_KIND, _SCHEMA_VERSION}}})


def inspect_machine_config() -> MachineConfigInspection:
    """Read the machine configuration without requiring effective-config construction."""
    with file_transaction(config_path) as transaction:
        stored = _read_mapping(transaction)
    raw = cast(
        Mapping[object, object],
        upcast_for_read(config_path, cast(Mapping[str, object], stored), subject=_COMPUTER_SUBJECT),
    )
    return MachineConfigInspection(raw=raw, revision=_computed_revision(raw))


def patch_machine_config(patch: Mapping[object, object]) -> MachineConfigMutationResult:
    """Merge a semantic patch into the latest committed machine configuration."""
    _reject_schema_version_write(patch)
    return _mutate(MachineConfigOperation.PATCH, lambda raw: _deep_merge(raw, patch))


def patch_machine_config_at(
    patch: Mapping[object, object],
    expected_revision: str,
    *,
    delivered: Callable[[Destination], None] | None = None,
) -> MachineConfigMutationResult:
    """Merge a semantic patch only when the committed document matches `expected_revision`."""
    _reject_schema_version_write(patch)
    return _mutate(
        MachineConfigOperation.PATCH,
        lambda raw: _deep_merge(raw, patch),
        expected_revision=expected_revision,
        delivered=delivered,
    )


def remove_machine_config_fields(field_paths: tuple[tuple[str, ...], ...]) -> MachineConfigMutationResult:
    """Remove declared field paths from the latest committed machine configuration."""
    return _mutate(MachineConfigOperation.REMOVE, lambda raw: _remove_fields(raw, field_paths))


def set_machine_field(field_path: tuple[str, ...], value: object) -> MachineConfigMutationResult:
    """Set one typed field through the config-owned transaction."""
    if field_path and field_path[0] == _SCHEMA_VERSION:
        raise ReadOnlyDeclaration(_READ_ONLY_SCHEMA_VERSION_ERROR)
    return _mutate(MachineConfigOperation.FIELD, lambda raw: _set_sparse_field(raw, field_path, value))


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


def _ignore_delivery(_destination: Destination) -> None:
    """Keep migration destinations outside mutation outcomes for non-resource callers."""


def _mutate(
    operation: MachineConfigOperation,
    mutation: Callable[[dict[object, object]], dict[object, object]],
    *,
    expected_revision: str | None = None,
    delivered: Callable[[Destination], None] | None = None,
) -> MachineConfigMutationResult:
    """Apply one mutation under the stable file lock and validate before replacement."""
    with file_transaction(config_path) as transaction:
        stored = _read_mapping(transaction)
        committed = cast(dict[object, object], upcast(cast(Mapping[str, object], stored), _COMPUTER_SUBJECT))
        if expected_revision is not None:
            actual_revision = _computed_revision(cast(Mapping[object, object], committed))
            if actual_revision != expected_revision:
                raise StaleRevision(expected=expected_revision, actual=actual_revision)
        candidate = mutation(deepcopy(dict(committed)))
        if candidate.get(_KIND) != committed.get(_KIND):
            raise ReadOnlyDeclaration(_READ_ONLY_DECLARATION_ERROR)
        if candidate.get(_SCHEMA_VERSION) != committed.get(_SCHEMA_VERSION):
            raise ReadOnlyDeclaration(_READ_ONLY_SCHEMA_VERSION_ERROR)
        candidate[_SCHEMA_VERSION] = CURRENT_VERSION
        resolved = build_config_from_raw(candidate, config_path.parent, config_source=config_path)
        carry_pending(cast(Mapping[str, object], stored), _COMPUTER_SUBJECT, delivered=delivered or _ignore_delivery)
        _write_mapping(transaction, candidate)
    return MachineConfigMutationResult(
        operation=operation, raw=candidate, resolved=resolved, revision=_computed_revision(candidate)
    )


def _reject_schema_version_write(patch: Mapping[object, object]) -> None:
    """Keep schema version under the migration list's write authority."""
    if _SCHEMA_VERSION in patch:
        raise ReadOnlyDeclaration(_READ_ONLY_SCHEMA_VERSION_ERROR)


def stored_machine_document() -> Mapping[str, object] | None:
    """Read the stored machine document as it is on disk, before migration and without validation.

    Readers of entries still in transit out of the machine document need its stored shape. An empty
    file is an empty document; a document that is not a mapping is ``None``.
    """
    with file_transaction(MACHINE_CONFIG_PATH) as transaction:
        content = transaction.read_text(encoding=_UTF8)
    if not content:
        return {}
    document: object = round_trip_yaml().load(content)
    return document if isinstance(document, Mapping) else None


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
    transaction.replace_text(render_machine_config(cast(Mapping[str, object], document)))


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
