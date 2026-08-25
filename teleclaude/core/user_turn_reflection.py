"""Per-segment Discord reflection of one accepted user turn.

A submitted prompt may interleave human-typed text with platform-delivered
envelopes (peer segments, caller-identity messages, reminders, control
markers). Reflection delivers each part under its real authorship: ordinary
text as the session's human, identity segments as their originating caller,
and platform-owned segments not at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.conversation_messages import (
    MalformedPeerSegmentError,
    is_conversation_bridge_message,
    parse_peer_segments,
)
from teleclaude.core.db import db
from teleclaude.core.db._rows import InboundQueueRow
from teleclaude.core.identity import resolve_discord_author_alias
from teleclaude.core.injected_text import TranscriptCutSegment, TranscriptEntryKind, cut_transcript_entry
from teleclaude.core.models import MessageAuthor, MessageAuthorKind

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_PEER_REFLECTION_TRANSPORT_FAILURE_EVENT = "peer_reflection_transport_failure"
_PEER_REFLECTION_DISPATCHED_EVENT = "peer_reflection_dispatched"
_PEER_REFLECTION_SENT_OUTCOME = "sent"
_PEER_REFLECTION_FAILED_OUTCOME = "failed"
_PEER_REFLECTION_TRANSPORT_FAILURE_REASON = "transport_failure"
_PEER_REFLECTION_ALIAS_KIND = "peer"
_USER_INPUT_REFLECTION_SKIPPED_EVENT = "polling_user_input_reflection_skipped"
_IDENTITY_SEGMENT_UNPARSED_EVENT = "user_reflection_identity_segment_unparsed"
_PEER_REFLECTION_OMITTED_EVENT = "peer_reflection_omitted"
_ORPHANED_CLAIM_REASON = "claim_orphaned"
_REFLECTION_CLAIM_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class TurnReflectionResult:
    """Aggregated delivery facts for one reflected user turn."""

    platform_message_ids: tuple[str, ...]
    reflectable: bool
    failed: bool


# Disposition default when the Discord reflection lane is not engaged at all
# (origin already visible there, or the adapter is absent).
SKIPPED_TURN_REFLECTION = TurnReflectionResult((), True, False)


@dataclass(frozen=True)
class _IdentitySegmentPresentation:
    """Resolved Discord presentation for one injected identity segment."""

    actor_name: str
    actor_avatar_url: str | None
    body: str
    caller_session_id: str | None
    inbound_row_id: int | None = None


async def _resolve_identity_segment_presentation(
    session: Session,
    segment: TranscriptCutSegment,
    user_text: str,
    delivered_after: datetime | None,
) -> _IdentitySegmentPresentation | None:
    """Resolve one identity segment to its caller's presentation, or None."""
    opening = segment.opening or ""
    if is_conversation_bridge_message(opening):
        try:
            parsed = parse_peer_segments(segment.text)
        except MalformedPeerSegmentError:
            return None
        peer = parsed[0]
        actor_name, actor_avatar_url = resolve_discord_author_alias(
            peer.author,
            owning_session_id=session.session_id,
            job_role=peer.author_job_role,
        )
        return _IdentitySegmentPresentation(
            actor_name=actor_name,
            actor_avatar_url=actor_avatar_url,
            body=peer.body,
            caller_session_id=peer.original_source_session_id,
        )
    row = await _delivered_caller_row_for_segment(session, segment, delivered_after)
    if row is None:
        return None
    author = _caller_author_from_row(row)
    if author is None:
        return None
    body_start, body_end = segment.body_span if segment.body_span is not None else (0, 0)
    actor_name, actor_avatar_url = resolve_discord_author_alias(
        author,
        owning_session_id=session.session_id,
        job_role=row["caller_job_role"],
    )
    return _IdentitySegmentPresentation(
        actor_name=actor_name,
        actor_avatar_url=actor_avatar_url,
        body=user_text[body_start:body_end].strip(),
        caller_session_id=row["caller_session_id"],
        inbound_row_id=row["id"],
    )


async def _delivered_caller_row_for_segment(
    session: Session,
    segment: TranscriptCutSegment,
    delivered_after: datetime | None,
) -> InboundQueueRow | None:
    """Match one identity segment to the durable accepted row that delivered it.

    Rows composing an entry are always pasted after the previous user turn was
    submitted, so the lookup is bounded to deliveries after that turn's
    projection watermark. A match claims the row one-shot, so a replayed
    envelope never re-attributes a delivered one; the caller releases the claim
    when the adapter handoff yields no receipt, keeping the segment retryable.
    A row still carrying an orphaned claim (a crash mid-attempt) is finalized
    as omitted — delivery is unknowable, so it is never re-sent.
    """
    segment_text = segment.text.strip()
    rows = await db.fetch_recent_delivered_caller_inbound(
        session.session_id,
        delivered_after_iso=delivered_after.isoformat() if delivered_after is not None else None,
    )
    now = datetime.now(UTC)
    claim_cutoff_iso = (now - timedelta(seconds=_REFLECTION_CLAIM_TIMEOUT_S)).isoformat()
    for row in rows:
        if row["content"].strip() != segment_text:
            continue
        claimed_at = row["reflection_claimed_at"]
        if claimed_at is None:
            if await db.claim_inbound_reflection(row["id"], now_iso=now.isoformat()):
                return row
            continue
        if claimed_at >= claim_cutoff_iso:
            continue
        await db.finalize_inbound_reflection(row["id"], now_iso=now.isoformat())
        logger.warning(
            _PEER_REFLECTION_OMITTED_EVENT,
            session_id=session.session_id,
            inbound_row_id=row["id"],
            caller_session_id=row["caller_session_id"],
            reason=_ORPHANED_CLAIM_REASON,
        )
        return None
    return None


