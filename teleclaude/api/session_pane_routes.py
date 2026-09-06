"""Read-only HTTP endpoint for current agent terminal observations."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, clearance_sessions_tail
from teleclaude.api.session_access import check_session_access
from teleclaude.api.session_pane_models import SessionPaneDTO
from teleclaude.api.session_remote import is_remote_target
from teleclaude.config import config
from teleclaude.core.command_dispatch import parse_remote_dispatch_data_diagnosed
from teleclaude.core.models import MessageMetadata
from teleclaude.core.session_pane import get_session_pane

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)
REMOTE_SESSION_PANE_COMMAND = "get_session_pane"
NO_REMOTE_COMPUTER = ""
_STATE = SimpleNamespace(client=None)

router = APIRouter()


def configure(client: AdapterClient | None = None) -> None:
    """Wire the peer transport used for remote terminal observations."""
    if client is not None:
        _STATE.client = client


@router.get("/sessions/{session_id}/pane")
async def get_session_pane_endpoint(
    request: Request,
    session_id: str,
    computer: str | None = Query(None, description="Target computer"),
    _identity: CallerIdentity = Depends(clearance_sessions_tail),
) -> SessionPaneDTO:
    """Get an explicit live terminal observation independent of transcripts."""
    await check_session_access(request, session_id)

    try:
        if is_remote_target(computer, config.computer.name):
            if _STATE.client is None:
                raise HTTPException(status_code=503, detail="Remote session pane is unavailable")
            target_computer = computer or NO_REMOTE_COMPUTER
            metadata = MessageMetadata(human_email=_identity.email, human_role=_identity.human_role)
            message_id = await _STATE.client.send_request(
                target_computer,
                REMOTE_SESSION_PANE_COMMAND,
                metadata,
                session_id=session_id,
            )
            response_text = await _STATE.client.read_response(message_id, target_computer=target_computer)
            data = await parse_remote_dispatch_data_diagnosed(
                _STATE.client,
                response_text,
                target_computer=target_computer,
                command=REMOTE_SESSION_PANE_COMMAND,
            )
            return SessionPaneDTO.model_validate(data)

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
