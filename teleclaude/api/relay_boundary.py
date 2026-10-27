"""The API boundary of computer-addressed execution.

A request that names another computer is carried whole to it before any route
runs here, and executes there through the same route a request made on that
computer runs through
(`local/projects/teleclaude/spec/feature/integration/computer-addressed-execution`).
A request naming this computer, or none, runs here. No route opts in: the
boundary reads the computer a request names, so a route added later is
addressable with nothing done for it.

The caller is authenticated at the edge. This boundary carries the request
without sender-side authorization; the owning computer authorizes the caller's principal
(`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`).
Every way the crossing can fail reaches the caller as an error naming the
computer and the reason; nothing runs anywhere in its place.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from http import HTTPMethod, HTTPStatus
from typing import TYPE_CHECKING, Final

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, carried_caller_of, principal_for_carried_caller
from teleclaude.api.session_route_helpers import http_exception_for_relay_failure
from teleclaude.api.work_feedback import declared_refusal_response
from teleclaude.caller_identity import RelayedAct, cleared_command_path
from teleclaude.config.machine import config
from teleclaude.core.command_dispatch import (
    RelayFailure,
    RemoteDispatchError,
    RemoteDispatchReason,
    is_remote_target,
)
from teleclaude.core.inbound.fleet import known_computer_names
from teleclaude.core.operation_caller_identity import get_relayed_caller
from teleclaude.core.relay_carrier import carry_request
from teleclaude.types.commands import CommandType, RelayedResponse

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

type JsonObject = dict[str, object]  # guard: loose-dict - a request body is route-defined JSON

_DETAIL_FIELD = "detail"
_COMPUTER_PARAM = "computer"
_CONTENT_TYPE_HEADER = "content-type"
_DIRECT_FIELDS: Final = ("direct", "close_link")
_UNKNOWN_COMPUTER_DETAIL = "{computer} is unknown to {local}; the request was not sent and nothing was run."
_NESTED_RELAY_DETAIL = "a request carried here runs here; it names {computer}, and is not carried on."
_TRANSPORT_UNAVAILABLE_DETAIL = "the request to {computer} could not be sent: {error}"
_INVALID_RESPONSE_DETAIL = "{computer} answered the carried request with a response this computer cannot read."


@dataclass(frozen=True)
class _RelayRoute:
    """One request shape and the CLI act a caller that carries no command was cleared as."""

    method: HTTPMethod
    path: re.Pattern[str]
    act: RelayedAct


_LEGACY_ACT_ROUTES: Final[tuple[_RelayRoute, ...]] = (
    _RelayRoute(HTTPMethod.GET, re.compile(r"^/sessions$"), RelayedAct.LIST),
    _RelayRoute(HTTPMethod.GET, re.compile(r"^/sessions/[^/]+$"), RelayedAct.SHOW),
    _RelayRoute(HTTPMethod.POST, re.compile(r"^/sessions$"), RelayedAct.START),
    _RelayRoute(HTTPMethod.POST, re.compile(r"^/sessions/run$"), RelayedAct.RUN),
    _RelayRoute(HTTPMethod.POST, re.compile(r"^/sessions/[^/]+/(?:message|keys)$"), RelayedAct.SEND),
    _RelayRoute(HTTPMethod.GET, re.compile(r"^/sessions/[^/]+/(?:messages|pane)$"), RelayedAct.TAIL),
    _RelayRoute(HTTPMethod.DELETE, re.compile(r"^/sessions/[^/]+$"), RelayedAct.END),
    _RelayRoute(HTTPMethod.POST, re.compile(r"^/sessions/[^/]+/agent-restart$"), RelayedAct.RESTART),
    _RelayRoute(HTTPMethod.POST, re.compile(r"^/sessions/[^/]+/revive$"), RelayedAct.REVIVE),
    _RelayRoute(HTTPMethod.POST, re.compile(r"^/sessions/[^/]+/unsubscribe$"), RelayedAct.UNSUBSCRIBE),
    _RelayRoute(HTTPMethod.GET, re.compile(r"^/operations/[^/]+$"), RelayedAct.OPERATIONS_GET),
    _RelayRoute(HTTPMethod.GET, re.compile(r"^/history/search$"), RelayedAct.HISTORY_SEARCH),
    _RelayRoute(HTTPMethod.GET, re.compile(r"^/history/show/[^/]+$"), RelayedAct.HISTORY_SHOW),
)
_SESSION_ROUTES_WITH_BODY_COMPUTER: Final = frozenset(
    {(HTTPMethod.POST.value, "/sessions"), (HTTPMethod.POST.value, "/sessions/run")}
)
_DIRECT_CONVERSATION_ROUTES: Final = (
    (HTTPMethod.POST.value, re.compile(r"^/sessions$")),
    (HTTPMethod.POST.value, re.compile(r"^/sessions/[^/]+/message$")),
)


def is_known_computer(computer: str) -> bool:
    """Whether this computer has configured or discovered the named computer."""
    return computer in known_computer_names()


def unknown_computer_failure(computer: str) -> RelayFailure:
    """The refusal for a name this computer has neither configured nor discovered."""
    return RelayFailure(
        computer=computer,
        command=CommandType.RELAY_REQUEST.value,
        reason=RemoteDispatchReason.UNKNOWN_COMPUTER,
        detail=_UNKNOWN_COMPUTER_DETAIL.format(computer=computer, local=config.computer.name),
    )


def relay_failure_response(failure: RelayFailure) -> JSONResponse:
    """Present a failed crossing to the caller, naming the computer and the reason.

    An unknown name and a build that cannot take the relay ran nothing, so they are
    work refusals the operator is told about. A computer that did not answer has an
    unknown outcome: the answer names it and carries no instruction to run again.
    """
    detail = str(failure)
    if failure.reason is RemoteDispatchReason.UNKNOWN_COMPUTER:
        return declared_refusal_response(status_code=HTTPStatus.NOT_FOUND, detail=detail, work_feedback=failure.detail)
    if failure.reason is RemoteDispatchReason.RELAY_UNSUPPORTED:
        return declared_refusal_response(
            status_code=HTTPStatus.BAD_GATEWAY, detail=detail, work_feedback=failure.detail
        )
    if failure.reason is RemoteDispatchReason.UNREACHABLE:
        return JSONResponse(status_code=HTTPStatus.GATEWAY_TIMEOUT, content={_DETAIL_FIELD: detail})
    refusal = http_exception_for_relay_failure(failure)
    return JSONResponse(status_code=refusal.status_code, content={_DETAIL_FIELD: refusal.detail})


def _json_object(raw: bytes) -> JsonObject | None:
    """The request body as a JSON object, or None when it is not one."""
    if not raw:
        return None
    try:
        parsed: object = json.loads(raw)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return {str(key): value for key, value in parsed.items()}


def _is_direct_conversation(method: str, path: str, body: JsonObject | None) -> bool:
    """Whether the request opens or closes a direct conversation, which stays on its existing path."""
    if body is None or not any(body.get(field) is True for field in _DIRECT_FIELDS):
        return False
    return any(method == route_method and pattern.match(path) for route_method, pattern in _DIRECT_CONVERSATION_ROUTES)


def _addressed_computer(request: Request, body: JsonObject | None) -> str | None:
    """The computer the request names: its query parameter, else the body of a session create or run."""
    named = request.query_params.get(_COMPUTER_PARAM)
    if named:
        return named
    body_named = body.get(_COMPUTER_PARAM) if body is not None else None
    return body_named if isinstance(body_named, str) and body_named else None


def _cleared_command(request: Request, identity: CallerIdentity) -> str | None:
    """The command the caller cleared the request as; a client that predates carriage clears it by request shape."""
    if identity.command:
        return identity.command
    for route in _LEGACY_ACT_ROUTES:
        if request.method == route.method.value and route.path.match(request.url.path):
            return route.act.value
    return None


def _relayed_response(result: object, computer: str) -> Response:
    """Rebuild the owning computer's response exactly as it answered."""
    try:
        relayed = RelayedResponse.from_wire(result if isinstance(result, dict) else None)
        content = base64.b64decode(relayed.body_b64)
    except ValueError:
        detail = _INVALID_RESPONSE_DETAIL.format(computer=computer)
        return JSONResponse(status_code=HTTPStatus.BAD_GATEWAY, content={_DETAIL_FIELD: detail})
    response = Response(content=content, status_code=relayed.status_code)
    for name, value in relayed.headers:
        response.headers.append(name, value)
    return response


