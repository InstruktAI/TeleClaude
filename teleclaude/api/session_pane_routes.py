"""Read-only HTTP endpoint for current agent terminal observations."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import (
    CallerIdentity,
    carried_caller,
    principal_for_carried_caller,
)
from teleclaude.api.session_pane_models import SessionPaneDTO
from teleclaude.api.session_remote import is_remote_target
from teleclaude.api.session_route_helpers import http_exception_for_relay_failure
from teleclaude.config import config
from teleclaude.core.command_dispatch import RelayFailure, relay_caller_read
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
    session_id: str,
    computer: str | None = Query(None, description="Target computer"),
    _identity: CallerIdentity = Depends(carried_caller),
) -> SessionPaneDTO:
    """Get an explicit live terminal observation independent of transcripts."""
    try:
        if is_remote_target(computer, config.computer.name):
            if _STATE.client is None:
                raise HTTPException(status_code=503, detail="Remote session pane is unavailable")
            principal = principal_for_carried_caller(_identity, required=True)
            target_computer = computer or NO_REMOTE_COMPUTER
            data = await relay_caller_read(
                _STATE.client,
                target_computer,
                REMOTE_SESSION_PANE_COMMAND,
                principal=principal,
                session_id=session_id,
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
    except RelayFailure as exc:
        raise http_exception_for_relay_failure(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_session_pane failed (session=%s): %s", session_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get session pane: {exc}") from exc
