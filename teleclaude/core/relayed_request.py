"""Run an API request another computer carried here, as the caller this computer resolves.

The relaying computer authenticated its caller and carried the request whole
(`local/projects/teleclaude/spec/feature/integration/computer-addressed-execution`).
This computer decides the cleared command's person band from the caller's
principal and its own registries, at the scope of the object the request
addresses, then re-enters its own API with identity headers it authored itself
(`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`).
Nothing the relaying computer says about its caller beyond the principal and the
command it cleared is read as authority.
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass, replace
from http import HTTPStatus
from pathlib import Path
from typing import Final

import httpx
from instrukt_ai_logging import get_logger
from starlette.types import ASGIApp

from teleclaude.caller_identity import (
    CarriedIdentity,
    CliCaller,
    NoIdentityCliCaller,
    Person,
    PersonCliCaller,
    Platform,
    ProjectPath,
    RelayedAct,
    RoleResolver,
    RoleTarget,
    SessionOf,
    SystemCliCaller,
    ThisComputer,
    caller_from_principal,
)
from teleclaude.cli import CommandScope
from teleclaude.cli.telec.auth import command_scope, is_command_allowed
from teleclaude.config.machine import config
from teleclaude.config.referents import ReferentKind, unregistered_referent
from teleclaude.config.registered_homes import project_folder
from teleclaude.constants import LOGIN_REQUIRED_DETAIL
from teleclaude.core.db import db
from teleclaude.core.models import JsonDict
from teleclaude.core.operation_caller_identity import RelayedCaller, reset_relayed_caller, set_relayed_caller
from teleclaude.types.commands import RelayRequestCommand
from teleclaude.types.relayed_response import RelayedResponse

logger = get_logger(__name__)

_JSON_CONTENT_TYPE = "application/json"
# Headers describing one hop or the encoding of the bytes crossed here; the receiving side re-derives them.
_TRANSPORT_HEADERS: Final = frozenset(
    {
        "connection",
        "content-encoding",
        "content-length",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_CONTENT_TYPE_HEADER = "content-type"
_DETAIL_FIELD = "detail"
_REENTRY_BASE_URL = "http://localhost"
_SESSION_ID_GROUP = "session_id"
_SESSION_PATH = re.compile(rf"^/sessions/(?P<{_SESSION_ID_GROUP}>[^/]+)(?:/|$)")
_SESSIONLESS_SEGMENTS: Final = frozenset({"self", "run"})
# Fields whose value is a project path wherever a route takes it: a registered identity there is resolved here.
_PROJECT_PATH_FIELDS: Final = ("cwd", "project_path", "project_root")
# A route that takes `project` reads it as a path or as an identity itself; here it only names the scope of the object.
_PROJECT_REFERENCE_FIELDS: Final = (*_PROJECT_PATH_FIELDS, "project")
_THIS_COMPUTER_COMMANDS: Final = frozenset(
    act.value
    for act in (
        RelayedAct.LIST,
        RelayedAct.SHOW,
        RelayedAct.OPERATIONS_GET,
        RelayedAct.HISTORY_SEARCH,
        RelayedAct.HISTORY_SHOW,
    )
)
_ADMITTED_EVENT = "relay_request_admitted"
_REFUSED_EVENT = "relay_request_refused"
_LATE_DETAIL = "{method} {path} reached {computer} after its deadline; nothing was run."
_NO_COMMAND_DETAIL = "the request to {computer} names no command it was cleared as; nothing was run."
_NOT_PERMITTED_DETAIL = "role '{role}' is not permitted to call {command} on {computer}"
_APP_UNAVAILABLE_DETAIL = "{computer} has no API to carry the request into"
_REENTRY_FAILED_DETAIL = "the request could not be carried into the API: {error}"


@dataclass
class _ReentryState:
    """The ASGI application relayed requests re-enter."""

    app: ASGIApp | None = None


_REENTRY = _ReentryState()


def configure(app: ASGIApp) -> None:
    """Wire the API application relayed requests re-enter; called from APIServer."""
    _REENTRY.app = app


class _RelayRefused(Exception):
    """A relayed request this computer refuses before running it."""

    def __init__(self, status_code: HTTPStatus, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class _RelayedRequestView:
    """The parts of a relayed request that name the object it addresses."""

    path: str
    query: dict[str, str]
    body: dict[str, object] | None  # guard: loose-dict - the carried request body is route-defined JSON

    @classmethod
    def from_command(cls, command: RelayRequestCommand) -> _RelayedRequestView:
        query: dict[str, str] = {}
        for pair in command.query:
            if len(pair) == 2:
                query.setdefault(pair[0], pair[1])
        body: dict[str, object] | None = None  # guard: loose-dict - the carried request body is route-defined JSON
        raw_body = base64.b64decode(command.body_b64) if command.body_b64 else b""
        if raw_body:
            try:
                parsed: object = json.loads(raw_body)
            except (ValueError, UnicodeError):
                parsed = None
            if isinstance(parsed, dict):
                body = {str(key): value for key, value in parsed.items()}
        return cls(path=command.path, query=query, body=body)

    def session_id(self) -> str | None:
        """The session the path names, if any."""
        match = _SESSION_PATH.match(self.path)
        if match is None or match.group(_SESSION_ID_GROUP) in _SESSIONLESS_SEGMENTS:
            return None
        return match.group(_SESSION_ID_GROUP)

    def project_reference(self) -> str | None:
        """The project the request names, as a path on this computer or a registered project identity."""
        for name in _PROJECT_REFERENCE_FIELDS:
            query_value = self.query.get(name)
            if query_value:
                return query_value
            if self.body is not None:
                body_value = self.body.get(name)
                if isinstance(body_value, str) and body_value:
                    return body_value
        return None


def _refusal_response(status_code: HTTPStatus, detail: str) -> RelayedResponse:
    body = json.dumps({_DETAIL_FIELD: detail}).encode()
    return RelayedResponse(
        status_code=status_code,
        body_b64=base64.b64encode(body).decode(),
        headers=[[_CONTENT_TYPE_HEADER, _JSON_CONTENT_TYPE]],
    )


def _resolve_project_folder(reference: str) -> Path:
    """The folder of the project a request names on this computer, or a refusal naming the project."""
    folder = project_folder(reference)
    if folder is None:
        raise _RelayRefused(
            HTTPStatus.NOT_FOUND,
            str(unregistered_referent(ReferentKind.PROJECT, reference)),
        )
    return folder


def _resolve_project_references(command: RelayRequestCommand) -> RelayRequestCommand:
    """Resolve every registered project identity the request names to this computer's folder for it.

    A caller addressing another computer from a project's checkout names the project by its
    registered identity, since its own path means nothing here. This computer decides whether
    it holds that project and refuses by name when it does not; a path is left as given.
    """
    query = [[name, _project_value(name, value)] for name, value in command.query]
    view = _RelayedRequestView.from_command(command)
    body_b64 = command.body_b64
    if view.body is not None and any(name in _PROJECT_PATH_FIELDS for name in view.body):
        resolved_body = {name: _project_value(name, value) for name, value in view.body.items()}
        body_b64 = base64.b64encode(json.dumps(resolved_body).encode()).decode()
    return replace(command, query=query, body_b64=body_b64)


def _project_value[Value](name: str, value: Value) -> Value | str:
    """A project field's value with its registered identity resolved to a folder; any other field untouched."""
    if name in _PROJECT_PATH_FIELDS and isinstance(value, str) and value:
        return str(_resolve_project_folder(value))
    return value


