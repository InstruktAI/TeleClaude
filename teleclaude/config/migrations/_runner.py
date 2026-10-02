"""Persist configuration migrations and report each document outcome."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping
from enum import StrEnum
from io import StringIO
from pathlib import Path
from typing import TypedDict, cast

from instrukt_ai_logging import get_logger
from ruamel.yaml.error import YAMLError

from teleclaude.config._yaml import round_trip_yaml
from teleclaude.config.declaration import render_declared_config
from teleclaude.config.migrations import _steps
from teleclaude.config.migrations._chain import (
    CURRENT_VERSION,
    Destination,
    DocumentNewerThanInstallation,
    MigrationTrigger,
    document_version,
    require_registry_subject,
    upcast,
)
from teleclaude.config.migrations._registry import registered_documents, resolve_read_subject
from teleclaude.config.migrations.v003_relocate_person_invite_token import DestinationConflict as InvitationConflict
from teleclaude.config.migrations.v004_relocate_legacy_discord_provider_ids import HandoffConflict
from teleclaude.config.migrations.v009_fold_trusted_directories import RegistryConflict
from teleclaude.config.schema import ConfigKind
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.file_transaction import file_transaction
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.paths import REPO_ROOT

_LOG_MIGRATION = "config_migration"
_LOG_RUN = "config_migration_run"
_DOCUMENT_KEY_ERROR = "Unable to identify configuration document"


class MigrationOutcome(StrEnum):
    """Closed result vocabulary for one configuration migration."""

    FAILED = "failed"
    CURRENT = "current"
    MIGRATED_UNCOMMITTED = "migrated_uncommitted"
    WRITTEN_UNTRACKED = "written_untracked"
    RESTORED_AFTER_REFUSED_COMMIT = "restored_after_refused_commit"
    MIGRATED_COMMITTED = "migrated_committed"
    UPCAST_IN_MEMORY = "upcast_in_memory"


class MigrationFailureReason(StrEnum):
    """Closed diagnostic vocabulary for a refused migration."""

    NOT_A_MAPPING = "not_a_mapping"
    NEWER_VERSION = "newer_version"
    INVALID_VERSION = "invalid_version"
    PARSE_ERROR = "parse_error"
    DESTINATION_CONFLICT = "destination_conflict"
    MIGRATION_ERROR = "migration_error"
    COMMIT_REFUSED = "commit_refused"


_NOT_A_MAPPING = MigrationFailureReason.NOT_A_MAPPING
_NEWER_VERSION = MigrationFailureReason.NEWER_VERSION
_INVALID_VERSION = MigrationFailureReason.INVALID_VERSION
_PARSE_ERROR = MigrationFailureReason.PARSE_ERROR
_DESTINATION_CONFLICT = MigrationFailureReason.DESTINATION_CONFLICT
_MIGRATION_ERROR = MigrationFailureReason.MIGRATION_ERROR
_COMMIT_REFUSED = MigrationFailureReason.COMMIT_REFUSED
_MIGRATION_SUBJECT = "chore(config): migrate {path} to configuration version {version}"
_COMMIT_DOCUMENT_PATH = "{commit}:{path}"
_TELEC_EXECUTABLE = "telec"
_TELEC_INVOCATION_CWD = "TELEC_INVOCATION_CWD"
_PROCESS_CWD = "PWD"
_TELEC_CODE_COMMIT_ARGS = ("code", "commit")
_TELEC_APPROVED_FLAG = "--approved"
_TELEC_ONLY_FLAG = "--only"
_TELEC_NOT_FOUND = "The canonical telec executable is unavailable"
_TELEC_COMMIT_REFUSED = "The canonical telec commit did not land the migration"
_WORKTREE_DIRECTORY = "trees"
_INTEGRATION_WORKTREE = "_integration"
_UTF8 = "utf-8"
_SCHEMA_VERSION = "schema_version"
_OVERLAY_KINDS = frozenset(
    {ConfigSubjectKind.GLOBAL, ConfigSubjectKind.PERSON, ConfigSubjectKind.COMPANY, ConfigSubjectKind.PROJECT}
)

logger = get_logger(__name__)


class MigrationRecord(TypedDict):
    """Privacy-safe outcome for one configuration document."""

    document_key: str
    subject_kind: str
    subject_source: str
    from_version: int
    to_version: int
    trigger: MigrationTrigger
    outcome: MigrationOutcome
    reason: MigrationFailureReason | None
    commit: str | None


class MigrationCommitRefused(RuntimeError):
    """The canonical sealed commit command refused or failed to land a migration."""


def carry_pending(
    stored_document: Mapping[str, object], subject: SubjectRef, *, delivered: Callable[[Destination], None]
) -> None:
    """Deliver each moved value that remains in a stored document, in step order."""
    require_registry_subject(subject)
    version = document_version(stored_document)
    if version > CURRENT_VERSION:
        raise DocumentNewerThanInstallation(
            f"Configuration document version {version} is newer than installation version {CURRENT_VERSION}"
        )
    for step in _steps.STEPS[version:]:
        destination = getattr(step, "MOVES", None)
        if destination is None or subject.kind not in step.KINDS:
            continue
        pending = cast(object | None, step.pending(stored_document, subject))
        if pending is None:
            continue
        step.deliver(pending, subject)
        delivered(cast(Destination, destination))


def upcast_for_read(
    path: Path,
    stored_document: Mapping[str, object],
    *,
    subject: SubjectRef | None = None,
) -> Mapping[str, object]:
    """Resolve a read subject, apply its in-memory steps and report the upcast."""
    from_version = document_version(stored_document)
    read_subject = subject if subject is not None else resolve_read_subject(path, stored_document)
    migrated = upcast(stored_document, read_subject)
    if from_version < CURRENT_VERSION and read_subject is not None:
        _record(
            _document_key(path),
            read_subject,
            from_version,
            CURRENT_VERSION,
            MigrationTrigger.READ,
            MigrationOutcome.UPCAST_IN_MEMORY,
            None,
            None,
        )
    return migrated


def migrate_document(path: Path, subject: SubjectRef, trigger: MigrationTrigger) -> MigrationRecord:
    """Persist one document's pending migrations and apply the trigger's commit rule."""
    require_registry_subject(subject)
    key = _document_key(path)
    repository, relative_path, tracked = _repository_state(path)
    with file_transaction(path) as transaction:
        original = transaction.read_text(encoding=_UTF8)
        clean_before = repository is not None and tracked and not _path_is_dirty(repository, relative_path)
        if trigger is not MigrationTrigger.WRITER:
            _retire(subject)
        try:
            document = _parse_document(original)
        except YAMLError:
            return _record(key, subject, 0, CURRENT_VERSION, trigger, MigrationOutcome.FAILED, _PARSE_ERROR, None)
        if not isinstance(document, Mapping) or (subject.kind.value == "computer" and not original.strip()):
            return _record(
                key,
                subject,
                _version_or_zero(document),
                CURRENT_VERSION,
                trigger,
                MigrationOutcome.FAILED,
                _NOT_A_MAPPING,
                None,
            )
        try:
            from_version = document_version(document)
        except ValueError:
            return _record(key, subject, 0, CURRENT_VERSION, trigger, MigrationOutcome.FAILED, _INVALID_VERSION, None)
        if from_version > CURRENT_VERSION:
            return _record(
                key, subject, from_version, CURRENT_VERSION, trigger, MigrationOutcome.FAILED, _NEWER_VERSION, None
            )
        if subject.kind.value == "computer" and not document:
            return _record(
                key, subject, from_version, CURRENT_VERSION, trigger, MigrationOutcome.FAILED, _NOT_A_MAPPING, None
            )
        delivered: list[Destination] = []
        try:
            carry_pending(document, subject, delivered=delivered.append)
            migrated = upcast(document, subject)
            if migrated == document:
                return _record(
                    key, subject, from_version, CURRENT_VERSION, trigger, MigrationOutcome.CURRENT, None, None
                )
            text = _render(migrated, subject)
            transaction.replace_text(text)
        except (InvitationConflict, HandoffConflict, RegistryConflict):
            return _record(
                key,
                subject,
                from_version,
                CURRENT_VERSION,
                trigger,
                MigrationOutcome.FAILED,
                _DESTINATION_CONFLICT,
                None,
            )
        except DocumentNewerThanInstallation:
            return _record(
                key, subject, from_version, CURRENT_VERSION, trigger, MigrationOutcome.FAILED, _NEWER_VERSION, None
            )
        except (OSError, ValueError, TypeError):
            return _record(
                key, subject, from_version, CURRENT_VERSION, trigger, MigrationOutcome.FAILED, _MIGRATION_ERROR, None
            )
        if trigger is MigrationTrigger.WRITER:
            return _record(
                key,
                subject,
                from_version,
                CURRENT_VERSION,
                trigger,
                MigrationOutcome.MIGRATED_UNCOMMITTED,
                None,
                None,
            )
        if repository is None or not tracked:
            return _record(
                key,
                subject,
                from_version,
                CURRENT_VERSION,
                trigger,
                MigrationOutcome.WRITTEN_UNTRACKED,
                None,
                None,
            )
        if not clean_before:
            return _record(
                key,
                subject,
                from_version,
                CURRENT_VERSION,
                trigger,
                MigrationOutcome.MIGRATED_UNCOMMITTED,
                None,
                None,
            )
        assert relative_path is not None
        try:
            message = _MIGRATION_SUBJECT.format(path=relative_path, version=CURRENT_VERSION)
            commit = _commit_migration_document(repository, relative_path, message, migrated)
        except (MigrationCommitRefused, GitCommandError, OSError):
            if transaction.read_text(encoding=_UTF8) != text:
                return _record(
                    key,
                    subject,
                    from_version,
                    CURRENT_VERSION,
                    trigger,
                    MigrationOutcome.MIGRATED_UNCOMMITTED,
                    None,
                    None,
                )
            transaction.replace_text(_committed_text(repository, relative_path))
            return _record(
                key,
                subject,
                from_version,
                CURRENT_VERSION,
                trigger,
                MigrationOutcome.RESTORED_AFTER_REFUSED_COMMIT,
                _COMMIT_REFUSED,
                None,
            )
        return _record(
            key,
            subject,
            from_version,
            CURRENT_VERSION,
            trigger,
            MigrationOutcome.MIGRATED_COMMITTED,
            None,
            commit,
        )


def migrate_registered(trigger: MigrationTrigger) -> tuple[MigrationRecord, ...]:
    """Migrate each registry-named document and return its structured record."""
    records: list[MigrationRecord] = []
    for path, subject in registered_documents(trigger):
        records.append(migrate_document(path, subject, trigger))
    _run_summary(trigger, records)
    return tuple(records)


def _retire(subject: SubjectRef) -> None:
    """Run every retirement effect owned by the matching subject kind."""
    for step in _steps.STEPS:
        retire = getattr(step, "retire", None)
        if retire is not None and subject.kind in step.KINDS:
            retire(subject)


def _parse_document(content: str) -> object:
    """Parse an empty file as an empty mapping, preserving round-trip YAML types."""
    return round_trip_yaml().load(content) if content else {}


def _render(document: Mapping[str, object], subject: SubjectRef) -> str:
    """Render one migrated mapping with comments and key order preserved."""
    if subject.kind in _OVERLAY_KINDS:
        return render_declared_config(ConfigKind(subject.kind.value), document)
    buffer = StringIO()
    round_trip_yaml().dump(document, buffer)
    return buffer.getvalue()


def _repository_state(path: Path) -> tuple[Repo | None, str | None, bool]:
    """Resolve the owning repository and whether one document is tracked."""
    try:
        repository = Repo(path.parent, search_parent_directories=True)
    except (InvalidGitRepositoryError, NoSuchPathError):
        return None, None, False
    root = Path(cast(str, repository.working_tree_dir)).resolve()
    relative = path.resolve().relative_to(root).as_posix()
    try:
        repository.git.ls_files("--error-unmatch", "--", relative)
    except GitCommandError:
        return repository, relative, False
    return repository, relative, True


def _commit_migration_document(
    repository: Repo,
    relative_path: str,
    message: str,
    expected_document: Mapping[str, object],
) -> str:
    """Commit one migration and prove its exact document is in the owning repository."""
    executable = REPO_ROOT / "bin" / _TELEC_EXECUTABLE
    if REPO_ROOT.parent.name == _WORKTREE_DIRECTORY and REPO_ROOT.name != _INTEGRATION_WORKTREE:
        installed_executable = shutil.which(_TELEC_EXECUTABLE)
        if installed_executable is not None:
            executable = Path(installed_executable)
    if not executable.is_file():
        raise FileNotFoundError(_TELEC_NOT_FOUND)
    working_root = Path(cast(str, repository.working_tree_dir)).resolve()
    previous_commit = repository.head.commit.hexsha
    environment = os.environ.copy()  # fmt: skip  # guard: direct-env-read - allowed: host environment forwarded to canonical CLI
    environment[_TELEC_INVOCATION_CWD] = str(working_root)
    environment[_PROCESS_CWD] = str(working_root)
    arguments = [
        str(executable),
        *_TELEC_CODE_COMMIT_ARGS,
        message,
        _TELEC_APPROVED_FLAG,
        _TELEC_ONLY_FLAG,
        relative_path,
    ]
    # The sealed CLI is the only commit API that adds required author, session, and human-involvement metadata.
    try:
        subprocess.run(arguments, cwd=working_root, env=environment, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        commit = _verified_migration_commit(repository, relative_path, previous_commit, expected_document)
        if commit is not None:
            return commit
        raise MigrationCommitRefused(_TELEC_COMMIT_REFUSED) from exc
    commit = _verified_migration_commit(repository, relative_path, previous_commit, expected_document)
    if commit is None:
        raise MigrationCommitRefused(_TELEC_COMMIT_REFUSED)
    return commit


def _verified_migration_commit(
    repository: Repo,
    relative_path: str,
    previous_commit: str,
    expected_document: Mapping[str, object],
) -> str | None:
    """Return a new commit only when it contains the clean migrated document."""
    current_commit = repository.head.commit.hexsha
    if current_commit == previous_commit:
        return None
    changed_path_commits = repository.git.log(
        "--format=%H",
        f"{previous_commit}..{current_commit}",
        "--",
        relative_path,
    ).splitlines()
    if not changed_path_commits:
        return None
    migration_commit = cast(str, changed_path_commits[0])
    changed_paths = set(repository.commit(migration_commit).stats.files)
    if changed_paths != {relative_path}:
        return None
    committed_document = _parse_document(
        repository.git.show(_COMMIT_DOCUMENT_PATH.format(commit=migration_commit, path=relative_path))
    )
    if not isinstance(committed_document, Mapping) or dict(committed_document) != dict(expected_document):
        return None
    current_document = _parse_document(
        repository.git.show(_COMMIT_DOCUMENT_PATH.format(commit=current_commit, path=relative_path))
    )
    if not isinstance(current_document, Mapping) or dict(current_document) != dict(expected_document):
        return None
    if _path_is_dirty(repository, relative_path):
        return None
    return migration_commit


def _path_is_dirty(repository: Repo, relative_path: str | None) -> bool:
    """Check worktree and index changes for the one tracked document."""
    if relative_path is None:
        return False
    return repository.is_dirty(path=relative_path, untracked_files=False)


def _committed_text(repository: Repo, relative_path: str) -> str:
    """Read the tracked document from HEAD after a commit hook refuses it."""
    return cast(str, repository.git.show(f"HEAD:{relative_path}"))


def _document_key(path: Path) -> str:
    """Hash a resolved document path for privacy-safe operational records."""
    try:
        resolved = str(path.expanduser().resolve()).encode(_UTF8)
    except OSError as exc:
        raise RuntimeError(_DOCUMENT_KEY_ERROR) from exc
    return hashlib.sha256(resolved).hexdigest()


def _version_or_zero(document: object) -> int:
    """Read a valid version where possible for a failed parse record."""
    if not isinstance(document, Mapping):
        return 0
    try:
        return document_version(document)
    except ValueError:
        return 0


def _record(
    document_key: str,
    subject: SubjectRef,
    from_version: int,
    to_version: int,
    trigger: MigrationTrigger,
    outcome: MigrationOutcome,
    reason: MigrationFailureReason | None,
    commit: str | None,
) -> MigrationRecord:
    """Emit and return the privacy-safe per-document migration record."""
    record: MigrationRecord = {
        "document_key": document_key,
        "subject_kind": subject.kind.value,
        "subject_source": subject.source.value,
        "from_version": from_version,
        "to_version": to_version,
        "trigger": trigger,
        "outcome": outcome,
        "reason": reason,
        "commit": commit,
    }
    logger.info(_LOG_MIGRATION, **record)
    return record


def _run_summary(trigger: MigrationTrigger, records: list[MigrationRecord]) -> None:
    """Emit counts for every migration outcome in this run."""
    outcomes = Counter(record["outcome"].value for record in records)
    logger.info(_LOG_RUN, trigger=trigger.value, counts=dict(outcomes))
