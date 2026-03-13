"""Team channel provisioning mixin for Discord adapter.

Handles per-person private text channels under the Team category.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

if TYPE_CHECKING:
    from types import ModuleType

logger = get_logger(__name__)


class TeamChannelsMixin:
    """Mixin providing team channel provisioning for DiscordAdapter.

    Required host attributes:
    - _client: DiscordClientLike | None
    - _discord: ModuleType
    - _team_channel_map: dict[int, str]
    - _parse_optional_int(value) -> int | None
    - _require_async_callable(fn, *, label) -> Callable
    - _get_channel(channel_id) -> object | None (async)
    """

    _team_channel_map: dict[int, str]

    if TYPE_CHECKING:
        _discord: ModuleType
        _client: object

        def _parse_optional_int(self, value: object) -> int | None: ...

        @staticmethod
        def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]: ...

        async def _get_channel(self, channel_id: int) -> object | None: ...

    async def _ensure_team_channels(
        self,
        guild: object,
        category: object | None,
        people: list[object],
    ) -> None:
        """Create a private text channel per person under the Team category.

        Each channel is only visible to the person (matched by their Discord
        user ID from per-person config) and the bot. Everyone else is denied.
        """
        if category is None:
            return

        from teleclaude.cli.config_handlers import get_person_config

        for person in people:
            name = getattr(person, "name", None)
            if not isinstance(name, str) or not name.strip():
                continue
            slug = name.lower().replace(" ", "-")

            # Resolve the person's Discord user ID from per-person config
            discord_user_id: int | None = None
            try:
                person_cfg = get_person_config(name)
                if person_cfg.creds.discord:
                    discord_user_id = self._parse_optional_int(person_cfg.creds.discord.user_id)  # type: ignore[attr-defined]
            except Exception:
                pass

            ch_id = await self._find_or_create_private_text_channel(guild, category, slug, discord_user_id)
            if ch_id is not None:
                person_folder = os.path.join(os.path.expanduser("~"), ".teleclaude", "people", name)
                self._team_channel_map[ch_id] = person_folder
            # Ensure permissions are correct on existing channels too
            if ch_id is not None and discord_user_id is not None:
                await self._ensure_channel_private(ch_id, guild, discord_user_id)

    # guard: loose-dict-func - kwargs is a heterogeneous discord.py channel create dict; a TypedDict would need discord-py types
    async def _find_or_create_private_text_channel(
        self,
        guild: object,
        category: object | None,
        name: str,
        owner_user_id: int | None,
    ) -> int | None:
        """Find or create a text channel with private permissions.

        Denies @everyone view access, allows only the owner and the bot.
        """
        channels = getattr(guild, "channels", None)
        if channels is None:
            logger.warning("Guild channel cache not populated; refusing to create text channel '%s'", name)
            return None

        for ch in channels:
            ch_name = getattr(ch, "name", None)
            ch_type = getattr(ch, "type", None)
            is_text = ch_type is not None and getattr(ch_type, "value", ch_type) == 0
            if isinstance(ch_name, str) and ch_name.lower() == name.lower() and is_text:
                found_id = self._parse_optional_int(getattr(ch, "id", None))  # type: ignore[attr-defined]
                if found_id is not None:
                    return found_id

        # Build permission overwrites for a private channel
        overwrites = self._build_private_overwrites(guild, owner_user_id)

        create_fn = getattr(guild, "create_text_channel", None)
        if not callable(create_fn):
            return None

        try:
            create = self._require_async_callable(create_fn, label="guild.create_text_channel")  # type: ignore[attr-defined]
            # guard: loose-dict - dynamic kwargs; category key conditionally added
            kwargs: dict[str, object] = {"name": name, "overwrites": overwrites}
            if category is not None:
                kwargs["category"] = category
            channel = await create(**kwargs)
            ch_id = self._parse_optional_int(getattr(channel, "id", None))  # type: ignore[attr-defined]
            if ch_id is not None:
                logger.info("Created private Discord text channel: %s (id=%s)", name, ch_id)
            return ch_id
        except Exception as exc:
            logger.warning("Failed to create private text channel '%s': %s", name, exc)
            return None

    def _build_private_overwrites(self, guild: object, owner_user_id: int | None) -> dict[object, object]:
        """Build Discord permission overwrites: deny @everyone, allow owner + bot."""
        PermissionOverwrite = getattr(self._discord, "PermissionOverwrite", None)  # type: ignore[attr-defined]
        if PermissionOverwrite is None:
            return {}

        overwrites: dict[object, object] = {}

        # Deny @everyone
        default_role = getattr(guild, "default_role", None)
        if default_role is not None:
            overwrites[default_role] = PermissionOverwrite(view_channel=False, read_messages=False)

        # Allow the bot
        bot_user = getattr(self._client, "user", None) if self._client is not None else None  # type: ignore[attr-defined]
        if bot_user is not None:
            overwrites[bot_user] = PermissionOverwrite(
                view_channel=True, read_messages=True, send_messages=True, manage_messages=True
            )

        # Allow the person
        if owner_user_id is not None:
            Object = getattr(self._discord, "Object", None)  # type: ignore[attr-defined]
            get_member = getattr(guild, "get_member", None)
            member = get_member(owner_user_id) if callable(get_member) else None
            if member is not None:
                overwrites[member] = PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True)
            elif Object is not None:
                # Use Object as fallback (discord.py accepts it for overwrites)
                overwrites[Object(id=owner_user_id)] = PermissionOverwrite(
                    view_channel=True, read_messages=True, send_messages=True
                )

        return overwrites

    async def _ensure_channel_private(self, channel_id: int, guild: object, owner_user_id: int) -> None:
        """Verify and fix permissions on an existing team channel."""
        channel = await self._get_channel(channel_id)  # type: ignore[attr-defined]
        if channel is None:
            return

        default_role = getattr(guild, "default_role", None)
        if default_role is None:
            return

        overwrites = getattr(channel, "overwrites", None)
        if overwrites and default_role in overwrites:
            existing = overwrites[default_role]
            view_pair = getattr(existing, "pair", lambda: (None, None))()
            if view_pair and len(view_pair) >= 2:
                return

        # Permissions not set — apply them
        overwrites_dict = self._build_private_overwrites(guild, owner_user_id)
        edit_fn = getattr(channel, "edit", None)
        if callable(edit_fn):
            try:
                await self._require_async_callable(edit_fn, label="channel.edit overwrites")(overwrites=overwrites_dict)  # type: ignore[attr-defined]
                logger.info("Applied private permissions to team channel %s", channel_id)
            except Exception as exc:
                logger.warning("Failed to apply private permissions to channel %s: %s", channel_id, exc)