async def _role_target(command: str, caller: PersonCliCaller, view: _RelayedRequestView) -> RoleTarget:
    """The object whose scope decides the person band of ``command`` here."""
    if command in _THIS_COMPUTER_COMMANDS:
        return ThisComputer()
    scope = command_scope(command)
    match scope:
        case CommandScope.PLATFORM | None:
            return Platform()
        case CommandScope.TARGET_SESSION:
            session_id = view.session_id()
            session = await db.get_session(session_id) if session_id else None
            return SessionOf(session.project_path) if session is not None else ThisComputer()
        case CommandScope.INVOCATION | CommandScope.TARGET_PATH | CommandScope.NAMED_TRUSTED_DIRECTORY:
            reference = view.project_reference()
            folder = project_folder(reference) if reference else None
            return ProjectPath(folder) if folder is not None else Platform()
        case CommandScope.CONFIG_SUBJECT | CommandScope.NAMED_COMPANY:
            # The configuration route decides the exact target; the band here admits the role held anywhere here.
            return ThisComputer()
        case CommandScope.CALLER_PERSON:
            return Person(caller.person_slug) if caller.person_slug else Platform()


async def _admit(command: RelayRequestCommand, caller: CliCaller, view: _RelayedRequestView) -> str | None:
    """Decide the carried command's person band here and return the role it was admitted at, if any."""
    computer = config.computer.name
    if isinstance(caller, SystemCliCaller):
        return None
    if isinstance(caller, NoIdentityCliCaller):
        raise _RelayRefused(HTTPStatus.UNAUTHORIZED, LOGIN_REQUIRED_DETAIL)
    if command.cleared_command is None:
        raise _RelayRefused(HTTPStatus.BAD_REQUEST, _NO_COMMAND_DETAIL.format(computer=computer))
    target = await _role_target(command.cleared_command, caller, view)
    role = RoleResolver().role_for(caller, target)
    if not is_command_allowed(command.cleared_command, None, role):
        raise _RelayRefused(
            HTTPStatus.FORBIDDEN,
            _NOT_PERMITTED_DETAIL.format(role=role, command=command.cleared_command, computer=computer),
        )
    return role


