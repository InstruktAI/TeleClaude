"""Closed vocabularies and per-row delivery for an operation outcome decision."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum

from instrukt_ai_logging import get_logger

from teleclaude.core.db_models import Operation

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
            await deliver(operation, outcome=DeliveryOutcome.STALE)
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
