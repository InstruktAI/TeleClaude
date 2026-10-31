"""Resolve caller authority and execute requests on the computer holding their objects."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import assert_never, cast

from fastapi import HTTPException
from pydantic import TypeAdapter

from teleclaude.caller_identity import (
    CliCaller,
    NoIdentityCliCaller,
    PersonCliCaller,
    ProjectPath,
    RelayedAct,
    RoleResolver,
    RoleTarget,
    SessionOf,
    SystemCliCaller,
    ThisComputer,
    caller_from_principal,
    is_operator_principal,
)
from teleclaude.cli.telec.auth import is_command_allowed
from teleclaude.config.machine import config
from teleclaude.constants import HUMAN_ROLE_CUSTOMER, LOGIN_REQUIRED_DETAIL
from teleclaude.core import command_handlers
from teleclaude.core.agent_status_projection import project_peer_agent_status
from teleclaude.core.command_dispatch import execute_command_envelope
from teleclaude.core.db import SessionRecordAbsent, SessionRecordFound, SessionRecordOutsideReach, db
from teleclaude.core.models import JsonDict, JsonValue, RedisInboundMessage, SessionEntryPoint
from teleclaude.core.models._types import json_int
from teleclaude.core.operations.service import get_operations_service
from teleclaude.core.session_inspection import OUTSIDE_REACH_DETAIL_TEMPLATE, inspect_local
from teleclaude.core.session_listing import (
    SESSION_IDS_FIELD,
    SessionListingSelection,
    build_session_listing_selection,
    normalize_session_ids,
)
from teleclaude.core.session_message_projection import (
    SessionMessageProjectionOptions,
    build_session_messages_dto,
)
from teleclaude.core.session_pane import get_session_pane
from teleclaude.core.session_status import AgentStatusValue
from teleclaude.history.search_payload import HistorySearchPayload
from teleclaude.history.service import (
    HistoryDetailPayload,
    HistoryRelayCommand,
    HistoryShowRequest,
    build_history_detail_payload,
    build_history_search_payload,
    parse_history_agents,
    resolve_history_reach,
)
from teleclaude.identity_reach import Reach
from teleclaude.types.command_wire import command_from_dict
from teleclaude.types.commands import (
    CommandType,
    CreateSessionCommand,
    InternalCommand,
    ProcessMessageCommand,
    RelayRequestCommand,
)
from teleclaude.utils.transcript_discovery import SessionId

_SESSION_ID_FIELD = "session_id"
_INCLUDE_CLOSED_FIELD = "include_closed"
_OPERATION_ID_FIELD = "operation_id"
_Q_FIELD = "q"
_AGENT_FIELD = "agent"
_LIMIT_FIELD = "limit"
_INCLUDE_WORKERS_FIELD = "include_workers"
_IDENTITY_FIELD = "identity"
_PROJECT_FIELD = "project"
_SINCE_FIELD = "since"
_INCLUDE_TOOLS_FIELD = "include_tools"
_INCLUDE_THINKING_FIELD = "include_thinking"
_HISTORY_THINKING_FIELD = "thinking"
_HISTORY_RAW_FIELD = "raw"
_TAIL_CHARS_FIELD = "tail_chars"
_TAIL_SCOPE_FIELD = "tail_scope"
_AGENT_STATUS_FIELD = "agent_status"
_AGENT_STATUS_EXACT_FIELD = "agent_status_exact"
_PANE_RUNTIME_FIELD = "runtime"
_PANE_CAPTURED_AT_FIELD = "captured_at"
_PANE_AVAILABLE_FIELD = "available"
_PANE_TEXT_FIELD = "text"
_DEFAULT_TAIL_CHARS = 10000
_DEFAULT_HISTORY_AGENT = "all"
_DEFAULT_HISTORY_LIMIT = 20
_DEFAULT_TAIL_SCOPE = "all"
_JSON_SERIALIZATION_MODE = "json"
_SESSION_KIND = "session"
_OPERATION_KIND = "operation"
_NOT_FOUND_DETAIL_TEMPLATE = "{kind} {object_id} not found on {computer}"
_UNKNOWN_ACT_DETAIL_TEMPLATE = "unknown relayed act on {computer}"
_NOT_PERMITTED_DETAIL_TEMPLATE = "role '{role}' is not permitted to call {act} on {computer}"
_COMMAND_PAYLOAD_REQUIRED_DETAIL = "command payload is required for relayed execution"
_INVALID_HISTORY_ACCESS_DETAIL = LOGIN_REQUIRED_DETAIL
_HISTORY_SHOW_REQUEST_ADAPTER: TypeAdapter[HistoryShowRequest] = TypeAdapter(HistoryShowRequest)


class RelayRead(StrEnum):
    """Closed set of caller-facing reads executed by the computer that owns the data."""

    SESSION_MESSAGES = "get_session_messages"
    SESSION_PANE = "get_session_pane"
    OPERATION = "get_operation"
    SESSIONS = "list_sessions"
    SESSION_RECORD = "get_session_record"


class RelayedReadNotFound(LookupError):
    """A caller read whose object is absent or outside its owner's reachable scope."""


