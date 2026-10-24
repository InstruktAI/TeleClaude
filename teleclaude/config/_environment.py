"""Explicit-source environment reference and environment-file operations."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Final

from dotenv import dotenv_values

from teleclaude.config._coerce import as_bool
from teleclaude.file_transaction import FileTransaction, file_transaction

_ENV_REFERENCE_PATTERN: Final = re.compile(r"\$\{([^}]*)\}")
_NAME_GROUP: Final = "name"
_DEFAULT_GROUP: Final = "default"
_REFERENCE_NAME: Final = r"[A-Za-z_][A-Za-z0-9_]*"
_ENV_REFERENCE_BODY: Final = re.compile(
    rf"(?P<{_NAME_GROUP}>{_REFERENCE_NAME})(?::-(?P<{_DEFAULT_GROUP}>.*))?", re.DOTALL
)
WHOLE_REFERENCE_SCHEMA_PATTERN: Final = rf"^\$\{{{_REFERENCE_NAME}(?::-[^}}]*)?\}}$"
"""ECMA-262 pattern a JSON Schema validator matches against a value that is one whole reference."""
_TRUE_TEXT: Final = "true"
_FALSE_TEXT: Final = "false"
_INVALID_REFERENCE_MESSAGE: Final = (
    "Invalid environment reference at '{location}': expected ${{NAME}} or ${{NAME:-default}}"
)
_ENV_ASSIGNMENT: Final = "="
_ENV_EXPORT_PREFIX: Final = "export "
_NEWLINE: Final = "\n"
_EMPTY_TEXT: Final = ""
_OWNER_ONLY_MODE: Final = 0o600
_LIST_IDENTITY_KEYS: Final = ("id", "slug", "key", "name", "email", "address")


class CompanyCredentialsError(ValueError):
    """Raised when an owner-only tier environment file is unsafe to read."""


class MissingEnvironmentReferenceError(ValueError):
    """Raised when an overlay reference is absent from its supplied environment."""


class InvalidEnvironmentReferenceError(ValueError):
    """Raised when a ``${...}`` token is neither ``${NAME}`` nor ``${NAME:-default}``."""


@dataclass(frozen=True)
class EnvironmentReference:
    """One placeholder occurrence in a structured configuration document."""

    name: str
    path: tuple[str | int, ...]
    default: str | None = None


@dataclass(frozen=True)
class _ParsedReference:
    """One ``${NAME}`` or ``${NAME:-default}`` token."""

    name: str
    default: str | None


def find_environment_references(value: object, path: tuple[str | int, ...] = ()) -> list[EnvironmentReference]:
    """Return every ``${NAME}`` and ``${NAME:-default}`` reference in a structured value."""
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
        return [
            EnvironmentReference(reference.name, path, reference.default)
            for reference in _parse_references(value, path)
        ]
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
    return whole_reference_name(current) if isinstance(current, str) else None


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
    if not _parse_references(value, path):
        return value
    # Only a value that is one whole reference can be absent; a reference embedded in a longer
    # value has no absent form, so it resolves or fails.
    preserve_whole_value = preserve_unresolved and whole_reference_name(value) is not None
    return _ENV_REFERENCE_PATTERN.sub(
        lambda match: _resolve_reference(match, environment, config_path, preserve_whole_value, path), value
    )


def resolve_whole_reference(value: str, environment: Mapping[str, str]) -> str | None:
    """Resolve a value that is one whole reference; ``None`` when it has no value in ``environment``."""
    match = _ENV_REFERENCE_PATTERN.fullmatch(value)
    if match is None:
        return value
    reference = _parse_reference(match.group(1), ())
    if reference.name in environment:
        return environment[reference.name]
    return reference.default


def read_environment_file(path: Path, *, owner_only: bool = False, interpolate: bool = True) -> dict[str, str]:
    """Read one environment file, enforcing owner-only secret storage when required."""
    if not path.exists():
        return {}
    if owner_only:
        require_owner_only_environment(path)
    return {key: value for key, value in dotenv_values(path, interpolate=interpolate).items() if value is not None}


def write_environment_value(path: Path, name: str, value: str, *, creation_mode: int | None = None) -> None:
    """Atomically replace one environment value while preserving unrelated lines."""
    mutate_environment_value(path, name, value, creation_mode=creation_mode)


def mutate_environment_value(path: Path, name: str, value: str | None, *, creation_mode: int | None = None) -> None:
    """Atomically replace or clear one key while consuming every existing assignment."""
    if value is None:
        _validate_environment_name(name)
    else:
        _validate_environment_values({name: value})
    with file_transaction(path) as transaction:
        replace_environment_value(transaction, name, value, creation_mode=creation_mode)


def read_environment_transaction(
    transaction: FileTransaction, *, owner_only: bool = False, interpolate: bool = True
) -> dict[str, str]:
    """Read environment values from an already-held file transaction."""
    if owner_only and transaction.path.exists():
        require_owner_only_environment(transaction.path)
    parsed = dotenv_values(stream=StringIO(transaction.read_text()), interpolate=interpolate)
    return {key: value for key, value in parsed.items() if value is not None}


def prepare_environment_value(transaction: FileTransaction, name: str, value: str | None) -> str:
    """Prepare one line-preserving environment update without writing through the held transaction."""
    if value is None:
        _validate_environment_name(name)
    else:
        _validate_environment_values({name: value})
    lines = transaction.read_text().splitlines(keepends=True)
    rewritten: list[str] = []
    found = False
    for line in lines:
        assignment = _environment_assignment(line)
        if assignment is None or assignment.name != name:
            rewritten.append(line)
            continue
        if not found and value is not None:
            rewritten.append(_assignment_line(name, value, assignment.prefix))
        found = True
    if rewritten and not rewritten[-1].endswith(_NEWLINE):
        rewritten[-1] = f"{rewritten[-1]}{_NEWLINE}"
    if value is not None and not found:
        rewritten.append(_assignment_line(name, value))
    return _EMPTY_TEXT.join(rewritten)


def replace_environment_value(
    transaction: FileTransaction, name: str, value: str | None, *, creation_mode: int | None = None
) -> None:
    """Replace one environment value through the held transaction using the canonical line-preserving writer."""
    transaction.replace_text(prepare_environment_value(transaction, name, value), creation_mode=creation_mode)


def write_environment_values(
    path: Path,
    values: Mapping[str, str],
    *,
    creation_mode: int | None = None,
    only_if_missing: bool = False,
) -> bool:
    """Atomically apply named values, optionally leaving an existing file untouched."""
    _validate_environment_values(values)
    with file_transaction(path) as transaction:
        if only_if_missing and path.exists():
            return False
        replace_environment_values(transaction, values, creation_mode=creation_mode)
    return True


def replace_environment_values(
    transaction: FileTransaction, values: Mapping[str, str], *, creation_mode: int | None = None
) -> None:
    """Apply the existing batch writer through a transaction its owner already holds."""
    _validate_environment_values(values)
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
    transaction.replace_text(_EMPTY_TEXT.join(rewritten), creation_mode=creation_mode)


def reconcile_environment_values(path: Path, values: Mapping[str, str], removals: frozenset[str]) -> None:
    """Atomically apply environment additions and remove retired names from one file."""
    _validate_environment_values(values)
    for name in removals:
        _validate_environment_name(name)
    with file_transaction(path) as transaction:
        lines = transaction.read_text().splitlines(keepends=True)
        remaining = dict(values)
        rewritten: list[str] = []
        for line in lines:
            assignment = _environment_assignment(line)
            if assignment is None:
                rewritten.append(line)
                continue
            if assignment.name in removals:
                continue
            if assignment.name in remaining:
                rewritten.append(_assignment_line(assignment.name, remaining.pop(assignment.name), assignment.prefix))
                continue
            rewritten.append(line)
        if rewritten and not rewritten[-1].endswith(_NEWLINE):
            rewritten[-1] = f"{rewritten[-1]}{_NEWLINE}"
        rewritten.extend(_assignment_line(name, value) for name, value in remaining.items())
        transaction.replace_text("".join(rewritten))


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
    references = _parse_references(raw, path)
    if not references:
        return effective if effective is not None else raw
    name = whole_reference_name(raw)
    if name is None:
        if effective is not None and str(effective) == _expand_embedded_reference_value(raw, environment):
            return raw
        raise ValueError(_embedded_reference_update_message(path))
    if effective is None:
        return raw
    prior_value = environment.get(name, references[0].default)
    if not _same_environment_value(effective, prior_value):
        next_value = _environment_text(effective)
        prior_update = updates.setdefault(name, next_value)
        if prior_update != next_value:
            raise ValueError(_conflicting_reference_message(name, path))
    return raw


def _environment_text(value: object) -> str:
    """Render a typed value as the text its environment entry holds."""
    if isinstance(value, bool):
        return _TRUE_TEXT if value else _FALSE_TEXT
    return str(value)


def _same_environment_value(value: object, text: str | None) -> bool:
    """Whether environment ``text`` already carries typed ``value``, judged by the value's own type."""
    if text is None:
        return False
    try:
        if isinstance(value, bool):
            return as_bool(text) is value
        if isinstance(value, int | float):
            return type(value)(text) == value
    except ValueError:
        return False
    return str(value) == text


