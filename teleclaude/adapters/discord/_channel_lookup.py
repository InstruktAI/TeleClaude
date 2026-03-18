"""Shared helpers for Discord channel cache lookups."""

from __future__ import annotations

from collections.abc import Callable

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


def find_existing_text_channel_id(
    guild: object,
    name: str,
    parse_optional_int: Callable[[object], int | None],
) -> int | None:
    """Return the id of an existing Discord text channel with the given name."""
    channels = getattr(guild, "channels", None)
    if channels is None:
        logger.warning("Guild channel cache not populated; refusing to create text channel '%s'", name)
        return None

    for channel in channels:
        channel_name = getattr(channel, "name", None)
        channel_type = getattr(channel, "type", None)
        is_text = channel_type is not None and getattr(channel_type, "value", channel_type) == 0
        if isinstance(channel_name, str) and channel_name.lower() == name.lower() and is_text:
            found_id = parse_optional_int(getattr(channel, "id", None))
            if found_id is not None:
                return found_id

    return None
