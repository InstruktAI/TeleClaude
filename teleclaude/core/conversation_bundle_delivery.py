"""Bundle send and replay mechanics for conversation delivery.

Extracted from `conversation_delivery.py` (Task 8 module-size precedent):
this module owns "how to actually send or replay ONE bundle", distinct from
`conversation_delivery.py`'s collection and per-peer orchestration concerns.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.command_dispatch import parse_remote_dispatch_data_diagnosed
from teleclaude.core.conversation_messages import format_peer_message, resolve_session_event_author
from teleclaude.core.conversation_segments import ConversationSegment, LocalConversationPayload
from teleclaude.core.db import PeerBundleSegmentInput, db
from teleclaude.core.models import MessageAuthor, MessageMetadata, PeerBundleSegmentWireDict
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import ProcessMessageCommand

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.command_service import CommandService
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_BUNDLE_DELIVERED_EVENT = "conversation_delivery_bundle_delivered"
_REPLAY_STUCK_EVENT = "conversation_delivery_replay_stuck"
_REPLAY_FAILED_EVENT = "conversation_delivery_replay_failed"
_DIRECT_IGNITION_DELIVERY_ROLE = "direct_ignition"


def _delivery_key(
    *,
    link_id: str,
    source_session_id: str,
    target_session_id: str,
    role: str,
    from_timestamp: datetime,
    to_timestamp: datetime | None,
) -> str:
    """Build a deterministic dedupe key for one mirrored conversation slice."""
    to_iso = to_timestamp.isoformat() if to_timestamp else "-"
    return f"linked:{link_id}:{source_session_id}:{target_session_id}:{role}:{from_timestamp.isoformat()}:{to_iso}"


def _sender_identity(
    source_session: Session,
    *,
    source_computer: str | None,
) -> tuple[str, str]:
    """Build sender computer and actor identity values."""
    sender_computer = source_computer or source_session.computer_name or config.computer.name
    actor_id = f"system:{sender_computer}:{source_session.session_id}"
    return sender_computer, actor_id


def _segment_authored_span(segment: ConversationSegment, *, source_session_id: str) -> PeerBundleSegmentInput:
    """Reduce one composed segment to its durable authored-span input."""
    if isinstance(segment.payload, LocalConversationPayload):
        message = segment.payload.message
        return PeerBundleSegmentInput(
            original_source_session_id=source_session_id,
            author=message.author,
            author_job_role=None,
            occurred_at=message.occurred_at,
            body=message.body,
        )
    peer_segment = segment.payload.peer_segment
    return PeerBundleSegmentInput(
        original_source_session_id=peer_segment.original_source_session_id,
        author=peer_segment.author,
        author_job_role=None,
        occurred_at=peer_segment.occurred_at,
        body=peer_segment.body,
    )


def _segment_to_wire_dict(segment: PeerBundleSegmentInput) -> PeerBundleSegmentWireDict:
    """Serialize one authored-span input to a cross-computer wire dict.

    The counterpart to `command_handlers/_message.py`'s
    `_peer_bundle_segment_from_wire`, which decodes this exact shape back
    into a typed author on the receiving computer.
    """
    return {
        "original_source_session_id": segment.original_source_session_id,
        "author_kind": segment.author.kind.value,
        "author_display": segment.author.display,
        "author_agent_runtime": segment.author.agent_runtime,
        "author_thinking_mode": segment.author.thinking_mode,
        "author_machine_role": segment.author.machine_role,
        "author_job_role": segment.author_job_role,
        "occurred_at": segment.occurred_at.isoformat(),
        "body": segment.body,
    }


async def _persist_peer_bundle_segments(
    *,
    bundle_key: str,
    link_id: str,
    source_session_id: str,
    target_session_id: str,
    segments: list[ConversationSegment],
) -> None:
    """Durably record the bundle's structural provenance before it is sent.

    This is what lets the target session relay the content onward by durable
    bundle identity, without re-deriving structure by parsing its own
    rendered transcript text. Persistence must succeed before the framed text
    is sent — a caught-and-logged failure here used to leave the fallback
    text-parsing path silently reachable forever for this block, after the
    cursor had already advanced; propagating instead makes the whole
    delivery fail closed (no send, no cursor advance) so the next pass
    retries both atomically.
    """
    await db.create_peer_bundle(
        bundle_key=bundle_key,
        link_id=link_id,
        source_session_id=source_session_id,
        target_session_id=target_session_id,
        segments=[_segment_authored_span(segment, source_session_id=source_session_id) for segment in segments],
    )


async def persist_direct_ignition_bundle(
    *,
    link_id: str,
    source_session_id: str,
    target_session_id: str,
    author: MessageAuthor,
    author_job_role: str | None,
    occurred_at: datetime,
    body: str,
) -> str:
    """Persist the direct ignition's single authored span before dispatch."""
    bundle_key = _delivery_key(
        link_id=link_id,
        source_session_id=source_session_id,
        target_session_id=target_session_id,
        role=_DIRECT_IGNITION_DELIVERY_ROLE,
        from_timestamp=occurred_at,
        to_timestamp=occurred_at,
    )
    await db.create_peer_bundle(
        bundle_key=bundle_key,
        link_id=link_id,
        source_session_id=source_session_id,
        target_session_id=target_session_id,
        segments=[
            PeerBundleSegmentInput(
                original_source_session_id=source_session_id,
                author=author,
                author_job_role=author_job_role,
                occurred_at=occurred_at,
                body=body,
            )
        ],
    )
    return bundle_key