async def _carry(request: Request, target: str, identity: CallerIdentity, raw_body: bytes) -> Response:
    """Carry the request to the computer it names and return that computer's response."""
    if get_relayed_caller() is not None:
        detail = _NESTED_RELAY_DETAIL.format(computer=target)
        return JSONResponse(status_code=HTTPStatus.BAD_REQUEST, content={_DETAIL_FIELD: detail})
    try:
        principal = principal_for_carried_caller(identity, required=True)
    except HTTPException as refusal:
        return JSONResponse(status_code=refusal.status_code, content={_DETAIL_FIELD: refusal.detail})

    if not is_known_computer(target):
        return relay_failure_response(unknown_computer_failure(target))

    cleared = _cleared_command(request, identity)
    try:
        result = await carry_request(
            destination=target,
            method=request.method,
            path=request.url.path,
            query=[[name, value] for name, value in request.query_params.multi_items()],
            body=raw_body,
            content_type=request.headers.get(_CONTENT_TYPE_HEADER),
            principal=principal,
            caller_session_id=identity.session_id or None,
            cleared_command=cleared_command_path(cleared) if cleared else None,
        )
    except RelayFailure as failure:
        return relay_failure_response(failure)
    except RemoteDispatchError as error:
        return relay_failure_response(
            RelayFailure(
                computer=target, command=CommandType.RELAY_REQUEST.value, reason=error.reason, detail=str(error)
            )
        )
    except (RuntimeError, ValueError) as error:
        detail = _TRANSPORT_UNAVAILABLE_DETAIL.format(computer=target, error=error)
        return JSONResponse(status_code=HTTPStatus.SERVICE_UNAVAILABLE, content={_DETAIL_FIELD: detail})
    return _relayed_response(result, target)


async def relay_boundary(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Carry a request that names another computer to it; run every other request here."""
    peek_body = (request.method, request.url.path) in _SESSION_ROUTES_WITH_BODY_COMPUTER
    raw_body = await request.body() if peek_body else b""
    body = _json_object(raw_body) if peek_body else None
    target = _addressed_computer(request, body)
    if target is None or not is_remote_target(target, config.computer.name):
        return await call_next(request)
    if not peek_body:
        raw_body = await request.body()
        body = _json_object(raw_body)
    if _is_direct_conversation(request.method, request.url.path, body):
        return await call_next(request)

    identity = carried_caller_of(request)
    return await _carry(request, target, identity, raw_body)
