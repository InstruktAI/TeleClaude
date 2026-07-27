"""Restart-safe conversation replay based on transcript truth and directional cursors."""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import HUMAN_ROLE_ADMIN, LOCAL_COMPUTER
from teleclaude.core.agents import AgentName
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.conversation_messages import (
    format_peer_message,
    is_conversation_bridge_message,
)
from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_listeners import (
    ConversationLink,
    ConversationLinkMember,
    get_active_links_for_session,
    get_peer_members,
)
from teleclaude.output_projection.conversation_projector import project_entries
from teleclaude.output_projection.models import (
    WEB_POLICY,
    ProjectionSurface,
    TranscriptChannel,
    VisibilityPolicy,
    visibility_policy_for_person,
)
from teleclaude.types.commands import ProcessMessageCommand
from teleclaude.utils.transcript import _get_entries_for_agent, _parse_timestamp

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.command_service import CommandService
    from teleclaude.core.models import Session

logger = get_logger(__name__)


@dataclass(frozen=True)
class ConversationSegment:
    """Visible conversation content that should be mirrored to linked peers."""

    role: str
    text: str
    timestamp: datetime | None
    is_human_authored: bool


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


def _target_computer_name(peer_computer_name: str | None) -> str:
    """Normalize the peer routing computer name."""
    if not peer_computer_name or peer_computer_name == LOCAL_COMPUTER:
        return config.computer.name
    return peer_computer_name


def _sender_identity(
    source_session: Session,
    *,
    source_computer: str | None,
) -> tuple[str, str]:
    """Build sender computer and actor identity values."""
    sender_computer = source_computer or source_session.computer_name or config.computer.name
    actor_id = f"system:{sender_computer}:{source_session.session_id}"
    return sender_computer, actor_id


async def _collect_visible_conversation_segments_since(
    transcript_path: str,
    agent_name: AgentName,
    since_timestamp: datetime,
    policy: VisibilityPolicy = WEB_POLICY,
) -> list[ConversationSegment]:
    """Collect visible user and assistant text after the provided cursor."""

    def _collect() -> list[ConversationSegment]:
        entries = _get_entries_for_agent(transcript_path, agent_name)
        if not entries:
            return []

        segments: list[ConversationSegment] = []
        current_role: str | None = None
        current_is_human_authored = False
        current_parts: list[str] = []
        current_timestamp: datetime | None = None

        for block in project_entries(entries, policy, since=since_timestamp.isoformat()):
            if block.role not in {"user", "assistant"} or block.block_type != "text":
                continue
            raw_text = str(block.block.get("text", "")).strip()
            if not raw_text:
                continue
            # Skip only peer-bridge blocks we injected for direct links; re-shipping
            # those creates the A-to-B-to-A echo loop.
            if block.role == TranscriptChannel.USER and is_conversation_bridge_message(raw_text):
                continue
            block_timestamp = _parse_timestamp(block.timestamp) if block.timestamp else None
            if current_role == block.role and current_is_human_authored == block.is_human_authored:
                current_parts.append(raw_text)
                current_timestamp = block_timestamp or current_timestamp
                continue
            if current_role and current_parts:
                segments.append(
                    ConversationSegment(
                        role=current_role,
                        text="\n\n".join(current_parts).strip(),
                        timestamp=current_timestamp,
                        is_human_authored=current_is_human_authored,
                    )
                )
            current_role = block.role
            current_is_human_authored = block.is_human_authored
            current_parts = [raw_text]
            current_timestamp = block_timestamp

        if current_role and current_parts:
            segments.append(
                ConversationSegment(
                    role=current_role,
                    text="\n\n".join(current_parts).strip(),
                    timestamp=current_timestamp,
                    is_human_authored=current_is_human_authored,
                )
            )
        return segments

    return await asyncio.to_thread(_collect)


