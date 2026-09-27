"""Person-addressed messaging endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.api_models import PersonMessageRequest
from teleclaude.core.person_messaging import (
    ChannelCapabilityError,
    ChannelCredentialError,
    PersonNotFoundError,
    send_person_message,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/people", tags=["people"])


@router.post("/message")
async def send_message(
    body: PersonMessageRequest,
    identity: CallerIdentity = Depends(carried_caller),
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
