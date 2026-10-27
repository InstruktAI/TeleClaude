"""Carry one API request to a computer that executes it.

The single crossing from a request this computer holds to the computer that owns
what the request addresses
(`local/projects/teleclaude/spec/feature/integration/computer-addressed-execution`).
The API boundary carries a request whose caller named another computer; a daemon-side
service carries a request it chooses to send elsewhere. Both build the same
`RelayRequestCommand`, which always records the computer that requested it, so the
owner treats every carried request as relayed whether or not a caller session came
with it.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config
from teleclaude.core.command_dispatch import RELAY_REQUEST_TIMEOUT_S, RemoteDispatchError, dispatch_command
from teleclaude.core.models import JsonValue
from teleclaude.types.commands import RelayRequestCommand

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

_SENT_EVENT = "relay_request_sent"
_ANSWERED_EVENT = "relay_request_answered"
_FAILED_EVENT = "relay_request_failed"


@dataclass
class _CarrierState:
    """The transport requests are carried over."""

    client: AdapterClient | None = None


_STATE = _CarrierState()


def configure(client: AdapterClient | None) -> None:
    """Wire the transport client; called from APIServer."""
    _STATE.client = client


async def carry_request(
    *,
    destination: str,
    method: str,
    path: str,
    query: list[list[str]],
    body: bytes,
    content_type: str | None,
    principal: str,
    caller_session_id: str | None,
    cleared_command: str | None,
    deadline_s: float = RELAY_REQUEST_TIMEOUT_S,
) -> JsonValue | None:
    """Carry the request to ``destination`` and return the data block of its wire response.

    ``deadline_s`` is the seconds the request may take end to end: the owner refuses it after that,
    and this side waits no longer. A caller whose own wait is shorter than the default passes its
    budget so the relay never outlives the wait that issued it.

    Raises ``RelayFailure`` for a failure the relay names, ``RemoteDispatchError`` for any other
    refusal of the crossing, and ``RuntimeError`` or ``ValueError`` when the transport cannot send.
    """
    command = RelayRequestCommand(
        computer=destination,
        method=method,
        path=path,
        deadline_at=time.time() + deadline_s,
        query=query,
        body_b64=base64.b64encode(body).decode(),
        content_type=content_type,
        caller_session_id=caller_session_id,
        caller_computer=config.computer.name,
        cleared_command=cleared_command,
    )
    logger.info(
        _SENT_EVENT,
        computer=destination,
        method=command.method,
        path=command.path,
        command=command.cleared_command,
        caller_session_id=command.caller_session_id,
    )
    try:
        result = await dispatch_command(_STATE.client, command, principal=principal)
    except RemoteDispatchError as error:
        logger.warning(_FAILED_EVENT, computer=destination, reason=error.reason.value, error=str(error))
        raise
    except (RuntimeError, ValueError) as error:
        logger.warning(_FAILED_EVENT, computer=destination, error=str(error))
        raise
    logger.info(_ANSWERED_EVENT, computer=destination, method=command.method, path=command.path)
    return result