async def deliver_bundle(
    *,
    source_session: Session,
    link_id: str,
    target_session_id: str,
    target_computer: str,
    segments: list[ConversationSegment],
    since_timestamp: datetime,
    source_computer: str | None,
    client: AdapterClient,
    command_service: CommandService,
) -> tuple[bool, datetime | None, str | None]:
    """Deliver all segments since the cursor as ONE bundled bridge message.

    Returns ``(delivered, latest_segment_timestamp, bundle_key)``. Latest timestamp is
    the cursor advancement target on success — the caller writes it to
    ``conversation_delivery_state`` only when delivered is True. Empty
    segments yields ``(False, None)``; callers must skip cursor advancement.
    """
    if not segments:
        return False, None, None

    sender_computer, actor_id = _sender_identity(source_session, source_computer=source_computer)
    actor_name = f"system@{sender_computer}"
    origin = (source_session.last_input_origin or "").strip() or InputOrigin.TERMINAL.value

    messages = [
        segment.payload.message
        if isinstance(segment.payload, LocalConversationPayload)
        else segment.payload.peer_segment
        for segment in segments
    ]
    framed_message = format_peer_message(messages=messages)

    latest_ts = max(segment.source_timestamp for segment in segments)
    upper_bound = latest_ts

    source_message_id = _delivery_key(
        link_id=link_id,
        source_session_id=source_session.session_id,
        target_session_id=target_session_id,
        role="bundle",
        from_timestamp=since_timestamp,
        to_timestamp=upper_bound,
    )

    if target_computer == config.computer.name:
        # Same-computer delivery shares this daemon's own DB with the target
        # session, so the structural record is written directly here — the
        # receiving session's own relay-onward collector reads it back by
        # durable identity. Persisted BEFORE the text is sent: an exception
        # here fails the whole delivery closed (propagates to the caller,
        # no cursor advance) rather than sending text with no structural
        # record behind it — the exact gap that let the fallback text-parsing
        # path stay silently reachable after a persistence failure.
        await _persist_peer_bundle_segments(
            bundle_key=source_message_id,
            link_id=link_id,
            source_session_id=source_session.session_id,
            target_session_id=target_session_id,
            segments=segments,
        )
        caller_author = resolve_session_event_author(
            session_id=source_session.session_id,
            system_role=source_session.system_role,
            active_agent=source_session.active_agent,
            thinking_mode=source_session.thinking_mode,
        )
        await command_service.process_message(
            ProcessMessageCommand(
                session_id=target_session_id,
                text=framed_message,
                origin=origin,
                actor_id=actor_id,
                actor_name=actor_name,
                source_message_id=source_message_id,
                source_channel_id=link_id,
                caller_session_id=source_session.session_id,
                caller_author_kind=caller_author.kind.value,
                caller_author_display=caller_author.display,
                caller_agent_runtime=caller_author.agent_runtime,
                caller_thinking_mode=caller_author.thinking_mode,
                caller_machine_role=caller_author.machine_role,
                caller_job_role=source_session.job,
            )
        )
        logger.info(
            _BUNDLE_DELIVERED_EVENT,
            link_id=link_id,
            source_session_id=source_session.session_id,
            target_session_id=target_session_id,
            segment_count=len(segments),
            route="same_computer",
            delivered_through_ts=latest_ts.isoformat(),
        )
        return True, latest_ts, source_message_id

    # Cross-computer delivery cannot write into the target computer's DB
    # directly, so the structural bundle is carried on the command itself
    # and persisted by the receiving computer on receipt
    # (`command_handlers/_message.py`'s `_persist_peer_bundle_from_command`)
    # — the structural counterpart to the same-computer branch's direct
    # local write above. Routed through `command_payload` (matching
    # `forward_command_to_peer`'s established pattern), never the raw-string
    # command form, which the receiving side's dispatcher does not resolve
    # to message acceptance at all.
    cross_computer_command = ProcessMessageCommand(
        session_id=target_session_id,
        text=framed_message,
        origin=origin,
        actor_id=actor_id,
        actor_name=actor_name,
        source_message_id=source_message_id,
        source_channel_id=link_id,
        peer_bundle_key=source_message_id,
        peer_bundle_link_id=link_id,
        peer_bundle_source_session_id=source_session.session_id,
        peer_bundle_segments=[
            _segment_to_wire_dict(_segment_authored_span(segment, source_session_id=source_session.session_id))
            for segment in segments
        ],
    )
    message_id = await client.send_request(
        target_computer,
        cross_computer_command.command_type.value,
        MessageMetadata(),
        session_id=target_session_id,
        command_payload=cross_computer_command.to_dict(),
    )
    # The receiving computer's acceptance is not assumed: it persists the
    # structural bundle BEFORE queueing the message and rejects the whole
    # command if that fails (`_persist_peer_bundle_from_command`). Reading
    # the response here — the same pattern `forward_command_to_peer` already
    # uses for every other cross-computer command — surfaces that rejection
    # as an exception, so the caller treats it as a failed delivery (no
    # cursor advance, retried next pass) instead of reporting success for a
    # bundle the target never actually accepted.
    response_text = await client.read_response(message_id, timeout=10.0, target_computer=target_computer)
    await parse_remote_dispatch_data_diagnosed(
        client,
        response_text,
        target_computer=target_computer,
        command=cross_computer_command.command_type.value,
    )
    logger.info(
        _BUNDLE_DELIVERED_EVENT,
        link_id=link_id,
        source_session_id=source_session.session_id,
        target_session_id=target_session_id,
        segment_count=len(segments),
        route="cross_computer",
        target_computer=target_computer,
        delivered_through_ts=latest_ts.isoformat(),
    )
    return True, latest_ts, source_message_id


