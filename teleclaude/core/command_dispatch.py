"""Computer-aware command dispatch for local and peer-owned commands."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from redis.exceptions import RedisError

from teleclaude.config.machine import config
from teleclaude.constants import SHUTDOWN_REFUSAL_KIND
from teleclaude.core.agent_dispatch import (
    AgentDispatchFailure,
    AgentDispatchOutcome,
    AgentDispatchReason,
    AgentDispatchStage,
    emit_agent_dispatch_decision,
)
from teleclaude.core.command_input import CommandInputMode
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.models import AgentDispatchMode, JsonDict, JsonValue, MessageMetadata
from teleclaude.core.models._types import SessionOriginMetadata
from teleclaude.core.reconciliation import (
    DEFAULT_FEATURE_ID_REGISTRY,
    DETERMINISTIC_AGENT_ROUTING_FEATURE_ID,
    HANDOFF_AGENT_FEATURE_ID,
    INTERACTIVE_COMMAND_INPUT_FEATURE_ID,
    decode_capability_set,
)
from teleclaude.core.shutdown_drain import ShutdownRefusal
from teleclaude.types.commands import (
    CommandType,
    CreateSessionCommand,
    HandoffAgentCommand,
    InternalCommand,
    ProcessMessageCommand,
    ResponseMode,
)

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
    CommandType.HANDOFF_AGENT: "handoff_agent",
    CommandType.REVIVE_AGENT: "restart_agent",
    CommandType.RUN_AGENT_COMMAND: "run_agent_command",
    CommandType.GET_SESSION_DATA: "get_session_data",
    CommandType.UNSUBSCRIBE_SESSION: "unsubscribe",
    CommandType.CLOSE_SESSION: "close_session",
    CommandType.SYSTEM: "system_command",
    CommandType.SET_VOICE_FOCUS: "set_voice_focus",
    CommandType.ACTIVATE_PROCEDURE: "activate_procedure",
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
_RELAY_FAILURE_DETAIL_TEMPLATE = "Remote {command} on {computer} failed: {detail}"
_RELAY_FAILURE_ENVELOPE_DETAIL = ""
_ERROR_KIND_FIELD = "kind"
_ERROR_DETAIL_FIELD = "detail"
_NOT_FOUND_ERROR_KIND = "not_found"
_REFUSED_ERROR_KIND = "refused_by_target"
_RETRY_AFTER_FIELD = "retry_after_seconds"
_READ_TIMEOUT_DETAIL = "target did not answer before the read timed out"
_PEER_REQUEST_DETAIL = "peer request failed"


class RemoteDispatchReason(StrEnum):
    """Stable reasons that a remote dispatch boundary may refuse."""

    TARGET_DISPATCH_CAPABILITY_REQUIRED = "target_dispatch_capability_required"
    INVALID_REMOTE_JSON = "invalid_remote_json"
    INVALID_REMOTE_RESPONSE = "invalid_remote_response"
    INVALID_REMOTE_STATUS = "invalid_remote_status"
    PEER_REPORTED_ERROR = "peer_reported_error"
    REMOTE_DISPATCH_FAILED = "remote_dispatch_failed"
    UNREACHABLE = "unreachable"
    NOT_FOUND = "not_found"
    REFUSED_BY_TARGET = "refused_by_target"
    PEER_DRAINING = "peer_draining"
    PEER_ERROR = "peer_error"


_RELAY_ERROR_KIND_REASONS: dict[str, RemoteDispatchReason] = {
    _NOT_FOUND_ERROR_KIND: RemoteDispatchReason.NOT_FOUND,
    _REFUSED_ERROR_KIND: RemoteDispatchReason.REFUSED_BY_TARGET,
    SHUTDOWN_REFUSAL_KIND: RemoteDispatchReason.PEER_DRAINING,
}


class RemoteDispatchError(RuntimeError):
    """Raised when a peer returns an error or malformed response envelope."""

    def __init__(
        self,
        message: str,
        *,
        reason: RemoteDispatchReason = RemoteDispatchReason.REMOTE_DISPATCH_FAILED,
    ) -> None:
        super().__init__(message)
        self.reason = reason


class PeerReportedError(RemoteDispatchError):
    """Raised when a peer returns an error response envelope."""

    def __init__(self, message: str) -> None:
        super().__init__(message, reason=RemoteDispatchReason.PEER_REPORTED_ERROR)


class RelayFailure(RemoteDispatchError):
    """A caller read failed on its named target computer."""

    def __init__(
        self,
        *,
        computer: str,
        command: str,
        reason: RemoteDispatchReason,
        detail: str,
    ) -> None:
        self.computer = computer
        self.command = command
        super().__init__(
            _RELAY_FAILURE_DETAIL_TEMPLATE.format(command=command, computer=computer, detail=detail),
            reason=reason,
        )


def is_relay_failure_detail(detail: object, *, command: str, computer: str) -> bool:
    """Whether a failure detail is the envelope ``RelayFailure`` writes for a failed read on ``computer``."""
    envelope_prefix = _RELAY_FAILURE_DETAIL_TEMPLATE.format(
        command=command, computer=computer, detail=_RELAY_FAILURE_ENVELOPE_DETAIL
    )
    return isinstance(detail, str) and detail.startswith(envelope_prefix)


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
        raise RemoteDispatchError(
            f"Remote command {command} returned invalid JSON",
            reason=RemoteDispatchReason.INVALID_REMOTE_JSON,
        ) from exc

    if not isinstance(envelope_obj, dict):
        raise RemoteDispatchError(
            f"Remote command {command} returned invalid response",
            reason=RemoteDispatchReason.INVALID_REMOTE_RESPONSE,
        )

    envelope = cast(JsonDict, envelope_obj)
    status = envelope.get("status")
    if status == "error":
        error = envelope.get("error")
        if isinstance(error, dict) and error.get(_ERROR_KIND_FIELD) in _RELAY_ERROR_KIND_REASONS:
            relay_reason = _RELAY_ERROR_KIND_REASONS[str(error.get(_ERROR_KIND_FIELD))]
            detail_raw = error.get(_ERROR_DETAIL_FIELD)
            detail = detail_raw if isinstance(detail_raw, str) else str(error)
            raise RelayFailure(computer=target_computer, command=command, reason=relay_reason, detail=detail)
        if isinstance(error, dict) and error.get("kind") == "agent_dispatch_failure":
            try:
                reason = AgentDispatchReason(str(error.get("reason")))
            except ValueError as exc:
                raise RemoteDispatchError(
                    "Remote dispatch returned an invalid refusal", reason=RemoteDispatchReason.INVALID_REMOTE_RESPONSE
                ) from exc
            raise AgentDispatchFailure(reason, "Target refused the dispatch request")
        detail = str(error) if error else f"Remote command {command} failed on {target_computer}"
        raise PeerReportedError(detail)
    if status != "success":
        raise RemoteDispatchError(
            f"Remote command {command} returned invalid status",
            reason=RemoteDispatchReason.INVALID_REMOTE_STATUS,
        )

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


async def relay_caller_read(
    client: AdapterClient,
    target: str,
    read: str,
    *,
    principal: str,
    session_id: str | None = None,
    request: JsonDict | None = None,
) -> JsonValue:
    """Send one caller read through the relay and normalize its typed failures."""
    try:
        message_id = await client.send_request(
            target,
            read,
            MessageMetadata(origin_metadata=cast(SessionOriginMetadata | None, request)),
            principal=principal,
            session_id=session_id,
        )
        response_text = await client.read_response(message_id, target_computer=target)
    except TimeoutError as exc:
        raise RelayFailure(
            computer=target,
            command=read,
            reason=RemoteDispatchReason.UNREACHABLE,
            detail=str(exc) or _READ_TIMEOUT_DETAIL,
        ) from exc
    except (OSError, RedisError) as exc:
        raise RelayFailure(
            computer=target,
            command=read,
            reason=RemoteDispatchReason.PEER_ERROR,
            detail=str(exc) or _PEER_REQUEST_DETAIL,
        ) from exc

    try:
        return await parse_remote_dispatch_data_diagnosed(
            client,
            response_text,
            target_computer=target,
            command=read,
        )
    except AgentDispatchFailure as exc:
        raise RelayFailure(
            computer=target,
            command=read,
            reason=RemoteDispatchReason.REFUSED_BY_TARGET,
            detail=str(exc),
        ) from exc
    except PeerReportedError as exc:
        raise RelayFailure(
            computer=target,
            command=read,
            reason=RemoteDispatchReason.PEER_ERROR,
            detail=str(exc),
        ) from exc


async def invoke_command_handler(command: InternalCommand, *, source_computer: str | None = None) -> JsonValue | None:
    """Resolve and run this computer's handler for a command, unconditionally.

    The *execution* entry: it runs the handler regardless of response mode and
    reads no mode itself. An operation's own work body calls this directly —
    by the time an operation is running, the submit decision has already been
    made, and routing back through the *dispatch* entry (``run_local_command``)
    would re-submit the command it is already executing.
    """
    cmds = get_command_service()
    handler_name = COMMAND_HANDLER_METHODS.get(command.command_type)
    if handler_name is None:
        raise ValueError(f"No handler registered for command type: {command.command_type.value}")
    handler = getattr(cmds, handler_name)

    result = await handler(command)
    return cast(JsonValue, result)


async def run_local_command(command: InternalCommand, *, source_computer: str | None = None) -> JsonValue | None:
    """Run an internal command against this computer's command service.

    A RECEIPT command reaching this *dispatch* entry is submitted, never
    executed here: this computer owns the command (local caller, or a peer's
    forward that landed on the owning computer), so it persists the row and
    returns the receipt as this call's result. The operation's own work body
    is what later calls ``invoke_command_handler`` to actually run it.
    """
    if command.response_mode == ResponseMode.RECEIPT:
        from teleclaude.core.operations.service import (  # noqa: PLC0415 - deferred: operations.service imports invoke_command_handler from this module
            get_operations_service,
        )

        receipt = await get_operations_service().submit(
            command, caller=command.caller, client_request_id=command.request_id
        )
        return cast(JsonValue, dict(receipt))

    return await invoke_command_handler(command, source_computer=source_computer)


def shutdown_refusal_envelope(refusal: ShutdownRefusal) -> JsonDict:
    """The retryable reply that answers work this draining computer refused before accepting it."""
    return {
        "status": "error",
        "error": {
            _ERROR_KIND_FIELD: SHUTDOWN_REFUSAL_KIND,
            _ERROR_DETAIL_FIELD: str(refusal),
            _RETRY_AFTER_FIELD: refusal.retry_after_seconds,
        },
    }


async def execute_command_envelope(command: InternalCommand, *, source_computer: str | None = None) -> JsonDict:
    """Run a command and return the Redis request/response envelope."""
    try:
        data = await run_local_command(command, source_computer=source_computer)
    except ShutdownRefusal as exc:
        return shutdown_refusal_envelope(exc)
    except AgentDispatchFailure as exc:
        return {"status": "error", "error": {"kind": "agent_dispatch_failure", "reason": exc.reason.value}}
    except (OSError, RuntimeError, LookupError, ValueError, TypeError) as exc:
        return {"status": "error", "error": str(exc)}
    return {"status": "success", "data": data}


def required_command_capabilities(command: InternalCommand) -> frozenset[str]:
    """Return capabilities required by a command's concrete routing semantics."""
    required: set[str] = set()
    if isinstance(command, (CreateSessionCommand, ProcessMessageCommand)) and (
        command.command_input_mode is CommandInputMode.INTERACTIVE_SHORTHAND
    ):
        required.add(INTERACTIVE_COMMAND_INPUT_FEATURE_ID)
    if isinstance(command, CreateSessionCommand):
        intent = command.launch_intent
        if intent is not None and intent.dispatch_mode in {
            AgentDispatchMode.AUTOMATIC,
            AgentDispatchMode.MANUAL_PREFERENCE,
        }:
            required.add(DETERMINISTIC_AGENT_ROUTING_FEATURE_ID)
    if isinstance(command, HandoffAgentCommand):
        required.add(HANDOFF_AGENT_FEATURE_ID)
    return frozenset(required)


