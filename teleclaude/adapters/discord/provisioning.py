"""Infrastructure provisioning helpers mixin for Discord adapter.

Handles guild resolution, channel/category/forum creation, and config persistence.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


class ProvisioningMixin:
    """Mixin providing guild and channel creation helpers for DiscordAdapter.

    Required host attributes:
    - _client: DiscordClientLike | None
    - _guild_id: int | None
    - _parse_optional_int(value) -> int | None
    - _require_async_callable(fn, *, label) -> Callable
    - _get_channel(channel_id) -> object | None (async)
    - _is_forum_channel(channel) -> bool
    """

    _guild_id: int | None

    if TYPE_CHECKING:
        _client: object

        def _parse_optional_int(self, value: object) -> int | None: ...

        @staticmethod
        def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]: ...

        async def _get_channel(self, channel_id: int) -> object | None: ...

        def _is_forum_channel(self, channel: object) -> bool: ...

    async def _resolve_guild(self) -> object | None:
        """Resolve the configured guild by ID."""
        if self._client is None or self._guild_id is None:
            return None

        get_guild_fn = getattr(self._client, "get_guild", None)
        guild = get_guild_fn(self._guild_id) if callable(get_guild_fn) else None

        if guild is None:
            fetch_guild_fn = getattr(self._client, "fetch_guild", None)
            if callable(fetch_guild_fn):
                try:
                    guild = await self._require_async_callable(fetch_guild_fn, label="fetch_guild")(self._guild_id)
                except Exception as exc:
                    logger.debug("Failed to fetch guild %s: %s", self._guild_id, exc)

        return guild  # type: ignore[no-any-return]

    async def _find_or_create_category(self, guild: object, name: str) -> object | None:
        """Find an existing category by name, or create one.

        Only creates when the guild cache is confirmed populated (categories is
        a list). If the cache is unavailable (None), refuses to create to
        prevent duplicate categories from transient gateway issues.
        """
        categories = getattr(guild, "categories", None)
        if categories is None:
            logger.warning("Guild category cache not populated; refusing to create '%s' to prevent duplicates", name)
            return None

        for cat in categories:
            cat_name = getattr(cat, "name", None)
            if isinstance(cat_name, str) and cat_name.lower() == name.lower():
                logger.debug("Found existing Discord category: %s (id=%s)", name, getattr(cat, "id", "?"))
                return cat  # type: ignore[no-any-return]

        # Cache is populated and category not found — safe to create.
        create_fn = getattr(guild, "create_category", None)
        if not callable(create_fn):
            logger.debug("Guild has no create_category method; skipping category creation")
            return None

        try:
            category = await self._require_async_callable(create_fn, label="guild.create_category")(name=name)
            logger.info("Created Discord category: %s (id=%s)", name, getattr(category, "id", "?"))
            return category
        except Exception as exc:
            logger.warning("Failed to create Discord category '%s': %s", name, exc)
            return None

    async def _find_or_create_forum(self, guild: object, category: object | None, name: str, topic: str) -> int | None:
        """Find an existing forum by name, or create one under the category.

        Refuses to create when the guild channel cache is not populated.
        """
        channels = getattr(guild, "channels", None)
        if channels is None:
            logger.warning("Guild channel cache not populated; refusing to create forum '%s'", name)
            return None

        for ch in channels:
            ch_name = getattr(ch, "name", None)
            if isinstance(ch_name, str) and ch_name.lower() == name.lower() and self._is_forum_channel(ch):
                found_id = self._parse_optional_int(getattr(ch, "id", None))
                if found_id is not None:
                    logger.debug("Found existing Discord forum: %s (id=%s)", name, found_id)
                    return found_id

        # Cache is populated and forum not found — safe to create.
        create_fn = getattr(guild, "create_forum", None)
        if not callable(create_fn):
            logger.warning("Guild has no create_forum method; cannot create '%s'", name)
            return None

        try:
            create = self._require_async_callable(create_fn, label="guild.create_forum")
            if category is not None:
                forum = await create(name=name, topic=topic, category=category)
            else:
                forum = await create(name=name, topic=topic)
            forum_id = self._parse_optional_int(getattr(forum, "id", None))
            if forum_id is not None:
                logger.info("Created Discord forum: %s (id=%s)", name, forum_id)
            return forum_id
        except Exception as exc:
            logger.warning("Failed to create Discord forum '%s': %s", name, exc)
            return None

    async def _find_or_create_text_channel(self, guild: object, category: object | None, name: str) -> int | None:
        """Find an existing text channel by name, or create one under the category.

        Refuses to create when the guild channel cache is not populated.
        """
        channels = getattr(guild, "channels", None)
        if channels is None:
            logger.warning("Guild channel cache not populated; refusing to create text channel '%s'", name)
            return None

        for ch in channels:
            ch_name = getattr(ch, "name", None)
            ch_type = getattr(ch, "type", None)
            # discord.ChannelType.text has value 0
            is_text = ch_type is not None and getattr(ch_type, "value", ch_type) == 0
            if isinstance(ch_name, str) and ch_name.lower() == name.lower() and is_text:
                found_id = self._parse_optional_int(getattr(ch, "id", None))
                if found_id is not None:
                    logger.debug("Found existing Discord text channel: %s (id=%s)", name, found_id)
                    return found_id

        # Cache is populated and channel not found — safe to create.
        create_fn = getattr(guild, "create_text_channel", None)
        if not callable(create_fn):
            logger.warning("Guild has no create_text_channel method; cannot create '%s'", name)
            return None

        try:
            create = self._require_async_callable(create_fn, label="guild.create_text_channel")
            if category is not None:
                channel = await create(name=name, category=category)
            else:
                channel = await create(name=name)
            ch_id = self._parse_optional_int(getattr(channel, "id", None))
            if ch_id is not None:
                logger.info("Created Discord text channel: %s (id=%s)", name, ch_id)
            return ch_id
        except Exception as exc:
            logger.warning("Failed to create Discord text channel '%s': %s", name, exc)
            return None

    @staticmethod
    def _persist_project_forum_ids(project_changes: list[tuple[str, int | None]]) -> None:
        """Write auto-provisioned project forum IDs to config.yml trusted_dirs.

        A None value removes the discord_forum key for that entry so stale IDs
        do not persist across restarts when re-provisioning fails.
        """
        import yaml

        from teleclaude.config import config_path

        try:
            with open(config_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}

            comp = raw.get("computer", {})
            trusted_dirs = comp.get("trusted_dirs", [])
            name_to_id = dict(project_changes)

            for td in trusted_dirs:
                if isinstance(td, dict) and td.get("name") in name_to_id:
                    new_id = name_to_id[td["name"]]
                    if new_id is None:
                        td.pop("discord_forum", None)
                    else:
                        td["discord_forum"] = new_id

            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(raw, f, default_flow_style=False, sort_keys=False)

            logger.info("Persisted project forum IDs to %s: %s", config_path, name_to_id)
        except Exception as exc:
            logger.warning("Failed to persist project forum IDs to config: %s", exc)

    @staticmethod
    def _persist_discord_channel_ids(changes: dict[str, int | dict[str, int]]) -> None:
        """Write auto-provisioned channel IDs to config.yml."""
        import yaml

        from teleclaude.config import config_path

        try:
            with open(config_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}

            discord_section = raw.setdefault("discord", {})
            for key, value in changes.items():
                if key == "categories" and isinstance(value, dict):
                    existing_cats = discord_section.get("categories") or {}
                    existing_cats.update(value)
                    discord_section["categories"] = existing_cats
                else:
                    discord_section[key] = value

            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(raw, f, default_flow_style=False, sort_keys=False)

            logger.info("Persisted discord channel IDs to %s: %s", config_path, changes)
        except Exception as exc:
            logger.warning("Failed to persist discord channel IDs to config: %s", exc)
