"""Render templates and materialize layered regular-file template trees into their targets."""

from __future__ import annotations

import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from os import PathLike
from pathlib import Path

from teleclaude.git import InvalidGitRepositoryError, Repo
from teleclaude.paths import REPO_ROOT


class HomeTemplateDisposition(StrEnum):
    """Closed outcomes for one materialized template."""

    WRITTEN = "written"
    UNCHANGED = "unchanged"
    PRESERVED = "preserved"
    HELD = "held"


class HomeTemplateConflictKind(StrEnum):
    """Template and filesystem conflicts that prevent safe template materialization."""

    SOURCE_ROOT = "source-root-not-directory"
    SOURCE_ROOT_UNTRACKED = "source-root-outside-checkout"
    SOURCE_DIRECTORY = "source-path-not-directory"
    SOURCE_FILE = "source-not-regular-file"
    TARGET_ROOT = "target-root-not-directory"
    TARGET_DIRECTORY = "target-path-not-directory"
    TARGET_FILE = "target-not-regular-file"
    DOT_SEGMENT = "unmarked-dot-prefixed-source-path"
    EMPTY_MARKER = "empty-dot-marker"
    EMPTY_CREATE_MARKER = "empty-create-marker"
    CREATE_MARKER_ON_DIRECTORY = "create-marker-on-directory"
    LAYER_COLLISION = "layer-collision"


class HomeTemplateMaterializationConflict(Exception):
    """A template path has a filesystem kind that cannot be safely copied."""

    def __init__(self, kind: HomeTemplateConflictKind, path: Path) -> None:
        self.kind = kind
        self.path = path
        super().__init__(_CONFLICT_MESSAGE.format(kind=kind.value, path=path))


class TemplateLayerCollision(HomeTemplateMaterializationConflict):
    """Two planned files claim one target path, or one planned file sits where another needs a directory."""

    def __init__(self, target: Path, source: Path, other_target: Path, other_source: Path) -> None:
        super().__init__(HomeTemplateConflictKind.LAYER_COLLISION, target)
        self.source = source
        self.other_target = other_target
        self.other_source = other_source
        self.args = (
            _COLLISION_MESSAGE.format(
                kind=self.kind.value,
                target=target,
                source=source,
                other_target=other_target,
                other_source=other_source,
            ),
        )


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


class TemplateTarget(StrEnum):
    """The closed set of target kinds a layered template installation addresses."""

    TELECLAUDE_HOME = "teleclaude-home"
    PERSON_HOME = "person-home"
    PERSON_MASTER = "person-master"
    COMPANY_HOME = "company-home"
    COMPANY_MASTER = "company-master"
    PROJECT = "project"
    COMPANY_HELP_DESK = "company-help-desk"
    PROJECT_HELP_DESK = "project-help-desk"


@dataclass(frozen=True)
class TemplateLayer:
    """One template tree under the templates root and the directory it mounts at inside a target."""

    tree: str
    mount: Path


@dataclass(frozen=True)
class PlannedTemplateFile:
    """One rendered template and the target it installs to."""

    source: Path
    target: Path
    content: bytes
    create_once: bool


@dataclass(frozen=True)
class PlannedTemplateTarget:
    """One target root and every rendered file its layers install there."""

    root: Path
    kind: TemplateTarget
    files: tuple[PlannedTemplateFile, ...]


@dataclass(frozen=True)
class TemplateInstallationPlan:
    """A validated multi-target installation: nothing is written until it is applied."""

    targets: tuple[PlannedTemplateTarget, ...]


_TEMPLATE_TREE_DIRNAME = "templates"
_TARGET_ROOT_MOUNT = Path()
_DOCS_MOUNT = Path("docs")
_DOCS_TREE = "docs"
_TEMPLATE_LAYERS: Mapping[TemplateTarget, tuple[TemplateLayer, ...]] = {
    TemplateTarget.TELECLAUDE_HOME: (TemplateLayer("home", _TARGET_ROOT_MOUNT),),
    TemplateTarget.PERSON_HOME: (TemplateLayer(_DOCS_TREE, _DOCS_MOUNT),),
    TemplateTarget.PERSON_MASTER: (TemplateLayer("home-person", _TARGET_ROOT_MOUNT),),
    TemplateTarget.COMPANY_HOME: (TemplateLayer(_DOCS_TREE, _DOCS_MOUNT),),
    TemplateTarget.COMPANY_MASTER: (TemplateLayer("home-company", _TARGET_ROOT_MOUNT),),
    TemplateTarget.PROJECT: (TemplateLayer(_DOCS_TREE, _DOCS_MOUNT),),
    TemplateTarget.COMPANY_HELP_DESK: (TemplateLayer("help-desk-company", _TARGET_ROOT_MOUNT),),
    TemplateTarget.PROJECT_HELP_DESK: (TemplateLayer("help-desk-project", _TARGET_ROOT_MOUNT),),
}
_DOT_MARKER = "dot_"
_CREATE_MARKER = "create_"
_DOT_PREFIX = "."
_EMPTY_NAME = ""
_NUL = "\0"
_LS_FILES_NUL_OPTION = "-z"
_PATHSPEC_SEPARATOR = "--"
_TEMPLATE_ENCODING = "utf-8"
_EXCLUSIVE_CREATE_MODE = "xb"
_CONFLICT_MESSAGE = "{kind}: {path}"
_COLLISION_MESSAGE = "{kind}: {target} (from {source}) conflicts with {other_target} (from {other_source})"
_PLACEHOLDER_PATTERN = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