def _caller_author_from_row(row: InboundQueueRow) -> MessageAuthor | None:
    """Rebuild the typed caller author snapshot persisted at acceptance."""
    if not row["caller_session_id"] or not row["caller_author_kind"] or not row["caller_author_display"]:
        return None
    return MessageAuthor(
        kind=MessageAuthorKind(row["caller_author_kind"]),
        display=row["caller_author_display"],
        session_id=row["caller_session_id"],
        agent_runtime=row["caller_agent_runtime"],
        thinking_mode=row["caller_thinking_mode"],
        machine_role=row["caller_machine_role"],
    )


async def _reflect_identity_segment(
    session: Session,
    adapter_client: AdapterClient,
    presentation: _IdentitySegmentPresentation,
    sequence_index: int,
) -> tuple[str | None, bool]:
    """Reflect one identity segment as its caller; return (message_id, delivered).

    Adapter transport failures are absorbed inside the UI lane and surface here
    as a None receipt; an exception escaping the broadcast is a programming
    error and propagates.
    """
    message_id = await adapter_client.broadcast_peer_reflection(
        session,
        presentation.body,
        actor_name=presentation.actor_name,
        actor_avatar_url=presentation.actor_avatar_url,
    )
    delivered = message_id is not None
    if not delivered:
        logger.error(
            _PEER_REFLECTION_TRANSPORT_FAILURE_EVENT,
            session_id=session.session_id,
            sequence_index=sequence_index,
            caller_session_id=presentation.caller_session_id,
        )
    logger.info(
        _PEER_REFLECTION_DISPATCHED_EVENT,
        outcome=_PEER_REFLECTION_SENT_OUTCOME if delivered else _PEER_REFLECTION_FAILED_OUTCOME,
        reason=None if delivered else _PEER_REFLECTION_TRANSPORT_FAILURE_REASON,
        session_id=session.session_id,
        sequence_index=sequence_index,
        alias_kind=_PEER_REFLECTION_ALIAS_KIND,
        avatar_present=bool(presentation.actor_avatar_url),
        platform_message_id=message_id,
        body_len=len(presentation.body),
        caller_session_id=presentation.caller_session_id,
    )
    return message_id, delivered


async def reflect_user_turn_segments(
    session: Session,
    adapter_client: AdapterClient,
    *,
    user_text: str,
    source: str,
    delivered_after: datetime | None,
) -> TurnReflectionResult:
    """Reflect ordinary and identity parts of one turn under their real authorship."""
    platform_message_ids: list[str] = []
    reflectable = failed = False
    for sequence_index, segment in enumerate(cut_transcript_entry(user_text, is_user_entry=True)):
        if segment.kind in {TranscriptEntryKind.PLATFORM_CONTROL, TranscriptEntryKind.REMINDER}:
            continue
        if segment.kind is TranscriptEntryKind.IDENTITY_CONTENT:
            reflectable = True
            presentation = await _resolve_identity_segment_presentation(session, segment, user_text, delivered_after)
            if presentation is None:
                logger.warning(
                    _IDENTITY_SEGMENT_UNPARSED_EVENT,
                    session_id=session.session_id,
                    sequence_index=sequence_index,
                )
                continue
            if not presentation.body.strip():
                continue
            message_id: str | None = None
            delivered = False
            try:
                message_id, delivered = await _reflect_identity_segment(
                    session, adapter_client, presentation, sequence_index
                )
            finally:
                # The claim finalizes only on a platform receipt; a receiptless
                # attempt releases the row so a later pass can retry it. A crash
                # before this block self-heals through the claim timeout.
                if presentation.inbound_row_id is not None:
                    if message_id is not None:
                        await db.finalize_inbound_reflection(
                            presentation.inbound_row_id, now_iso=datetime.now(UTC).isoformat()
                        )
                    else:
                        await db.release_inbound_reflection(presentation.inbound_row_id)
            failed = failed or not delivered
            if message_id is not None:
                platform_message_ids.append(message_id)
            continue
        segment_text = segment.text
        if not segment_text.strip():
            continue
        reflectable = True
        try:
            message_ids = await adapter_client.broadcast_user_input(session, segment_text, source)
            platform_message_ids.extend(message_ids)
        except ValueError as exc:
            failed = True
            logger.debug(_USER_INPUT_REFLECTION_SKIPPED_EVENT, session_id=session.session_id, error=str(exc))
    return TurnReflectionResult(tuple(platform_message_ids), reflectable, failed)
