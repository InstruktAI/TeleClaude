"""Operation ownership derived from command facts stored on the row."""

from __future__ import annotations

import json
from typing import cast

from teleclaude.core.db_models import Operation
from teleclaude.core.models._types import JsonDict
from teleclaude.core.operations._kinds import (
    _COMMAND_TYPE_TO_OPERATION_KIND,
    OPERATION_KIND_AGENT_HANDOFF,
    OPERATION_KIND_AGENT_RESTART,
    OPERATION_KIND_SESSION_CLOSE,
)
from teleclaude.types.commands import command_from_dict

_SESSION_OPERATION_KINDS = frozenset(
    {OPERATION_KIND_SESSION_CLOSE, OPERATION_KIND_AGENT_RESTART, OPERATION_KIND_AGENT_HANDOFF}
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
