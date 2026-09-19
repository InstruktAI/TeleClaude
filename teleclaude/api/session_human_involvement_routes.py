"""Self-scoped admission endpoint for one human-involvement declaration."""

from fastapi import APIRouter, Depends, HTTPException

from teleclaude.api.auth import CallerIdentity, clearance_sessions_result
from teleclaude.api_models import SendResultRequest
from teleclaude.api_session_actions_models import (
    HumanInvolvementValidationRequest,
    HumanInvolvementValidationResponseDTO,
)
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.human_involvement import human_involvement_refusal_detail, validate_human_involvement
from teleclaude.types.commands import SystemCommand

router = APIRouter()


@router.post("/sessions/self/result")
async def send_result_endpoint(
    request: SendResultRequest,
    identity: CallerIdentity = Depends(clearance_sessions_result),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Send formatted session output through the command service."""
    cmd = SystemCommand(
        command="deliver_result",
        session_id=identity.session_id,
        data={"content": request.content, "output_format": request.output_format},
    )
    try:
        return await get_command_service().deliver_result(cmd)  # type: ignore[return-value]
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/sessions/self/human-involvement")
async def validate_human_involvement_endpoint(
    request: HumanInvolvementValidationRequest,
    identity: CallerIdentity = Depends(clearance_sessions_result),
) -> HumanInvolvementValidationResponseDTO:
    """Validate one action-local declaration for the authenticated agent session."""
    validation = await validate_human_involvement(
        session_id=identity.session_id,
        reason=request.reason,
        session_store=db,
    )
    if not validation.admitted:
        raise HTTPException(status_code=400, detail=human_involvement_refusal_detail(validation))
    return HumanInvolvementValidationResponseDTO(human_involved=True)
