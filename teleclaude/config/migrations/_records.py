"""The privacy-safe record of one configuration document's migration outcome."""

from __future__ import annotations

import hashlib
import logging
from enum import StrEnum
from pathlib import Path
from typing import TypedDict

from instrukt_ai_logging import TRACE, get_logger

from teleclaude.config.migrations._chain import MigrationTrigger
from teleclaude.config_subjects import SubjectRef

_LOG_MIGRATION = "config_migration"
_DOCUMENT_KEY_ERROR = "Unable to identify configuration document"
_UTF8 = "utf-8"

logger = get_logger(__name__)


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
    FIELD_CONSTRAINT_REFUSED = "field_constraint_refused"


# A migration run whose document did not land committed is an anomaly, not routine progress.
# A read-time adaptation fires per configuration read, so it sits below the production level.
_OUTCOME_LOG_LEVELS: dict[MigrationOutcome, int] = {
    MigrationOutcome.FAILED: logging.ERROR,
    MigrationOutcome.RESTORED_AFTER_REFUSED_COMMIT: logging.WARNING,
    MigrationOutcome.MIGRATED_UNCOMMITTED: logging.WARNING,
    MigrationOutcome.WRITTEN_UNTRACKED: logging.INFO,
    MigrationOutcome.MIGRATED_COMMITTED: logging.INFO,
    MigrationOutcome.CURRENT: logging.INFO,
    MigrationOutcome.UPCAST_IN_MEMORY: TRACE,
}
# A writer migrates in place and commits the document with its own change, so leaving it
# uncommitted is that trigger's expected outcome.
_EXPECTED_UNCOMMITTED_TRIGGERS = frozenset({MigrationTrigger.WRITER})


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
    diagnostic: str | None


def document_key(path: Path) -> str:
    """Hash a resolved document path for privacy-safe operational records."""
    try:
        resolved = str(path.expanduser().resolve()).encode(_UTF8)
    except OSError as exc:
        raise RuntimeError(_DOCUMENT_KEY_ERROR) from exc
    return hashlib.sha256(resolved).hexdigest()


def record_migration(
    document_key: str,
    subject: SubjectRef,
    from_version: int,
    to_version: int,
    trigger: MigrationTrigger,
    outcome: MigrationOutcome,
    reason: MigrationFailureReason | None,
    commit: str | None,
    diagnostic: str | None = None,
) -> MigrationRecord:
    """Emit and return the privacy-safe per-document migration record.

    ``diagnostic`` carries a refusal's schema-owned text or a refused commit command's output.
    """
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
        "diagnostic": diagnostic,
    }
    logger.log(_log_level(outcome, trigger), _LOG_MIGRATION, **record)
    return record


def _log_level(outcome: MigrationOutcome, trigger: MigrationTrigger) -> int:
    """Return the level a migration record is logged at for its outcome and trigger."""
    if outcome is MigrationOutcome.MIGRATED_UNCOMMITTED and trigger in _EXPECTED_UNCOMMITTED_TRIGGERS:
        return logging.INFO
    return _OUTCOME_LOG_LEVELS[outcome]
