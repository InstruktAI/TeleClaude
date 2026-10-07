"""Closed vocabularies and per-row delivery for an operation outcome decision."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.control_delivery import handoff_control_payload
from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.db_models import Operation
from teleclaude.core.inbound_errors import SessionMessageRejectedError
from teleclaude.core.injected_text import EnvelopeName, occurrence_fields, semantic_envelope
from teleclaude.core.operations._remote_delivery import forward_outcome_to_caller_computer

logger = get_logger(__name__)


class DeliveryReason(StrEnum):
    """Closed reasons recorded for an operation outcome delivery decision."""

    DELIVERED = "delivered"
    NO_CALLER = "no_caller"
    CALLER_UNREACHABLE = "caller_unreachable"
    DELIVERY_FAULT = "delivery_fault"


class DeliveryOutcome(StrEnum):
    """Closed terminal outcomes carried by an operation delivery decision."""

    STALE = "stale"
    COMPLETED = "completed"
    FAILED = "failed"


async def deliver_recovered_operations(
    operations: list[Operation],
    *,
    emit: Callable[..., None],
    deliver: Callable[..., Awaitable[None]],
) -> None:
    """Emit and deliver each retained operation's outcome, containing per-row faults.

    A raised fault is recorded under its own delivery-decision reason instead of
    propagating — the whole reason this delivery moved out of the operations
    startup stage is so a per-row fault here can no longer abort the boot.
    """
    for operation in operations:
        try:
            emit(operation.kind, operation.operation_id, error=operation.error_text)
            await deliver(
                operation, outcome=DeliveryOutcome.STALE, occurred_at=parse_iso_datetime(operation.completed_at)
            )
        except Exception as exc:
            logger.info(
                "operation_delivery_decision",
                operation_id=operation.operation_id,
                kind=operation.kind,
                outcome=DeliveryOutcome.STALE,
                reason=DeliveryReason.DELIVERY_FAULT,
                error=f"{type(exc).__name__}: {exc}",
                exc_info=True,
            )


async def deliver_operation_outcome(
    operation: Operation, *, outcome: DeliveryOutcome, occurred_at: datetime | None
) -> None:
    """Deliver an address — never the result or error — to the operation's recorded caller.

    A row with no recorded caller emits its event (already done by the
    caller) and delivers nothing. Delivery is not retried: the row already
    holds the outcome, so a retry buys nothing and risks a duplicate wake.
    """
    if not operation.caller_session_id:
        logger.info(
            "operation_delivery_decision",
            operation_id=operation.operation_id,
            kind=operation.kind,
            outcome=outcome,
            reason=DeliveryReason.NO_CALLER,
        )
        return

    if operation.caller_computer and operation.caller_computer != config.computer.name:
        delivered = await forward_outcome_to_caller_computer(operation, outcome=outcome, occurred_at=occurred_at)
        logger.info(
            "operation_delivery_decision",
            operation_id=operation.operation_id,
            kind=operation.kind,
            outcome=outcome,
            reason=DeliveryReason.DELIVERED if delivered else DeliveryReason.CALLER_UNREACHABLE,
        )
        return

    body = f"Operation {operation.operation_id} ({operation.kind}) {outcome}"
    if operation.slug:
        body += f" for {operation.slug}"
    body += f" on {config.computer.name}. Run `telec operations get {operation.operation_id}` to read the result."

    try:
        await handoff_control_payload(
            session_id=operation.caller_session_id,
            body=body,
            source_key=f"operation:{operation.operation_id}",
            envelope=semantic_envelope(EnvelopeName.NOTIFICATION, fields=occurrence_fields(occurred_at), body=body),
        )
    except SessionMessageRejectedError:
        logger.info(
            "operation_delivery_decision",
            operation_id=operation.operation_id,
            kind=operation.kind,
            outcome=outcome,
            reason=DeliveryReason.CALLER_UNREACHABLE,
        )
        return

    logger.info(
        "operation_delivery_decision",
        operation_id=operation.operation_id,
        kind=operation.kind,
        outcome=outcome,
        reason=DeliveryReason.DELIVERED,
    )