def act_for_command(command: InternalCommand) -> RelayedAct | None:
    """Derive the person-band verb from the command this computer will execute."""
    match command.command_type:
        case CommandType.CREATE_SESSION:
            if not isinstance(command, CreateSessionCommand):
                return None
            if command.entry_point is SessionEntryPoint.API_CREATE:
                return RelayedAct.START
            if command.entry_point is SessionEntryPoint.RUN_SESSION_API:
                return RelayedAct.RUN
            return None
        case CommandType.PROCESS_MESSAGE | CommandType.KEYS:
            return RelayedAct.SEND
        case CommandType.CLOSE_SESSION:
            return RelayedAct.END
        case CommandType.RESTART_AGENT:
            return RelayedAct.RESTART
        case CommandType.REVIVE_AGENT:
            return RelayedAct.REVIVE
        case CommandType.UNSUBSCRIBE_SESSION:
            return RelayedAct.UNSUBSCRIBE
        case (
            CommandType.HANDLE_VOICE
            | CommandType.HANDLE_FILE
            | CommandType.START_AGENT
            | CommandType.RESUME_AGENT
            | CommandType.RUN_AGENT_COMMAND
            | CommandType.HANDOFF_AGENT
            | CommandType.GET_SESSION_DATA
            | CommandType.SYSTEM
            | CommandType.SET_VOICE_FOCUS
            | CommandType.ACTIVATE_PROCEDURE
            | CommandType.RELAY_REQUEST
        ):
            return None
        case _:
            return assert_never(command.command_type)


def act_for_read(command: str | HistoryRelayCommand) -> RelayedAct | None:
    """Resolve a caller read to the same person band used by its command form."""
    if command == HistoryRelayCommand.SEARCH.value:
        return RelayedAct.HISTORY_SEARCH
    if command == HistoryRelayCommand.SHOW.value:
        return RelayedAct.HISTORY_SHOW
    try:
        read = RelayRead(command)
    except ValueError:
        return None
    match read:
        case RelayRead.SESSION_MESSAGES | RelayRead.SESSION_PANE:
            return RelayedAct.TAIL
        case RelayRead.OPERATION:
            return RelayedAct.OPERATIONS_GET
        case RelayRead.SESSIONS:
            return RelayedAct.LIST
        case RelayRead.SESSION_RECORD:
            return RelayedAct.SHOW
        case _:
            return assert_never(read)


async def dispatch_relayed_command(
    command_payload: JsonDict | None,
    principal: str,
    *,
    request_id: str,
    source_computer: str | None,
) -> JsonDict:
    """Resolve a relay principal on this computer, admit the act, then execute it."""
    if command_payload is None:
        raise ValueError(_COMMAND_PAYLOAD_REQUIRED_DETAIL)
    command = command_from_dict(command_payload)
    command.request_id = request_id
    command.relayed_principal = None
    command.relayed_principal = principal
    if isinstance(command, RelayRequestCommand):
        # A relayed API request is admitted by its own handler, at the scope of the object it addresses.
        return await execute_command_envelope(command, source_computer=source_computer)
    caller = caller_from_principal(principal)
    resolver = RoleResolver()
    act = act_for_command(command)
    session, target = await _command_target(command, act)
    role = _authorize(caller, act, target, resolver)
    _apply_resolved_person(command, caller, session, role)
    if isinstance(command, CreateSessionCommand):
        # Only the relayed principal decides the operator here; the flag the sender serialized is never trusted.
        command.operator = is_operator_principal(principal)
    return await execute_command_envelope(command, source_computer=source_computer)


