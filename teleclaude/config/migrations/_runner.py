"""Persist configuration migrations and report each document outcome."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import cast

from instrukt_ai_logging import get_logger
from ruamel.yaml.error import YAMLError

from teleclaude.config._yaml import round_trip_yaml
from teleclaude.config.declaration import render_declared_config, render_machine_config
from teleclaude.config.errors import ConfigLoadError, describe_load_error
from teleclaude.config.field_constraints import FieldConstraintRefusal
from teleclaude.config.loader import load_project_config
from teleclaude.config.migrations import _steps
from teleclaude.config.migrations._carry import carry_pending
from teleclaude.config.migrations._chain import (
    Destination,
    DocumentNewerThanInstallation,
    MigrationTrigger,
    document_version,
    require_registry_subject,
    upcast,
)
from teleclaude.config.migrations._records import (
    MigrationFailureReason,
    MigrationOutcome,
    MigrationRecord,
    document_key,
    record_migration,
)
from teleclaude.config.migrations._registry import registered_documents
from teleclaude.config.migrations.daemon_reach import DaemonReach
from teleclaude.config.migrations.v003_relocate_person_invite_token import DestinationConflict as InvitationConflict
from teleclaude.config.migrations.v004_relocate_legacy_discord_provider_ids import HandoffConflict
from teleclaude.config.migrations.v009_fold_trusted_directories import RegistryConflict
from teleclaude.config.schema import CURRENT_SCHEMA_VERSION, ConfigKind
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.core.migration_signal import MigrationSignalError, MigrationStore, signal_migration_started
from teleclaude.deployment.release_checkout import is_release_installation
from teleclaude.file_transaction import FileTransaction, file_transaction
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.paths import REPO_ROOT, ConfigFileName

_LOG_RUN = "config_migration_run"


_NOT_A_MAPPING = MigrationFailureReason.NOT_A_MAPPING
_NEWER_VERSION = MigrationFailureReason.NEWER_VERSION
_INVALID_VERSION = MigrationFailureReason.INVALID_VERSION
_PARSE_ERROR = MigrationFailureReason.PARSE_ERROR
_DESTINATION_CONFLICT = MigrationFailureReason.DESTINATION_CONFLICT
_MIGRATION_ERROR = MigrationFailureReason.MIGRATION_ERROR
_COMMIT_REFUSED = MigrationFailureReason.COMMIT_REFUSED
_FIELD_CONSTRAINT_REFUSED = MigrationFailureReason.FIELD_CONSTRAINT_REFUSED
_READ_VALIDATION_REFUSED = MigrationFailureReason.READ_VALIDATION_REFUSED
_WITHHELD_UNREADABLE_DIAGNOSTIC = "{reach}; the stored version could not be read ({detail})"
_MIGRATION_SUBJECT = "chore(config): migrate {path} to configuration version {version}"
_COMMIT_DOCUMENT_PATH = "{commit}:{path}"
_HEAD_REFERENCE = "HEAD"
_TELEC_EXECUTABLE = "telec"
_TELEC_INVOCATION_CWD = "TELEC_INVOCATION_CWD"
_PROCESS_CWD = "PWD"
_TELEC_REPO_COMMIT_ARGS = ("repo", "commit")
_TELEC_APPROVED_FLAG = "--approved"
_TELEC_ONLY_FLAG = "--only"
_TELEC_NOT_FOUND = "The canonical telec executable is unavailable"
_TELEC_COMMIT_REFUSED = "The canonical telec commit did not land the migration"
_TELEC_COMMIT_REFUSED_WITH_OUTPUT = "{refusal} (exit {exit_code}): {output}"
# Bound the refusal output carried into a migration record to its most recent part.
_REFUSAL_OUTPUT_TAIL_CHARS = 2000
_WORKTREE_DIRECTORY = "trees"
_INTEGRATION_WORKTREE = "_integration"
_UTF8 = "utf-8"
_SCHEMA_VERSION = "schema_version"
_OVERLAY_KINDS = frozenset(
    {ConfigSubjectKind.GLOBAL, ConfigSubjectKind.PERSON, ConfigSubjectKind.COMPANY, ConfigSubjectKind.PROJECT}
)

logger = get_logger(__name__)


class MigrationCommitRefused(RuntimeError):
    """The canonical sealed commit command refused or failed to land a migration."""


def migrate_document(path: Path, subject: SubjectRef, trigger: MigrationTrigger) -> MigrationRecord:
    """Persist one document's pending migrations and apply the trigger's commit rule."""
    require_registry_subject(subject)
    key = document_key(path)
    repository, relative_path, tracked = _repository_state(path)
    with file_transaction(path) as transaction:
        original = transaction.read_text(encoding=_UTF8)
        clean_before = repository is not None and tracked and not _path_is_dirty(repository, relative_path)
        retained = trigger is not MigrationTrigger.WRITER and _is_installed_release_declaration(path, subject)
        if trigger is not MigrationTrigger.WRITER and not retained:
            try:
                _retire(subject)
            except MigrationSignalError:
                return record_migration(
                    key, subject, 0, CURRENT_SCHEMA_VERSION, trigger, MigrationOutcome.FAILED, _MIGRATION_ERROR, None
                )
        try:
            document = _parse_document(original)
        except YAMLError:
            return record_migration(
                key, subject, 0, CURRENT_SCHEMA_VERSION, trigger, MigrationOutcome.FAILED, _PARSE_ERROR, None
            )
        if not isinstance(document, Mapping) or (subject.kind.value == "computer" and not original.strip()):
            return record_migration(
                key,
                subject,
                _version_or_zero(document),
                CURRENT_SCHEMA_VERSION,
                trigger,
                MigrationOutcome.FAILED,
                _NOT_A_MAPPING,
                None,
            )
        try:
            from_version = document_version(document)
        except ValueError:
            return record_migration(
                key, subject, 0, CURRENT_SCHEMA_VERSION, trigger, MigrationOutcome.FAILED, _INVALID_VERSION, None
            )
        if from_version > CURRENT_SCHEMA_VERSION:
            return record_migration(
                key,
                subject,
                from_version,
                CURRENT_SCHEMA_VERSION,
                trigger,
                MigrationOutcome.FAILED,
                _NEWER_VERSION,
                None,
            )
        if subject.kind.value == "computer" and not document:
            return record_migration(
                key,
                subject,
                from_version,
                CURRENT_SCHEMA_VERSION,
                trigger,
                MigrationOutcome.FAILED,
                _NOT_A_MAPPING,
                None,
            )
        delivered: list[Destination] = []
        try:
            if not retained:
                _signal_and_carry_pending(document, subject, from_version, delivered.append)
            migrated = upcast(document, subject)
            if retained:
                outcome = _retained_outcome(path, document, migrated)
                return record_migration(
                    key, subject, from_version, CURRENT_SCHEMA_VERSION, trigger, outcome, None, None
                )
            if migrated == document:
                return record_migration(
                    key, subject, from_version, CURRENT_SCHEMA_VERSION, trigger, MigrationOutcome.CURRENT, None, None
                )
            text = _render(migrated, subject)
            transaction.replace_text(text)
        except (InvitationConflict, HandoffConflict, RegistryConflict):
            return record_migration(
                key,
                subject,
                from_version,
                CURRENT_SCHEMA_VERSION,
                trigger,
                MigrationOutcome.FAILED,
                _DESTINATION_CONFLICT,
                None,
            )
        except DocumentNewerThanInstallation:
            return record_migration(
                key,
                subject,
                from_version,
                CURRENT_SCHEMA_VERSION,
                trigger,
                MigrationOutcome.FAILED,
                _NEWER_VERSION,
                None,
            )
        except FieldConstraintRefusal as refusal:
            return record_migration(
                key,
                subject,
                from_version,
                CURRENT_SCHEMA_VERSION,
                trigger,
                MigrationOutcome.FAILED,
                _FIELD_CONSTRAINT_REFUSED,
                None,
                diagnostic=str(refusal),
            )
        except ConfigLoadError as refusal:
            return record_migration(
                key,
                subject,
                from_version,
                CURRENT_SCHEMA_VERSION,
                trigger,
                MigrationOutcome.FAILED,
                _READ_VALIDATION_REFUSED,
                None,
                diagnostic=describe_load_error(refusal),
            )
        except (OSError, ValueError, TypeError, MigrationSignalError):
            return record_migration(
                key,
                subject,
                from_version,
                CURRENT_SCHEMA_VERSION,
                trigger,
                MigrationOutcome.FAILED,
                _MIGRATION_ERROR,
                None,
            )
        if trigger is MigrationTrigger.WRITER:
            return record_migration(
                key,
                subject,
                from_version,
                CURRENT_SCHEMA_VERSION,
                trigger,
                MigrationOutcome.MIGRATED_UNCOMMITTED,
                None,
                None,
            )
        if repository is None or not tracked:
            return record_migration(
                key,
                subject,
                from_version,
                CURRENT_SCHEMA_VERSION,
                trigger,
                MigrationOutcome.WRITTEN_UNTRACKED,
                None,
                None,
            )
        if not clean_before:
            return record_migration(
                key,
                subject,
                from_version,
                CURRENT_SCHEMA_VERSION,
                trigger,
                MigrationOutcome.MIGRATED_UNCOMMITTED,
                None,
                None,
            )
        assert relative_path is not None
        return _commit_migrated_document(
            _CommitRequest(repository, relative_path, migrated, text, key, subject, from_version, trigger),
            transaction,
        )


@dataclass(frozen=True)
class _CommitRequest:
    """What landing one migrated document needs: where it lives, what it became, and how to record the outcome."""

    repository: Repo
    relative_path: str
    migrated: Mapping[str, object]
    text: str
    key: str
    subject: SubjectRef
    from_version: int
    trigger: MigrationTrigger


def _commit_migrated_document(request: _CommitRequest, transaction: FileTransaction) -> MigrationRecord:
    """Land the migrated document through the sealed commit, restoring it when the commit is refused."""
    try:
        message = _MIGRATION_SUBJECT.format(path=request.relative_path, version=CURRENT_SCHEMA_VERSION)
        commit = _commit_migration_document(request.repository, request.relative_path, message, request.migrated)
    except (MigrationCommitRefused, GitCommandError, OSError) as refusal:
        if transaction.read_text(encoding=_UTF8) != request.text:
            return record_migration(
                request.key,
                request.subject,
                request.from_version,
                CURRENT_SCHEMA_VERSION,
                request.trigger,
                MigrationOutcome.MIGRATED_UNCOMMITTED,
                _COMMIT_REFUSED,
                None,
                diagnostic=str(refusal),
            )
        transaction.replace_text(_committed_text(request.repository, request.relative_path))
        return record_migration(
            request.key,
            request.subject,
            request.from_version,
            CURRENT_SCHEMA_VERSION,
            request.trigger,
            MigrationOutcome.RESTORED_AFTER_REFUSED_COMMIT,
            _COMMIT_REFUSED,
            None,
            diagnostic=str(refusal),
        )
    return record_migration(
        request.key,
        request.subject,
        request.from_version,
        CURRENT_SCHEMA_VERSION,
        request.trigger,
        MigrationOutcome.MIGRATED_COMMITTED,
        None,
        commit,
    )


def _signal_and_carry_pending(
    document: Mapping[str, object], subject: SubjectRef, from_version: int, delivered: Callable[[Destination], None]
) -> None:
    """Signal that a migration is starting when the document is behind, then deliver its pending moves."""
    if from_version < CURRENT_SCHEMA_VERSION:
        signal_migration_started(MigrationStore.CONFIGURATION)
    carry_pending(document, subject, delivered=delivered)


def _is_installed_release_declaration(path: Path, subject: SubjectRef) -> bool:
    """Whether the document is the project declaration of a release of the installation.

    That declaration is part of the selected release source: it is evaluated and validated in memory,
    like any read, and a migration run never retires state from it, carries values out of it,
    rewrites it or commits it. Every other document keeps the persisting contract.
    """
    return (
        subject.kind is ConfigSubjectKind.PROJECT
        and path.name == ConfigFileName.OVERLAY
        and is_release_installation(path.resolve().parent)
    )


def _retained_outcome(path: Path, document: Mapping[str, object], migrated: Mapping[str, object]) -> MigrationOutcome:
    """Evaluate the retained declaration as any read does; only a document that loads is current or adapted in memory.

    Ordinary project loading judges the stored declaration (version adaptation, secret references,
    reference expansion, the full schema and its relationships, and home ownership), so a declaration
    the daemon would refuse is never reported as evaluated. Nothing is written.
    """
    load_project_config(path)
    return MigrationOutcome.CURRENT if migrated == document else MigrationOutcome.UPCAST_IN_MEMORY


def migrate_registered(trigger: MigrationTrigger, daemon_reach: DaemonReach) -> tuple[MigrationRecord, ...]:
    """Migrate each registry-named document and return its structured record.

    A run never stores a document at a version the running daemon cannot read. While the daemon's reach
    withholds the run, nothing is stored and no retirement runs; the installed release declaration, which a
    run only evaluates, is still evaluated, and every other covered document is recorded as withheld.
    """
    withheld = daemon_reach.withholds(CURRENT_SCHEMA_VERSION)
    records: list[MigrationRecord] = []
    for path, subject in registered_documents(trigger):
        if withheld and not _is_installed_release_declaration(path, subject):
            records.append(_withhold_document(path, subject, trigger, daemon_reach))
        else:
            records.append(migrate_document(path, subject, trigger))
    _run_summary(trigger, records)
    return tuple(records)


def _withhold_document(
    path: Path, subject: SubjectRef, trigger: MigrationTrigger, daemon_reach: DaemonReach
) -> MigrationRecord:
    """Record one document as left at its stored version, naming the daemon's reach and the current version.

    The record carries the stored version when it can be read; otherwise the version is absent and the reason
    and diagnostic say why it could not be read, without judging the document.
    """
    stored = _read_stored_version(path)
    diagnostic = daemon_reach.describe(CURRENT_SCHEMA_VERSION)
    if stored.detail is not None:
        diagnostic = _WITHHELD_UNREADABLE_DIAGNOSTIC.format(reach=diagnostic, detail=stored.detail)
    return record_migration(
        document_key(path),
        subject,
        stored.version,
        CURRENT_SCHEMA_VERSION,
        trigger,
        MigrationOutcome.WITHHELD,
        stored.reason,
        None,
        diagnostic=diagnostic,
    )


@dataclass(frozen=True)
class _StoredVersion:
    """A document's stored version, or why it could not be read."""

    version: int | None = None
    reason: MigrationFailureReason | None = None
    detail: str | None = None