def whole_reference_name(value: str) -> str | None:
    """Return the name when the whole value is exactly one well-formed reference, else ``None``."""
    match = _ENV_REFERENCE_PATTERN.fullmatch(value)
    body = _ENV_REFERENCE_BODY.fullmatch(match.group(1)) if match is not None else None
    return body.group(_NAME_GROUP) if body is not None else None


def _parse_references(value: str, path: tuple[str | int, ...]) -> list[_ParsedReference]:
    """Return every reference embedded in a string value, rejecting any malformed ``${...}`` token."""
    return [_parse_reference(match.group(1), path) for match in _ENV_REFERENCE_PATTERN.finditer(value)]


def _parse_reference(body: str, path: tuple[str | int, ...]) -> _ParsedReference:
    match = _ENV_REFERENCE_BODY.fullmatch(body)
    if match is None:
        raise InvalidEnvironmentReferenceError(_invalid_reference_message(path))
    return _ParsedReference(match.group(_NAME_GROUP), match.group(_DEFAULT_GROUP))


def _resolve_reference(
    match: re.Match[str],
    environment: Mapping[str, str],
    config_path: Path | None,
    preserve_unresolved: bool,
    path: tuple[str | int, ...],
) -> str:
    reference = _parse_reference(match.group(1), path)
    if reference.name in environment:
        return environment[reference.name]
    if reference.default is not None:
        return reference.default
    if preserve_unresolved:
        return match.group(0)
    raise MissingEnvironmentReferenceError(
        _missing_reference_message(EnvironmentReference(reference.name, path), config_path)
    )