async def execute_relayed_read(
    command: str,
    message: RedisInboundMessage,
) -> JsonValue:
    """Answer a relay read using the principal and records held by this computer."""
    principal = message.caller_principal
    caller = caller_from_principal(principal)
    resolver = RoleResolver()
    act = act_for_read(command)
    computer = config.computer.name
    request = message.origin_metadata or {}
    session_id = message.session_id or ""
    session: object | None = None
    target: RoleTarget = ThisComputer()
    if command in (RelayRead.SESSION_MESSAGES.value, RelayRead.SESSION_PANE.value):
        session = await db.get_session(session_id) if session_id else None
        if session is None:
            raise _read_not_found(_SESSION_KIND, session_id, computer)
        target = SessionOf(session.project_path)
    if command == RelayRead.SESSION_RECORD.value and session_id:
        # An absent id keeps the computer target; its read answers not-found below.
        recorded_session = await db.get_session(session_id)
        if recorded_session is not None:
            target = SessionOf(recorded_session.project_path)
    _authorize(caller, act, target, resolver)

    if command == RelayRead.SESSION_MESSAGES.value:
        role = resolver.role_for(caller, target) if isinstance(caller, PersonCliCaller) else None
        try:
            dto = await build_session_messages_dto(
                session_id,
                recipient_email=caller.email if isinstance(caller, PersonCliCaller) else None,
                recipient_role=role,
                options=_session_message_projection_options(request),
            )
        except LookupError as exc:
            raise _read_not_found(_SESSION_KIND, session_id, computer) from exc
        messages_payload = cast(JsonDict, dto.model_dump(mode=_JSON_SERIALIZATION_MODE))
        exact_status = dto.agent_status or AgentStatusValue.UNKNOWN
        messages_payload[_AGENT_STATUS_FIELD] = project_peer_agent_status(exact_status).value
        messages_payload[_AGENT_STATUS_EXACT_FIELD] = exact_status.value
        return messages_payload

    if command == RelayRead.SESSION_PANE.value:
        try:
            pane = await get_session_pane(session_id)
        except LookupError as exc:
            raise _read_not_found(_SESSION_KIND, session_id, computer) from exc
        return {
            _SESSION_ID_FIELD: pane.session_id,
            _PANE_RUNTIME_FIELD: pane.runtime,
            _PANE_CAPTURED_AT_FIELD: pane.captured_at.isoformat(),
            _PANE_AVAILABLE_FIELD: pane.available,
            _PANE_TEXT_FIELD: pane.text,
        }

    if command == RelayRead.OPERATION.value:
        operation_id_raw = request.get(_OPERATION_ID_FIELD)
        operation_id = operation_id_raw if isinstance(operation_id_raw, str) else ""
        try:
            operation = await get_operations_service().get_operation_for_caller(
                operation_id=operation_id,
                caller_session_id=None,
                caller=caller,
                relayed_principal=principal,
            )
        except HTTPException as exc:
            if exc.status_code == 404:
                raise _read_not_found(_OPERATION_KIND, operation_id, computer) from exc
            raise
        return cast(JsonDict, dict(operation))

    if command == RelayRead.SESSIONS.value:
        include_closed_raw = request.get(_INCLUDE_CLOSED_FIELD)
        include_closed = include_closed_raw if isinstance(include_closed_raw, bool) else False
        try:
            session_ids = normalize_session_ids(request.get(SESSION_IDS_FIELD))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        selection: SessionListingSelection = build_session_listing_selection(
            caller,
            include_closed=include_closed,
            session_ids=session_ids,
        )
        sessions = await command_handlers.list_sessions(selection=selection)
        return cast(
            JsonValue,
            [session.to_peer_dict() for session in sessions],
        )

    if command == RelayRead.SESSION_RECORD.value:
        record_read = await inspect_local(caller, session_id)
        match record_read:
            case SessionRecordFound(values=values):
                return values
            case SessionRecordOutsideReach():
                raise PermissionError(OUTSIDE_REACH_DETAIL_TEMPLATE.format(session_id=session_id, computer=computer))
            case SessionRecordAbsent():
                raise _read_not_found(_SESSION_KIND, session_id, computer)
            case _:
                assert_never(record_read)

    if command == HistoryRelayCommand.SEARCH.value:
        reach = await _history_reach(caller)
        agent_filter = _string_or_default(request.get(_AGENT_FIELD), _DEFAULT_HISTORY_AGENT)
        agents = parse_history_agents(agent_filter)
        limit_raw = request.get(_LIMIT_FIELD)
        limit = limit_raw if isinstance(limit_raw, int) else _DEFAULT_HISTORY_LIMIT
        include_workers_raw = request.get(_INCLUDE_WORKERS_FIELD)
        include_workers = include_workers_raw if isinstance(include_workers_raw, bool) else False
        search_payload: HistorySearchPayload = await asyncio.to_thread(
            build_history_search_payload,
            computer=computer,
            query=_string_or_default(request.get(_Q_FIELD), ""),
            agents=agents,
            limit=limit,
            reach=reach,
            include_workers=include_workers,
            identity=_optional_string(request.get(_IDENTITY_FIELD)),
            project=_optional_string(request.get(_PROJECT_FIELD)),
        )
        return cast(JsonValue, search_payload)

    if command == HistoryRelayCommand.SHOW.value:
        show_data = cast(Mapping[str, object], _HISTORY_SHOW_REQUEST_ADAPTER.validate_python(request))
        requested_session = str(SessionId(cast(str, show_data[_SESSION_ID_FIELD])))
        detail_payload: HistoryDetailPayload | None = await asyncio.to_thread(
            build_history_detail_payload,
            requested_session,
            reach=await _history_reach(caller),
            agents=parse_history_agents(cast(str, show_data[_AGENT_FIELD])),
            include_thinking=cast(bool, show_data[_HISTORY_THINKING_FIELD]),
            raw=cast(bool, show_data[_HISTORY_RAW_FIELD]),
        )
        return cast(JsonValue, detail_payload)

    raise PermissionError(_UNKNOWN_ACT_DETAIL_TEMPLATE.format(computer=computer))


