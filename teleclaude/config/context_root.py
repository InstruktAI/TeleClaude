"""Declaration-driven resolution of an invocation context root."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import NamedTuple, cast

import yaml

from teleclaude.config.migrations._registry import resolve_read_subject
from teleclaude.config.migrations.read import upcast_for_read
from teleclaude.config.schema import ConfigKind
from teleclaude.paths import ConfigFileName

_UTF8 = "utf-8"
_KIND_FIELD = "kind"
_INVALID_DECLARATION = "Invalid configuration declaration in {path}"
_RAW_DECLARATION_READ_FAILURE = "Failed to read {subject} declaration {path}: {error}"
_RAW_DECLARATION_MAPPING_FAILURE = "{subject_capitalized} declaration must be a mapping: {path}"
_INVALID_REPOSITORY_RELATIVE_PATH = "Path must be repository-relative: {path}"
_ROOT_RELATIVE_PATH = "."
_PARENT_PATH_COMPONENT = ".."
_CONFIG_FILE_NAME = ConfigFileName.OVERLAY.value


class ContextRoot(NamedTuple):
    """An anchoring configuration declaration and its root directory."""

    path: Path
    kind: ConfigKind


class ConfigDeclaration(NamedTuple):
    """A nearest configuration declaration and its declared tier."""

    path: Path
    kind: ConfigKind


def nearest_config_declaration(
    start: Path,
    *,
    error_factory: Callable[[Path, Exception], Exception] | None = None,
    directory_cache: dict[Path, ConfigDeclaration | None | Exception] | None = None,
) -> ConfigDeclaration | None:
    """Return the nearest declaration, including non-anchoring company declarations."""
    current = start.expanduser().resolve()
    if current.is_file():
        current = current.parent
    visited: list[Path] = []
    while True:
        if directory_cache is not None and current in directory_cache:
            cached = directory_cache[current]
            for directory in visited:
                directory_cache[directory] = cached
            if isinstance(cached, Exception):
                raise cached
            declaration = cached
            break
        marker = current / ConfigFileName.OVERLAY
        if marker.is_file():
            try:
                kind = load_declared_config_kind(marker)
            except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
                if error_factory is not None:
                    error = error_factory(marker, exc)
                    if directory_cache is not None:
                        directory_cache[current] = error
                        for directory in visited:
                            directory_cache[directory] = error
                    raise error from exc
                raise
            declaration = ConfigDeclaration(path=marker, kind=kind)
            break
        if current.parent == current:
            declaration = None
            break
        visited.append(current)
        current = current.parent
    if directory_cache is not None:
        directory_cache[current] = declaration
        for directory in visited:
            directory_cache[directory] = declaration
    return declaration


def resolve_context_root(start: Path) -> ContextRoot | None:
    """Return the nearest anchoring declaration, or no context root."""
    declaration = nearest_config_declaration(start)
    if declaration is None or declaration.kind is ConfigKind.COMPANY:
        return None
    return ContextRoot(path=declaration.path.parent, kind=declaration.kind)


def load_declared_config_kind(path: Path) -> ConfigKind:
    """Read a root's declared configuration tier from its in-memory migrated view."""
    payload: object = yaml.safe_load(path.read_text(encoding=_UTF8)) or {}
    return declared_config_kind(path, payload)


def declared_config_kind(path: Path, payload: object) -> ConfigKind:
    """Resolve a declaration kind from parsed content using the normal migration semantics.

    ``path`` names the declaration's location for subject resolution; the content may
    come from anywhere, such as a committed tree.
    """
    if not isinstance(payload, Mapping):
        raise ValueError(_INVALID_DECLARATION.format(path=path))
    subject = resolve_read_subject(path, payload)
    if subject is None:
        raise ValueError(_INVALID_DECLARATION.format(path=path))
    raw = upcast_for_read(path, payload, subject=subject)
    if not isinstance(raw, dict):
        raise ValueError(_INVALID_DECLARATION.format(path=path))
    value = raw.get(_KIND_FIELD)
    try:
        return ConfigKind(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(_INVALID_DECLARATION.format(path=path)) from exc


def load_raw_declaration(path: Path, *, subject: str) -> Mapping[object, object]:
    """Read a declaration mapping in its current in-memory shape without validation."""
    try:
        payload = yaml.safe_load(path.read_text(encoding=_UTF8)) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(_RAW_DECLARATION_READ_FAILURE.format(subject=subject, path=path, error=exc)) from exc
    if not isinstance(payload, Mapping):
        raise ValueError(_RAW_DECLARATION_MAPPING_FAILURE.format(subject_capitalized=subject.capitalize(), path=path))
    return cast(Mapping[object, object], upcast_for_read(path, payload))
