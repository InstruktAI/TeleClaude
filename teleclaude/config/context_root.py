"""Declaration-driven resolution of an invocation context root."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import NamedTuple, cast

import yaml

from teleclaude.config.migrations import resolve_read_subject
from teleclaude.config.migrations._runner import upcast_for_read
from teleclaude.config.schema import ConfigKind
from teleclaude.git_tree import TreeSource, list_tree_paths, read_tree_path
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


class OwningHome(NamedTuple):
    """An owning home root inside a repository tree and its declared kind."""

    root: Path
    kind: ConfigKind

    def relative_path(self, repository_path: str | Path) -> str:
        """Return a repository path in this home's coordinates."""
        return Path(repository_path).relative_to(self.root).as_posix()


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
    return _load_declared_config_kind(path, payload)


def _load_declared_config_kind(path: Path, payload: object) -> ConfigKind:
    """Resolve a declaration kind from parsed content using the normal migration semantics."""
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


def owning_home(relative_path: str | Path, source: TreeSource) -> OwningHome | None:
    """Resolve the nearest declared owning home for a path inside a Git tree."""
    tree_paths = set(list_tree_paths(source))
    return _owning_home(relative_path, source, tree_paths, {})


def group_paths_by_owning_home(
    relative_paths: Iterable[str | Path],
    source: TreeSource,
    *,
    tree_paths: set[str] | None = None,
) -> dict[OwningHome, list[str]]:
    """Partition repository-relative paths by the homes declared in one Git tree."""
    paths_in_tree = tree_paths if tree_paths is not None else set(list_tree_paths(source))
    kind_cache: dict[Path, ConfigKind] = {}
    grouped: dict[OwningHome, list[str]] = {}
    for relative_path in relative_paths:
        home = _owning_home(relative_path, source, paths_in_tree, kind_cache)
        if home is None:
            continue
        display_path = relative_path.as_posix() if isinstance(relative_path, Path) else relative_path
        grouped.setdefault(home, []).append(display_path)
    return grouped


def _owning_home(
    relative_path: str | Path,
    source: TreeSource,
    tree_paths: set[str],
    kind_cache: dict[Path, ConfigKind],
) -> OwningHome | None:
    """Resolve one path using declarations present in the supplied tree."""
    path_text = relative_path.as_posix() if isinstance(relative_path, Path) else relative_path
    candidate = PurePosixPath(path_text)
    if candidate.is_absolute() or _PARENT_PATH_COMPONENT in candidate.parts:
        raise ValueError(_INVALID_REPOSITORY_RELATIVE_PATH.format(path=path_text))
    directory = candidate.parent
    while True:
        marker = directory / _CONFIG_FILE_NAME
        marker_relative_path = marker.as_posix()
        if marker_relative_path in tree_paths:
            root = Path(*directory.parts) if directory.parts else Path(_ROOT_RELATIVE_PATH)
            kind = kind_cache.get(root)
            if kind is None:
                marker_path = (source.repository_root / root / _CONFIG_FILE_NAME).resolve()
                payload: object = yaml.safe_load(read_tree_path(source, marker_relative_path).decode(_UTF8)) or {}
                kind = _load_declared_config_kind(marker_path, payload)
                kind_cache[root] = kind
            return OwningHome(root=root, kind=kind)
        if directory == PurePosixPath(_ROOT_RELATIVE_PATH):
            return None
        directory = directory.parent


def load_raw_declaration(path: Path, *, subject: str) -> Mapping[object, object]:
    """Read a declaration mapping in its current in-memory shape without validation."""
    try:
        payload = yaml.safe_load(path.read_text(encoding=_UTF8)) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(_RAW_DECLARATION_READ_FAILURE.format(subject=subject, path=path, error=exc)) from exc
    if not isinstance(payload, Mapping):
        raise ValueError(_RAW_DECLARATION_MAPPING_FAILURE.format(subject_capitalized=subject.capitalize(), path=path))
    return cast(Mapping[object, object], upcast_for_read(path, payload))
