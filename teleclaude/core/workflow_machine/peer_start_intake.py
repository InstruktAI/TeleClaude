"""The computer that holds an item answers another computer\'s request to record or settle a helper start.

``local/projects/teleclaude/spec/feature/workflow/item-lifecycle`` (Helpers of a driver). Only the platform\'s own
principal may ask. The creator\'s membership is judged here, on this computer\'s item records and cluster evidence.
"""

from __future__ import annotations

from typing import cast

from teleclaude.caller_identity import SystemCliCaller, caller_from_principal
from teleclaude.config.machine import config
from teleclaude.core.models import JsonDict, JsonValue, RedisInboundMessage
from teleclaude.core.workflow_machine.helpers import (
    HelperStartRefused,
    register_from_ancestor,
    settle_helper_start,
)
from teleclaude.core.workflow_machine.peer_starts import (
    ANCESTOR_FIELD,
    CREATOR_COMPUTER_FIELD,
    CREATOR_FIELD,
    DEADLINE_FIELD,
    ENTRIES_FIELD,
    KEYS_FIELD,
    NEW_COMPUTER_FIELD,
    PARENT_FIELD,
    SESSION_COMPUTER_FIELD,
    SESSION_FIELD,
    START_KEY_FIELD,
    PeerStartRequest,
    StartEntry,
    creation_open_here,
    keys_still_open,
)
from teleclaude.types.workflow_record import RemoteMember

PEER_START_COMMANDS = frozenset(request.value for request in PeerStartRequest)
SYSTEM_ONLY = "{request} is answered for the platform's own principal only"
MALFORMED = "{request} on {computer} carries no {field}"


def _text(request: JsonDict, field: str, command: str) -> str:
    value = request.get(field)
    if not isinstance(value, str) or not value:
        raise PermissionError(MALFORMED.format(request=command, computer=config.computer.name, field=field))
    return value


def _number(request: JsonDict, field: str, command: str) -> float:
    value = request.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise PermissionError(MALFORMED.format(request=command, computer=config.computer.name, field=field))
    return float(value)


async def serve_peer_start(command: str, message: RedisInboundMessage) -> JsonValue:
    """Record or settle helper starts on this computer\'s items for a creator on another computer."""
    if not isinstance(caller_from_principal(message.caller_principal), SystemCliCaller):
        raise PermissionError(SYSTEM_ONLY.format(request=command))
    request: JsonDict = dict(message.origin_metadata or {})
    local = config.computer.name
    if command == PeerStartRequest.REGISTER.value:
        try:
            entries = await register_from_ancestor(
                _text(request, CREATOR_FIELD, command),
                _text(request, CREATOR_COMPUTER_FIELD, command),
                _text(request, ANCESTOR_FIELD, command),
                _text(request, NEW_COMPUTER_FIELD, command),
                _text(request, START_KEY_FIELD, command),
                _number(request, DEADLINE_FIELD, command),
            )
        except HelperStartRefused as refusal:
            raise PermissionError(str(refusal)) from refusal
        return cast(JsonValue, [entry.to_wire() for entry in entries])
    if command == PeerStartRequest.IN_FLIGHT.value:
        asked = request.get(KEYS_FIELD)
        if not isinstance(asked, list):
            raise PermissionError(MALFORMED.format(request=command, computer=local, field=KEYS_FIELD))
        return cast(JsonValue, await keys_still_open([key for key in asked if isinstance(key, str)]))
    if command == PeerStartRequest.CREATION_STATE.value:
        keys = request.get(KEYS_FIELD)
        key = keys[0] if isinstance(keys, list) and keys and isinstance(keys[0], str) else ""
        if not key:
            raise PermissionError(MALFORMED.format(request=command, computer=local, field=KEYS_FIELD))
        return creation_open_here(key, _number(request, DEADLINE_FIELD, command))
    session_id = request.get(SESSION_FIELD)
    session_computer = request.get(SESSION_COMPUTER_FIELD)
    parent = request.get(PARENT_FIELD)
    raw_entries = request.get(ENTRIES_FIELD)
    if not isinstance(session_id, str) or not isinstance(session_computer, str) or not isinstance(raw_entries, list):
        raise PermissionError(MALFORMED.format(request=command, computer=local, field=SESSION_FIELD))
    remote = (
        RemoteMember(session_id=session_id, computer=session_computer, parent=str(parent or ""))
        if session_id and session_computer != local and parent
        else None
    )
    for raw in raw_entries:
        entry = StartEntry.from_wire(raw)
        if entry is not None:
            await settle_helper_start(entry.root, entry.item, entry.key, session_id, remote)
    return []
