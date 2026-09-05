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
from teleclaude.core.injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from teleclaude.core.models import MessageMetadata
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


def direct_ignition_occurrence_key(
    *,
    link_id: str,
    source_session_id: str,
    target_session_id: str,
    occurred_at: datetime,
) -> str:
    """Return the deterministic occurrence key for direct ignition delivery."""
    return _delivery_key(
        link_id=link_id,
        source_session_id=source_session_id,
        target_session_id=target_session_id,
        role=_DIRECT_IGNITION_DELIVERY_ROLE,
        from_timestamp=occurred_at,
        to_timestamp=occurred_at,
    )


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
                text_kind=TranscriptEntryKind.IDENTITY_CONTENT,
                source_feature=InjectedTextSourceFeature.PEER_BUNDLE,
                occurrence_key=source_message_id,
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

    # Routed through command_payload so the remote command handler accepts the
    # framed text through its normal deduplicated inbound path.
    cross_computer_command = ProcessMessageCommand(
        session_id=target_session_id,
        text=framed_message,
        origin=origin,
        text_kind=TranscriptEntryKind.IDENTITY_CONTENT,
        source_feature=InjectedTextSourceFeature.PEER_BUNDLE,
        occurrence_key=source_message_id,
        actor_id=actor_id,
        actor_name=actor_name,
        source_message_id=source_message_id,
        source_channel_id=link_id,
    )
    message_id = await client.send_request(
        target_computer,
        cross_computer_command.command_type.value,
        MessageMetadata(),
        session_id=target_session_id,
        command_payload=cross_computer_command.to_dict(),
    )
    # A remote acceptance failure is surfaced as an exception, so the caller
    # retains the cursor and retries the handoff.
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
