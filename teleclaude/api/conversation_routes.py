"""The fleet master's conversation endpoints, called by the daemons of the fleet's computers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.caller_identity import SYSTEM_PRINCIPAL_PREFIX
from teleclaude.core.workflow_store.github_conversation_master import registered_conversation_poster
from teleclaude.core.workflow_store.github_conversation_wire import (
    CONVERSATION_API_PREFIX,
    LIMIT_NOTICE_ROUTE,
    POSITION_ROUTE,
    POST_TURN_ROUTE,
    LimitNoticeRequest,
    LimitNoticeResponse,
    Outcome,
    PositionRequest,
    PositionResponse,
    PostTurnRequest,
    PostTurnResponse,
    RefusalCause,
)

router = APIRouter(prefix=CONVERSATION_API_PREFIX, tags=["conversation"])
_DAEMONS_ONLY = "conversation endpoints answer the fleet's daemons only"
_NO_POSTER = "this computer runs no conversation poster"
_NO_POSTER_STATUS = 503
_FORBIDDEN_STATUS = 403


def _daemon(identity: CallerIdentity = Depends(carried_caller)) -> CallerIdentity:
    """Admit only a platform caller: a daemon of the fleet, never a person or an agent session."""
    if not identity.principal or not identity.principal.startswith(SYSTEM_PRINCIPAL_PREFIX):
        raise HTTPException(status_code=_FORBIDDEN_STATUS, detail=_DAEMONS_ONLY)
    return identity


@router.post(POST_TURN_ROUTE, response_model=PostTurnResponse)
async def post_turn(body: PostTurnRequest, _identity: CallerIdentity = Depends(_daemon)) -> PostTurnResponse:
    """Write a captured turn's comments to GitHub, as the master."""
    poster = registered_conversation_poster()
    if poster is None:
        return PostTurnResponse(outcome=Outcome.REFUSED, cause=RefusalCause.NOT_MASTER, uncertain=body.possibly_sent)
    return await poster.post_turn(body)


@router.post(POSITION_ROUTE, response_model=PositionResponse)
async def position(body: PositionRequest, _identity: CallerIdentity = Depends(_daemon)) -> PositionResponse:
    """Report which turns of a session the destination already holds."""
    poster = registered_conversation_poster()
    if poster is None:
        return PositionResponse(outcome=Outcome.REFUSED, cause=RefusalCause.NOT_MASTER)
    return await poster.position(body)


@router.post(LIMIT_NOTICE_ROUTE, response_model=LimitNoticeResponse)
async def limit_notice(body: LimitNoticeRequest, _identity: CallerIdentity = Depends(_daemon)) -> LimitNoticeResponse:
    """Pause the conversation after a limit response another computer received."""
    poster = registered_conversation_poster()
    if poster is None:
        raise HTTPException(status_code=_NO_POSTER_STATUS, detail=_NO_POSTER)
    return await poster.report_limit(body)
