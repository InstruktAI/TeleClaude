"""Persistence for accepted inbound message metadata."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from teleclaude.core.db import InboundQueueRow, db
from teleclaude.core.injected_text import visible_input_update
from teleclaude.core.models import Session
from teleclaude.core.models._session import SessionField
from teleclaude.core.session_listeners import record_startup_work_accepted


async def record_accepted_input_metadata(
    *,
    session_id: str,
    origin: str,
    message_text: str,
    origin_metadata: Mapping[str, object] | None,
    visible_source_text: str | None,
    caller_session_id: str | None,
) -> None:
    """Persist accepted-input state, retaining origin on control-only turns."""
    visible_updates = visible_input_update(message_text, visible_source_text=visible_source_text)
    if visible_updates:
        visible_updates[SessionField.LAST_INPUT_ORIGIN.value] = origin
    await db.update_session(
        session_id,
        last_message_sent=message_text[:200],
        last_message_sent_at=datetime.now(UTC).isoformat(),
        **visible_updates,
    )
    if origin_metadata:
        await db.update_origin_metadata(session_id, origin, dict(origin_metadata))
    await record_startup_work_accepted(session_id, caller_session_id)


def _accepted_input_fields_match(session: Session, *, origin: str, message_text: str) -> bool:
    """Return whether session state already represents this accepted input."""
    return (
        session.last_message_sent == message_text[:200]
        and session.last_message_sent_at is not None
        and session.last_input_origin == origin
    )


def _origin_metadata_contains(
    session: Session,
    *,
    origin: str,
    origin_metadata: Mapping[str, object] | None,
) -> bool:
    """Return whether the session origin section already contains the queued metadata."""
    if not origin_metadata:
        return True
    section = session.get_origin_section(origin)
    return all(section.get(key) == value for key, value in origin_metadata.items())


async def ensure_inbound_acceptance_metadata(
    session: Session,
    row: InboundQueueRow,
    origin_metadata: Mapping[str, object] | None,
    visible_source_text: str | None,
) -> None:
    """Backfill accepted metadata for rows queued before enqueue-time writes existed."""
    session_id = row["session_id"]
    origin = row["origin"]
    message_text = row["content"]

    if not _accepted_input_fields_match(session, origin=origin, message_text=message_text):
        await record_accepted_input_metadata(
            session_id=session_id,
            origin=origin,
            message_text=message_text,
            origin_metadata=origin_metadata,
            visible_source_text=visible_source_text,
            caller_session_id=row.get("caller_session_id"),
        )
        return

    if not _origin_metadata_contains(session, origin=origin, origin_metadata=origin_metadata):
        await db.update_origin_metadata(session_id, origin, dict(origin_metadata or {}))
