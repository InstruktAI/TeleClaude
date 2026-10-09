"""Resolve a session's stored Discord destination to its conversation address."""

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from teleclaude.core.models import DiscordMetadataField
from teleclaude.services.discord import build_discord_jump_url

if TYPE_CHECKING:
    from teleclaude.core.models import Session


DISCORD_ORIGIN_KEY = "discord"


class SessionAddressMissReason(StrEnum):
    """Reasons a supplied session cannot produce a Discord conversation address."""

    UNKNOWN_SESSION = "unknown_session"
    NO_DISCORD_ORIGIN = "no_discord_origin"
    NO_DESTINATION = "no_destination"
    NO_GUILD = "no_guild"


@dataclass(frozen=True)
class SessionAddressResolved:
    """A resolved native conversation address for a session."""

    url: str


@dataclass(frozen=True)
class SessionAddressMissed:
    """An expected reason a supplied session has no native conversation address."""

    reason: SessionAddressMissReason


SessionAddressResolution = SessionAddressResolved | SessionAddressMissed


def _coerce_identifier(value: object) -> int | None:
    """Return an integer identifier when the stored value represents one."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def resolve_session_conversation_url(session: "Session | None") -> SessionAddressResolution:
    """Resolve a supplied session to its native conversation address or owned miss."""
    if session is None:
        return SessionAddressMissed(SessionAddressMissReason.UNKNOWN_SESSION)
    origin = session.get_origin_section(DISCORD_ORIGIN_KEY)
    guild_id = _coerce_identifier(origin.get(DiscordMetadataField.GUILD_ID))
    thread_id = _coerce_identifier(origin.get(DiscordMetadataField.THREAD_ID))
    channel_id = _coerce_identifier(origin.get(DiscordMetadataField.CHANNEL_ID))
    destination = thread_id or channel_id
    if destination is None:
        reason = SessionAddressMissReason.NO_DESTINATION if origin else SessionAddressMissReason.NO_DISCORD_ORIGIN
        return SessionAddressMissed(reason)
    url = build_discord_jump_url(guild_id, destination, is_thread=thread_id is not None)
    if url is None:
        return SessionAddressMissed(SessionAddressMissReason.NO_GUILD)
    return SessionAddressResolved(url)
