"""Materialize regular-file templates into the TeleClaude home."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from teleclaude.paths import REPO_ROOT, TELECLAUDE_HOME


class HomeTemplateDisposition(StrEnum):
    """Closed outcomes for one materialized home template."""

    WRITTEN = "written"
    UNCHANGED = "unchanged"


class HomeTemplateConflictKind(StrEnum):
    """Filesystem type conflicts that prevent safe template materialization."""

    SOURCE_ROOT = "source-root-not-directory"
    SOURCE_DIRECTORY = "source-path-not-directory"
    SOURCE_FILE = "source-not-regular-file"
    TARGET_ROOT = "target-root-not-directory"
    TARGET_DIRECTORY = "target-path-not-directory"
    TARGET_FILE = "target-not-regular-file"
    DOT_SEGMENT = "unmarked-dot-prefixed-source-path"
    EMPTY_MARKER = "empty-dot-marker"


class HomeTemplateMaterializationConflict(Exception):
    """A template path has a filesystem kind that cannot be safely copied."""

    def __init__(self, kind: HomeTemplateConflictKind, path: Path) -> None:
        self.kind = kind
        self.path = path
        super().__init__(f"{kind.value}: {path}")


@dataclass(frozen=True)
class HomeTemplateOutcome:
    """The observed disposition of one source template."""

    source: Path
    target: Path
    disposition: HomeTemplateDisposition


_HOME_TEMPLATE_ROOT = REPO_ROOT / "templates" / "home"
_DOT_MARKER = "dot_"
_DOT_PREFIX = "."
_EMPTY_NAME = ""


def materialize_home_templates(
    home: Path = TELECLAUDE_HOME,
    *,
    source_root: Path = _HOME_TEMPLATE_ROOT,
) -> tuple[HomeTemplateOutcome, ...]:
    """Copy declared regular files to ``home``, leaving identical files untouched."""
    _require_directory(source_root, HomeTemplateConflictKind.SOURCE_ROOT)
    _require_or_create_directory(home, HomeTemplateConflictKind.TARGET_ROOT)
    outcomes: list[HomeTemplateOutcome] = []
    for source in _source_files(source_root):
        relative_source = source.relative_to(source_root)
        relative_target = _map_target_path(relative_source, source)
        _require_regular_file(source)
        target = home / relative_target
        _ensure_target_parents(target.parent, home)
        source_bytes = source.read_bytes()
        disposition = _write_if_changed(source_bytes, target)
        outcomes.append(HomeTemplateOutcome(source, target, disposition))
    return tuple(outcomes)


def _source_files(source_root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    directories = [source_root]
    while directories:
        directory = directories.pop()
        _require_directory(
            directory,
            HomeTemplateConflictKind.SOURCE_ROOT
            if directory == source_root
            else HomeTemplateConflictKind.SOURCE_DIRECTORY,
        )
        for child in sorted(directory.iterdir(), reverse=True):
            mode = child.lstat().st_mode
            if stat.S_ISDIR(mode):
                directories.append(child)
            else:
                files.append(child)
    return tuple(sorted(files))


def _map_target_path(relative_source: Path, source: Path) -> Path:
    target_parts: list[str] = []
    for segment in relative_source.parts:
        if segment.startswith(_DOT_PREFIX) and not segment.startswith(_DOT_MARKER):
            raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.DOT_SEGMENT, source)
        if segment.startswith(_DOT_MARKER):
            mapped_name = segment[len(_DOT_MARKER) :]
            if mapped_name == _EMPTY_NAME:
                raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.EMPTY_MARKER, source)
            target_parts.append(f"{_DOT_PREFIX}{mapped_name}")
        else:
            target_parts.append(segment)
    return Path(*target_parts)


def _require_directory(path: Path, kind: HomeTemplateConflictKind) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        raise HomeTemplateMaterializationConflict(kind, path) from None
    if not stat.S_ISDIR(mode):
        raise HomeTemplateMaterializationConflict(kind, path)


def _require_or_create_directory(path: Path, kind: HomeTemplateConflictKind) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        path.mkdir(parents=True)
        mode = path.lstat().st_mode
    if not stat.S_ISDIR(mode):
        raise HomeTemplateMaterializationConflict(kind, path)


def _require_regular_file(path: Path) -> None:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.SOURCE_FILE, path)


def _ensure_target_parents(directory: Path, home: Path) -> None:
    relative_directory = directory.relative_to(home)
    current = home
    for segment in relative_directory.parts:
        current /= segment
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            current.mkdir()
            mode = current.lstat().st_mode
        if not stat.S_ISDIR(mode):
            raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.TARGET_DIRECTORY, current)


def _write_if_changed(content: bytes, target: Path) -> HomeTemplateDisposition:
    try:
        mode = target.lstat().st_mode
    except FileNotFoundError:
        target.write_bytes(content)
        return HomeTemplateDisposition.WRITTEN
    if not stat.S_ISREG(mode):
        raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.TARGET_FILE, target)
    if target.read_bytes() == content:
        return HomeTemplateDisposition.UNCHANGED
    target.write_bytes(content)
    return HomeTemplateDisposition.WRITTEN


__all__ = [
    "HomeTemplateConflictKind",
    "HomeTemplateDisposition",
    "HomeTemplateMaterializationConflict",
    "HomeTemplateOutcome",
    "materialize_home_templates",
]