def template_tree_root(checkout_root: Path) -> Path:
    """The directory of the template trees inside a TeleClaude checkout."""
    return checkout_root / _TEMPLATE_TREE_DIRNAME


_TEMPLATES_ROOT = template_tree_root(REPO_ROOT)


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


def plan_template_installation(
    targets: Sequence[tuple[Path, TemplateTarget]],
    *,
    values: Mapping[str, str],
    environ: Mapping[str, str],
    templates_root: Path = _TEMPLATES_ROOT,
) -> TemplateInstallationPlan:
    """Render every layer of every target and validate the whole set before anything is written.

    Refuses a target path two planned files produce, a planned file that would
    sit where another planned file needs a directory, a target root whose
    nearest existing ancestor is not a directory, and any filesystem-type
    conflict in an existing target tree.
    """
    planned_targets = tuple(
        PlannedTemplateTarget(root, kind, _render_target(root, kind, values, environ, templates_root))
        for root, kind in targets
    )
    _validate_planned_namespace(planned_targets)
    for planned in planned_targets:
        _require_root_ancestor_directory(planned.root)
        _validate_target_tree(planned.root, planned.files)
    return TemplateInstallationPlan(planned_targets)


def apply_template_installation(
    plan: TemplateInstallationPlan,
    *,
    held_targets: frozenset[Path] = frozenset(),
) -> tuple[HomeTemplateOutcome, ...]:
    """Write a validated plan, leaving held targets unread and unchanged."""
    outcomes: list[HomeTemplateOutcome] = []
    for planned in plan.targets:
        _require_or_create_directory(planned.root, HomeTemplateConflictKind.TARGET_ROOT)
        for file in planned.files:
            if file.target in held_targets:
                outcomes.append(HomeTemplateOutcome(file.source, file.target, HomeTemplateDisposition.HELD))
                continue
            _ensure_target_parents(file.target.parent, planned.root)
            if file.create_once:
                disposition = _write_if_absent(file.content, file.target)
            else:
                disposition = _write_if_changed(file.content, file.target)
            outcomes.append(HomeTemplateOutcome(file.source, file.target, disposition))
    return tuple(outcomes)


def materialize_template_targets(
    targets: Sequence[tuple[Path, TemplateTarget]],
    *,
    values: Mapping[str, str],
    environ: Mapping[str, str],
    templates_root: Path = _TEMPLATES_ROOT,
    held_targets: frozenset[Path] = frozenset(),
) -> tuple[HomeTemplateOutcome, ...]:
    """Plan and apply a layered installation, leaving held targets unchanged."""
    plan = plan_template_installation(targets, values=values, environ=environ, templates_root=templates_root)
    return apply_template_installation(plan, held_targets=held_targets)


def _render_target(
    root: Path,
    kind: TemplateTarget,
    values: Mapping[str, str],
    environ: Mapping[str, str],
    templates_root: Path,
) -> tuple[PlannedTemplateFile, ...]:
    files: list[PlannedTemplateFile] = []
    for layer in _TEMPLATE_LAYERS[kind]:
        source_root = templates_root / layer.tree
        _require_directory(source_root, HomeTemplateConflictKind.SOURCE_ROOT)
        for source in _source_files(source_root):
            relative_target, create_once = _map_target_path(source.relative_to(source_root), source)
            _require_regular_file(source)
            try:
                source_text = source.read_bytes().decode(_TEMPLATE_ENCODING)
            except UnicodeDecodeError:
                raise InvalidTemplateEncodingError(source) from None
            rendered = render_template(source_text, template=source, values=values, environ=environ)
            files.append(
                PlannedTemplateFile(
                    source=source,
                    target=root / layer.mount / relative_target,
                    content=rendered.encode(_TEMPLATE_ENCODING),
                    create_once=create_once,
                )
            )
    return tuple(files)


