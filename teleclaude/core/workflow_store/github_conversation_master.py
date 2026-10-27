"""Reach the fleet master's conversation poster: locally when this computer is the master, over the relay otherwise.

The poster lives only on the master, so every computer's captured turns, position questions and limit notices
cross to it here. A fleet that names no single live master, or a master that does not answer, leaves the caller to
hold what it has; nothing is posted by any other computer in its place.
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from http import HTTPMethod, HTTPStatus
from typing import Protocol

from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ValidationError
from redis.exceptions import RedisError

from teleclaude.config.machine import config
from teleclaude.constants import SYSTEM_DAEMON_PRINCIPAL
from teleclaude.core.command_dispatch import RemoteDispatchError
from teleclaude.core.inbound.fleet import MasterUnavailability, observe_fleet_from_heartbeats
from teleclaude.core.relay_carrier import carry_request
from teleclaude.core.workflow_store.github_conversation_wire import (
    LIMIT_NOTICE_PATH,
    POSITION_PATH,
    POST_TURN_PATH,
    LimitNoticeRequest,
    LimitNoticeResponse,
    PositionRequest,
    PositionResponse,
    PostTurnRequest,
    PostTurnResponse,
)
from teleclaude.types.commands import RelayedResponse

logger = get_logger(__name__)

_JSON_CONTENT_TYPE = "application/json"
_UNREACHABLE_EVENT = "conversation_master_unreachable"
_NO_MASTER = "the fleet names no live master"
_CONFLICTING_MASTERS = "the fleet names more than one master"
_FLEET_UNOBSERVABLE = "the fleet cannot be observed: {error}"
_CARRY_FAILED = "the master could not be reached: {error}"
_MASTER_REFUSED = "the master answered HTTP {status}"
_ANSWER_UNREADABLE = "the master's answer could not be read"
_NO_LOCAL_POSTER = "this computer is the master but runs no conversation poster"


class MasterUnreachable(RuntimeError):
    """The master could not be reached or did not answer; the caller keeps what it holds and tries again later."""


class ConversationPoster(Protocol):
    """What the fleet master does with the conversation requests of every computer."""

    async def post_turn(self, request: PostTurnRequest) -> PostTurnResponse:
        """Write a captured turn's comments to its destination, or say when to try again."""
        ...

    async def position(self, request: PositionRequest) -> PositionResponse:
        """Report which turns of a session the destination already holds."""
        ...

    async def report_limit(self, request: LimitNoticeRequest) -> LimitNoticeResponse:
        """Pause the conversation after a limit response and say until when."""
        ...


class _PosterRegistry:
    """The one poster this process serves, set when the daemon starts as a master."""

    poster: ConversationPoster | None = None


_REGISTRY = _PosterRegistry()


def register_conversation_poster(poster: ConversationPoster | None) -> None:
    """Install, or with None remove, the poster this computer runs as the fleet master."""
    _REGISTRY.poster = poster


def registered_conversation_poster() -> ConversationPoster | None:
    """The poster this computer runs, or None when it runs none."""
    return _REGISTRY.poster


async def _master_name() -> str | None:
    """The computer that posts: None when this computer is it. Raises ``MasterUnreachable`` when none is."""
    try:
        fleet = await observe_fleet_from_heartbeats()
    except (OSError, RedisError) as error:
        raise MasterUnreachable(_FLEET_UNOBSERVABLE.format(error=error)) from error
    resolution = fleet.resolve_master()
    if resolution.master is None:
        if resolution.unavailability is MasterUnavailability.CONFLICTING_MASTERS:
            raise MasterUnreachable(_CONFLICTING_MASTERS)
        raise MasterUnreachable(_NO_MASTER)
    return None if resolution.master.name == config.computer.name else resolution.master.name


async def _carry[Response: BaseModel](
    path: str, request: BaseModel, response_model: type[Response], owner: str
) -> Response:
    try:
        result = await carry_request(
            destination=owner,
            method=HTTPMethod.POST.value,
            path=path,
            query=[],
            body=request.model_dump_json().encode(),
            content_type=_JSON_CONTENT_TYPE,
            principal=SYSTEM_DAEMON_PRINCIPAL,
            caller_session_id=None,
            cleared_command=None,
        )
        relayed = RelayedResponse.from_wire(result if isinstance(result, dict) else None)
    except (RemoteDispatchError, RuntimeError, ValueError) as error:
        raise MasterUnreachable(_CARRY_FAILED.format(error=error)) from error
    if relayed.status_code != HTTPStatus.OK:
        raise MasterUnreachable(_MASTER_REFUSED.format(status=relayed.status_code))
    try:
        return response_model.model_validate_json(base64.b64decode(relayed.body_b64))
    except (ValueError, ValidationError) as error:
        raise MasterUnreachable(_ANSWER_UNREADABLE) from error


class ConversationMasterLink:
    """Send a conversation request to the master, wherever it is."""

    async def post_turn(self, request: PostTurnRequest) -> PostTurnResponse:
        """Hand a captured turn to the master."""
        return await self._route(POST_TURN_PATH, request, PostTurnResponse, lambda poster: poster.post_turn(request))

    async def position(self, request: PositionRequest) -> PositionResponse:
        """Ask the master which turns of a session the destination already holds."""
        return await self._route(POSITION_PATH, request, PositionResponse, lambda poster: poster.position(request))

    async def report_limit(self, request: LimitNoticeRequest) -> LimitNoticeResponse:
        """Tell the master of a limit response this computer received."""
        return await self._route(
            LIMIT_NOTICE_PATH, request, LimitNoticeResponse, lambda poster: poster.report_limit(request)
        )

    async def _route[Response: BaseModel](
        self,
        path: str,
        request: BaseModel,
        response_model: type[Response],
        local: Callable[[ConversationPoster], Awaitable[Response]],
    ) -> Response:
        try:
            owner = await _master_name()
            if owner is not None:
                return await _carry(path, request, response_model, owner)
            poster = registered_conversation_poster()
            if poster is None:
                raise MasterUnreachable(_NO_LOCAL_POSTER)
            return await local(poster)
        except MasterUnreachable as error:
            logger.info(_UNREACHABLE_EVENT, path=path, reason=str(error))
            raise
