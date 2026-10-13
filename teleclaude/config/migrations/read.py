"""Bring a stored configuration document to the current shape in memory, for reading only.

Nothing here writes or commits: the persisting migration run lives in ``_runner``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from teleclaude.config.migrations._chain import MigrationTrigger, document_version, upcast
from teleclaude.config.migrations._records import MigrationOutcome, document_key, record_migration
from teleclaude.config.migrations._registry import resolve_read_subject
from teleclaude.config.schema import CURRENT_SCHEMA_VERSION
from teleclaude.config_subjects import SubjectRef


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
    if from_version < CURRENT_SCHEMA_VERSION and read_subject is not None:
        record_migration(
            document_key(path),
            read_subject,
            from_version,
            CURRENT_SCHEMA_VERSION,
            MigrationTrigger.READ,
            MigrationOutcome.UPCAST_IN_MEMORY,
            None,
            None,
        )
    return migrated