def _read_stored_version(path: Path) -> _StoredVersion:
    """Read a document's stored version without judging the document beyond reading it."""
    try:
        document = _parse_document(path.read_text(encoding=_UTF8))
    except (OSError, UnicodeDecodeError) as error:
        return _StoredVersion(reason=_MIGRATION_ERROR, detail=type(error).__name__)
    except YAMLError as error:
        return _StoredVersion(reason=_PARSE_ERROR, detail=type(error).__name__)
    if not isinstance(document, Mapping):
        return _StoredVersion(reason=_NOT_A_MAPPING)
    try:
        return _StoredVersion(version=document_version(document))
    except ValueError:
        return _StoredVersion(reason=_INVALID_VERSION)


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
    if subject.kind is ConfigSubjectKind.COMPUTER:
        return render_machine_config(document)
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
        *_TELEC_REPO_COMMIT_ARGS,
        message,
        _TELEC_APPROVED_FLAG,
        _TELEC_ONLY_FLAG,
        relative_path,
    ]
    # The sealed CLI is the only commit API that adds required author, session, and human-involvement metadata.
    completed = subprocess.run(
        arguments, cwd=working_root, env=environment, capture_output=True, text=True, check=False
    )
    commit = _verified_migration_commit(repository, relative_path, previous_commit, expected_document)
    if commit is None:
        raise MigrationCommitRefused(_refusal_with_output(completed))
    return commit


def _refusal_with_output(completed: subprocess.CompletedProcess[str]) -> str:
    """Describe a migration commit that did not land with the tail of the command's own output."""
    output = (completed.stdout + completed.stderr).strip()
    return _TELEC_COMMIT_REFUSED_WITH_OUTPUT.format(
        refusal=_TELEC_COMMIT_REFUSED, exit_code=completed.returncode, output=output[-_REFUSAL_OUTPUT_TAIL_CHARS:]
    )


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
    return cast(
        str,
        repository.git.show(
            _COMMIT_DOCUMENT_PATH.format(commit=_HEAD_REFERENCE, path=relative_path), strip_newline_in_stdout=False
        ),
    )


def _version_or_zero(document: object) -> int:
    """Read a valid version where possible for a failed parse record."""
    if not isinstance(document, Mapping):
        return 0
    try:
        return document_version(document)
    except ValueError:
        return 0


def _run_summary(trigger: MigrationTrigger, records: list[MigrationRecord]) -> None:
    """Emit counts for every migration outcome in this run."""
    outcomes = Counter(record["outcome"].value for record in records)
    logger.info(_LOG_RUN, trigger=trigger.value, counts=dict(outcomes))
