"""Persist and present notices for terminal inbound delivery outcomes."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, NotRequired, TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.core.control_delivery import handoff_control_payload
from teleclaude.core.db import InboundQueueRow, db
from teleclaude.core.delivery.models import InvalidDestinationOverrideError
from teleclaude.core.delivery.router import Router, resolve_destination
from teleclaude.core.inbound_errors import SessionMessageRejectedError
from teleclaude.core.inbound_queue import (
    DeliveryTerminalCause,
    HoldNoticeRecipientUnavailableError,
)
from teleclaude.core.injected_text import (
    EnvelopeName,
    InjectedInputAuthority,
    InjectedTextSourceFeature,
    authority_for_source_feature,
    semantic_envelope,
)
from teleclaude.core.models import CleanupTrigger, MessageMetadata, Session
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_status import is_session_terminal

from ._message_acceptance import settle_undelivered_wake

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

_CONTINUATION_DELIVERY_FAILURE_NOTICE = (
    "Restart continuation stimulus could not be confirmed delivered. Session kept alive for inspection."
)
_INBOUND_HOLD_EXPIRED_NOTICE = "A message did not reach the agent because its input was occupied."
_HOLD_NOTICE_UI_ORIGINS = frozenset({InputOrigin.DISCORD, InputOrigin.TELEGRAM, InputOrigin.WHATSAPP})
_HOLD_NOTICE_NO_RECEIPT_ERROR = "Expired conversation notice received no channel delivery receipt"
_CALLER_SEND_DELIVERY_EXHAUSTED_EVENT = "caller_send_delivery_exhausted"
_CALLER_SEND_DELIVERY_FAILURE_NOTICE_TEMPLATE = (
    "Delivery to session {target_session_id} was exhausted before reaching its agent."
)
_CALLER_SEND_CONTROL_SOURCE_KEY_TEMPLATE = "caller-send-delivery-exhausted:{inbound_row_id}"


class _CallerSendDeliveryExhaustedOutcome(StrEnum):
    """Closed terminal outcomes for a caller-send delivery exhaustion."""

    CALLER_NOTIFIED = "caller_notified"
    UNADDRESSABLE = "unaddressable"
    NOTIFICATION_FAILED = "notification_failed"


class _CallerSendDeliveryExhaustedReason(StrEnum):
    """Closed reasons for each caller-send delivery exhaustion outcome."""

    CALLER_NOTIFIED = "caller_notified"
    CALLER_TERMINAL = "caller_terminal"
    CALLER_NOT_LOCAL = "caller_not_local"
    CALLER_ABSENT = "caller_absent"
    SELF_SEND = "self_send"
    CALLER_BECAME_UNAVAILABLE = "caller_became_unavailable"
    HANDOFF_ERROR = "handoff_error"


class _CallerSendDeliveryExhaustedLogFields(TypedDict):
    """Body-free correlations for one terminal caller-send exhaustion decision."""

    inbound_row_id: int
    target_session_id: str
    caller_session_id: str | None
    source_occurrence_id: str | None
    outcome: _CallerSendDeliveryExhaustedOutcome
    reason: _CallerSendDeliveryExhaustedReason
    control_payload_row_id: NotRequired[int]


def _record_caller_send_delivery_exhausted(
    row: InboundQueueRow,
    *,
    outcome: _CallerSendDeliveryExhaustedOutcome,
    reason: _CallerSendDeliveryExhaustedReason,
    control_payload_row_id: int | None = None,
) -> None:
    """Emit one body-free terminal decision for an exhausted caller-send row."""
    fields: _CallerSendDeliveryExhaustedLogFields = {
        "inbound_row_id": row["id"],
        "target_session_id": row["session_id"],
        "caller_session_id": row["caller_session_id"],
        "source_occurrence_id": row["occurrence_key"],
        "outcome": outcome,
        "reason": reason,
    }
    if control_payload_row_id is not None:
        fields["control_payload_row_id"] = control_payload_row_id
    logger.info(_CALLER_SEND_DELIVERY_EXHAUSTED_EVENT, **fields)


def _session_is_addressable(session: Session | None) -> bool:
    """Return whether a local session can receive a control-delivery handoff."""
    return session is not None and not is_session_terminal(
        lifecycle_status=session.lifecycle_status,
        closed_at=session.closed_at,
    )


async def _notify_caller_send_delivery_exhausted(row: InboundQueueRow) -> None:
    """Persist an exhaustion notice only for the original live local caller."""
    caller_session_id = row["caller_session_id"]
    target_session_id = row["session_id"]
    if caller_session_id is None:
        _record_caller_send_delivery_exhausted(
            row,
            outcome=_CallerSendDeliveryExhaustedOutcome.UNADDRESSABLE,
            reason=_CallerSendDeliveryExhaustedReason.CALLER_ABSENT,
        )
        return
    if caller_session_id == target_session_id:
        _record_caller_send_delivery_exhausted(
            row,
            outcome=_CallerSendDeliveryExhaustedOutcome.UNADDRESSABLE,
            reason=_CallerSendDeliveryExhaustedReason.SELF_SEND,
        )
        return

    caller_session = await db.get_session(caller_session_id)
    if caller_session is None:
        _record_caller_send_delivery_exhausted(
            row,
            outcome=_CallerSendDeliveryExhaustedOutcome.UNADDRESSABLE,
            reason=_CallerSendDeliveryExhaustedReason.CALLER_NOT_LOCAL,
        )
        return
    if not _session_is_addressable(caller_session):
        _record_caller_send_delivery_exhausted(
            row,
            outcome=_CallerSendDeliveryExhaustedOutcome.UNADDRESSABLE,
            reason=_CallerSendDeliveryExhaustedReason.CALLER_TERMINAL,
        )
        return

    notice_body = _CALLER_SEND_DELIVERY_FAILURE_NOTICE_TEMPLATE.format(target_session_id=target_session_id)
    try:
        control_payload_row_id = await handoff_control_payload(
            session_id=caller_session_id,
            body=notice_body,
            source_key=_CALLER_SEND_CONTROL_SOURCE_KEY_TEMPLATE.format(inbound_row_id=row["id"]),
            envelope=semantic_envelope(
                EnvelopeName.NOTIFICATION,
                body=notice_body,
            ),
        )
    except SessionMessageRejectedError:
        _record_caller_send_delivery_exhausted(
            row,
            outcome=_CallerSendDeliveryExhaustedOutcome.UNADDRESSABLE,
            reason=_CallerSendDeliveryExhaustedReason.CALLER_BECAME_UNAVAILABLE,
        )
        return
    except Exception:
        _record_caller_send_delivery_exhausted(
            row,
            outcome=_CallerSendDeliveryExhaustedOutcome.NOTIFICATION_FAILED,
            reason=_CallerSendDeliveryExhaustedReason.HANDOFF_ERROR,
        )
        raise

    if not _session_is_addressable(await db.get_session(caller_session_id)):
        _record_caller_send_delivery_exhausted(
            row,
            outcome=_CallerSendDeliveryExhaustedOutcome.UNADDRESSABLE,
            reason=_CallerSendDeliveryExhaustedReason.CALLER_BECAME_UNAVAILABLE,
            control_payload_row_id=control_payload_row_id,
        )
        return
    _record_caller_send_delivery_exhausted(
        row,
        outcome=_CallerSendDeliveryExhaustedOutcome.CALLER_NOTIFIED,
        reason=_CallerSendDeliveryExhaustedReason.CALLER_NOTIFIED,
        control_payload_row_id=control_payload_row_id,
    )


async def notify_delivery_exhausted(
    row: InboundQueueRow,
    cause: DeliveryTerminalCause,
    *,
    client: AdapterClient,
) -> None:
    """Present the durable notice associated with a terminal delivery cause.

    A control wake that ended undelivered first has its acceptance retired
    (``settle_undelivered_wake``), whatever the cause. A rejected row carries no
    notice. A conversation row that expired while held notifies its
    conversation channel. Every other terminal cause, including the expiry of a
    held platform-authored row, reaches the producer of the row.
    """
    await settle_undelivered_wake(row, cause)
    if cause is DeliveryTerminalCause.REJECTED:
        return
    source = InjectedTextSourceFeature(row["source_feature"])
    if (
        cause is DeliveryTerminalCause.HOLD_EXPIRED
        and authority_for_source_feature(source) is InjectedInputAuthority.CONVERSATION
    ):
        origin = InputOrigin(row["origin"])
        if origin not in _HOLD_NOTICE_UI_ORIGINS:
            raise HoldNoticeRecipientUnavailableError
        session = await db.get_session(row["session_id"])
        if session is None:
            raise HoldNoticeRecipientUnavailableError
        metadata = MessageMetadata(
            channel_id=row["source_channel_id"],
            target_adapter_key=origin.value,
        )
        try:
            if origin is InputOrigin.DISCORD and metadata.channel_id:
                destination = resolve_destination(session, origin.value, metadata=metadata)
                has_addressable_channel = destination.channel_id is not None
            else:
                has_addressable_channel = Router.origin_section_has_channel(session, origin.value)
        except InvalidDestinationOverrideError as exc:
            raise HoldNoticeRecipientUnavailableError from exc
        if not has_addressable_channel:
            raise HoldNoticeRecipientUnavailableError
        message_id = await client.send_message(
            session,
            _INBOUND_HOLD_EXPIRED_NOTICE,
            metadata=metadata,
            cleanup_trigger=CleanupTrigger.NEXT_TURN,
            ephemeral=False,
        )
        if message_id is None:
            raise RuntimeError(_HOLD_NOTICE_NO_RECEIPT_ERROR)
        return
    if row["source_feature"] == InjectedTextSourceFeature.CALLER_SEND.value:
        await _notify_caller_send_delivery_exhausted(row)
        return
    if row["source_feature"] != InjectedTextSourceFeature.AGENT_RESTART.value:
        return
    session = await db.get_session(row["session_id"])
    if session is None or is_session_terminal(
        lifecycle_status=session.lifecycle_status,
        closed_at=session.closed_at,
    ):
        return
    await client.send_message(session, _CONTINUATION_DELIVERY_FAILURE_NOTICE)
    logger.info(
        "agent_restart_continuation_delivery_failed",
        outcome="operator_notified",
        session_active=True,
        session_id=session.session_id,
        inbound_row_id=row["id"],
        occurrence_key=row["occurrence_key"],
    )
