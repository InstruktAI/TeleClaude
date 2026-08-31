"""Resolve a session's stored Discord destination to its conversation address."""

from typing import TYPE_CHECKING

from teleclaude.core.models import DiscordMetadataField
from teleclaude.services.discord import build_discord_jump_url

if TYPE_CHECKING:
    from teleclaude.core.models import Session


DISCORD_ORIGIN_KEY = "discord"


def _coerce_identifier(value: object) -> int | None:
    """Return an integer identifier when the stored value represents one."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def resolve_session_conversation_url(session: "Session") -> str | None:
    """Return the native conversation address for a session, when resolvable."""
    origin = session.get_origin_section(DISCORD_ORIGIN_KEY)
    guild_id = _coerce_identifier(origin.get(DiscordMetadataField.GUILD_ID))
    thread_id = _coerce_identifier(origin.get(DiscordMetadataField.THREAD_ID))
    channel_id = _coerce_identifier(origin.get(DiscordMetadataField.CHANNEL_ID))
    destination = thread_id or channel_id
    if destination is None:
        return None
    return build_discord_jump_url(guild_id, destination, is_thread=thread_id is not None)
