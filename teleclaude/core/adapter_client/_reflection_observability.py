"""Observability contract for reflected-human presentation delivery."""

from enum import StrEnum

from instrukt_ai_logging import get_logger

from teleclaude.core.identity import ReflectionAvatarSource

logger = get_logger(__name__)

_USER_REFLECTION_PRESENTATION_EVENT = "user_reflection_presentation"


class UserReflectionPresentationOutcome(StrEnum):
    """Terminal outcomes for reflected-human presentation delivery."""

    ACCEPTED = "accepted"
    SENT = "sent"
    NOT_DELIVERED = "not_delivered"


class UserReflectionPresentationReason(StrEnum):
    """Closed reasons for reflected-human presentation observations."""

    NON_DISCORD_REFLECTION = "non_discord_reflection"
    PLATFORM_RECEIPT = "platform_receipt"
    NO_PLATFORM_RECEIPT = "no_platform_receipt"


def observe_user_reflection_presentation(
    *,
    session_id: str,
    reflection_id: str,
    outcome: UserReflectionPresentationOutcome,
    reason: UserReflectionPresentationReason,
    actor_avatar_supplied: bool,
    identity_avatar_available: bool,
    avatar_source: ReflectionAvatarSource | None = None,
    actor_name_present: bool | None = None,
    platform_message_ids: list[str] | None = None,
) -> None:
    """Record a reflection presentation decision without message or identity data."""
    logger.info(
        _USER_REFLECTION_PRESENTATION_EVENT,
        outcome=outcome,
        reason=reason,
        session_id=session_id,
        reflection_id=reflection_id,
        actor_avatar_supplied=actor_avatar_supplied,
        identity_avatar_available=identity_avatar_available,
        avatar_source=avatar_source,
        avatar_present=avatar_source is not ReflectionAvatarSource.NONE if avatar_source is not None else None,
        actor_name_present=actor_name_present,
        platform_message_ids=platform_message_ids,
    )
