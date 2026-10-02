"""Personal-assistant session launch API route."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import TYPE_CHECKING, Final, Literal

from fastapi import APIRouter, Depends, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.agent_dispatch_errors import (
    agent_dispatch_http_refusal,
    emit_run_accepted,
    emit_run_outcome,
    run_dispatch_refusal_reason,
    run_refusal_outcome,
)
from teleclaude.api.auth import CallerIdentity, caller_for_role_resolution, carried_caller
from teleclaude.api.run_session_refusals import RunSessionRefusal
from teleclaude.api.session_route_helpers import build_metadata, dispatch_caller_command
from teleclaude.api_models import CreateSessionResponseDTO, RunPersonalAssistantRequest
from teleclaude.caller_identity import PersonCliCaller
from teleclaude.core.agent_dispatch import AgentDispatchReason, RunSessionThinkingMode, decision_basis_digest
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.db import db
from teleclaude.core.models import AgentDispatchMode, SessionEntryPoint, SessionLaunchIntent, SessionLaunchKind
from teleclaude.invite import scaffold_personal_workspace
from teleclaude.types.commands import CreateSessionCommand

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

_ROUTE: Final[str] = "/sessions/run-pa"
_CREATE_COMMAND: Final[str] = "new_session"
_SKIP_LISTENER_FIELD: Final[str] = "skip_listener_registration"
_INITIATOR_FIELD: Final[str] = "initiator_session_id"
_INITIAL_INPUT_FIELD: Final[str] = "initial_input"
_SESSION_ID_FIELD: Final[str] = "session_id"
_TMUX_SESSION_NAME_FIELD: Final[str] = "tmux_session_name"
_AGENT_FIELD: Final[str] = "agent"
_SUCCESS_STATUS: Final[Literal["success"]] = "success"
_NO_PERSON_DETAIL: Final[str] = "No person resolved for the caller."
_MAPPING_ERROR: Final[str] = "Personal assistant launch did not map to session creation."
_CREATION_ERROR: Final[str] = "Failed to create personal assistant session."
_FAILURE_LOG: Final[str] = "run_personal_assistant failed: %s"

_STATE = SimpleNamespace(client=None)
router = APIRouter()


def configure(*, client: AdapterClient | None = None) -> None:
    """Wire the command client used by this route."""
    if client is not None:
        _STATE.client = client


@router.post(_ROUTE, response_model_exclude_none=True)
async def run_personal_assistant(
    request: RunPersonalAssistantRequest,
    identity: CallerIdentity = Depends(carried_caller),
) -> CreateSessionResponseDTO:
    """Launch the caller's assistant with an optional brief and no parent session."""
    request_id = str(uuid.uuid4())
    entry_point = SessionEntryPoint.PERSONAL_ASSISTANT_LAUNCH
    dispatch_mode = AgentDispatchMode.AUTOMATIC
    basis_digest = decision_basis_digest(
        mode=dispatch_mode,
        role=None,
        todo_kind=None,
        preferred_agent=None,
        fixed_agent=None,
    )
    emit_run_accepted(
        request_id=request_id,
        dispatch_mode=dispatch_mode,
        agent_supplied=False,
        entry_point=entry_point,
        command_kind=None,
        working_slug_present=False,
        caller_kind_present=False,
        preferred_agent=None,
        fixed_agent=None,
        decision_basis_digest=basis_digest,
    )

    caller = caller_for_role_resolution(identity)
    if not isinstance(caller, PersonCliCaller) or not caller.person_slug:
        reason = AgentDispatchReason.PERSON_UNRESOLVED
        emit_run_outcome(
            selected_agent=None,
            request_id=request_id,
            entry_point=entry_point,
            dispatch_mode=dispatch_mode,
            outcome=run_refusal_outcome(reason),
            reason=reason,
        )
        raise RunSessionRefusal(status_code=403, detail=_NO_PERSON_DETAIL, reason=reason)

    workspace = scaffold_personal_workspace(caller.person_slug)
    caller_session = await db.get_session(identity.session_id) if identity.session_id else None
    company = caller_session.company if caller_session is not None else None
    opening_input = request.brief
    metadata = build_metadata(project_path=str(workspace), company=company, human_email=caller.email)
    metadata.launch_intent = SessionLaunchIntent(
        kind=SessionLaunchKind.AGENT_THEN_MESSAGE if opening_input is not None else SessionLaunchKind.AGENT,
        thinking_mode=RunSessionThinkingMode.SLOW.value,
        message=opening_input,
        dispatch_mode=dispatch_mode,
    )
    cmd = CommandMapper.map_api_input(
        _CREATE_COMMAND,
        {
            _SKIP_LISTENER_FIELD: True,
            _INITIATOR_FIELD: None,
            _INITIAL_INPUT_FIELD: opening_input,
        },
        metadata,
    )
    if not isinstance(cmd, CreateSessionCommand):
        raise TypeError(_MAPPING_ERROR)
    cmd.entry_point = entry_point
    cmd.request_id = request_id
    if cmd.launch_intent is not None:
        cmd.launch_intent.accepted_at_origin = True

    try:
        data = await dispatch_caller_command(_STATE.client, cmd, identity)
        if not isinstance(data, dict):
            raise HTTPException(status_code=500, detail=_CREATION_ERROR)
        session_id = data.get(_SESSION_ID_FIELD)
        tmux_session_name = data.get(_TMUX_SESSION_NAME_FIELD)
        if not session_id or not tmux_session_name:
            raise HTTPException(status_code=500, detail=_CREATION_ERROR)
        emit_run_outcome(
            selected_agent=data.get(_AGENT_FIELD) if isinstance(data.get(_AGENT_FIELD), str) else None,
            request_id=request_id,
            session_id=str(session_id),
            entry_point=entry_point,
            dispatch_mode=dispatch_mode,
        )
        return CreateSessionResponseDTO(
            status=_SUCCESS_STATUS,
            session_id=str(session_id),
            tmux_session_name=str(tmux_session_name),
            agent=data.get(_AGENT_FIELD) if isinstance(data.get(_AGENT_FIELD), str) else None,
        )
    except HTTPException:
        raise
    except Exception as exc:
        refusal = agent_dispatch_http_refusal(exc)
        if refusal is not None:
            reason = run_dispatch_refusal_reason(exc)
            if reason is not None:
                emit_run_outcome(
                    selected_agent=None,
                    request_id=request_id,
                    entry_point=entry_point,
                    dispatch_mode=dispatch_mode,
                    outcome=run_refusal_outcome(reason),
                    reason=reason,
                )
            raise refusal from exc
        logger.error(_FAILURE_LOG, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=_CREATION_ERROR) from exc