async def _deliver_bundle(
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
) -> tuple[bool, datetime | None]:
    """Deliver all segments since the cursor as ONE bundled bridge message.

    Returns ``(delivered, latest_segment_timestamp)``. Latest timestamp is
    the cursor advancement target on success — the caller writes it to
    ``conversation_delivery_state`` only when delivered is True. Empty
    segments yields ``(False, None)``; callers must skip cursor advancement.
    """
    if not segments:
        return False, None

    sender_computer, actor_id = _sender_identity(source_session, source_computer=source_computer)
    actor_name = f"system@{sender_computer}"
    origin = (source_session.last_input_origin or "").strip() or InputOrigin.TERMINAL.value

    bundle_segments = [(seg.timestamp, seg.text, seg.is_human_authored) for seg in segments]
    framed_message = format_peer_message(
        sender_session_id=source_session.session_id,
        sender_computer=sender_computer,
        segments=bundle_segments,
    )

    latest_ts: datetime | None = None
    for seg in segments:
        if seg.timestamp is not None and (latest_ts is None or seg.timestamp > latest_ts):
            latest_ts = seg.timestamp
    upper_bound = latest_ts or since_timestamp

    source_message_id = _delivery_key(
        link_id=link_id,
        source_session_id=source_session.session_id,
        target_session_id=target_session_id,
        role="bundle",
        from_timestamp=since_timestamp,
        to_timestamp=upper_bound,
    )

    if target_computer == config.computer.name:
        await command_service.process_message(
            ProcessMessageCommand(
                session_id=target_session_id,
                text=framed_message,
                origin=origin,
                actor_id=actor_id,
                actor_name=actor_name,
                source_message_id=source_message_id,
                source_channel_id=link_id,
            )
        )
        return True, latest_ts

    await client.send_request(
        computer_name=target_computer,
        command=f"message {shlex.quote(framed_message)}",
        session_id=target_session_id,
        metadata=MessageMetadata(
            origin=origin,
            actor_id=actor_id,
            actor_name=actor_name,
            platform_message_id=source_message_id,
        ),
    )
    return True, latest_ts


def _max_segment_timestamp(segments: list[ConversationSegment]) -> datetime | None:
    latest: datetime | None = None
    for seg in segments:
        if seg.timestamp is not None and (latest is None or seg.timestamp > latest):
            latest = seg.timestamp
    return latest


def _trim_trailing_user_turn(segments: list[ConversationSegment]) -> list[ConversationSegment]:
    """Drop the trailing run of ``user``-channel segments with no agent reply.

    A bare human turn at the end of the bundle means the human typed but the
    agent has not yet replied. Shipping it would deliver an unanswered human
    turn to the peer; the requirement is that human input rides with the
    agent's response. Holding the trailing user-channel segments past the
    cursor lets the next ``agent_stop`` cycle pick them up bundled with the
    reply.

    The collector now cuts segments on authorship as well as channel role, so
    a trailing run of user-channel content can span more than one segment
    (for example a machine injection immediately followed by human text) —
    trim the whole run, not just the last segment.
    """
    trim_from = len(segments)
    while trim_from > 0 and segments[trim_from - 1].role == TranscriptChannel.USER:
        trim_from -= 1
    return segments[:trim_from]


async def _replay_pending_bundle(
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
) -> bool:
    """Re-send the bounded bundle for a peer with orphaned pending_through_ts.

    Returns True iff the replay handoff completed and the cursor should advance
    to ``pending_dt``. Returns False on send failure or unsuccessful handoff
    (caller should NOT advance the cursor).
    """
    bounded = [s for s in all_segments if s.timestamp is None or s.timestamp <= pending_dt]
    if not bounded:
        # Transcript pruning edge case: the planned range is no longer
        # reachable from the source transcript. We CANNOT advance the cursor
        # past the pending bound without a durable handoff — that would mean
        # the pre-write happened, no send actually occurred, and the content
        # is now unreachable. Stay stuck (do not promote) and log loudly so
        # the operator can intervene.
        logger.error(
            "Conversation delivery replay cannot reconstruct bounded bundle "
            "(transcript pruned past pending bound): source=%s peer=%s link=%s "
            "pending=%s — leaving pending in place; manual intervention required.",
            source_session.session_id,
            target_session_id,
            link_id,
            pending_dt.isoformat(),
        )
        return False
    try:
        bundle_delivered, _ = await _deliver_bundle(
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
            "Conversation delivery replay failed: source=%s peer=%s link=%s error=%s",
            source_session.session_id,
            target_session_id,
            link_id,
            exc,
        )
        return False
    return bundle_delivered


