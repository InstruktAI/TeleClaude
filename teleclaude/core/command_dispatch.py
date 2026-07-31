"""Computer-aware command dispatch for local and peer-owned commands."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from teleclaude.config import config
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.models import JsonDict, JsonValue, MessageMetadata
from teleclaude.core.reconciliation import DEFAULT_FEATURE_ID_REGISTRY, decode_capability_set
from teleclaude.types.commands import CommandType, InternalCommand, ResponseMode

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient


COMMAND_HANDLER_METHODS: dict[CommandType, str] = {
    CommandType.CREATE_SESSION: "create_session",
    CommandType.PROCESS_MESSAGE: "process_message",
    CommandType.HANDLE_VOICE: "handle_voice",
    CommandType.HANDLE_FILE: "handle_file",
    CommandType.KEYS: "keys",
    CommandType.START_AGENT: "start_agent",
    CommandType.RESUME_AGENT: "resume_agent",
    CommandType.RESTART_AGENT: "restart_agent",
    CommandType.RUN_AGENT_COMMAND: "run_agent_command",
    CommandType.GET_SESSION_DATA: "get_session_data",
    CommandType.UNSUBSCRIBE_SESSION: "unsubscribe",
    CommandType.CLOSE_SESSION: "close_session",
    CommandType.SYSTEM: "system_command",
}

PEER_NAME_FIELD = "name"
PEER_CAPABILITY_SET_FIELD = "capability_set"
PEER_VERSION_FIELD = "version"
PEER_VERSION_CONTEXT_TEMPLATE = " (version {version})"
PEER_VERSION_SKEW_DIAGNOSTIC_TEMPLATE = (
    "Remote command {command} failed on {target_computer}: {target_computer} appears to be running "
    "an outdated TeleClaude build{version_context}; update it. Original peer error: {error}"
)
NO_VERSION_CONTEXT = ""


class RemoteDispatchError(RuntimeError):
    """Raised when a peer returns an error or malformed response envelope."""


class PeerReportedError(RemoteDispatchError):
    """Raised when a peer returns an error response envelope."""


def is_remote_target(computer: str | None, local_computer: str) -> bool:
    """Return whether a command targets a peer computer rather than this one."""
    return bool(computer) and computer not in ("local", local_computer)


def parse_remote_dispatch_data(
    envelope_text: str,
    *,
    target_computer: str,
    command: str,
) -> JsonValue:
    try:
        envelope_obj: object = json.loads(envelope_text)
    except json.JSONDecodeError as exc:
        raise RemoteDispatchError(f"Remote command {command} returned invalid JSON") from exc

    if not isinstance(envelope_obj, dict):
        raise RemoteDispatchError(f"Remote command {command} returned invalid response")

    envelope = cast(JsonDict, envelope_obj)
    status = envelope.get("status")
    if status == "error":
        error = envelope.get("error")
        detail = str(error) if error else f"Remote command {command} failed on {target_computer}"
        raise PeerReportedError(detail)
    if status != "success":
        raise RemoteDispatchError(f"Remote command {command} returned invalid status")

    return envelope.get("data")


async def diagnose_peer_dispatch_failure(
    client: AdapterClient,
    *,
    target_computer: str,
    command: str,
    error: PeerReportedError,
) -> PeerReportedError:
    """Enrich a peer-reported error when discovery proves the peer is behind."""
    for peer in await client.discover_peers():
        if peer.get(PEER_NAME_FIELD) != target_computer:
            continue
        peer_capabilities = frozenset(decode_capability_set(peer.get(PEER_CAPABILITY_SET_FIELD)))
        if not DEFAULT_FEATURE_ID_REGISTRY.carried_set() - peer_capabilities:
            return error
        peer_version = peer.get(PEER_VERSION_FIELD)
        version_context = (
            PEER_VERSION_CONTEXT_TEMPLATE.format(version=peer_version)
            if isinstance(peer_version, str) and peer_version
            else NO_VERSION_CONTEXT
        )
        return PeerReportedError(
            PEER_VERSION_SKEW_DIAGNOSTIC_TEMPLATE.format(
                command=command,
                target_computer=target_computer,
                version_context=version_context,
                error=error,
            )
        )
    return error


async def parse_remote_dispatch_data_diagnosed(
    client: AdapterClient,
    envelope_text: str,
    *,
    target_computer: str,
    command: str,
) -> JsonValue:
    """Parse a peer response and enrich only peer-reported failures."""
    try:
        return parse_remote_dispatch_data(
            envelope_text,
            target_computer=target_computer,
            command=command,
        )
    except PeerReportedError as error:
        diagnosed_error = await diagnose_peer_dispatch_failure(
            client,
            target_computer=target_computer,
            command=command,
            error=error,
        )
        if diagnosed_error is error:
            raise
        raise diagnosed_error from error


async def run_local_command(command: InternalCommand) -> JsonValue | None:
    """Run an internal command against this computer's command service."""
    cmds = get_command_service()
    handler_name = COMMAND_HANDLER_METHODS.get(command.command_type)
    if handler_name is None:
        raise ValueError(f"No handler registered for command type: {command.command_type.value}")
    handler = getattr(cmds, handler_name)

    if command.response_mode == ResponseMode.RECEIPT:
        raise ValueError(
            f"RECEIPT commands must go through OperationsService, "
            f"not the command dispatcher: {command.command_type.value}"
        )

    if command.response_mode == ResponseMode.FIRE_AND_FORGET:
        await handler(command)
        return None

    result = await handler(command)
    return cast(JsonValue, result)


async def execute_command_envelope(command: InternalCommand) -> JsonDict:
    """Run a command and return the Redis request/response envelope."""
    try:
        data = await run_local_command(command)
    except (OSError, RuntimeError, LookupError, ValueError, TypeError) as exc:
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "data": data}


async def forward_command_to_peer(client: AdapterClient, command: InternalCommand) -> JsonValue | None:
    """Forward a serialized command to the peer named by ``command.computer``."""
    target_computer = command.computer
    if not target_computer:
        raise ValueError("command.computer is required for peer forwarding")

    message_id = await client.send_request(
        target_computer,
        command.command_type.value,
        MessageMetadata(),
        session_id=getattr(command, "session_id", None),
        command_payload=command.to_dict(),
    )
    if command.response_mode == ResponseMode.FIRE_AND_FORGET:
        return None

    timeout = 30.0 if command.command_type is CommandType.CREATE_SESSION else 3.0
    if command.command_type is CommandType.KEYS:
        timeout = 10.0
    response_text = await client.read_response(
        message_id,
        timeout=timeout,
        target_computer=target_computer,
    )
    return await parse_remote_dispatch_data_diagnosed(
        client,
        response_text,
        target_computer=target_computer,
        command=command.command_type.value,
    )


async def dispatch_command(client: AdapterClient | None, command: InternalCommand) -> JsonValue | None:
    """Dispatch locally or forward once based on ``command.computer``."""
    if is_remote_target(command.computer, config.computer.name):
        if client is None:
            raise RuntimeError("No transport adapter available for remote execution")
        return await forward_command_to_peer(client, command)
    return await run_local_command(command)
