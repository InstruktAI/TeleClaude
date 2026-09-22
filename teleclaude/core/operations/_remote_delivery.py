"""Forward a durable operation's terminal outcome to the caller's own computer."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db_models import Operation
from teleclaude.core.models import MessageMetadata

logger = get_logger(__name__)


async def forward_outcome_to_caller_computer(operation: Operation, *, outcome: str) -> bool:
    """Forward the outcome notification to the computer the caller's session lives on.

    The owning computer (this one) keeps the row; only the address crosses
    the transport, via the same notification vocabulary
    `deliver_remote_stop_notification` already uses for a caller whose
    session was never created here.
    """
    assert operation.caller_session_id is not None
    assert operation.caller_computer is not None
    client = get_command_service().client
    slug_arg = operation.slug or "-"
    try:
        await client.send_request(
            operation.caller_computer,
            f"/operation_outcome {operation.operation_id} {config.computer.name} "
            f"{operation.caller_session_id} {operation.kind} {outcome} {slug_arg}",
            MessageMetadata(),
        )
    except Exception:
        logger.warning(
            "remote_operation_outcome_forward_failed",
            operation_id=operation.operation_id,
            caller_computer=operation.caller_computer,
            exc_info=True,
        )
        return False
    return True
