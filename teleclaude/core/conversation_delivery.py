"""Restart-safe conversation replay based on transcript truth and directional cursors."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import (
    HUMAN_ROLE_ADMIN,
    LOCAL_COMPUTER,
    ConversationDeliveryDisposition,
    ConversationDeliveryRefusalReason,
)
from teleclaude.core.agents import AgentName
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.conversation_bundle_delivery import deliver_bundle
from teleclaude.core.conversation_delivery_settlement import (
    BundleSettlementOutcome,
    BundleSettlementReason,
    empty_bundle_settlement,
    record_bundle_settled,
    settle_pending_bundle,
    suppress_bare_noop_segments,
)
from teleclaude.core.conversation_messages import (
    MalformedPeerSegmentError,
    is_conversation_bridge_message,
    parse_peer_segments,
)
from teleclaude.core.conversation_segments import (
    CollectedSegment,
    ConversationSegment,
    ForwardedConversationPayload,
    ForwardedProjectedSegment,
    LocalConversationPayload,
    ProjectedSegment,
)
from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.db import db
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.injected_text import TranscriptEntryKind, cut_transcript_entry
from teleclaude.core.models import HumanFacingMessage, MessageAuthor, MessageAuthorKind
from teleclaude.core.session_listeners import (
    ConversationLink,
    ConversationLinkMember,
    get_active_links_for_session,
    get_peer_members,
)
from teleclaude.output_projection.conversation_projector import project_entries
from teleclaude.output_projection.models import (
    WEB_POLICY,
    ProjectedAuthor,
    ProjectedAuthorKind,
    ProjectionSurface,
    TranscriptChannel,
    VisibilityPolicy,
    visibility_policy_for_person,
)
from teleclaude.utils.transcript import (
    _get_entries_for_agent,
    _parse_timestamp,
    extract_real_user_text_from_entry,
    native_entry_id,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.command_service import CommandService
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_MALFORMED_PEER_SEGMENT_EVENT = "conversation_delivery_malformed_peer_segment"
_MISSING_HUMAN_IDENTITY_EVENT = "conversation_delivery_missing_human_identity"
_DELIVERY_FAILED_EVENT = "conversation_delivery_failed"
_PEER_PASS_FAILED_EVENT = "conversation_delivery_peer_pass_failed"
_CURSOR_BACKFILLED_EVENT = "conversation_delivery_cursor_backfilled"
_TEXT_PART_SEPARATOR = "\n\n"
_EMPTY_BLOCK_TEXT = ""
_LEGACY_PRE_CUTOVER_REASON = "legacy_pre_cutover"
_DELIVERY_DISPOSITION_EVENT = "conversation_delivery_segment_disposition"
_SEGMENT_ECHO_SUPPRESSED_EVENT = "conversation_segment_echo_suppressed"


class _MalformedConversationSegmentError(Exception):
    """Raised when a bridge entry lacks the structural proof peer replay requires."""

    def __init__(
        self,
        *,
        entry_ref: str,
        entry_text: str,
        entry_timestamp: datetime,
        reason: ConversationDeliveryRefusalReason,
    ) -> None:
        self.entry_ref = entry_ref
        self.entry_text = entry_text
        self.entry_timestamp = entry_timestamp
        self.reason = reason


@dataclass(frozen=True)
class _MalformedConversationSegment:
    """One bridge entry that cannot use the post-cutover structural path."""

    entry_ref: str
    entry_text: str
    entry_timestamp: datetime
    reason: ConversationDeliveryRefusalReason


def _target_computer_name(peer_computer_name: str | None) -> str:
    """Normalize the peer routing computer name."""
    if not peer_computer_name or peer_computer_name == LOCAL_COMPUTER:
        return config.computer.name
    return peer_computer_name


async def _collect_visible_conversation_segments_since(
    transcript_path: str,
    agent_name: AgentName,
    since_timestamp: datetime,
    session_id: str,
    policy: VisibilityPolicy = WEB_POLICY,
) -> list[CollectedSegment] | _MalformedConversationSegment:
    """Collect visible user and assistant text after the provided cursor.

    Reads the transcript, projects, and cuts local or forwarded segments.
    Local authorship is the projector's own classification. Whether a user
    block is peer content is decided by its native entry's durable
    accepted-turn binding, never by the rendered prefix: a binding proving an
    ``injected_peer`` part is the only path into bundle correlation, and the
    exact matching peer bundle is then correlated by durable bundle identity
    (the accepted row's own ``source_message_id``) — never by the array
    position bundles happen to arrive in. A binding that exists and proves no
    ``injected_peer`` part is structural proof the entry is ordinary local
    content, even when its text happens to start with a peer segment header —
    it is never routed into the bridge path. Only a peer-shaped block with no
    binding at all — a genuine binding race, not evidence either way — raises
    a hold. A binding proving an ``injected_peer`` part whose bundle does not
    reconcile also fails closed: returns a failure so the caller holds
    delivery without cursor advancement, rather than falling back to
    re-parsing rendered text under a guessed attribution.
    """

    def _collect() -> list[CollectedSegment]:
        entries = _get_entries_for_agent(transcript_path, agent_name)
        if not entries:
            return []

        segments: list[CollectedSegment] = []
        current_role: str | None = None
        current_author: ProjectedAuthor | None = None
        current_parts: list[str] = []
        current_timestamp: datetime | None = None

        def _flush() -> None:
            if not current_role or not current_parts:
                return
            if current_timestamp is None:
                # Measured across live transcripts, every visible message entry
                # carries a timestamp; this is defensive, not a primary path.
                return
            assert current_author is not None  # set alongside current_role/current_parts
            segments.append(
                ProjectedSegment(
                    role=current_role,
                    text=_TEXT_PART_SEPARATOR.join(current_parts).strip(),
                    timestamp=current_timestamp,
                    author=current_author,
                )
            )

        for block in project_entries(entries, policy, agent_name, since=since_timestamp.isoformat()):
            if block.role not in {"user", "assistant"} or block.block_type != "text":
                continue
            raw_text = str(block.block.get("text", _EMPTY_BLOCK_TEXT))
            if not raw_text.strip():
                continue
            if block.role == TranscriptChannel.USER:
                raw_entry = entries[block.entry_index]
                entry_text = extract_real_user_text_from_entry(raw_entry, agent_name)
                entry_id = (
                    native_entry_id(raw_entry, agent_name, timestamp=raw_entry.get("timestamp"), text=entry_text)
                    if entry_text is not None
                    else None
                )
                if entry_text is not None and is_conversation_bridge_message(entry_text):
                    _flush()
                    current_role = None
                    current_author = None
                    current_parts = []
                    current_timestamp = None
                    block_timestamp = _parse_timestamp(block.timestamp) if block.timestamp else None
                    if block_timestamp is None:
                        continue
                    try:
                        for cut in cut_transcript_entry(entry_text, is_user_entry=True):
                            if cut.kind is not TranscriptEntryKind.IDENTITY_CONTENT:
                                continue
                            for peer_segment in parse_peer_segments(cut.text):
                                segments.append(
                                    ForwardedProjectedSegment(
                                        source_timestamp=block_timestamp,
                                        peer_segment=peer_segment,
                                    )
                                )
                    except MalformedPeerSegmentError as exc:
                        raise _MalformedConversationSegmentError(
                            entry_ref=entry_id if entry_id is not None else entry_text,
                            entry_text=entry_text,
                            entry_timestamp=block_timestamp,
                            reason=ConversationDeliveryRefusalReason.BUNDLE_AUTHOR_INVALID,
                        ) from exc
                    continue
            normalized_text = raw_text.strip()
            block_timestamp = _parse_timestamp(block.timestamp) if block.timestamp else None
            if current_role == block.role and current_author == block.author:
                current_parts.append(normalized_text)
                current_timestamp = block_timestamp or current_timestamp
                continue
            _flush()
            current_role = block.role
            current_author = block.author
            current_parts = [normalized_text]
            current_timestamp = block_timestamp

        _flush()
        return segments

    try:
        return await asyncio.to_thread(_collect)
    except _MalformedConversationSegmentError as exc:
        return _MalformedConversationSegment(
            entry_ref=exc.entry_ref,
            entry_text=exc.entry_text,
            entry_timestamp=exc.entry_timestamp,
            reason=exc.reason,
        )


def _max_segment_source_timestamp(segments: list[ConversationSegment]) -> datetime | None:
    if not segments:
        return None
    return max(segment.source_timestamp for segment in segments)


def _should_hold_as_unanswered_local_human(segment: ConversationSegment) -> bool:
    """Return whether the segment is a local human turn awaiting an agent reply."""
    if not isinstance(segment.payload, LocalConversationPayload):
        return False
    return (
        segment.payload.role == TranscriptChannel.USER
        and segment.payload.message.author.kind is MessageAuthorKind.HUMAN
    )


def _trim_trailing_user_turn(segments: list[ConversationSegment]) -> list[ConversationSegment]:
    """Drop the trailing run of ``user``-channel segments with no agent reply.

    A local human turn at the end of the bundle means the human typed but the
    agent has not yet replied. Holding that trailing local-human run lets the
    next ``agent_stop`` cycle deliver it with the reply. Forwarded peer
    segments terminate the run even though their transcript container is a
    user-channel block: they are already-authored conversation content.
    """
    trim_from = len(segments)
    while trim_from > 0 and _should_hold_as_unanswered_local_human(segments[trim_from - 1]):
        trim_from -= 1
    return segments[:trim_from]


def _needs_human_identity(segments: list[CollectedSegment]) -> bool:
    """Return True when at least one segment requires a resolved human identity."""
    return any(
        isinstance(segment, ProjectedSegment) and segment.author.kind is ProjectedAuthorKind.HUMAN
        for segment in segments
    )


async def _resolve_session_authors(
    source_session: Session,
    segments: list[CollectedSegment],
) -> tuple[MessageAuthor, MessageAuthor | None] | None:
    """Resolve the per-delivery agent author, and the human author when needed.

    Resolution happens once per delivery, not per segment. Returns ``None``
    when a ``HUMAN`` segment is present but no human identity can be
    resolved — the caller holds delivery for this peer rather than
    substituting a generic identity.
    """
    assert source_session.active_agent is not None  # guaranteed by deliver_pending_conversation_updates
    agent_author = MessageAuthor.for_agent(
        session_id=source_session.session_id,
        active_agent=source_session.active_agent,
        thinking_mode=source_session.thinking_mode,
    )
    if not _needs_human_identity(segments):
        return agent_author, None
    if not source_session.human_email:
        return None
    try:
        display_name = get_identity_resolver().resolve_by_email(source_session.human_email).display_name
    except ValueError:
        return None
    human_author = MessageAuthor.for_human(session_id=source_session.session_id, display_name=display_name)
    return agent_author, human_author


def _resolve_conversation_segment_author(
    projected_author: ProjectedAuthor,
    *,
    source_session_id: str,
    agent_author: MessageAuthor,
    human_author: MessageAuthor | None,
) -> MessageAuthor:
    """Turn one segment's projector classification into its resolved author."""
    if projected_author.kind is ProjectedAuthorKind.HUMAN:
        assert human_author is not None  # resolved whenever a HUMAN segment is present
        return human_author
    if projected_author.kind is ProjectedAuthorKind.AGENT:
        return agent_author
    assert projected_author.label is not None  # MACHINE always carries a label
    return MessageAuthor.for_machine(session_id=source_session_id, role_label=projected_author.label)


def _build_conversation_segments(
    projected: list[CollectedSegment],
    *,
    source_session_id: str,
    agent_author: MessageAuthor,
    human_author: MessageAuthor | None,
) -> list[ConversationSegment]:
    """Map projector-classified segments to segments carrying a resolved author.

    No author is reconstructed from channel role — every segment's author
    comes from its own ``ProjectedAuthor``, resolved via the session-level
    authors computed once for this delivery.
    """
    segments: list[ConversationSegment] = []
    for segment in projected:
        if isinstance(segment, ForwardedProjectedSegment):
            segments.append(
                ConversationSegment(
                    source_timestamp=segment.source_timestamp,
                    payload=ForwardedConversationPayload(peer_segment=segment.peer_segment),
                )
            )
            continue
        author = _resolve_conversation_segment_author(
            segment.author,
            source_session_id=source_session_id,
            agent_author=agent_author,
            human_author=human_author,
        )
        segments.append(
            ConversationSegment(
                source_timestamp=segment.timestamp,
                payload=LocalConversationPayload(
                    role=segment.role,
                    message=HumanFacingMessage(author=author, occurred_at=segment.timestamp, body=segment.text),
                ),
            )
        )
    return segments


def _retain_segments_for_target(
    segments: list[ConversationSegment],
    target_session_id: str,
    *,
    link_id: str,
) -> list[ConversationSegment]:
    """Suppress only forwarded segments whose original source is this target."""
    retained: list[ConversationSegment] = []
    for index, segment in enumerate(segments):
        if (
            isinstance(segment.payload, ForwardedConversationPayload)
            and segment.payload.peer_segment.original_source_session_id == target_session_id
        ):
            logger.info(
                _SEGMENT_ECHO_SUPPRESSED_EVENT,
                outcome="suppressed",
                reason="original_source_is_target",
                link_id=link_id,
                target_session_id=target_session_id,
                segment_id=f"{segment.source_timestamp.isoformat()}:{index}",
                original_source_session_id=segment.payload.peer_segment.original_source_session_id,
                cursor_advanced=False,
            )
            continue
        retained.append(segment)
    return retained


async def _record_delivery_disposition(
    *,
    link_id: str,
    source_session_id: str,
    target_session_id: str,
    failure: _MalformedConversationSegment,
    disposition: ConversationDeliveryDisposition,
    cursor_advanced: bool,
) -> bool:
    """Persist and observe one bounded outcome for an unprocessable entry."""
    recorded = await db.mark_conversation_delivery_disposition(
        link_id=link_id,
        source_session_id=source_session_id,
        target_session_id=target_session_id,
        disposition=disposition,
        entry_ref=failure.entry_ref,
        reason=failure.reason,
    )
    if recorded:
        logger.info(
            _DELIVERY_DISPOSITION_EVENT,
            outcome=disposition.value,
            reason=failure.reason.value,
            link_id=link_id,
            source_session_id=source_session_id,
            target_session_id=target_session_id,
            entry_ref=failure.entry_ref,
            replay_boundary=failure.entry_timestamp.isoformat(),
            cursor_advanced=cursor_advanced,
        )
    return recorded


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
            _CURSOR_BACKFILLED_EVENT,
            link_id=link_id,
            source_session_id=source_session_id,
            target_session_id=target_session_id,
            anchored_at=cursor_dt.isoformat(),
        )
    since_timestamp = cursor_dt
    if not source_session.native_log_file:
        return 0

    target_session = await db.get_session(target_session_id)
    recipient_policy = visibility_policy_for_person(
        human_role=target_session.human_role if target_session is not None else HUMAN_ROLE_ADMIN,
        person_email=target_session.human_email if target_session is not None else None,
        surface=ProjectionSurface.WEB,
    )
    all_projected = await _collect_visible_conversation_segments_since(
        source_session.native_log_file,
        agent_name,
        since_timestamp,
        source_session_id,
        recipient_policy,
    )
    target_computer = _target_computer_name(peer_computer)

    if isinstance(all_projected, _MalformedConversationSegment):
        logger.error(
            _MALFORMED_PEER_SEGMENT_EVENT,
            source_session_id=source_session_id,
            target_session_id=target_session_id,
            link_id=link_id,
            replay_boundary=since_timestamp.isoformat(),
            entry_ref=all_projected.entry_ref,
            reason=all_projected.reason.value,
        )
        recorded = await _record_delivery_disposition(
            link_id=link_id,
            source_session_id=source_session_id,
            target_session_id=target_session_id,
            failure=all_projected,
            disposition=ConversationDeliveryDisposition.TERMINAL_MALFORMED,
            cursor_advanced=True,
        )
        if recorded:
            await db.upsert_conversation_delivery_state(
                link_id=link_id,
                source_session_id=source_session_id,
                target_session_id=target_session_id,
                delivered_through_ts=all_projected.entry_timestamp.isoformat(),
                pending_through_ts=None,
            )
        return 0

    resolved_authors = await _resolve_session_authors(source_session, all_projected)
    if resolved_authors is None:
        logger.error(
            _MISSING_HUMAN_IDENTITY_EVENT,
            source_session_id=source_session_id,
            target_session_id=target_session_id,
            link_id=link_id,
            human_email_present=bool(source_session.human_email),
        )
        return 0
    agent_author, human_author = resolved_authors
    all_segments = _build_conversation_segments(
        all_projected,
        source_session_id=source_session_id,
        agent_author=agent_author,
        human_author=human_author,
    )
    deliverable_segments, _ = suppress_bare_noop_segments(all_segments)
    target_segments = _retain_segments_for_target(deliverable_segments, target_session_id, link_id=link_id)

    pending_dt: datetime | None = None
    if persisted is not None and persisted.pending_through_ts:
        pending_candidate = parse_iso_datetime(persisted.pending_through_ts)
        if pending_candidate is not None and pending_candidate > cursor_dt:
            pending_dt = pending_candidate

    delivered = 0
    if pending_dt is not None:
        pending_settlement = await settle_pending_bundle(
            source_session=source_session,
            link_id=link_id,
            target_session_id=target_session_id,
            target_computer=target_computer,
            pending_dt=pending_dt,
            source_segments=all_segments,
            deliverable_segments=target_segments,
            since_timestamp=since_timestamp,
            source_computer=source_computer,
            client=client,
            command_service=command_service,
        )
        if not pending_settlement.settled:
            return 0
        delivered += int(pending_settlement.bundle_delivered)
        fresh_untrimmed = [segment for segment in all_segments if segment.source_timestamp > pending_dt]
        since_timestamp = pending_dt
        cursor_iso: str | None = pending_dt.isoformat()
    else:
        fresh_untrimmed = all_segments
        cursor_iso = cursor_dt.isoformat()

    fresh_processed = _trim_trailing_user_turn(fresh_untrimmed)
    latest_source_timestamp = _max_segment_source_timestamp(fresh_processed)
    if latest_source_timestamp is None:
        return delivered
    fresh_deliverable, bare_noop_suppressed = suppress_bare_noop_segments(fresh_processed)
    fresh_segments = _retain_segments_for_target(fresh_deliverable, target_session_id, link_id=link_id)

    if not fresh_segments:
        await db.upsert_conversation_delivery_state(
            link_id=link_id,
            source_session_id=source_session_id,
            target_session_id=target_session_id,
            delivered_through_ts=latest_source_timestamp.isoformat(),
            pending_through_ts=None,
        )
        settlement_outcome, settlement_reason = empty_bundle_settlement(bare_noop_suppressed=bare_noop_suppressed)
        record_bundle_settled(
            outcome=settlement_outcome,
            reason=settlement_reason,
            link_id=link_id,
            source_session_id=source_session_id,
            target_session_id=target_session_id,
            bundle_key=None,
            delivered_through_ts=latest_source_timestamp,
        )
        return delivered

    await db.upsert_conversation_delivery_state(
        link_id=link_id,
        source_session_id=source_session_id,
        target_session_id=target_session_id,
        delivered_through_ts=cursor_iso,
        pending_through_ts=latest_source_timestamp.isoformat(),
    )
    try:
        bundle_delivered, _, bundle_key = await deliver_bundle(
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
            _DELIVERY_FAILED_EVENT,
            link_id=link_id,
            source_session_id=source_session_id,
            target_session_id=target_session_id,
            error=str(exc),
        )
        return delivered
    if not bundle_delivered:
        return delivered
    # Advance cursor past all fresh segments so the next iteration doesn't re-process them.
    await db.upsert_conversation_delivery_state(
        link_id=link_id,
        source_session_id=source_session_id,
        target_session_id=target_session_id,
        delivered_through_ts=latest_source_timestamp.isoformat(),
        pending_through_ts=None,
    )
    record_bundle_settled(
        outcome=BundleSettlementOutcome.ADVANCED,
        reason=BundleSettlementReason.BUNDLE_DELIVERED,
        link_id=link_id,
        source_session_id=source_session_id,
        target_session_id=target_session_id,
        bundle_key=bundle_key,
        delivered_through_ts=latest_source_timestamp,
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
            # Each (link, peer) pair reads and advances its own directional
            # cursor (db.conversation_delivery_state, keyed by link+source+
            # target) — a shared loop with no per-pair isolation is its own
            # kind of shared bit: an unhandled failure delivering to one peer
            # would abort every remaining pair's attempt this pass, even
            # though their cursors are otherwise fully independent. One
            # stalled direction must leave every other direction delivering.
            try:
                delivered += await _deliver_for_peer(
                    source_session=source_session,
                    link=link,
                    peer=peer,
                    agent_name=agent_name,
                    source_computer=source_computer,
                    client=client,
                    command_service=service,
                )
            except Exception as exc:
                logger.warning(
                    _PEER_PASS_FAILED_EVENT,
                    link_id=link.link_id,
                    source_session_id=source_session_id,
                    target_session_id=peer.session_id,
                    error=str(exc),
                    exc_info=True,
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
                _DELIVERY_FAILED_EVENT,
                source_session_id=source_session_id,
                error=str(exc),
                trigger="debounced",
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
