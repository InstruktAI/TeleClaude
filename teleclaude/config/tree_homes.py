"""Which committed home owns a repository path, read from a Git tree source rather than the working tree."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import NamedTuple

import yaml

from teleclaude.config.context_root import declared_config_kind
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


class ResolvedTreeHome(NamedTuple):
    """A home whose committed declaration resolved to one kind."""

    root: Path
    kind: ConfigKind
    error: None


class UnreadableTreeHome(NamedTuple):
    """A home whose committed declaration could not be read."""

    root: Path
    kind: None
    error: Exception


type TreeHome = ResolvedTreeHome | UnreadableTreeHome


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
    home_cache: dict[Path, TreeHome] = {}
    grouped: dict[OwningHome, list[str]] = {}
    for relative_path in relative_paths:
        home = _owning_home(relative_path, source, paths_in_tree, home_cache)
        if home is None:
            continue
        display_path = relative_path.as_posix() if isinstance(relative_path, Path) else relative_path
        grouped.setdefault(home, []).append(display_path)
    return grouped


def homes_at_or_beneath(relative_directory: str | Path, source: TreeSource) -> list[TreeHome]:
    """List homes declared at or below a repository-relative directory in a Git tree."""
    directory = _repository_relative_directory(relative_directory)
    tree_paths = set(list_tree_paths(source))
    marker_paths = sorted(
        path
        for path in tree_paths
        if PurePosixPath(path).name == _CONFIG_FILE_NAME and PurePosixPath(path).parent.is_relative_to(directory)
    )
    homes: list[TreeHome] = []
    for marker_path in marker_paths:
        root = Path(PurePosixPath(marker_path).parent.as_posix())
        homes.append(_read_tree_home(root, marker_path, source))
    return homes


def group_paths_by_owning_home_tolerant(
    relative_paths: Iterable[str | Path],
    source: TreeSource,
    *,
    tree_paths: set[str] | None = None,
) -> dict[TreeHome, list[str]]:
    """Partition paths by nearest tree home, retaining unreadable declarations as entries."""
    paths_in_tree = tree_paths if tree_paths is not None else set(list_tree_paths(source))
    home_cache: dict[Path, TreeHome] = {}
    grouped: dict[TreeHome, list[str]] = {}
    for relative_path in relative_paths:
        home = _tree_home_for_path(relative_path, source, paths_in_tree, home_cache)
        if home is None:
            continue
        display_path = relative_path.as_posix() if isinstance(relative_path, Path) else relative_path
        grouped.setdefault(home, []).append(display_path)
    return grouped


def _owning_home(
    relative_path: str | Path,
    source: TreeSource,
    tree_paths: set[str],
    home_cache: dict[Path, TreeHome],
) -> OwningHome | None:
    """Resolve one path using declarations present in the supplied tree."""
    entry = _tree_home_for_path(relative_path, source, tree_paths, home_cache)
    if entry is None:
        return None
    if isinstance(entry, UnreadableTreeHome):
        raise entry.error
    return OwningHome(root=entry.root, kind=entry.kind)


def _tree_home_for_path(
    relative_path: str | Path,
    source: TreeSource,
    tree_paths: set[str],
    home_cache: dict[Path, TreeHome],
) -> TreeHome | None:
    """Resolve a path to its nearest declaration present in the supplied tree."""
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
            home = home_cache.get(root)
            if home is None:
                home = _read_tree_home(root, marker_relative_path, source)
                home_cache[root] = home
            return home
        if directory == PurePosixPath(_ROOT_RELATIVE_PATH):
            return None
        directory = directory.parent


def _read_tree_home(root: Path, marker_relative_path: str, source: TreeSource) -> TreeHome:
    """Read a declaration from the tree while retaining parse and read failures."""
    marker_path = (source.repository_root / root / _CONFIG_FILE_NAME).resolve()
    try:
        payload: object = yaml.safe_load(read_tree_path(source, marker_relative_path).decode(_UTF8)) or {}
        return ResolvedTreeHome(root=root, kind=declared_config_kind(marker_path, payload), error=None)
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        return UnreadableTreeHome(root=root, kind=None, error=exc)


def _repository_relative_directory(relative_directory: str | Path) -> PurePosixPath:
    """Validate and normalize a repository-relative directory."""
    path_text = relative_directory.as_posix() if isinstance(relative_directory, Path) else relative_directory
    directory = PurePosixPath(path_text)
    if directory.is_absolute() or _PARENT_PATH_COMPONENT in directory.parts:
        raise ValueError(_INVALID_REPOSITORY_RELATIVE_PATH.format(path=path_text))
    return directory
