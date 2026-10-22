"""Operation ownership derived from command facts stored on the row."""

from __future__ import annotations

import json
from typing import cast

from fastapi import HTTPException

from teleclaude.config.machine import config
from teleclaude.core.db_models import Operation
from teleclaude.core.models._types import JsonDict
from teleclaude.core.operations._kinds import (
    _COMMAND_TYPE_TO_OPERATION_KIND,
    OperationKind,
)
from teleclaude.types.command_wire import command_from_dict

_SESSION_OPERATION_KINDS = frozenset(
    {OperationKind.SESSION_CLOSE, OperationKind.AGENT_RESTART, OperationKind.AGENT_HANDOFF}
)


def was_started_by_principal(operation: Operation, principal: str) -> bool:
    """Match a remote operation to the principal recorded on its command."""
    if operation.kind not in _SESSION_OPERATION_KINDS:
        return False
    try:
        payload = json.loads(operation.payload_json)
        if not isinstance(payload, dict):
            return False
        command = command_from_dict(cast(JsonDict, payload))
    except (KeyError, TypeError, ValueError):
        return False
    return (
        _COMMAND_TYPE_TO_OPERATION_KIND.get(command.command_type) == operation.kind
        and command.relayed_principal == principal
    )


CALLER_CONTINUITY_REFUSED = "Operation caller continuity is unavailable or disagrees with the recorded caller"


def require_caller_continuity(
    operation: Operation, principal: str | None, computer: str | None, session_id: str | None
) -> None:
    """Check every existing-row return without rewriting its immutable submission identity."""
    remote = any(value is not None and value != config.computer.name for value in (computer, operation.caller_computer))
    # Legacy local receipts retain their old address-based dedupe; absence never becomes a stored principal.
    if (
        ((remote or operation.caller_principal is not None) and operation.caller_principal != principal)
        or operation.caller_computer != computer
        or operation.caller_session_id != session_id
        or (remote and (not principal or not operation.caller_principal))
    ):
        raise HTTPException(status_code=409, detail=CALLER_CONTINUITY_REFUSED)
