"""Read-only HTTP endpoint for current agent terminal observations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.api.session_pane_models import SessionPaneDTO
from teleclaude.core.session_pane import get_session_pane

logger = get_logger(__name__)

router = APIRouter()


@router.get("/sessions/{session_id}/pane")
async def get_session_pane_endpoint(
    session_id: str,
    _identity: CallerIdentity = Depends(carried_caller),
) -> SessionPaneDTO:
    """Get an explicit live terminal observation independent of transcripts."""
    try:
        result = await get_session_pane(session_id)
        return SessionPaneDTO(
            session_id=result.session_id,
            runtime=result.runtime,
            captured_at=result.captured_at.isoformat(),
            available=result.available,
            text=result.text,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_session_pane failed (session=%s): %s", session_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get session pane: {exc}") from exc
