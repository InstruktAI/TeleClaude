"""Durable forward migration for registered person-overlay identity claims."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast
from uuid import uuid4

import yaml

from teleclaude.config._file_io import file_transaction
from teleclaude.config.declaration import render_declared_config
from teleclaude.config.schema import ConfigKind, PersonEntry
from teleclaude.paths import (
    PEOPLE_DIR,
    PERSON_CLAIM_MIGRATION_LOCK_PATH,
    PERSON_CLAIM_MIGRATION_STATE_PATH,
    ConfigFileName,
)

_UTF8 = "utf-8"
_WRITE_MODE = "w"
_LOCK_EXCLUSIVE = fcntl.LOCK_EX
_TARGETS_FIELD = "targets"
_COMPLETED_FIELD = "completed"
_PERSON_SLUG_FIELD = "slug"
_KIND_FIELD = "kind"
_TEMPORARY_PREFIX = "."
_TEMPORARY_SEPARATOR = "."
_TEMPORARY_SUFFIX = ".tmp"
_STATE_ERROR = "Invalid person-claim migration state: {path}"
_TARGET_ERROR = (
    "Person config claim migration could not complete for {path}; required claim {claim} remains unavailable"
)


class PersonClaimMigrationError(ValueError):
    """Raised when durable person-claim transition state cannot be trusted."""


@dataclass
class PersonClaimMigrationState:
    """Captured transition targets and their completed paths."""

    targets: dict[str, str]
    completed: list[str]


class PersonClaimMigrationPayload(TypedDict):
    """Serialized form of one claim-transition state."""

    targets: dict[str, str]
    completed: list[str]


def capture_required() -> bool:
    """Return whether the transition has not yet captured its eligible target set."""
    with _migration_guard():
        return _load_state() is None


def migrate_person_claim_for_target(path: Path, people: Iterable[PersonEntry]) -> None:
    """Complete the captured claim transition for one requested overlay when eligible."""
    target = _canonical_path(path)
    with _migration_guard():
        state = _state_for_people(people)
        if target not in state.targets or target in state.completed:
            return
        if not _complete_target(Path(target), state.targets[target]):
            raise PersonClaimMigrationError(_TARGET_ERROR.format(path=target, claim=_PERSON_SLUG_FIELD))
        state.completed.append(target)
        _write_state(state)


def migrate_person_claims(people: Iterable[PersonEntry]) -> bool:
    """Attempt every pending captured transition target without stopping at one failure."""
    with _migration_guard():
        state = _state_for_people(people)
        for target, slug in state.targets.items():
            if target in state.completed:
                continue
            if not _complete_target(Path(target), slug):
                continue
            state.completed.append(target)
            _write_state(state)
        return _is_complete(state)


def person_claims_complete() -> bool:
    """Return whether capture exists and every captured target is complete."""
    with _migration_guard():
        state = _load_state()
        return state is not None and _is_complete(state)


def _state_for_people(people: Iterable[PersonEntry]) -> PersonClaimMigrationState:
    state = _load_state()
    if state is not None:
        return state
    state = _capture_state(people)
    _write_state(state)
    return state


def _capture_state(people: Iterable[PersonEntry]) -> PersonClaimMigrationState:
    targets: dict[str, str] = {}
    completed: list[str] = []
    for person in people:
        if person.slug is None:
            continue
        path = PEOPLE_DIR / person.slug / ConfigFileName.OVERLAY
        if path.is_file():
            target = _canonical_path(path)
            targets[target] = person.slug
            document = _load_document(path)
            if document is not None and _PERSON_SLUG_FIELD in document:
                completed.append(target)
    return PersonClaimMigrationState(targets=targets, completed=completed)


def _complete_target(path: Path, slug: str) -> bool:
    try:
        with file_transaction(path) as transaction:
            document = _load_document_content(transaction.read_text())
            if document is None or document.get(_KIND_FIELD) != ConfigKind.PERSON.value:
                return False
            if _PERSON_SLUG_FIELD in document:
                return True
            updated_document = {**document, _PERSON_SLUG_FIELD: slug}
            transaction.replace_text(
                render_declared_config(path, ConfigKind.PERSON, updated_document, schema_root=path.parent.parent.parent)
            )
            return True
    except OSError:
        return False


def _load_document(path: Path) -> Mapping[str, object] | None:
    try:
        return _load_document_content(path.read_text(encoding=_UTF8))
    except (OSError, yaml.YAMLError):
        return None


def _load_document_content(content: str) -> Mapping[str, object] | None:
    document: object = yaml.safe_load(content) or {}
    return cast(Mapping[str, object], document) if isinstance(document, dict) else None


def _load_state() -> PersonClaimMigrationState | None:
    if not PERSON_CLAIM_MIGRATION_STATE_PATH.exists():
        return None
    try:
        raw_state: object = json.loads(PERSON_CLAIM_MIGRATION_STATE_PATH.read_text(encoding=_UTF8))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersonClaimMigrationError(_STATE_ERROR.format(path=PERSON_CLAIM_MIGRATION_STATE_PATH)) from exc
    if not isinstance(raw_state, dict):
        raise PersonClaimMigrationError(_STATE_ERROR.format(path=PERSON_CLAIM_MIGRATION_STATE_PATH))
    raw_targets = raw_state.get(_TARGETS_FIELD)
    raw_completed = raw_state.get(_COMPLETED_FIELD)
    if not isinstance(raw_targets, dict) or not isinstance(raw_completed, list):
        raise PersonClaimMigrationError(_STATE_ERROR.format(path=PERSON_CLAIM_MIGRATION_STATE_PATH))
    if not all(isinstance(path, str) and isinstance(slug, str) for path, slug in raw_targets.items()):
        raise PersonClaimMigrationError(_STATE_ERROR.format(path=PERSON_CLAIM_MIGRATION_STATE_PATH))
    if not all(isinstance(path, str) and path in raw_targets for path in raw_completed):
        raise PersonClaimMigrationError(_STATE_ERROR.format(path=PERSON_CLAIM_MIGRATION_STATE_PATH))
    return PersonClaimMigrationState(
        targets=cast(dict[str, str], raw_targets),
        completed=cast(list[str], raw_completed),
    )


def _write_state(state: PersonClaimMigrationState) -> None:
    PERSON_CLAIM_MIGRATION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = _temporary_name(PERSON_CLAIM_MIGRATION_STATE_PATH)
    temporary_path = PERSON_CLAIM_MIGRATION_STATE_PATH.with_name(temporary_name)
    try:
        with temporary_path.open(_WRITE_MODE, encoding=_UTF8) as handle:
            payload = PersonClaimMigrationPayload(targets=state.targets, completed=state.completed)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write(os.linesep)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, PERSON_CLAIM_MIGRATION_STATE_PATH)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def _temporary_name(path: Path) -> str:
    """Return a process-unique temporary filename beside one durable state file."""
    return _TEMPORARY_SEPARATOR.join((_TEMPORARY_PREFIX, path.name, str(os.getpid()), uuid4().hex, _TEMPORARY_SUFFIX))


def _is_complete(state: PersonClaimMigrationState) -> bool:
    return set(state.targets) <= set(state.completed)


def _canonical_path(path: Path) -> str:
    return str(path.expanduser().resolve())


@contextmanager
def _migration_guard() -> Iterator[None]:
    PERSON_CLAIM_MIGRATION_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PERSON_CLAIM_MIGRATION_LOCK_PATH.open(_WRITE_MODE, encoding=_UTF8) as lock_file:
        fcntl.flock(lock_file.fileno(), _LOCK_EXCLUSIVE)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