async def _deliver_for_peer(
    *,
    source_session: Session,
    link: ConversationLink,
    peer: ConversationLinkMember,
    agent_name: AgentName,
    source_computer: str | None,
    client: AdapterClient,
    command_service: CommandService,
) -> int:
    """Drive replay-then-fresh delivery for a single (link, peer) pair.

    Returns the number of bundles handed off durably (0 or 1 in the no-pending
    case; up to 2 when crash recovery and a fresh bundle both succeed).
    """
    link_id = link.link_id
    target_session_id = peer.session_id
    peer_computer = peer.computer_name
    source_session_id = source_session.session_id

    persisted = await db.get_conversation_delivery_state(
        link_id=link_id,
        source_session_id=source_session_id,
        target_session_id=target_session_id,
    )
    cursor_dt = (
        parse_iso_datetime(persisted.delivered_through_ts) if persisted and persisted.delivered_through_ts else None
    )
    if cursor_dt is None:
        # Active link without an anchored cursor: repair using the link's
        # creation timestamp as the floor so any post-link transcript content
        # is still delivered. `create_or_reuse_direct_link` writes the anchor
        # at link creation; if that row is missing, ``link.created_at`` is
        # the authoritative replacement.
        cursor_dt = link.created_at
        await db.upsert_conversation_delivery_state(
            link_id=link_id,
            source_session_id=source_session_id,
            target_session_id=target_session_id,
            delivered_through_ts=cursor_dt.isoformat(),
            pending_through_ts=None,
        )
        logger.warning(
            "Backfilled missing delivery cursor from link.created_at: link=%s source=%s target=%s anchored_at=%s",
            link_id,
            source_session_id,
            target_session_id,
            cursor_dt.isoformat(),
        )
    since_timestamp = cursor_dt
    if not source_session.native_log_file:
        return 0

    target_session = await db.get_session(target_session_id)
    target_policy = visibility_policy_for_person(
        human_role=target_session.human_role if target_session is not None else HUMAN_ROLE_ADMIN,
        person_email=target_session.human_email if target_session is not None else None,
        surface=ProjectionSurface.WEB,
    )
    all_segments = await _collect_visible_conversation_segments_since(
        source_session.native_log_file,
        agent_name,
        since_timestamp,
        target_policy,
    )
    target_computer = _target_computer_name(peer_computer)

    pending_dt: datetime | None = None
    if persisted is not None and persisted.pending_through_ts:
        pending_candidate = parse_iso_datetime(persisted.pending_through_ts)
        if pending_candidate is not None and pending_candidate > cursor_dt:
            pending_dt = pending_candidate

    delivered = 0
    if pending_dt is not None:
        if not await _replay_pending_bundle(
            source_session=source_session,
            link_id=link_id,
            target_session_id=target_session_id,
            target_computer=target_computer,
            pending_dt=pending_dt,
            all_segments=all_segments,
            since_timestamp=since_timestamp,
            source_computer=source_computer,
            client=client,
            command_service=command_service,
        ):
            return 0
        await db.upsert_conversation_delivery_state(
            link_id=link_id,
            source_session_id=source_session_id,
            target_session_id=target_session_id,
            delivered_through_ts=pending_dt.isoformat(),
            pending_through_ts=None,
        )
        delivered += 1
        fresh_segments = [s for s in all_segments if s.timestamp is not None and s.timestamp > pending_dt]
        since_timestamp = pending_dt
        cursor_iso: str | None = pending_dt.isoformat()
    else:
        fresh_segments = all_segments
        cursor_iso = cursor_dt.isoformat()

    fresh_segments = _trim_trailing_user_turn(fresh_segments)

    if not fresh_segments:
        return delivered

    latest_ts_all = _max_segment_timestamp(fresh_segments)

    if latest_ts_all is not None:
        await db.upsert_conversation_delivery_state(
            link_id=link_id,
            source_session_id=source_session_id,
            target_session_id=target_session_id,
            delivered_through_ts=cursor_iso,
            pending_through_ts=latest_ts_all.isoformat(),
        )
    try:
        bundle_delivered, _ = await _deliver_bundle(
            source_session=source_session,
            link_id=link_id,
            target_session_id=target_session_id,
            target_computer=target_computer,
            segments=fresh_segments,
            since_timestamp=since_timestamp,
            source_computer=source_computer,
            client=client,
            command_service=command_service,
        )
    except Exception as exc:
        logger.warning(
            "Conversation delivery failed: source=%s peer=%s link=%s error=%s",
            source_session_id,
            target_session_id,
            link_id,
            exc,
        )
        return delivered
    if not bundle_delivered or latest_ts_all is None:
        return delivered
    # Advance cursor past all fresh segments so the next iteration doesn't re-process them.
    await db.upsert_conversation_delivery_state(
        link_id=link_id,
        source_session_id=source_session_id,
        target_session_id=target_session_id,
        delivered_through_ts=latest_ts_all.isoformat(),
        pending_through_ts=None,
    )
    return delivered + 1