async def replay_pending_bundle(
    *,
    source_session: Session,
    link_id: str,
    target_session_id: str,
    target_computer: str,
    pending_dt: datetime,
    all_segments: list[ConversationSegment],
    since_timestamp: datetime,
    source_computer: str | None,
    client: AdapterClient,
    command_service: CommandService,
) -> tuple[bool, str | None]:
    """Re-send the bounded bundle for a peer with orphaned pending_through_ts.

    Returns the handoff result and its bundle key when delivery completed.
    """
    bounded = [segment for segment in all_segments if segment.source_timestamp <= pending_dt]
    if not bounded:
        # Transcript pruning edge case: the planned range is no longer
        # reachable from the source transcript. We CANNOT advance the cursor
        # past the pending bound without a durable handoff — that would mean
        # the pre-write happened, no send actually occurred, and the content
        # is now unreachable. Stay stuck (do not promote) and log loudly so
        # the operator can intervene.
        logger.error(
            _REPLAY_STUCK_EVENT,
            link_id=link_id,
            source_session_id=source_session.session_id,
            target_session_id=target_session_id,
            pending_through_ts=pending_dt.isoformat(),
            reason="range_unreconstructable",
        )
        return False, None
    try:
        bundle_delivered, _, bundle_key = await deliver_bundle(
            source_session=source_session,
            link_id=link_id,
            target_session_id=target_session_id,
            target_computer=target_computer,
            segments=bounded,
            since_timestamp=since_timestamp,
            source_computer=source_computer,
            client=client,
            command_service=command_service,
        )
    except Exception as exc:
        logger.warning(
            _REPLAY_FAILED_EVENT,
            link_id=link_id,
            source_session_id=source_session.session_id,
            target_session_id=target_session_id,
            pending_through_ts=pending_dt.isoformat(),
            error=str(exc),
        )
        return False, None
    return bundle_delivered, bundle_key