def _source_files(source_root: Path) -> tuple[Path, ...]:
    """List the files the checkout holding ``source_root`` tracks under it, as present in the working tree."""
    try:
        repository = Repo(source_root, search_parent_directories=True)
    except InvalidGitRepositoryError:
        raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.SOURCE_ROOT_UNTRACKED, source_root) from None
    working_tree = repository.working_tree_dir
    if working_tree is None:
        raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.SOURCE_ROOT_UNTRACKED, source_root)
    checkout_root = Path(working_tree).resolve()
    resolved_source_root = source_root.resolve()
    output = repository.git.ls_files(_LS_FILES_NUL_OPTION, _PATHSPEC_SEPARATOR, str(resolved_source_root))
    files: list[Path] = []
    for entry in output.split(_NUL):
        if not entry:
            continue
        tracked = checkout_root / entry
        if not tracked.exists() and not tracked.is_symlink():
            continue
        files.append(source_root / tracked.relative_to(resolved_source_root))
    return tuple(sorted(files))


def _map_target_path(relative_source: Path, source: Path) -> tuple[Path, bool]:
    """Map marker segments to installed names; the second value says whether the file is create-once."""
    target_parts: list[str] = []
    create_once = False
    last_index = len(relative_source.parts) - 1
    for index, segment in enumerate(relative_source.parts):
        if segment.startswith(_CREATE_MARKER):
            if index != last_index:
                raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.CREATE_MARKER_ON_DIRECTORY, source)
            segment = segment[len(_CREATE_MARKER) :]
            if segment == _EMPTY_NAME:
                raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.EMPTY_CREATE_MARKER, source)
            create_once = True
        if segment.startswith(_DOT_PREFIX) and not segment.startswith(_DOT_MARKER):
            raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.DOT_SEGMENT, source)
        if segment.startswith(_DOT_MARKER):
            mapped_name = segment[len(_DOT_MARKER) :]
            if mapped_name == _EMPTY_NAME:
                raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.EMPTY_MARKER, source)
            target_parts.append(f"{_DOT_PREFIX}{mapped_name}")
        else:
            target_parts.append(segment)
    return Path(*target_parts), create_once


def _validate_planned_namespace(targets: tuple[PlannedTemplateTarget, ...]) -> None:
    """Refuse duplicate target paths and planned files that are ancestors of other planned paths or roots."""
    planned: dict[Path, Path] = {}
    for target in targets:
        for file in target.files:
            existing_source = planned.get(file.target)
            if existing_source is not None:
                raise TemplateLayerCollision(file.target, existing_source, file.target, file.source)
            planned[file.target] = file.source
    for target in targets:
        for file in target.files:
            for ancestor in file.target.parents:
                ancestor_source = planned.get(ancestor)
                if ancestor_source is not None:
                    raise TemplateLayerCollision(ancestor, ancestor_source, file.target, file.source)
        for candidate in (target.root, *target.root.parents):
            candidate_source = planned.get(candidate)
            if candidate_source is not None and target.files:
                first = target.files[0]
                raise TemplateLayerCollision(candidate, candidate_source, first.target, first.source)


def _require_root_ancestor_directory(root: Path) -> None:
    """Require the nearest existing path at or above ``root`` to be a directory."""
    for candidate in (root, *root.parents):
        try:
            mode = candidate.lstat().st_mode
        except (FileNotFoundError, NotADirectoryError):
            continue
        if not stat.S_ISDIR(mode):
            raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.TARGET_ROOT, candidate)
        return


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


def _validate_target_tree(root: Path, files: tuple[PlannedTemplateFile, ...]) -> None:
    try:
        mode = root.lstat().st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(mode):
        raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.TARGET_ROOT, root)
    for file in files:
        current = root
        for segment in file.target.relative_to(root).parts[:-1]:
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
            mode = file.target.lstat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(mode):
            raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.TARGET_FILE, file.target)


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


def _write_if_absent(content: bytes, target: Path) -> HomeTemplateDisposition:
    """Create ``target`` exclusively; a file another writer created first is kept as it is."""
    try:
        with target.open(_EXCLUSIVE_CREATE_MODE) as created:
            created.write(content)
    except FileExistsError:
        if not stat.S_ISREG(target.lstat().st_mode):
            raise HomeTemplateMaterializationConflict(HomeTemplateConflictKind.TARGET_FILE, target) from None
        return HomeTemplateDisposition.PRESERVED
    return HomeTemplateDisposition.WRITTEN


__all__ = [
    "HomeTemplateConflictKind",
    "HomeTemplateDisposition",
    "HomeTemplateMaterializationConflict",
    "HomeTemplateOutcome",
    "InvalidTemplateEncodingError",
    "PlannedTemplateFile",
    "PlannedTemplateTarget",
    "TemplateInstallationPlan",
    "TemplateLayer",
    "TemplateLayerCollision",
    "TemplateTarget",
    "UnresolvedPlaceholderError",
    "apply_template_installation",
    "materialize_template_targets",
    "plan_template_installation",
    "render_template",
    "template_tree_root",
]
