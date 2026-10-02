"""Configuration-document subjects, resolved from the tier registries."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path

from teleclaude.config.migrations import v001_declare_tier_kind
from teleclaude.config.migrations._chain import CURRENT_VERSION, MigrationTrigger, document_version
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef, SubjectSource
from teleclaude.core.project_state import resolve_project_state_root
from teleclaude.paths import COMPANIES_ROOT, GLOBAL_CONFIG_PATH, MACHINE_CONFIG_PATH, PEOPLE_DIR, ConfigFileName
from teleclaude.project_manifest import load_roots
from teleclaude.runtime.config import require_own_checkout

_SCHEMA_VERSION = "schema_version"
_KIND_FIELD = "kind"
_OVERLAY_KINDS = frozenset(
    {ConfigSubjectKind.GLOBAL, ConfigSubjectKind.PERSON, ConfigSubjectKind.COMPANY, ConfigSubjectKind.PROJECT}
)
_CONFIG_NAME = ConfigFileName.OVERLAY


def registered_subject(path: Path) -> SubjectRef | None:
    """Return the registry subject for a document path when a tier registry names it."""
    resolved = path.expanduser().resolve()
    if resolved == MACHINE_CONFIG_PATH.resolve():
        return SubjectRef(ConfigSubjectKind.COMPUTER)
    if resolved == GLOBAL_CONFIG_PATH.resolve():
        return SubjectRef(ConfigSubjectKind.GLOBAL)
    instance = _registered_instance(resolved, PEOPLE_DIR)
    if instance is not None:
        return SubjectRef(ConfigSubjectKind.PERSON, instance)
    instance = _registered_instance(resolved, COMPANIES_ROOT)
    if instance is not None:
        return SubjectRef(ConfigSubjectKind.COMPANY, instance)
    roots = {root.expanduser().resolve() for root in load_roots()}
    if resolved in {root / _CONFIG_NAME for root in roots}:
        return SubjectRef(ConfigSubjectKind.PROJECT)
    if resolved.name == _CONFIG_NAME and (resolved.parent / ".git").is_file():
        try:
            owner = resolve_project_state_root(resolved.parent).resolve()
        except FileNotFoundError:
            return None
        if owner in roots:
            return SubjectRef(ConfigSubjectKind.PROJECT)
    return None


def resolve_read_subject(path: Path, document: Mapping[str, object]) -> SubjectRef | None:
    """Use a registry subject when available, otherwise the document's tier declaration.

    Every tier but project is located by its registry, so an overlay from before
    the declaring migration that no registry names is read as a project.
    """
    version = document_version(document)
    if version < CURRENT_VERSION:
        subject = registered_subject(path)
        if subject is not None:
            return subject
        if version < v001_declare_tier_kind.VERSION and _KIND_FIELD not in document and path.name == _CONFIG_NAME:
            return SubjectRef(kind=ConfigSubjectKind.PROJECT, source=SubjectSource.DECLARATION)
    declared_kind = document.get(_KIND_FIELD)
    if not isinstance(declared_kind, str):
        return None
    try:
        kind = ConfigSubjectKind(declared_kind)
    except ValueError:
        return None
    if kind not in _OVERLAY_KINDS:
        return None
    return SubjectRef(kind=kind, source=SubjectSource.DECLARATION)


def _registered_instance(path: Path, root: Path) -> str | None:
    """Resolve a person or company document by its immediate registry directory."""
    resolved_root = root.resolve()
    try:
        relative = path.relative_to(resolved_root)
    except ValueError:
        return None
    if len(relative.parts) != 2 or relative.name != _CONFIG_NAME:
        return None
    instance = relative.parts[0]
    directory = resolved_root / instance
    return instance if directory.is_dir() else None


def registered_documents(trigger: MigrationTrigger) -> Iterator[tuple[Path, SubjectRef]]:
    """Enumerate every registry-named document covered by a run trigger."""
    yield MACHINE_CONFIG_PATH, SubjectRef(ConfigSubjectKind.COMPUTER)
    yield GLOBAL_CONFIG_PATH, SubjectRef(ConfigSubjectKind.GLOBAL)
    if trigger is MigrationTrigger.INSTALL:
        return
    for instance in _directory_instances(PEOPLE_DIR):
        yield PEOPLE_DIR / instance / _CONFIG_NAME, SubjectRef(ConfigSubjectKind.PERSON, instance)
    for instance in _directory_instances(COMPANIES_ROOT):
        yield COMPANIES_ROOT / instance / _CONFIG_NAME, SubjectRef(ConfigSubjectKind.COMPANY, instance)
    for root in load_roots():
        require_own_checkout(root)
        yield root / _CONFIG_NAME, SubjectRef(ConfigSubjectKind.PROJECT)


def _directory_instances(root: Path) -> tuple[str, ...]:
    """List directories containing a registered tier document."""
    if not root.exists():
        return ()
    return tuple(sorted(entry.name for entry in root.iterdir() if entry.is_dir() and (entry / _CONFIG_NAME).is_file()))
