"""Reason notes: the stated reasons a ready item is tested against, recorded as structurally marked ledger notes.

``local/projects/teleclaude/spec/feature/workflow/item-lifecycle`` (Returning a ready item to preparation): each call that
states a reason writes it as a note attributed to the calling session; the machine finds reason notes by their kind, never
by their text. The same session repeating the same reason within the current stamp's cycle is a retry and adds nothing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from teleclaude.events.envelope import occurrence_id
from teleclaude.types.workflow_record import Act, LedgerEntry, NoteKind, WorkflowRecord

REASON_ACT: Final = "reason"
DIGEST_LENGTH: Final = 16
NO_ROLE: Final = ""


@dataclass(frozen=True)
class RecordedReason:
    """The outcome of recording one reason: the record, the note that carries it and whether this call wrote it."""

    record: WorkflowRecord
    note: LedgerEntry
    created: bool


def cycle_start_seq(record: WorkflowRecord) -> int:
    """The ledger position of the current stamp cycle: the last stamp act, or the start of the ledger for a carried stamp."""
    return max((entry.seq for entry in record.ledger if entry.act is Act.STAMP), default=0)


def reason_notes(record: WorkflowRecord) -> list[LedgerEntry]:
    """Every reason note of the current stamp cycle, in ledger order."""
    start = cycle_start_seq(record)
    return [entry for entry in record.ledger if entry.note_kind is NoteKind.REASON and entry.seq > start]


def context_notes(record: WorkflowRecord) -> list[LedgerEntry]:
    """Every note of the current stamp cycle, reasons and ordinary context notes alike, in ledger order."""
    start = cycle_start_seq(record)
    return [entry for entry in record.ledger if entry.act is Act.NOTE and entry.seq > start]


def record_reason(
    record: WorkflowRecord, *, project_root: str, item_id: str, session_id: str, role: str | None, text: str
) -> RecordedReason:
    """The record with the reason noted for the session, or unchanged with the earlier note when it is a retry."""
    for entry in reason_notes(record):
        if entry.session_id == session_id and entry.text == text:
            return RecordedReason(record=record, note=entry, created=False)
    digest = hashlib.sha256(text.encode()).hexdigest()[:DIGEST_LENGTH]
    start = cycle_start_seq(record)
    note = LedgerEntry(
        seq=len(record.ledger) + 1,
        act=Act.NOTE,
        key=occurrence_id(project_root, item_id, REASON_ACT, session_id, digest, str(start)),
        epoch=record.claim_epoch,
        at=datetime.now(UTC).isoformat(),
        role=role or NO_ROLE,
        session_id=session_id,
        bound=digest,
        text=text,
        note_kind=NoteKind.REASON,
    )
    updated = record.model_copy(deep=True)
    updated.ledger.append(note)
    return RecordedReason(record=updated, note=note, created=True)