async def deliver_pending_conversation_updates(
    source_session_id: str,
    *,
    client: AdapterClient,
    command_service: CommandService | None = None,
    source_computer: str | None = None,
) -> int:
    """Deliver any new transcript activity from this session to its linked peers."""
    source_session = await db.get_session(source_session_id)
    if source_session is None:
        return 0
    if not source_session.native_log_file or not source_session.active_agent:
        return 0

    try:
        agent_name = AgentName.from_str(source_session.active_agent)
    except ValueError:
        return 0

    service = command_service or get_command_service()
    links = await get_active_links_for_session(source_session_id)
    if not links:
        return 0

    delivered = 0
    for link in links:
        peers = await get_peer_members(link_id=link.link_id, sender_session_id=source_session_id)
        for peer in peers:
            delivered += await _deliver_for_peer(
                source_session=source_session,
                link=link,
                peer=peer,
                agent_name=agent_name,
                source_computer=source_computer,
                client=client,
                command_service=service,
            )

    return delivered


async def reconcile_outstanding_conversation_deliveries(
    computer_name: str,
    *,
    client: AdapterClient,
    command_service: CommandService | None = None,
) -> int:
    """Startup repair for conversation deliveries that were not mirrored before restart."""
    sessions = await db.list_sessions(computer_name=computer_name, include_headless=True)
    repaired = 0
    for session in sessions:
        if session.closed_at is not None:
            continue
        repaired += await deliver_pending_conversation_updates(
            session.session_id,
            client=client,
            command_service=command_service,
            source_computer=session.computer_name,
        )
    return repaired


# Debounce window for coalescing rapid agent_stops on the same source session
# into a single bundled delivery. Codex emits agent_stops after each tool turn,
# so without coalescing, a multi-turn task fans out N separate deliveries to
# every linked peer. Reset semantics: each new agent_stop within this window
# postpones the firing by another full window.
_DEBOUNCE_WINDOW_S: float = 10.0
_pending_deliveries: dict[str, asyncio.Task[None]] = {}


def schedule_debounced_delivery(
    source_session_id: str,
    *,
    client: AdapterClient,
    command_service: CommandService | None = None,
    source_computer: str | None = None,
) -> None:
    """Coalesce N rapid agent_stops on this source into one delayed delivery.

    Cancels any pending timer for ``source_session_id`` and starts a fresh
    ``_DEBOUNCE_WINDOW_S`` timer. When the timer fires, runs
    ``deliver_pending_conversation_updates`` once. Synchronous (not a
    coroutine) because the caller doesn't want to await — it just signals
    that delivery should run after the window quiets.
    """
    pending = _pending_deliveries.pop(source_session_id, None)
    if pending is not None and not pending.done():
        pending.cancel()

    task: asyncio.Task[None]

    async def _run() -> None:
        try:
            await asyncio.sleep(_DEBOUNCE_WINDOW_S)
        except asyncio.CancelledError:
            return
        try:
            await deliver_pending_conversation_updates(
                source_session_id,
                client=client,
                command_service=command_service,
                source_computer=source_computer,
            )
        except Exception as exc:
            logger.warning(
                "Debounced conversation delivery failed: source=%s error=%s",
                source_session_id,
                exc,
            )
        finally:
            # Race guard: a fresh signal may have replaced the registry entry
            # while we were running. Only clear the slot if it still points to
            # OUR task — otherwise we'd orphan the newer pending task.
            current = _pending_deliveries.get(source_session_id)
            if current is task:
                _pending_deliveries.pop(source_session_id, None)

    task = asyncio.create_task(_run(), name=f"conversation-delivery-{source_session_id}")
    _pending_deliveries[source_session_id] = task
