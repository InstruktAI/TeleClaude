"""Explicit-source environment reference and environment-file operations."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from dotenv import dotenv_values

from teleclaude.config._file_io import file_transaction

_ENV_REFERENCE_PREFIX: Final = "${"
_ENV_REFERENCE_SUFFIX: Final = "}"
_ENV_REFERENCE_PATTERN: Final = re.compile(r"\$\{([^}]+)\}")
_ENV_ASSIGNMENT: Final = "="
_ENV_EXPORT_PREFIX: Final = "export "
_NEWLINE: Final = "\n"
_OWNER_ONLY_MODE: Final = 0o600
_LIST_IDENTITY_KEYS: Final = ("id", "slug", "key", "name", "email", "address")


class CompanyCredentialsError(Exception):
    """Raised when a required company environment file is unsafe to read."""


class MissingEnvironmentReferenceError(ValueError):
    """Raised when an overlay reference is absent from its supplied environment."""


@dataclass(frozen=True)
class EnvironmentReference:
    """One placeholder occurrence in a structured configuration document."""

    name: str
    path: tuple[str | int, ...]


def find_environment_references(value: object, path: tuple[str | int, ...] = ()) -> list[EnvironmentReference]:
    """Return every non-empty ``${NAME}`` placeholder in a structured value."""
    if isinstance(value, Mapping):
        references: list[EnvironmentReference] = []
        for key, child in value.items():
            references.extend(find_environment_references(child, (*path, str(key))))
        return references
    if isinstance(value, list):
        references = []
        for index, child in enumerate(value):
            references.extend(find_environment_references(child, (*path, index)))
        return references
    if isinstance(value, str):
        return [EnvironmentReference(name, path) for name in _reference_names(value)]
    return []


def environment_reference_at_path(value: object, path: tuple[str, ...]) -> str | None:
    """Return the placeholder name at a dotted structured path, if one is present."""
    current = value
    for part in path:
        if isinstance(current, Mapping):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return _placeholder_name(current) if isinstance(current, str) else None


def expand_environment_references(
    value: object,
    environment: Mapping[str, str],
    *,
    config_path: Path | None = None,
    preserve_unresolved: bool = False,
) -> object:
    """Resolve placeholders using only ``environment`` without ambient fallback."""
    return _expand_environment_references(value, environment, config_path, preserve_unresolved, ())


def _expand_environment_references(
    value: object,
    environment: Mapping[str, str],
    config_path: Path | None,
    preserve_unresolved: bool,
    path: tuple[str | int, ...],
) -> object:
    """Resolve a structured value while retaining each leaf's location."""
    if isinstance(value, Mapping):
        return {
            key: _expand_environment_references(
                child,
                environment,
                config_path,
                preserve_unresolved,
                (*path, str(key)),
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [
            _expand_environment_references(
                child,
                environment,
                config_path,
                preserve_unresolved,
                (*path, index),
            )
            for index, child in enumerate(value)
        ]
    if not isinstance(value, str):
        return value
    references = _reference_names(value)
    if not references:
        return value
    return _ENV_REFERENCE_PATTERN.sub(
        lambda match: _resolve_reference(match.group(1), environment, config_path, preserve_unresolved, path), value
    )


def read_environment_file(path: Path, *, company_restricted: bool = False) -> dict[str, str]:
    """Read one environment file, applying company secret access policy when required."""
    if not path.exists():
        return {}
    if company_restricted:
        _require_owner_only_company_environment(path)
    return {key: value for key, value in dotenv_values(path).items() if value is not None}


def write_environment_value(path: Path, name: str, value: str, *, creation_mode: int | None = None) -> None:
    """Atomically replace one environment value while preserving unrelated lines."""
    write_environment_values(path, {name: value}, creation_mode=creation_mode)


def write_environment_values(path: Path, values: Mapping[str, str], *, creation_mode: int | None = None) -> None:
    """Atomically apply named values to one environment file."""
    _validate_environment_values(values)
    with file_transaction(path) as transaction:
        lines = transaction.read_text().splitlines(keepends=True)
        remaining = dict(values)
        rewritten: list[str] = []
        for line in lines:
            assignment = _environment_assignment(line)
            if assignment is not None and assignment.name in remaining:
                rewritten.append(_assignment_line(assignment.name, remaining.pop(assignment.name), assignment.prefix))
            else:
                rewritten.append(line)
        if rewritten and not rewritten[-1].endswith(_NEWLINE):
            rewritten[-1] = f"{rewritten[-1]}{_NEWLINE}"
        rewritten.extend(_assignment_line(name, value) for name, value in remaining.items())
        transaction.replace_text("".join(rewritten), creation_mode=creation_mode)


def reconcile_environment_references(
    raw: object,
    effective: object,
    environment: Mapping[str, str],
) -> tuple[object, dict[str, str]]:
    """Retain raw references and derive required owning-environment updates."""
    updates: dict[str, str] = {}
    reconciled = _reconcile(raw, effective, environment, updates, ())
    return reconciled, updates


def company_environment_creation_mode() -> int:
    """Return the creation mode mandated for company credential files."""
    return _OWNER_ONLY_MODE


def _reconcile(
    raw: object,
    effective: object,
    environment: Mapping[str, str],
    updates: dict[str, str],
    path: tuple[str | int, ...],
) -> object:
    if isinstance(raw, Mapping):
        effective_mapping = effective if isinstance(effective, Mapping) else {}
        result = dict(effective_mapping)
        for key, raw_value in raw.items():
            result[key] = _reconcile(raw_value, effective_mapping.get(key), environment, updates, (*path, str(key)))
        return result
    if isinstance(raw, list):
        return _reconcile_list(raw, effective, environment, updates, path)
    if not isinstance(raw, str):
        return effective if effective is not None else raw
    references = _reference_names(raw)
    if not references:
        return effective if effective is not None else raw
    name = _placeholder_name(raw)
    if name is None:
        if effective is not None and str(effective) == _expand_embedded_reference_value(raw, environment):
            return raw
        raise ValueError(_embedded_reference_update_message(path))
    if effective is None:
        return raw
    next_value = str(effective)
    prior_value = environment.get(name)
    if next_value != prior_value:
        prior_update = updates.setdefault(name, next_value)
        if prior_update != next_value:
            raise ValueError(_conflicting_reference_message(name, path))
    return raw


def _placeholder_name(value: str) -> str | None:
    if value.startswith(_ENV_REFERENCE_PREFIX) and value.endswith(_ENV_REFERENCE_SUFFIX):
        name = value[len(_ENV_REFERENCE_PREFIX) : -len(_ENV_REFERENCE_SUFFIX)]
        return name or None
    return None


def _reference_names(value: str) -> list[str]:
    """Return every non-empty placeholder name embedded in a string value."""
    return [match.group(1) for match in _ENV_REFERENCE_PATTERN.finditer(value) if match.group(1)]


def _resolve_reference(
    name: str,
    environment: Mapping[str, str],
    config_path: Path | None,
    preserve_unresolved: bool,
    path: tuple[str | int, ...],
) -> str:
    if name in environment:
        return environment[name]
    if preserve_unresolved:
        return f"{_ENV_REFERENCE_PREFIX}{name}{_ENV_REFERENCE_SUFFIX}"
    raise MissingEnvironmentReferenceError(_missing_reference_message(EnvironmentReference(name, path), config_path))


def _expand_embedded_reference_value(value: str, environment: Mapping[str, str]) -> str:
    """Resolve a loaded reference-bearing string without consulting ambient state."""
    return _ENV_REFERENCE_PATTERN.sub(lambda match: environment.get(match.group(1), match.group(0)), value)


def _reconcile_list(
    raw: list[object],
    effective: object,
    environment: Mapping[str, str],
    updates: dict[str, str],
    path: tuple[str | int, ...],
) -> list[object]:
    """Retain references without constraining a saved list to its old cardinality."""
    if not isinstance(effective, list):
        return list(raw)
    if len(raw) == len(effective):
        return [
            _reconcile(raw_value, effective[index], environment, updates, (*path, index))
            for index, raw_value in enumerate(raw)
        ]
    remaining = list(enumerate(raw))
    reconciled: list[object] = []
    for index, effective_value in enumerate(effective):
        raw_index = _matching_raw_list_item(remaining, effective_value, environment)
        if raw_index is None:
            if any(_contains_environment_reference(raw_value) for _, raw_value in remaining):
                raise ValueError(_ambiguous_list_reconciliation_message(path))
            reconciled.append(effective_value)
            continue
        _, raw_value = remaining.pop(raw_index)
        reconciled.append(_reconcile(raw_value, effective_value, environment, updates, (*path, index)))
    return reconciled


def _matching_raw_list_item(
    remaining: list[tuple[int, object]], effective: object, environment: Mapping[str, str]
) -> int | None:
    """Find the raw list item whose stable literal shape identifies an effective item."""
    for index, (_, raw) in enumerate(remaining):
        if raw == effective:
            return index
    matches = [
        index for index, (_, raw) in enumerate(remaining) if _matches_effective_value(raw, effective, environment)
    ]
    return matches[0] if matches else None


def _matches_effective_value(raw: object, effective: object, environment: Mapping[str, str]) -> bool:
    """Match a raw item by its non-placeholder structure while treating references as values."""
    if isinstance(raw, str) and _placeholder_name(raw) is not None:
        return True
    if isinstance(raw, str) and isinstance(effective, str) and _reference_names(raw):
        return _expand_embedded_reference_value(raw, environment) == effective
    if isinstance(raw, Mapping) and isinstance(effective, Mapping):
        return _mapping_matches_effective_value(raw, effective, environment)
    if isinstance(raw, list) and isinstance(effective, list):
        return len(raw) == len(effective) and all(
            _matches_effective_value(raw_value, effective[index], environment) for index, raw_value in enumerate(raw)
        )
    return raw == effective


def _mapping_matches_effective_value(
    raw: Mapping[object, object], effective: Mapping[object, object], environment: Mapping[str, str]
) -> bool:
    """Match reference-bearing mappings through a durable item identity when available."""
    if not _contains_environment_reference(raw):
        return raw == effective
    for key in _LIST_IDENTITY_KEYS:
        if key in raw and key in effective:
            return raw[key] == effective[key]
    return all(
        key in effective and _matches_effective_value(raw_value, effective[key], environment)
        for key, raw_value in raw.items()
        if not _contains_environment_reference(raw_value)
    )


def _contains_environment_reference(value: object) -> bool:
    """Report whether a structured value contains a raw environment reference."""
    if isinstance(value, str):
        return bool(_reference_names(value))
    if isinstance(value, Mapping):
        return any(_contains_environment_reference(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_environment_reference(child) for child in value)
    return False


def _missing_reference_message(reference: EnvironmentReference, config_path: Path | None) -> str:
    location = _render_reference_path(reference.path)
    source = str(config_path) if config_path is not None else "configuration"
    return f"Missing local environment reference '{reference.name}' at '{location}' in {source}"


def _conflicting_reference_message(name: str, path: tuple[str | int, ...]) -> str:
    return f"Conflicting values supplied for environment reference '{name}' at '{_render_reference_path(path)}'"


def _embedded_reference_update_message(path: tuple[str | int, ...]) -> str:
    return f"Cannot update an embedded environment reference at '{_render_reference_path(path)}'"


def _ambiguous_list_reconciliation_message(path: tuple[str | int, ...]) -> str:
    return f"Cannot reconcile changed list references without a stable identity at '{_render_reference_path(path)}'"


def _render_reference_path(path: tuple[str | int, ...]) -> str:
    return ".".join(str(part) for part in path) or "<root>"


def _require_owner_only_company_environment(path: Path) -> None:
    file_mode = path.stat().st_mode
    if file_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise CompanyCredentialsError(
            f"Company environment file is group/world-accessible ({stat.filemode(file_mode)}); expected owner-only: {path}"
        )
    if not os.access(path, os.R_OK):
        raise CompanyCredentialsError(f"Company environment file is not readable: {path}")


def _validate_environment_values(values: Mapping[str, str]) -> None:
    for name, value in values.items():
        if not name or any(character in name for character in "\r\n="):
            raise ValueError("Invalid environment variable name")
        if any(character in value for character in "\r\n"):
            raise ValueError("Environment variable value cannot contain newlines")


@dataclass(frozen=True)
class _EnvironmentAssignment:
    """One parsed environment assignment and its retained declaration prefix."""

    name: str
    prefix: str


def _environment_assignment(line: str) -> _EnvironmentAssignment | None:
    stripped = line.lstrip()
    prefix = _ENV_EXPORT_PREFIX if stripped.startswith(_ENV_EXPORT_PREFIX) else ""
    candidate = stripped.removeprefix(prefix)
    name, separator, _value = candidate.partition(_ENV_ASSIGNMENT)
    return _EnvironmentAssignment(name, prefix) if separator and name else None


def _assignment_line(name: str, value: str, prefix: str = "") -> str:
    return f"{prefix}{name}{_ENV_ASSIGNMENT}{value}{_NEWLINE}"
