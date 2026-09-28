"""Pure versioned transforms for configuration documents."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from enum import StrEnum
from typing import Final, Protocol, cast

from teleclaude.config.subjects import ConfigSubjectKind, SubjectRef, SubjectSource

_SCHEMA_VERSION = "schema_version"
_VERSION_ERROR = "Configuration schema_version must be a non-negative integer"
_STEP_ORDER_ERROR = "Configuration migration steps must be numbered 1..N in order"
_NEWER_ERROR = "Configuration document version {document_version} is newer than installation version {current_version}"
_MISSING_SUBJECT = "An older configuration document is not named by a tier registry"
_REGISTRY_SUBJECT_REQUIRED = "Persisted migrations require a configuration subject from a tier registry"
_MOVES_FIELD = "MOVES"


class Destination(StrEnum):
    """Config-owned destinations for values moving between documents."""

    INVITATIONS = "invitations"
    HANDOFF = "handoff"
    PROJECT_REGISTRY = "project_registry"


class MigrationTrigger(StrEnum):
    """Closed entry-point vocabulary for persisted configuration migration."""

    READ = "read"
    WRITER = "writer"
    REGISTRATION = "registration"
    INSTALL = "install"
    MAINTENANCE = "maintenance"


class DocumentNewerThanInstallation(ValueError):
    """A document's declared version is beyond the installed migration list."""


class RegistrySubjectRequired(ValueError):
    """A persistence path received a declaration-only read subject."""


def require_registry_subject(subject: SubjectRef) -> None:
    """Refuse persistence when its subject came from a read-only declaration."""
    if subject.source is not SubjectSource.REGISTRY:
        raise RegistrySubjectRequired(_REGISTRY_SUBJECT_REQUIRED)


from teleclaude.config.migrations import _steps  # noqa: E402  # Destination must exist before step modules import it


class Step(Protocol):
    """One pure document transformation and optional persisted effects."""

    VERSION: int
    KINDS: frozenset[ConfigSubjectKind]
    READ_REQUIRES_REGISTRY: bool

    def up(self, document: MutableMapping[str, object], subject: SubjectRef) -> None: ...


STEPS: Final = _steps.STEPS
if tuple(step.VERSION for step in STEPS) != tuple(range(1, len(STEPS) + 1)):
    raise RuntimeError(_STEP_ORDER_ERROR)
CURRENT_VERSION: Final = len(STEPS)


def document_version(document: Mapping[str, object]) -> int:
    """Read and validate the document's version, defaulting an absent field to zero."""
    version = document.get(_SCHEMA_VERSION, 0)
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise ValueError(_VERSION_ERROR)
    return version


def upcast(document: Mapping[str, object], subject: SubjectRef | None) -> MutableMapping[str, object]:
    """Apply every remaining migration in memory and return the current document."""
    version = document_version(document)
    if version > CURRENT_VERSION:
        raise DocumentNewerThanInstallation(
            _NEWER_ERROR.format(document_version=version, current_version=CURRENT_VERSION)
        )
    current = cast(MutableMapping[str, object], deepcopy(document))
    if version == CURRENT_VERSION:
        return current
    if subject is None:
        raise ValueError(_MISSING_SUBJECT)
    for step in STEPS[version:]:
        has_registry_standing = subject.source is SubjectSource.REGISTRY
        if subject.kind in step.KINDS and (has_registry_standing or not step.READ_REQUIRES_REGISTRY):
            step.up(current, subject)
        current[_SCHEMA_VERSION] = step.VERSION
    return current


def in_transit(document: Mapping[str, object], subject: SubjectRef, destination: Destination) -> tuple[object, ...]:
    """Return values still in a stored document for a destination."""
    version = document_version(document)
    if version > CURRENT_VERSION:
        raise DocumentNewerThanInstallation(
            _NEWER_ERROR.format(document_version=version, current_version=CURRENT_VERSION)
        )
    pending_values: list[object] = []
    for step in STEPS[version:]:
        has_registry_standing = subject.source is SubjectSource.REGISTRY
        if getattr(step, _MOVES_FIELD, None) is destination and (
            has_registry_standing or not step.READ_REQUIRES_REGISTRY
        ):
            pending = cast(object | None, step.pending(document, subject))
            if pending is not None:
                pending_values.append(pending)
    return tuple(pending_values)