async def redecide_deferred(command: InternalCommand) -> None:
    """Recheck a relay-authorized receipt command against the target's current session facts."""
    principal = command.relayed_principal
    if principal is None:
        return
    act = act_for_command(command)
    if act not in (RelayedAct.END, RelayedAct.RESTART):
        return
    session_id = _command_session_id(command)
    session = await db.get_session(session_id) if session_id else None
    if session is None:
        return
    caller = caller_from_principal(principal)
    target: RoleTarget = SessionOf(session.project_path)
    _authorize(caller, act, target, RoleResolver())


async def _command_target(
    command: InternalCommand,
    act: RelayedAct | None,
) -> tuple[object | None, RoleTarget]:
    if act in (RelayedAct.START, RelayedAct.RUN):
        if isinstance(command, CreateSessionCommand):
            return None, ProjectPath(Path(command.project_path))
        return None, ThisComputer()
    session_id = _command_session_id(command)
    session = await db.get_session(session_id) if session_id else None
    if session is None:
        return None, ThisComputer()
    return session, SessionOf(session.project_path)


def _command_session_id(command: InternalCommand) -> str | None:
    session_id = getattr(command, _SESSION_ID_FIELD, None)
    return session_id if isinstance(session_id, str) and session_id else None


def _authorize(
    caller: CliCaller,
    act: RelayedAct | None,
    target: RoleTarget,
    resolver: RoleResolver,
) -> str | None:
    if isinstance(caller, SystemCliCaller):
        return None
    if act is None or isinstance(caller, NoIdentityCliCaller):
        raise PermissionError(_UNKNOWN_ACT_DETAIL_TEMPLATE.format(computer=config.computer.name))
    role = resolver.role_for(caller, target)
    if not is_command_allowed(act.value, None, role):
        raise PermissionError(
            _NOT_PERMITTED_DETAIL_TEMPLATE.format(role=role, act=act.value, computer=config.computer.name)
        )
    return role


def _apply_resolved_person(
    command: InternalCommand,
    caller: CliCaller,
    session: object | None,
    role: str | None,
) -> None:
    if isinstance(command, CreateSessionCommand) and isinstance(caller, PersonCliCaller):
        command.human_email = caller.email
        command.human_role = None
    if isinstance(command, ProcessMessageCommand):
        command.sender_human_role = None
        if isinstance(caller, PersonCliCaller) and session is not None:
            command.sender_human_role = role or HUMAN_ROLE_CUSTOMER


def _session_message_projection_options(data: JsonDict) -> SessionMessageProjectionOptions:
    include_tools_raw = data.get(_INCLUDE_TOOLS_FIELD)
    return SessionMessageProjectionOptions(
        since=_optional_string(data.get(_SINCE_FIELD)),
        include_tools=include_tools_raw if isinstance(include_tools_raw, bool) else None,
        include_thinking=bool(data.get(_INCLUDE_THINKING_FIELD)),
        tail_chars=json_int(data.get(_TAIL_CHARS_FIELD) or _DEFAULT_TAIL_CHARS),
        tail_scope=_string_or_default(data.get(_TAIL_SCOPE_FIELD), _DEFAULT_TAIL_SCOPE),
    )


async def _history_reach(caller: CliCaller) -> Reach:
    reach = await asyncio.to_thread(resolve_history_reach, caller)
    if reach is None:
        raise PermissionError(_INVALID_HISTORY_ACCESS_DETAIL)
    return reach


def _read_not_found(kind: str, object_id: str, computer: str) -> RelayedReadNotFound:
    return RelayedReadNotFound(_NOT_FOUND_DETAIL_TEMPLATE.format(kind=kind, object_id=object_id, computer=computer))


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _string_or_default(value: object, default: str) -> str:
    return value if isinstance(value, str) else default
