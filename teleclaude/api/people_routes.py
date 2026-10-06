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
    RecipientsUnreachedError,
    RecipientUnresolvableError,
    send_person_message_to_caller,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/people", tags=["people"])
_MESSAGE_STATUS_KEY = "status"
_MESSAGE_DELIVERIES_KEY = "deliveries"
_MESSAGE_FAILURES_KEY = "failures"
_RECIPIENT_KEY = "recipient"
_CHANNEL_KEY = "channel"
_MESSAGE_ID_KEY = "message_id"
_DETAIL_KEY = "detail"
_OK_STATUS = "ok"


@router.post("/message")
async def send_message(
    body: PersonMessageRequest,
    identity: CallerIdentity = Depends(carried_caller),
) -> dict[str, object]:  # guard: loose-dict - transient delivery result is consumed by the CLI handler only
    """Dispatch a person-addressed message through the routed channel."""
    try:
        outcome = await send_person_message_to_caller(
            body.recipient,
            identity.principal,
            body.text,
            file=body.file,
            subject=body.subject,
            channel=body.channel,
            origin_session_id=identity.session_id,
        )
    except RecipientUnresolvableError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RecipientsUnreachedError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except PersonNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ChannelCredentialError, ChannelCapabilityError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("send_person_message failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Failed to send message: {exc}") from exc

    return {
        _MESSAGE_STATUS_KEY: _OK_STATUS,
        _MESSAGE_DELIVERIES_KEY: [
            {
                _RECIPIENT_KEY: delivery.recipient,
                _CHANNEL_KEY: delivery.channel.value,
                _MESSAGE_ID_KEY: delivery.message_id,
            }
            for delivery in outcome.deliveries
        ],
        _MESSAGE_FAILURES_KEY: [
            {_RECIPIENT_KEY: failure.recipient, _DETAIL_KEY: failure.detail} for failure in outcome.failures
        ],
    }
