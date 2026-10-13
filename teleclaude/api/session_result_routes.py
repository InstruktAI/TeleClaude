"""Self-scoped endpoint for delivering one session's formatted result."""

from fastapi import APIRouter, Depends, HTTPException

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.api_session_actions_models import SendResultRequest
from teleclaude.core.command_registry import get_command_service
from teleclaude.types.commands import SystemCommand

router = APIRouter()


@router.post("/sessions/self/result")
async def send_result_endpoint(
    request: SendResultRequest,
    identity: CallerIdentity = Depends(carried_caller),
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
