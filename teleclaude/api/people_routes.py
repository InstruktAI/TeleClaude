"""People listing and person-addressed messaging endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, clearance_message_send
from teleclaude.api_models import PersonDTO, PersonMessageRequest
from teleclaude.cli import config_handlers as config_handlers_module
from teleclaude.core.person_messaging import (
    ChannelCapabilityError,
    ChannelCredentialError,
    PersonNotFoundError,
    send_person_message,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/people", tags=["people"])


@router.get("")
async def list_people() -> list[PersonDTO]:
    """List people from global config (safe subset only)."""
    try:
        global_cfg = config_handlers_module.get_global_config()
        return [
            PersonDTO(
                name=p.name,
                email=p.email,
                role=p.role,
                expertise=p.expertise,
            )
            for p in global_cfg.people
        ]
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("list_people failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list people: {exc}") from exc


@router.post("/message")
async def send_message(
    body: PersonMessageRequest,
    identity: CallerIdentity = Depends(clearance_message_send),
) -> dict[str, object]:  # guard: loose-dict - ad hoc {status, channel, message_id} response, no consumer contract
    """Dispatch a person-addressed message through the routed channel."""
    try:
        outcome = await send_person_message(
            body.slug,
            body.text,
            file=body.file,
            subject=body.subject,
            channel=body.channel,
            origin_session_id=identity.session_id,
        )
    except PersonNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ChannelCredentialError, ChannelCapabilityError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("send_person_message failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Failed to send message: {exc}") from exc

    return {"status": "ok", "channel": outcome.channel.value, "message_id": outcome.message_id}
