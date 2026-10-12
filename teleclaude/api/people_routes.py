"""Person-addressed messaging endpoint."""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.api_models import PEOPLE_API_PREFIX, PERSON_MESSAGE_ROUTE, PersonMessageRequest
from teleclaude.core.operation_caller_identity import get_relayed_caller
from teleclaude.core.person_messaging import (
    CarriedAttachment,
    CarriedMessageParts,
    CarriedRequestError,
    ChannelCapabilityError,
    ChannelCredentialError,
    PersonMessageNotOwner,
    PersonMessageOwnerUnavailable,
    PersonMessageRefused,
    PersonNotFoundError,
    RecipientsUnreachedError,
    RecipientUnresolvableError,
    send_person_message_to_caller,
)

logger = get_logger(__name__)

router = APIRouter(prefix=PEOPLE_API_PREFIX, tags=["people"])
_MESSAGE_STATUS_KEY = "status"
_MESSAGE_DELIVERIES_KEY = "deliveries"
_MESSAGE_FAILURES_KEY = "failures"
_RECIPIENT_KEY = "recipient"
_CHANNEL_KEY = "channel"
_MESSAGE_ID_KEY = "message_id"
_DETAIL_KEY = "detail"
_OK_STATUS = "ok"


def _carried_parts(body: PersonMessageRequest) -> CarriedMessageParts:
    """What the requesting computer's daemon sent along with a request it carried here."""
    attachment = (
        CarriedAttachment(name=body.file_name, content=base64.b64decode(body.file_content_b64))
        if body.file_name is not None and body.file_content_b64 is not None
        else None
    )
    return CarriedMessageParts(attachment=attachment, backlink_url=body.origin_backlink_url)


@router.post(PERSON_MESSAGE_ROUTE)
async def send_message(
    body: PersonMessageRequest,
    identity: CallerIdentity = Depends(carried_caller),
) -> dict[str, object]:  # guard: loose-dict - transient delivery result is consumed by the CLI handler only
    """Dispatch a person-addressed message through the routed channel, from the master."""
    try:
        outcome = await send_person_message_to_caller(
            body.recipient,
            identity.principal,
            body.text,
            file=body.file,
            subject=body.subject,
            channel=body.channel,
            origin_session_id=identity.session_id,
            cleared_command=identity.command,
            carried=_carried_parts(body) if get_relayed_caller() is not None else None,
        )
    except PersonMessageRefused as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except PersonMessageOwnerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PersonMessageNotOwner as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CarriedRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
