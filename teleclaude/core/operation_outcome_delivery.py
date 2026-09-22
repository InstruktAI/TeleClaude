"""Deliver a durable operation's terminal outcome to its recorded caller, remote case."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.core.control_delivery import handoff_control_payload
from teleclaude.core.db import db
from teleclaude.core.inbound_errors import SessionMessageRejectedError
from teleclaude.core.injected_text import EnvelopeName, semantic_envelope

logger = get_logger(__name__)


async def deliver_remote_operation_outcome(
    caller_session_id: str,
    operation_id: str,
    computer: str,
    kind: str,
    outcome: str,
    slug: str | None = None,
) -> bool:
    """Deliver an operation's outcome address to its recorded caller on this computer.

    The owning computer's row (`computer`) is the authority for the operation;
    this delivers only an address — never the result or error — to the caller
    whose session lives here. Same shape as
    `session_listeners.deliver_remote_stop_notification`: the caller's
    identity travels on the wire because the owning computer holds no
    listener row for a session that was never created there.
    """
    caller = await db.get_session(caller_session_id)
    if not caller:
        logger.warning(
            "remote_operation_outcome_undeliverable",
            caller_session_id=caller_session_id,
            operation_id=operation_id,
        )
        return False
    body = f"Operation {operation_id} ({kind}) {outcome}"
    if slug:
        body += f" for {slug}"
    body += f" on {computer}. Run `telec operations get {operation_id} --computer {computer}` to read the result."
    try:
        await handoff_control_payload(
            session_id=caller_session_id,
            body=body,
            source_key=f"operation:{operation_id}",
            envelope=semantic_envelope(EnvelopeName.NOTIFICATION, body=body),
        )
    except SessionMessageRejectedError as exc:
        logger.warning(
            "remote_operation_outcome_delivery_failed",
            caller_session_id=caller_session_id,
            operation_id=operation_id,
            reason=exc.reason,
        )
        return False
    return True
