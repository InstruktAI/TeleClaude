"""Coordinator-adoption session endpoint."""

from fastapi import APIRouter, Depends, HTTPException

from teleclaude.api.auth import CallerIdentity, clearance_sessions_coordinate, invalidate_session_cache
from teleclaude.core.session_coordinator import adopt_coordinator

_COORDINATOR_SESSION_ID_REQUIRED = "Only an agent session can acquire the coordinator role."

router = APIRouter()


@router.post("/sessions/self/coordinate")
async def coordinate_session(
    identity: CallerIdentity = Depends(clearance_sessions_coordinate),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Adopt the calling agent session as this project's coordinator."""
    if not identity.session_id:
        raise HTTPException(status_code=400, detail=_COORDINATOR_SESSION_ID_REQUIRED)
    result = await adopt_coordinator(identity.session_id)
    invalidate_session_cache(identity.session_id)
    return {
        "status": result.status.value,
        "holder_session_id": result.holder_session_id,
        "message": result.message,
    }
