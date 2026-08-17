"""Directional conversation-delivery cursor settlement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.conversation_bundle_delivery import replay_pending_bundle
from teleclaude.core.conversation_segments import ConversationSegment, LocalConversationPayload
from teleclaude.core.db import db
from teleclaude.core.session_output import is_bare_noop_output
from teleclaude.output_projection.models import TranscriptChannel

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.command_service import CommandService
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_BUNDLE_SETTLED_EVENT = "conversation_delivery_bundle_settled"


class BundleSettlementOutcome(StrEnum):
    """Closed outcomes for directional cursor settlement."""

    ADVANCED = "advanced"
    NOT_ADVANCED = "not_advanced"


class BundleSettlementReason(StrEnum):
    """Closed reasons for directional cursor settlement."""

    BUNDLE_DELIVERED = "bundle_delivered"
    NOTHING_FRESH = "nothing_fresh"
    BARE_NOOP_SUPPRESSED = "bare_noop_suppressed"


@dataclass(frozen=True)
class PendingBundleSettlement:
    """Result of replaying or structurally suppressing a pending range."""

    settled: bool
    bundle_delivered: bool


def suppress_bare_noop_segments(segments: list[ConversationSegment]) -> tuple[list[ConversationSegment], bool]:
    """Remove locally authored assistant no-op segments without touching forwarded content."""
    retained: list[ConversationSegment] = []
    suppressed = False
    for segment in segments:
        payload = segment.payload
        if (
            isinstance(payload, LocalConversationPayload)
            and payload.role == TranscriptChannel.ASSISTANT
            and is_bare_noop_output(payload.message.body)
        ):
            suppressed = True
            continue
        retained.append(segment)
    return retained, suppressed


def empty_bundle_settlement(*, bare_noop_suppressed: bool) -> tuple[BundleSettlementOutcome, BundleSettlementReason]:
    """Resolve the evidence values for a fresh range with no deliverable segments."""
    if bare_noop_suppressed:
        return BundleSettlementOutcome.ADVANCED, BundleSettlementReason.BARE_NOOP_SUPPRESSED
    return BundleSettlementOutcome.NOT_ADVANCED, BundleSettlementReason.NOTHING_FRESH


def record_bundle_settled(
    *,
    outcome: BundleSettlementOutcome,
    reason: BundleSettlementReason,
    link_id: str,
    source_session_id: str,
    target_session_id: str,
    bundle_key: str | None,
    delivered_through_ts: datetime,
) -> None:
    """Observe delivery only after its directional cursor is durable."""
    logger.info(
        _BUNDLE_SETTLED_EVENT,
        outcome=outcome.value,
        reason=reason.value,
        link_id=link_id,
        source_session_id=source_session_id,
        target_session_id=target_session_id,
        bundle_key=bundle_key,
        delivered_through_ts=delivered_through_ts.isoformat(),
    )


async def settle_pending_bundle(
    *,
    source_session: Session,
    link_id: str,
    target_session_id: str,
    target_computer: str,
    pending_dt: datetime,
    source_segments: list[ConversationSegment],
    deliverable_segments: list[ConversationSegment],
    since_timestamp: datetime,
    source_computer: str | None,
    client: AdapterClient,
    command_service: CommandService,
) -> PendingBundleSettlement:
    """Replay a pending range or settle it silently when it contains only suppressed output."""
    pending_source = [segment for segment in source_segments if segment.source_timestamp <= pending_dt]
    _, bare_noop_suppressed = suppress_bare_noop_segments(pending_source)
    pending_deliverable = [segment for segment in deliverable_segments if segment.source_timestamp <= pending_dt]

    if bare_noop_suppressed and not pending_deliverable:
        bundle_delivered = False
        bundle_key = None
        reason = BundleSettlementReason.BARE_NOOP_SUPPRESSED
    else:
        bundle_delivered, bundle_key = await replay_pending_bundle(
            source_session=source_session,
            link_id=link_id,
            target_session_id=target_session_id,
            target_computer=target_computer,
            pending_dt=pending_dt,
            all_segments=deliverable_segments,
            since_timestamp=since_timestamp,
            source_computer=source_computer,
            client=client,
            command_service=command_service,
        )
        if not bundle_delivered:
            return PendingBundleSettlement(settled=False, bundle_delivered=False)
        reason = BundleSettlementReason.BUNDLE_DELIVERED

    await db.upsert_conversation_delivery_state(
        link_id=link_id,
        source_session_id=source_session.session_id,
        target_session_id=target_session_id,
        delivered_through_ts=pending_dt.isoformat(),
        pending_through_ts=None,
    )
    record_bundle_settled(
        outcome=BundleSettlementOutcome.ADVANCED,
        reason=reason,
        link_id=link_id,
        source_session_id=source_session.session_id,
        target_session_id=target_session_id,
        bundle_key=bundle_key,
        delivered_through_ts=pending_dt,
    )
    return PendingBundleSettlement(settled=True, bundle_delivered=bundle_delivered)
