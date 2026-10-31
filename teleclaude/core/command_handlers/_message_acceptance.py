"""Persistence for accepted inbound message metadata."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from instrukt_ai_logging import get_logger

from teleclaude.core.db import InboundQueueRow, db
from teleclaude.core.inbound_queue import DeliveryTerminalCause
from teleclaude.core.injected_text import TranscriptEntryKind, visible_input_update, wake_occurrence_key
from teleclaude.core.models import Session
from teleclaude.core.models._session import SessionField
from teleclaude.core.session_listeners import record_startup_work_accepted
from teleclaude.core.session_status import is_session_terminal

logger = get_logger(__name__)
_ACCEPTANCE_EVIDENCE_WRITE_FAILED_EVENT = "inbound_acceptance_evidence_write_failed"
_UNDELIVERED_WAKE_SETTLED_EVENT = "undelivered_wake_settled"
_UNDELIVERED_WAKE_SETTLEMENT_FAILED_EVENT = "undelivered_wake_settlement_failed"


def is_canonical_wake(row: InboundQueueRow) -> bool:
    """Return whether the row's whole content is a canonical wake opening."""
    return (
        TranscriptEntryKind(row["text_kind"]) is TranscriptEntryKind.PLATFORM_CONTROL
        and wake_occurrence_key(row["content"]) is not None
    )


async def record_accepted_input_metadata(
    *,
    session_id: str,
    origin: str,
    message_text: str,
    origin_metadata: Mapping[str, object] | None,
    visible_source_text: str | None,
    caller_session_id: str | None,
) -> datetime:
    """Persist accepted-input state, retaining origin on control-only turns.

    Returns the instant written as the session's last accepted input, so the accepting caller can record which
    instant its acceptance used.
    """
    visible_updates = visible_input_update(message_text, visible_source_text=visible_source_text)
    if visible_updates:
        visible_updates[SessionField.LAST_INPUT_ORIGIN.value] = origin
    accepted_at = datetime.now(UTC)
    await db.update_session(
        session_id,
        last_message_sent=message_text[:200],
        last_message_sent_at=accepted_at.isoformat(),
        **visible_updates,
    )
    if origin_metadata:
        await db.update_origin_metadata(session_id, origin, dict(origin_metadata))
    await record_startup_work_accepted(session_id, caller_session_id)
    return accepted_at


async def record_acceptance_evidence(
    *,
    session_id: str,
    row_id: int,
    accepted_at: datetime,
    runtime_turn_id: str | None,
) -> None:
    """Record the instant an acceptance wrote and the turn identity its wake gate read, never raising.

    A worker can end the row undelivered before this evidence exists; its terminal settlement then found
    nothing to settle with. The row is therefore read again after the write, and a row already expired is
    settled here. Together with the terminal side reading the evidence after the row's terminal status is
    committed, whichever side finishes second sees both writes. A failure leaves the row without evidence, or
    unsettled, and never interrupts the post-insert callback, so the delivery worker still starts.
    """
    try:
        await db.record_inbound_acceptance_evidence(
            row_id,
            accepted_input_at=accepted_at,
            runtime_turn_id=runtime_turn_id,
        )
        row = await db.get_inbound_row(row_id)
        if row is not None and row["status"] == "expired":
            await settle_undelivered_wake(row)
    except Exception as exc:
        logger.warning(
            _ACCEPTANCE_EVIDENCE_WRITE_FAILED_EVENT,
            session_id=session_id,
            inbound_row_id=row_id,
            error=str(exc),
        )


async def settle_undelivered_wake(row: InboundQueueRow, cause: DeliveryTerminalCause | None = None) -> None:
    """Retire the acceptance of a control wake that ended undelivered, when nothing newer was recorded.

    The wake's acceptance stamped the session's input clock, and no turn followed, so the session keeps
    reading as running and every later control payload waits for a wake that is never sent. The session is
    given an idle boundary only while its input clock is no later than the wake's own acceptance instant and
    its runtime turn identity is absent or the one the wake saw; the check is part of the write. Newer input
    or a native turn leaves the session untouched. The wake itself is not repeated here: the next handoff,
    restore continuation or idle boundary wakes the session once the stale clock no longer suppresses it.

    The acceptance evidence is read fresh from the store, because the worker's row snapshot may predate it.
    A row without evidence is not settled. ``cause`` is for the log only: the acceptance side does not know
    which terminal path the worker took. Failures are logged and contained.
    """
    if not is_canonical_wake(row):
        return
    try:
        evidence = await db.get_inbound_acceptance_evidence(row["id"])
        if evidence is None:
            return
        session = await db.get_session(row["session_id"])
        if session is None or is_session_terminal(
            lifecycle_status=session.lifecycle_status, closed_at=session.closed_at
        ):
            return
        settled = await db.update_session_if_acceptance_unchanged(
            row["session_id"],
            accepted_input_at=evidence.accepted_input_at,
            accepted_runtime_turn_id=evidence.runtime_turn_id,
            last_agent_idle_at=datetime.now(UTC),
        )
    except Exception as exc:
        logger.warning(
            _UNDELIVERED_WAKE_SETTLEMENT_FAILED_EVENT,
            session_id=row["session_id"],
            inbound_row_id=row["id"],
            cause=cause.value if cause is not None else None,
            error=str(exc),
        )
        return
    if settled is not None:
        logger.info(
            _UNDELIVERED_WAKE_SETTLED_EVENT,
            session_id=row["session_id"],
            inbound_row_id=row["id"],
            cause=cause.value if cause is not None else None,
        )


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
    """Backfill accepted metadata for rows queued before enqueue-time writes existed.

    A canonical wake is exempt: the rewrite would only restamp its preview and the session clock, and the clock
    must stay the wake's acceptance instant so that instant bounds anything recorded after the wake.
    """
    if is_canonical_wake(row):
        return
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
