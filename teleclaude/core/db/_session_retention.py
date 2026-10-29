"""Mixin: retention of session records beyond their running life."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from instrukt_ai_logging import get_logger
from sqlalchemy import ColumnElement, func
from sqlmodel import select

from teleclaude.constants import RUNTIME_RECORD_RETENTION_WINDOW
from teleclaude.core.runtime_events import publish_session_source_change
from teleclaude.events.schemas.system import RuntimeSessionChange

from .. import db_models
from ..models._adapter import ARCHIVE_SECTION, ArchiveStampField
from ..origins import InputOrigin
from ..session_status import SessionLifecycleStatus

logger = get_logger(__name__)

_SOFT_DELETE_MISSING_EVENT = "session.soft_delete.skipped_missing"
_SOFT_DELETED_EVENT = "session.soft_deleted"
_ARCHIVE_ADOPTED_EVENT = "session.archive.adopted"
_ARCHIVE_JSON_PATH = f"$.{ARCHIVE_SECTION}"
_ARCHIVE_SOURCE_JSON_PATH = f"$.{ARCHIVE_SECTION}.{ArchiveStampField.SOURCE_IDENTITY}"
_ARCHIVED_TRANSITION_REASON = "archived"
_EMPTY_TITLE = ""
_RUNTIME_RETENTION_PRUNED_EVENT = "runtime_retention.pruned"


def not_archive_record() -> ColumnElement[bool]:
    """Selection clause that keeps archive records out of runtime session selection."""
    return func.json_extract(db_models.Session.origin_metadata, _ARCHIVE_JSON_PATH).is_(None)


@dataclass(frozen=True)
class ArchiveSessionRecord:
    """Recorded facts about retained history that no session record claims.

    Only facts a retained mirror attribution recorded are carried; a fact the history lacks stays absent.
    ``session_id`` restores a pruned session under its original identity; absent, the history receives a new one.
    """

    source_identity: str
    computer_name: str
    session_id: str | None = None
    native_session_id: str | None = None
    native_log_file: str | None = None
    transcript_files: tuple[str, ...] = ()
    active_agent: str | None = None
    project_path: str | None = None
    subdir: str | None = None
    title: str | None = None
    principal: str | None = None
    human_email: str | None = None
    config_subject: str | None = None
    subject_owner: str | None = None
    started_at: datetime | None = None
    closed_at: datetime | None = None


class DbSessionRetentionMixin:
    """Soft deletion and archive records: a session record outlives its running life and its pruning."""

    async def prune_runtime_retention(self, now: datetime) -> None:
        """Prune the runtime state that outlived its retention window, one owner at a time.

        The retained sessions are read once; each owner removes its own expired rows by its own predicate.
        """
        cutoff = now - RUNTIME_RECORD_RETENTION_WINDOW
        cutoff_iso = cutoff.isoformat()
        retained_session_ids = await self._retained_session_ids(closed_since=cutoff)
        control_payloads, procedure_events = await self.prune_control_delivery(
            cutoff_iso=cutoff_iso, retained_session_ids=retained_session_ids
        )
        send_intents, receipts, generations, cursors = await self.prune_output_state(
            cutoff_iso=cutoff_iso, retained_session_ids=retained_session_ids
        )
        reminder_entries = await self.prune_reminder_entries(
            cutoff_iso=cutoff_iso, retained_session_ids=retained_session_ids
        )
        logger.debug(
            _RUNTIME_RETENTION_PRUNED_EVENT,
            control_payloads=control_payloads,
            procedure_events=procedure_events,
            send_intents=send_intents,
            receipts=receipts,
            generations=generations,
            cursors=cursors,
            reminder_entries=reminder_entries,
        )

    async def soft_delete_session(self, session_id: str) -> None:
        """Stamp a closed session as soft-deleted and tell observers it left navigation.

        The write is idempotent: a session that is already soft-deleted keeps its original deletion time.
        """
        async with self._session() as db_session:
            row = await db_session.get(db_models.Session, session_id)
            if row is None:
                logger.debug(_SOFT_DELETE_MISSING_EVENT, session_id=session_id)
                return
            if row.deleted_at is not None:
                return
            row.deleted_at = datetime.now(UTC)
            db_session.add(row)
            await db_session.commit()
        logger.debug(_SOFT_DELETED_EVENT, session_id=session_id)
        await publish_session_source_change(session_id, RuntimeSessionChange.CLOSED)

    async def adopt_archive_session(self, record: ArchiveSessionRecord) -> str:
        """Retain history as a closed, non-running session record and return its TeleClaude id.

        The record owns no runtime, launches nothing and emits no lifecycle event. Adoption is idempotent
        per source identity, and restoring under a given id never replaces a record that already holds it.
        """
        async with self._session() as db_session:
            if record.session_id is not None:
                existing_id = (
                    await db_session.exec(
                        select(db_models.Session.session_id).where(db_models.Session.session_id == record.session_id)
                    )
                ).first()
                if existing_id is not None:
                    return str(existing_id)
            else:
                archived_id = (
                    await db_session.exec(
                        select(db_models.Session.session_id).where(
                            func.json_extract(db_models.Session.origin_metadata, _ARCHIVE_SOURCE_JSON_PATH)
                            == record.source_identity
                        )
                    )
                ).first()
                if archived_id is not None:
                    return str(archived_id)
            session_id = record.session_id or str(uuid.uuid4())
            now = datetime.now(UTC)
            started_at = record.started_at or record.closed_at or now
            closed_at = record.closed_at or started_at
            stamp = {ARCHIVE_SECTION: {ArchiveStampField.SOURCE_IDENTITY.value: record.source_identity}}
            db_session.add(
                db_models.Session(
                    session_id=session_id,
                    computer_name=record.computer_name,
                    title=record.title or _EMPTY_TITLE,
                    last_input_origin=InputOrigin.TERMINAL.value,
                    origin_metadata=json.dumps(stamp),
                    created_at=started_at,
                    last_activity=closed_at,
                    closed_at=closed_at,
                    project_path=record.project_path,
                    subdir=record.subdir,
                    config_subject=record.config_subject,
                    subject_owner=record.subject_owner,
                    human_email=record.human_email,
                    principal=record.principal,
                    lifecycle_status=SessionLifecycleStatus.CLOSED.value,
                    lifecycle_transitioned_at=closed_at,
                    lifecycle_transition_reason=_ARCHIVED_TRANSITION_REASON,
                    active_agent=record.active_agent,
                    native_session_id=record.native_session_id,
                    native_log_file=record.native_log_file,
                    transcript_files=json.dumps(list(record.transcript_files)),
                )
            )
            await db_session.commit()
        logger.info(_ARCHIVE_ADOPTED_EVENT, session_id=session_id, source_identity=record.source_identity)
        return session_id