def _expand_embedded_reference_value(value: str, environment: Mapping[str, str]) -> str:
    """Resolve a loaded reference-bearing string without consulting ambient state."""
    return _ENV_REFERENCE_PATTERN.sub(lambda match: _embedded_value(match, environment), value)


def _embedded_value(match: re.Match[str], environment: Mapping[str, str]) -> str:
    reference = _parse_reference(match.group(1), ())
    if reference.name in environment:
        return environment[reference.name]
    return reference.default if reference.default is not None else match.group(0)


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
    if isinstance(raw, str) and whole_reference_name(raw) is not None:
        return True
    if isinstance(raw, str) and isinstance(effective, str) and _parse_references(raw, ()):
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
        return bool(_parse_references(value, ()))
    if isinstance(value, Mapping):
        return any(_contains_environment_reference(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_environment_reference(child) for child in value)
    return False


def _missing_reference_message(reference: EnvironmentReference, config_path: Path | None) -> str:
    location = _render_reference_path(reference.path)
    source = str(config_path) if config_path is not None else "configuration"
    return f"Missing local environment reference '{reference.name}' at '{location}' in {source}"


def _invalid_reference_message(path: tuple[str | int, ...]) -> str:
    return _INVALID_REFERENCE_MESSAGE.format(location=_render_reference_path(path))


def _conflicting_reference_message(name: str, path: tuple[str | int, ...]) -> str:
    return f"Conflicting values supplied for environment reference '{name}' at '{_render_reference_path(path)}'"


def _embedded_reference_update_message(path: tuple[str | int, ...]) -> str:
    return f"Cannot update an embedded environment reference at '{_render_reference_path(path)}'"


def _ambiguous_list_reconciliation_message(path: tuple[str | int, ...]) -> str:
    return f"Cannot reconcile changed list references without a stable identity at '{_render_reference_path(path)}'"


def _render_reference_path(path: tuple[str | int, ...]) -> str:
    return ".".join(str(part) for part in path) or "<root>"


def resolve_owner_linked_environment(path: Path) -> Path:
    """Return the file an environment path names, following it only when it is a link this OS user owns.

    The returned path still has to pass ``require_owner_only_environment``; a link owned by
    anyone else is returned unresolved so that check refuses it.
    """
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return path
    if not stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != os.getuid():
        return path
    return path.resolve(strict=True)


def require_owner_only_environment(path: Path) -> None:
    """Require an existing regular readable file owned solely by this OS user."""
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise CompanyCredentialsError(f"Environment file is unavailable: {path}") from exc
    file_mode = metadata.st_mode
    if not stat.S_ISREG(file_mode) or metadata.st_uid != os.getuid():
        raise CompanyCredentialsError(f"Environment file is not an owner-controlled regular file: {path}")
    if file_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise CompanyCredentialsError(
            f"Environment file is group/world-accessible ({stat.filemode(file_mode)}); expected owner-only: {path}"
        )
    if not os.access(path, os.R_OK):
        raise CompanyCredentialsError(f"Environment file is not readable: {path}")


def _validate_environment_values(values: Mapping[str, str]) -> None:
    for name, value in values.items():
        _validate_environment_name(name)
        if any(character in value for character in "\r\n"):
            raise ValueError("Environment variable value cannot contain newlines")


def _validate_environment_name(name: str) -> None:
    if not name or any(character in name for character in "\r\n="):
        raise ValueError("Invalid environment variable name")


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