def _owner_identity(command: RelayRequestCommand, caller: CliCaller) -> CarriedIdentity:
    """The identity this computer authors for the re-entered request: never the relaying computer's.

    A person's role is the one this computer's own roster declares for them; the role admitted at the
    request's object is not carried, since routes resolve each object's role from the roster themselves.
    """
    person = caller if isinstance(caller, PersonCliCaller) else None
    return CarriedIdentity(
        session_id=command.caller_session_id,
        principal=command.relayed_principal,
        human_role=person.human_role if person is not None else None,
        email=person.email if person is not None else None,
        command=command.cleared_command,
    )


async def _reenter(command: RelayRequestCommand, identity: CarriedIdentity) -> RelayedResponse:
    app = _REENTRY.app
    if app is None:
        raise _RelayRefused(
            HTTPStatus.SERVICE_UNAVAILABLE, _APP_UNAVAILABLE_DETAIL.format(computer=config.computer.name)
        )
    headers = identity.to_headers()
    if command.content_type:
        headers[_CONTENT_TYPE_HEADER] = command.content_type
    body = base64.b64decode(command.body_b64) if command.body_b64 else None
    relayed = RelayedCaller(computer=command.caller_computer or "", session_id=command.caller_session_id)
    token = set_relayed_caller(relayed if command.caller_computer else None)
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url=_REENTRY_BASE_URL) as client:
            response = await client.request(
                command.method,
                httpx.URL(_REENTRY_BASE_URL).copy_with(path=command.path),
                params=[(name, value) for name, value in command.query],
                content=body,
                headers=headers,
            )
    except httpx.HTTPError as error:
        raise _RelayRefused(HTTPStatus.BAD_GATEWAY, _REENTRY_FAILED_DETAIL.format(error=error)) from error
    finally:
        reset_relayed_caller(token)
    return RelayedResponse(
        status_code=response.status_code,
        body_b64=base64.b64encode(response.content).decode(),
        headers=[
            [name, value] for name, value in response.headers.multi_items() if name.lower() not in _TRANSPORT_HEADERS
        ],
    )


async def handle_relay_request(command: RelayRequestCommand) -> JsonDict:
    """Run one relayed request here and answer with its complete response.

    A refusal this computer makes before running the request is that request's
    response, not a transport error: the caller receives it unchanged.
    """
    computer = config.computer.name
    try:
        if time.time() > command.deadline_at:
            raise _RelayRefused(
                HTTPStatus.GATEWAY_TIMEOUT,
                _LATE_DETAIL.format(method=command.method, path=command.path, computer=computer),
            )
        command = _resolve_project_references(command)
        caller = caller_from_principal(command.relayed_principal)
        view = _RelayedRequestView.from_command(command)
        role = await _admit(command, caller, view)
        logger.info(
            _ADMITTED_EVENT,
            method=command.method,
            path=command.path,
            command=command.cleared_command,
            role=role,
            caller_session_id=command.caller_session_id,
            caller_computer=command.caller_computer,
        )
        response = await _reenter(command, _owner_identity(command, caller))
    except _RelayRefused as refusal:
        logger.info(
            _REFUSED_EVENT,
            method=command.method,
            path=command.path,
            command=command.cleared_command,
            status_code=int(refusal.status_code),
            caller_session_id=command.caller_session_id,
            caller_computer=command.caller_computer,
        )
        response = _refusal_response(refusal.status_code, refusal.detail)
    return response.to_dict()
