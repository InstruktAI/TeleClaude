"""Render templates and materialize regular-file template trees."""

from __future__ import annotations

import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from os import PathLike
from pathlib import Path

from teleclaude.paths import REPO_ROOT, TELECLAUDE_HOME


class HomeTemplateDisposition(StrEnum):
    """Closed outcomes for one materialized template."""

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


class UnresolvedPlaceholderError(Exception):
    """A template contains placeholders that have no supplied or environment value."""

    def __init__(self, template: str, names: tuple[str, ...]) -> None:
        self.template = template
        self.names = names
        super().__init__(f"{template}: unresolved placeholders: {', '.join(names)}")


class InvalidTemplateEncodingError(Exception):
    """A template file cannot be decoded as UTF-8."""

    def __init__(self, template: Path) -> None:
        self.template = template
        super().__init__(f"template is not valid UTF-8: {template}")


_HOME_TEMPLATE_ROOT = REPO_ROOT / "templates" / "home"
_DOT_MARKER = "dot_"
_DOT_PREFIX = "."
_EMPTY_NAME = ""
_PLACEHOLDER_PATTERN = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


def render_template(
    text: str,
    *,
    template: str | PathLike[str],
    values: Mapping[str, str],
    environ: Mapping[str, str],
) -> str:
    """Resolve declared placeholders once, preferring caller values to environment."""
    unresolved: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in values:
            return values[name]
        if name in environ:
            return environ[name]
        unresolved.add(name)
        return match.group(0)

    rendered = _PLACEHOLDER_PATTERN.sub(replace, text)
    if unresolved:
        raise UnresolvedPlaceholderError(str(template), tuple(sorted(unresolved)))
    return rendered


def materialize_template_tree(
    source_root: Path = _HOME_TEMPLATE_ROOT,
    target_root: Path = TELECLAUDE_HOME,
    *,
    values: Mapping[str, str],
    environ: Mapping[str, str],
) -> tuple[HomeTemplateOutcome, ...]:
    """Render and materialize a template tree, preserving identical targets."""
    _require_directory(source_root, HomeTemplateConflictKind.SOURCE_ROOT)
    rendered_files: list[tuple[Path, Path, bytes]] = []
    for source in _source_files(source_root):
        relative_source = source.relative_to(source_root)
        relative_target = _map_target_path(relative_source, source)
        _require_regular_file(source)
        try:
            source_text = source.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            raise InvalidTemplateEncodingError(source) from None
        rendered = render_template(
            source_text,
            template=source,
            values=values,
            environ=environ,
        )
        rendered_files.append((source, target_root / relative_target, rendered.encode("utf-8")))

    _validate_target_tree(target_root, rendered_files)
    _require_or_create_directory(target_root, HomeTemplateConflictKind.TARGET_ROOT)
    outcomes: list[HomeTemplateOutcome] = []
    for source, target, content in rendered_files:
        _ensure_target_parents(target.parent, target_root)
        disposition = _write_if_changed(content, target)
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


def _ensure_target_parents(directory: Path, root: Path) -> None:
    current = root
    for segment in directory.relative_to(root).parts:
        current /= segment
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            current.mkdir()
            mode = current.lstat().st_mode
        if not stat.S_ISDIR(mode):
            raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.TARGET_DIRECTORY, current)


def _validate_target_tree(root: Path, files: list[tuple[Path, Path, bytes]]) -> None:
    try:
        mode = root.lstat().st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(mode):
        raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.TARGET_ROOT, root)
    for _, target, _ in files:
        current = root
        for segment in target.relative_to(root).parts[:-1]:
            current /= segment
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                break
            if not stat.S_ISDIR(mode):
                raise HomeTemplateMaterializationConflict(
                    HomeTemplateConflictKind.TARGET_DIRECTORY,
                    current,
                )
        try:
            mode = target.lstat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(mode):
            raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.TARGET_FILE, target)


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
    "InvalidTemplateEncodingError",
    "UnresolvedPlaceholderError",
    "materialize_template_tree",
    "render_template",
]