async def forward_command_to_peer(
    client: AdapterClient, command: InternalCommand, *, principal: str
) -> JsonValue | None:
    """Forward a serialized command and its required principal to its owning peer.

    The receiving computer resolves the principal and makes the person decision
    from its own session and project records.
    """
    target_computer = command.computer
    if not target_computer:
        raise ValueError("command.computer is required for peer forwarding")

    peer = next((item for item in await client.discover_peers() if item.get(PEER_NAME_FIELD) == target_computer), None)
    capabilities = frozenset(decode_capability_set(peer.get(PEER_CAPABILITY_SET_FIELD))) if peer else frozenset()
    missing_capabilities = required_command_capabilities(command) - capabilities
    if missing_capabilities:
        emit_agent_dispatch_decision(
            stage=AgentDispatchStage.TRANSPORT,
            outcome=AgentDispatchOutcome.REFUSED,
            reason=AgentDispatchReason.TARGET_CAPABILITY_MISSING,
            request_id=command.request_id,
        )
        missing = ", ".join(sorted(missing_capabilities))
        raise RemoteDispatchError(
            f"Target computer lacks required command capabilities: {missing}",
            reason=RemoteDispatchReason.TARGET_DISPATCH_CAPABILITY_REQUIRED,
        )
    if isinstance(command, CreateSessionCommand):
        intent = command.launch_intent
        needs_target_resolution = intent is not None and intent.dispatch_mode in {
            AgentDispatchMode.AUTOMATIC,
            AgentDispatchMode.MANUAL_PREFERENCE,
        }
        if needs_target_resolution:
            emit_agent_dispatch_decision(
                stage=AgentDispatchStage.TRANSPORT,
                outcome=AgentDispatchOutcome.FORWARDED,
                reason=AgentDispatchReason.TARGET_CAPABILITY_PRESENT,
                request_id=command.request_id,
                dispatch_mode=intent.dispatch_mode,
                entry_point=command.entry_point,
                job_role=command.job,
            )
        elif intent is not None and intent.dispatch_mode is AgentDispatchMode.FIXED:
            emit_agent_dispatch_decision(
                stage=AgentDispatchStage.TRANSPORT,
                outcome=AgentDispatchOutcome.LEGACY_FIXED,
                reason=AgentDispatchReason.FIXED_INTENT,
                selected_agent=intent.agent,
                request_id=command.request_id,
                dispatch_mode=intent.dispatch_mode,
                entry_point=command.entry_point,
                job_role=command.job,
            )

    message_id = await client.send_request(
        target_computer,
        command.command_type.value,
        MessageMetadata(),
        principal=principal,
        session_id=getattr(command, "session_id", None),
        command_payload=command.to_dict(),
    )

    timeout = 30.0 if command.command_type is CommandType.CREATE_SESSION else 3.0
    if command.command_type is CommandType.KEYS:
        timeout = 10.0
    elif command.response_mode is ResponseMode.RECEIPT:
        # Submission is a persist-and-return on the owning computer — not the
        # command's own work — so it needs less room than an IMMEDIATE round trip.
        timeout = 2.0
    try:
        response_text = await client.read_response(
            message_id,
            timeout=timeout,
            target_computer=target_computer,
        )
    except TimeoutError as exc:
        raise RelayFailure(
            computer=target_computer,
            command=command.command_type.value,
            reason=RemoteDispatchReason.UNREACHABLE,
            detail=_READ_TIMEOUT_DETAIL,
        ) from exc
    except (OSError, RedisError) as exc:
        raise RelayFailure(
            computer=target_computer,
            command=command.command_type.value,
            reason=RemoteDispatchReason.PEER_ERROR,
            detail=str(exc) or _PEER_REQUEST_DETAIL,
        ) from exc
    return await parse_remote_dispatch_data_diagnosed(
        client,
        response_text,
        target_computer=target_computer,
        command=command.command_type.value,
    )


async def dispatch_command(
    client: AdapterClient | None,
    command: InternalCommand,
    *,
    principal: str | None,
) -> JsonValue | None:
    """Dispatch locally or forward once based on ``command.computer``."""
    if is_remote_target(command.computer, config.computer.name):
        if client is None:
            raise RuntimeError("No transport adapter available for remote execution")
        if principal is None:
            raise ValueError("A principal is required for a relayed command")
        return await forward_command_to_peer(client, command, principal=principal)
    return await run_local_command(command)
