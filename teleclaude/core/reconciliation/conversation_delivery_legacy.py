"""Legacy conversation-delivery migration: inventory, upcast, and disposition.

A one-time (or repeat-until-clean) reconciliation pass, distinct from the
live per-poll collector (`conversation_delivery.py`): it inventories every
directional delivery cursor, recognizes retained pre-cutover content under
either historical writer form, rebuilds a frozen range from transcript truth,
and records a bounded disposition for every reachable direction. Never wired
into the live collector — "legacy recognition is evidence-bound... a merely
unbound entry is never eligible," which the live per-poll path has no way to
prove for an arbitrary block; this pass proves it once, deliberately, against
each direction's own recorded cursor state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.conversation_bundle_delivery import deliver_bundle
from teleclaude.core.conversation_messages import (
    MalformedPeerSegmentError,
    is_conversation_bridge_message,
    parse_legacy_v1_header,
    parse_peer_segments,
    peer_segment_from_authored_span,
)
from teleclaude.core.conversation_segments import ConversationSegment, ForwardedConversationPayload
from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.db import db
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.models import MessageAuthor
from teleclaude.utils.transcript import _get_entries_for_agent, _parse_timestamp

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.command_service import CommandService
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_LEGACY_UPCAST_EVENT = "legacy_direction_upcast"
_LEGACY_DISPOSITION_EVENT = "legacy_direction_disposition"
_LEGACY_UNRESOLVED_EVENT = "legacy_direction_unresolved_author"
_LEGACY_RECOVERY_EVENT = "legacy_direction_recovered"
_LEGACY_RECOVERY_STUCK_EVENT = "legacy_direction_recovery_stuck"


class LegacyDirectionDisposition(StrEnum):
    """Bounded terminal outcomes for one reachable legacy direction.

    Per the Cutover and legacy state invariant "every cursor gets a
    disposition": recovered and advanced, closed with retained state
    recorded, or surfaced for explicit recovery. No automatic abandonment,
    no silent cursor promotion.
    """

    RECOVERED = "recovered"
    CLOSED_RECORDED = "closed_recorded"
    NEEDS_RECOVERY = "needs_recovery"
    NO_RETAINED_STATE = "no_retained_state"


@dataclass(frozen=True)
class LegacyDirectionInventoryEntry:
    """One directional cursor, as found during inventory."""

    link_id: str
    source_session_id: str
    target_session_id: str
    link_status: str  # "active" | "closed" | "missing"
    delivered_through_ts: str | None
    pending_through_ts: str | None


async def inventory_legacy_directions() -> list[LegacyDirectionInventoryEntry]:
    """Enumerate every directional delivery cursor, active and closed alike.

    Read-only: no cursor is touched. This is the full reachable set the
    reconciliation pass owes a disposition to.
    """
    rows = await db.get_all_conversation_delivery_states()
    entries: list[LegacyDirectionInventoryEntry] = []
    for row in rows:
        link = await db.get_conversation_link(row.link_id)
        link_status = link.status if link is not None else "missing"
        entries.append(
            LegacyDirectionInventoryEntry(
                link_id=row.link_id,
                source_session_id=row.source_session_id,
                target_session_id=row.target_session_id,
                link_status=link_status,
                delivered_through_ts=row.delivered_through_ts,
                pending_through_ts=row.pending_through_ts,
            )
        )
    return entries


async def _resolve_legacy_author(original_source_session_id: str) -> MessageAuthor | None:
    """Resolve an author for a V1 entry from the source session record.

    V1 carries no author-token, so identity comes from durable evidence: the
    originating session's own record, if it still exists. Returns ``None``
    when unresolvable — the caller surfaces this as needing explicit
    recovery rather than guessing an author.
    """
    session = await db.get_session(original_source_session_id)
    if session is None:
        return None
    if session.active_agent:
        return MessageAuthor.for_agent(
            session_id=original_source_session_id,
            active_agent=session.active_agent,
            thinking_mode=session.thinking_mode,
        )
    if session.human_email:
        try:
            display_name = get_identity_resolver().resolve_by_email(session.human_email).display_name
        except ValueError:
            return None
        return MessageAuthor.for_human(session_id=original_source_session_id, display_name=display_name)
    return None


@dataclass(frozen=True)
class UpcastSegment:
    """One upcast legacy segment: typed provenance plus its transcript body."""

    original_source_session_id: str
    author: MessageAuthor
    occurred_at: datetime
    body: str


async def upcast_legacy_block(raw_text: str, block_timestamp: datetime) -> list[UpcastSegment] | None:
    """Upcast one bridge-classified transcript block under either historical writer form.

    Tries the current author-token grammar first (still a valid historical
    form for entries written after that grammar existed but before this
    delivery's structural persistence). Falls back to V1
    (`[TeleClaude - Peer (id) on <computer>]`, no author-token) only when the
    current grammar fails to parse — V1 predates it entirely. Returns
    ``None`` when neither form parses, or a V1 header's author cannot be
    resolved from durable evidence — never a guessed attribution.
    """
    try:
        segments = parse_peer_segments(raw_text)
    except MalformedPeerSegmentError:
        segments = None
    if segments is not None:
        return [
            UpcastSegment(
                original_source_session_id=segment.original_source_session_id,
                author=segment.author,
                occurred_at=segment.occurred_at,
                body=segment.body,
            )
            for segment in segments
        ]

    v1_match = parse_legacy_v1_header(raw_text)
    if v1_match is None:
        return None
    original_source_session_id, _computer = v1_match
    author = await _resolve_legacy_author(original_source_session_id)
    if author is None:
        logger.error(_LEGACY_UNRESOLVED_EVENT, original_source_session_id=original_source_session_id)
        return None
    body = raw_text.split("]", 1)[1].lstrip("\n") if "]" in raw_text else ""
    logger.info(
        _LEGACY_UPCAST_EVENT,
        original_source_session_id=original_source_session_id,
        writer_form="v1",
    )
    return [
        UpcastSegment(
            original_source_session_id=original_source_session_id,
            author=author,
            occurred_at=block_timestamp,
            body=body,
        )
    ]


async def classify_direction_disposition(entry: LegacyDirectionInventoryEntry) -> LegacyDirectionDisposition:
    """Classify one direction's disposition from its cursor and link state.

    Read-only classification — records nothing. A direction with no pending
    bound has no retained legacy state to recover: "recovered" applies only
    once an actual replay has run. Callers that perform the replay upgrade
    ``NEEDS_RECOVERY`` to ``RECOVERED`` themselves, after a durable handoff.
    """
    if entry.pending_through_ts is None:
        disposition = LegacyDirectionDisposition.NO_RETAINED_STATE
    elif entry.link_status == "closed":
        disposition = LegacyDirectionDisposition.CLOSED_RECORDED
    else:
        disposition = LegacyDirectionDisposition.NEEDS_RECOVERY
    logger.info(
        _LEGACY_DISPOSITION_EVENT,
        link_id=entry.link_id,
        source_session_id=entry.source_session_id,
        target_session_id=entry.target_session_id,
        disposition=disposition.value,
    )
    return disposition


async def collect_legacy_range(
    source_session: Session,
    *,
    since_timestamp: datetime,
    through_timestamp: datetime,
) -> list[UpcastSegment] | None:
    """Rebuild one frozen range from transcript truth, upcasting every bridge block in it.

    Returns ``None`` when any block in the range fails to upcast under
    either writer form — the range is held for explicit recovery rather than
    partially replayed.
    """
    if not source_session.native_log_file or not source_session.active_agent:
        return None
    try:
        agent_name = AgentName.from_str(source_session.active_agent)
    except ValueError:
        return None

    entries = _get_entries_for_agent(source_session.native_log_file, agent_name)
    if not entries:
        return []

    collected: list[UpcastSegment] = []
    for entry in entries:
        message = entry.get("message")
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        raw_text = content if isinstance(content, str) else ""
        if not raw_text or not is_conversation_bridge_message(raw_text):
            continue
        raw_ts = entry.get("timestamp")
        entry_ts = _parse_timestamp(raw_ts) if isinstance(raw_ts, str) else None
        if entry_ts is None or entry_ts <= since_timestamp or entry_ts > through_timestamp:
            continue
        upcast = await upcast_legacy_block(raw_text, entry_ts)
        if upcast is None:
            return None
        collected.extend(upcast)

    return collected


async def reconcile_legacy_directions(
    *,
    client: AdapterClient,
    command_service: CommandService,
) -> dict[str, LegacyDirectionDisposition]:
    """Reconcile every reachable legacy direction to a durable, bounded outcome.

    For each inventoried direction: classify a disposition, and for
    ``NEEDS_RECOVERY``, rebuild the frozen range from transcript truth under
    either historical writer form, deliver it exactly once through the same
    bundle primitive the live collector uses, and advance the cursor —
    upgrading the direction to ``RECOVERED``. A direction whose range cannot
    be safely rebuilt or delivered stays ``NEEDS_RECOVERY`` rather than being
    silently promoted or abandoned; per the Cutover and legacy state
    invariant, every reachable direction gets a disposition, never a guess.

    This is the one call site that reuses ``conversation_bundle_delivery.py``'s
    exactly-once bundle-delivery primitive; the live per-poll collector never
    imports this module back (see module docstring — no wiring in either
    direction).
    """
    from teleclaude.core.conversation_delivery import (  # noqa: PLC0415 - deferred: breaks a circular import through output_projection.conversation_projector -> utils.transcript._rendering -> conversation_projector at module-load time
        _target_computer_name,
    )

    dispositions: dict[str, LegacyDirectionDisposition] = {}
    for entry in await inventory_legacy_directions():
        disposition = await classify_direction_disposition(entry)
        if disposition is not LegacyDirectionDisposition.NEEDS_RECOVERY:
            dispositions[entry.link_id] = disposition
            continue

        source_session = await db.get_session(entry.source_session_id)
        target_session = await db.get_session(entry.target_session_id)
        since_dt = parse_iso_datetime(entry.delivered_through_ts) if entry.delivered_through_ts else None
        pending_dt = parse_iso_datetime(entry.pending_through_ts) if entry.pending_through_ts else None
        if source_session is None or target_session is None or since_dt is None or pending_dt is None:
            logger.error(
                _LEGACY_RECOVERY_STUCK_EVENT,
                link_id=entry.link_id,
                source_session_id=entry.source_session_id,
                target_session_id=entry.target_session_id,
                reason="missing_session_or_cursor",
            )
            dispositions[entry.link_id] = disposition
            continue

        upcast_segments = await collect_legacy_range(
            source_session, since_timestamp=since_dt, through_timestamp=pending_dt
        )
        if not upcast_segments:
            logger.error(
                _LEGACY_RECOVERY_STUCK_EVENT,
                link_id=entry.link_id,
                source_session_id=entry.source_session_id,
                target_session_id=entry.target_session_id,
                reason="range_unreconstructable",
            )
            dispositions[entry.link_id] = disposition
            continue

        bundle_segments = [
            ConversationSegment(
                source_timestamp=segment.occurred_at,
                payload=ForwardedConversationPayload(
                    peer_segment=peer_segment_from_authored_span(
                        original_source_session_id=segment.original_source_session_id,
                        author=segment.author,
                        occurred_at=segment.occurred_at,
                        body=segment.body,
                    )
                ),
            )
            for segment in upcast_segments
        ]

        delivered, latest_ts = await deliver_bundle(
            source_session=source_session,
            link_id=entry.link_id,
            target_session_id=entry.target_session_id,
            target_computer=_target_computer_name(target_session.computer_name),
            segments=bundle_segments,
            since_timestamp=since_dt,
            source_computer=source_session.computer_name,
            client=client,
            command_service=command_service,
        )
        if not delivered or latest_ts is None:
            logger.error(
                _LEGACY_RECOVERY_STUCK_EVENT,
                link_id=entry.link_id,
                source_session_id=entry.source_session_id,
                target_session_id=entry.target_session_id,
                reason="delivery_failed",
            )
            dispositions[entry.link_id] = disposition
            continue

        await db.upsert_conversation_delivery_state(
            link_id=entry.link_id,
            source_session_id=entry.source_session_id,
            target_session_id=entry.target_session_id,
            delivered_through_ts=latest_ts.isoformat(),
            pending_through_ts=None,
        )
        logger.info(
            _LEGACY_RECOVERY_EVENT,
            link_id=entry.link_id,
            source_session_id=entry.source_session_id,
            target_session_id=entry.target_session_id,
            recovered_through_ts=latest_ts.isoformat(),
        )
        dispositions[entry.link_id] = LegacyDirectionDisposition.RECOVERED

    return dispositions
