"""Bind accepted caller occurrences to native transcript entries without reading bodies."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from teleclaude.core.agents import AgentName
from teleclaude.core.conversation_messages import peer_segments_from_entry
from teleclaude.core.db import InboundQueueRow, NativeReference, TurnAuthoredPartInput, TurnReceiptEnvelopeInput, db
from teleclaude.core.identity import local_human_author
from teleclaude.core.inbound_types import GITHUB_ACTOR_ID_PREFIX, TurnPartKind
from teleclaude.core.injected_text import (
    InjectedEnvelopeCandidate,
    TranscriptEntryKind,
    caller_occurrence_key,
    is_peer_opening,
    scan_injected_envelopes,
)
from teleclaude.core.models import JsonDict, MessageAuthor, MessageAuthorKind
from teleclaude.utils.transcript import (
    extract_authored_user_text,
    native_entry_id,
)

if TYPE_CHECKING:
    from teleclaude.core.models import Session

_BINDING_ID_SEPARATOR = ":"
_GITHUB_UNKNOWN_DISPLAY = "GitHub user"


def binding_id_for_native_entry(session_id: str, entry_id: str) -> str:
    """Return the deterministic identifier for one session-local native entry."""
    return f"{session_id}{_BINDING_ID_SEPARATOR}{entry_id}"


def _caller_author(row: InboundQueueRow) -> MessageAuthor | None:
    kind = row["caller_author_kind"]
    display = row["caller_author_display"]
    session_id = row["caller_session_id"]
    if not isinstance(kind, str) or not isinstance(display, str) or not isinstance(session_id, str):
        return None
    return MessageAuthor(
        kind=MessageAuthorKind(kind),
        display=display,
        session_id=session_id,
        agent_runtime=row["caller_agent_runtime"] if isinstance(row["caller_agent_runtime"], str) else None,
        thinking_mode=row["caller_thinking_mode"] if isinstance(row["caller_thinking_mode"], str) else None,
        machine_role=row["caller_machine_role"] if isinstance(row["caller_machine_role"], str) else None,
    )


def _bound_parts(
    *,
    session: Session,
    text: str,
    envelope: InjectedEnvelopeCandidate,
    row: InboundQueueRow,
    caller_author: MessageAuthor,
    local_author: MessageAuthor,
) -> list[TurnAuthoredPartInput]:
    """Build ordered local, caller, and peer spans without consulting rendered bodies for identity."""
    all_envelopes = scan_injected_envelopes(text)
    caller_span = envelope.envelope_span
    parts: list[TurnAuthoredPartInput] = []
    cursor = 0
    for candidate in all_envelopes:
        if cursor < candidate.envelope_span[0]:
            parts.append(
                TurnAuthoredPartInput(
                    TurnPartKind.LOCAL, cursor, candidate.envelope_span[0], session.session_id, local_author
                )
            )
        if candidate.envelope_span == caller_span:
            parts.append(
                TurnAuthoredPartInput(
                    TurnPartKind.CALLER,
                    candidate.body_span[0],
                    candidate.body_span[1],
                    row["caller_session_id"],
                    caller_author,
                    row["caller_job_role"],
                )
            )
        elif is_peer_opening(candidate.opening):
            peer = peer_segments_from_entry(
                text[candidate.envelope_span[0] : candidate.envelope_span[1]], occurred_at=datetime.now(UTC)
            )[0]
            parts.append(
                TurnAuthoredPartInput(
                    TurnPartKind.PEER,
                    candidate.body_span[0],
                    candidate.body_span[1],
                    peer.original_source_session_id,
                    peer.author,
                    peer.author_job_role,
                )
            )
        cursor = candidate.envelope_span[1]
    if cursor < len(text):
        parts.append(TurnAuthoredPartInput(TurnPartKind.LOCAL, cursor, len(text), session.session_id, local_author))
    return sorted(parts, key=lambda part: part.span_start)


def _keyed_caller_envelopes(text: str) -> list[InjectedEnvelopeCandidate]:
    """Return the caller-identity envelopes in an entry that carry an occurrence key."""
    return [
        envelope
        for envelope in scan_injected_envelopes(text)
        if envelope.kind is TranscriptEntryKind.IDENTITY_CONTENT and caller_occurrence_key(envelope.opening) is not None
    ]


def _github_author(row: InboundQueueRow) -> tuple[MessageAuthor, str | None]:
    """Return the person who wrote a delivered GitHub comment and the login it was written under."""
    actor_id = row["actor_id"]
    login = actor_id.removeprefix(GITHUB_ACTOR_ID_PREFIX) if isinstance(actor_id, str) else None
    display = row["actor_name"] or login or _GITHUB_UNKNOWN_DISPLAY
    return MessageAuthor(kind=MessageAuthorKind.HUMAN, display=display), login


async def _bind_github_comment(
    session: Session,
    text: str,
    entry_id: str,
    agent_name: AgentName,
    pending: list[InboundQueueRow],
) -> None:
    """Bind a native entry to the delivered GitHub comment whose accepted text it carries.

    The accepted row is the authority for what the entry is: its stored content is the text the platform injected,
    so an entry whose authored text is exactly that content is the row's entry. Nothing is inferred from the text's shape.
    """
    if not session.native_session_id:
        return
    body = text.strip()
    row = next((candidate for candidate in pending if candidate["content"].strip() == body), None)
    occurrence_key = row["occurrence_key"] if row is not None else None
    if row is None or occurrence_key is None:
        return
    author, login = _github_author(row)
    part = TurnAuthoredPartInput(
        TurnPartKind.GITHUB,
        0,
        len(text),
        None,
        author,
        channel_login=login,
        channel_link=row["source_channel_id"],
    )
    created = await db.create_turn_binding(
        binding_id=binding_id_for_native_entry(session.session_id, entry_id),
        session_id=session.session_id,
        native_reference=NativeReference(agent_name.value, session.native_session_id, entry_id),
        parts=[part],
        receipt=TurnReceiptEnvelopeInput(
            inbound_queue_id=row["id"],
            envelope_index=0,
            occurrence_key=occurrence_key,
            envelope_span=(0, len(text)),
            body_span=(0, len(text)),
            authored_part_id=0,
        ),
    )
    if created:
        pending.remove(row)


async def bind_pending_native_turns(session: Session, entries: Sequence[JsonDict], agent_name: AgentName) -> None:
    """Persist keyed caller-envelope correlations before projection advances its watermark.

    Reads the transcript entries the projection pass already loaded.
    """
    if not session.native_session_id:
        return
    pending_rows = await db.get_unbound_delivered_caller_inbound(session.session_id)
    rows_by_key: dict[str, list[InboundQueueRow]] = {}
    for row in pending_rows:
        occurrence_key = row["occurrence_key"]
        if isinstance(occurrence_key, str):
            rows_by_key.setdefault(occurrence_key, []).append(row)
    pending_github_rows = await db.get_unbound_delivered_github_inbound(session.session_id)
    local_author = local_human_author(session)
    for entry in entries:
        text = extract_authored_user_text(entry, agent_name)
        if text is None:
            continue
        keyed_envelopes = _keyed_caller_envelopes(text)
        if not keyed_envelopes:
            if pending_github_rows:
                github_entry_id = native_entry_id(entry, agent_name)
                if github_entry_id is not None:
                    await _bind_github_comment(session, text, github_entry_id, agent_name, pending_github_rows)
            continue
        entry_id = native_entry_id(entry, agent_name)
        if entry_id is None:
            continue
        if len(keyed_envelopes) != 1:
            for envelope in keyed_envelopes:
                key = caller_occurrence_key(envelope.opening)
                if key is None:
                    continue
                for row in rows_by_key.get(key, []):
                    await db.mark_inbound_binding_conflict(
                        row["id"], NativeReference(agent_name.value, session.native_session_id, entry_id)
                    )
            continue
        envelope = keyed_envelopes[0]
        key = caller_occurrence_key(envelope.opening)
        if key is None:
            continue
        matching_rows = rows_by_key.get(key, [])
        if not matching_rows:
            continue
        if len(matching_rows) != 1:
            for duplicate_row in matching_rows:
                await db.mark_inbound_binding_conflict(
                    duplicate_row["id"], NativeReference(agent_name.value, session.native_session_id, entry_id)
                )
            continue
        row = matching_rows[0]
        author = _caller_author(row)
        if author is None:
            await db.mark_inbound_binding_conflict(
                row["id"], NativeReference(agent_name.value, session.native_session_id, entry_id)
            )
            continue
        parts = _bound_parts(
            session=session,
            text=text,
            envelope=envelope,
            row=row,
            caller_author=author,
            local_author=local_author,
        )
        caller_part_id = next(index for index, part in enumerate(parts) if part.part_kind is TurnPartKind.CALLER)
        created = await db.create_turn_binding(
            binding_id=binding_id_for_native_entry(session.session_id, entry_id),
            session_id=session.session_id,
            native_reference=NativeReference(agent_name.value, session.native_session_id, entry_id),
            parts=parts,
            receipt=TurnReceiptEnvelopeInput(
                inbound_queue_id=row["id"],
                envelope_index=0,
                occurrence_key=key,
                envelope_span=envelope.envelope_span,
                body_span=envelope.body_span,
                authored_part_id=caller_part_id,
            ),
        )
        if created:
            rows_by_key.pop(key, None)
