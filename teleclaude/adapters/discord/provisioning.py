"""Infrastructure provisioning helpers mixin for Discord adapter.

Handles guild resolution, channel/category/forum creation, and config persistence.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import replace
from enum import StrEnum
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.discord._channel_lookup import find_existing_text_channel_id
from teleclaude.config import config
from teleclaude.config.legacy_discord import (
    clear_legacy_project_forum_bindings,
    legacy_project_forum_bindings,
)
from teleclaude.core.db import db
from teleclaude.core.integration.discord_admin_state import (
    PROJECT_FORUM_KEY_PREFIX,
    DiscordArtifactKind,
    DiscordProvider,
    DiscordReflectionRecord,
    DiscordReflectionScope,
    DiscordScopeKind,
    project_forum_key,
    session_launcher_key,
)
from teleclaude.services.project_catalog import get_project_catalog_service
from teleclaude.services.project_catalog.models import ProjectCatalogEntry

logger = get_logger(__name__)

_PROJECT_FORUM_TOPIC = "Sessions for {name}"
_ID_ATTR = "id"
_NAME_ATTR = "name"
_DELETE_ATTR = "delete"
_FETCH_CHANNELS_ATTR = "fetch_channels"
_FETCH_CHANNELS_LABEL = "guild.fetch_channels"
_FORUM_DELETE_LABEL = "project forum delete"
_PRUNE_SKIPPED_EVENT = "discord.project_forum_prune.skipped"
_PRUNE_FORUM_DELETED_EVENT = "discord.project_forum_prune.forum_deleted"
_PRUNE_FORUM_FAILED_EVENT = "discord.project_forum_prune.forum_delete_failed"
_PRUNE_RECORD_CLEARED_EVENT = "discord.project_forum_prune.record_cleared"


class _StoredForumVerdict(StrEnum):
    """What one verification pass established about a stored project forum."""

    CURRENT = "current"
    GONE = "gone"
    UNVERIFIED = "unverified"


class _ProjectForumPruneSkip(StrEnum):
    """Why a reconciliation pass removed no unbacked project forum."""

    UNRESOLVED_ENTRY = "unresolved_registry_entry"
    UNRESOLVED_REGISTRY_FOLDER = "unresolved_registry_folder"
    CATCH_ALL_UNRESOLVED = "catch_all_forum_unresolved"
    CATEGORY_UNRESOLVED = "category_unresolved"
    LISTING_UNAVAILABLE = "channel_listing_unavailable"
    LISTING_FAILED = "channel_listing_failed"


AsyncDiscordCallable = Callable[..., Awaitable[object]]
discord_operation_exceptions: tuple[type[Exception], ...] = (AttributeError, RuntimeError, TypeError, ValueError)

try:
    from discord import DiscordException
except ImportError:
    pass
else:
    discord_operation_exceptions = (DiscordException,) + discord_operation_exceptions


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
        def _require_async_callable(fn: object, *, label: str) -> AsyncDiscordCallable: ...

        async def _get_channel(self, channel_id: int) -> object | None: ...

        @staticmethod
        def _is_forum_channel(channel: object) -> bool: ...

        async def _load_reflected_discord_ids(self) -> dict[str, int]: ...

        async def _migrate_legacy_discord_provider_ids(self) -> None: ...

        async def _ensure_category(
            self,
            guild: object,
            name: str,
            existing: dict[str, int],
            cat_changes: dict[str, int],
            *,
            key: str | None = None,
            create: bool = True,
        ) -> object | None: ...

        async def _persist_discord_channel_ids(self, changes: dict[str, int | dict[str, int]]) -> None: ...

        async def _project_forum_is_current(self, forum_id: int, category: object) -> bool: ...

        async def _sync_project_forum_positions(self, category: object | None) -> None: ...

        async def _build_project_forum_map(self) -> None: ...

        _project_category_id: int | None
        _all_sessions_channel_id: int | None

    async def resolve_guild(self) -> object | None:
        """Public wrapper for guild resolution used by infrastructure callers."""
        return await self._resolve_guild()

    async def persist_discord_channel_ids(self, changes: dict[str, int | dict[str, int]]) -> None:
        """Public wrapper for reflection persistence used by infrastructure callers."""
        await self._persist_discord_channel_ids(changes)

    @staticmethod
    def _legacy_project_forum_keys_by_root() -> dict[str, str]:
        """Return the still-valid name-based forum key for each bound folder."""
        keys_by_root: dict[str, str] = {}
        for binding in legacy_project_forum_bindings().entries:
            keys_by_root.setdefault(str(binding.folder.expanduser().resolve()), binding.logical_key)
        return keys_by_root

    @staticmethod
    def _project_forum_key(entry: ProjectCatalogEntry, legacy_keys_by_root: Mapping[str, str]) -> str | None:
        """Use identity when adopted and the former display name while still in transit."""
        if entry.identity is not None:
            return project_forum_key(entry.identity)
        return legacy_keys_by_root.get(str(entry.root)) or project_forum_key(entry.display_name)

    async def _migrate_legacy_project_forum_bindings(self) -> None:
        """Move resolved name-keyed forum records to their registry identities."""
        bindings = legacy_project_forum_bindings().entries
        if not bindings:
            return

        entries_by_root = {str(entry.root): entry for entry in get_project_catalog_service().list_entries()}
        imported_keys: set[str] = set()
        for binding in bindings:
            entry = entries_by_root.get(str(binding.folder.expanduser().resolve()))
            if entry is None or entry.identity is None:
                continue

            identity_key = project_forum_key(entry.identity)
            if binding.logical_key != identity_key:
                old_record = await db.get_discord_reflection(binding.logical_key)
                current_record = await db.get_discord_reflection(identity_key)
                if old_record is not None and current_record is None:
                    await db.upsert_discord_reflection(replace(old_record, logical_key=identity_key))
                    await db.delete_discord_reflection(binding.logical_key)
                elif old_record is not None and current_record is not None:
                    if old_record.provider_id != current_record.provider_id:
                        logger.warning(
                            "Keeping legacy Discord forum binding %s: identity key already points to another forum",
                            binding.logical_key,
                        )
                        continue
                    await db.delete_discord_reflection(binding.logical_key)
            imported_keys.add(binding.logical_key)

        if imported_keys:
            clear_legacy_project_forum_bindings(frozenset(imported_keys))

    async def _reconcile_project_forums(self) -> None:
        """Reconcile local forum channels and routing against the current registry."""
        if self._client is None or self._guild_id is None:
            return
        guild = await self._resolve_guild()
        if guild is None:
            logger.warning("Cannot reconcile project forums: guild %s not found", self._guild_id)
            return

        await self._migrate_legacy_discord_provider_ids()
        await self._migrate_legacy_project_forum_bindings()
        computer_name_slug = config.computer.name.lower().replace("-", "_").replace(" ", "_")
        category_key = f"projects_{computer_name_slug}"
        category_changes: dict[str, int] = {}
        existing_categories = await self._load_reflected_discord_ids()
        category = await self._ensure_category(
            guild,
            f"Projects - {config.computer.name}",
            existing_categories,
            category_changes,
            key=category_key,
        )
        if category is None:
            logger.warning("Cannot reconcile project forums: project category is unavailable")
            return

        self._project_category_id = self._parse_optional_int(getattr(category, "id", None))
        if category_changes:
            await self._persist_discord_channel_ids({"categories": category_changes})
        await self._ensure_project_forums(guild, category)
        await self._sync_project_forum_positions(category)
        await self._build_project_forum_map()

    async def _ensure_project_forums(self, guild: object, category: object | None) -> None:
        """Ensure every resolved registry identity has its own forum reflection."""
        if category is None:
            logger.warning("Skipping project forum provisioning: Projects category is unavailable")
            return

        catalog = get_project_catalog_service()
        entries = catalog.list_entries()
        category_forums = await self._list_category_forums(guild, category)
        legacy_keys_by_root = self._legacy_project_forum_keys_by_root()
        project_changes: list[tuple[str, int | None]] = []
        current_records: dict[str, DiscordReflectionRecord] = {}
        unverified_forum_keys: set[str] = set()
        claimed_forum_ids: set[int] = set()
        checked_forum_keys: set[str] = set()

        for entry in entries:
            forum_key = self._project_forum_key(entry, legacy_keys_by_root)
            if forum_key is None:
                continue
            if forum_key in checked_forum_keys:
                continue
            checked_forum_keys.add(forum_key)
            record = await db.get_discord_reflection(forum_key)
            if record is None:
                continue
            verdict = await self._stored_forum_verdict(record.provider_id, category, category_forums)
            if verdict is _StoredForumVerdict.GONE:
                continue
            if verdict is _StoredForumVerdict.UNVERIFIED:
                unverified_forum_keys.add(forum_key)
                claimed_forum_ids.add(record.provider_id)
                continue
            if record.provider_id in claimed_forum_ids:
                await db.delete_discord_reflection(forum_key)
                logger.warning("Discord forum %s is already assigned to another registry identity", forum_key)
                continue
            current_records[forum_key] = record
            claimed_forum_ids.add(record.provider_id)

        provisioned_forum_ids: dict[str, int] = {}
        for entry in entries:
            forum_key = self._project_forum_key(entry, legacy_keys_by_root)
            if forum_key is None:
                continue
            if (
                current_records.get(forum_key) is not None
                or forum_key in provisioned_forum_ids
                or forum_key in unverified_forum_keys
            ):
                continue
            stale_cleared = await db.get_discord_reflection(forum_key) is not None
            forum_id = await self._find_or_create_forum(
                guild,
                category,
                entry.display_name,
                entry.description or _PROJECT_FORUM_TOPIC.format(name=entry.display_name),
                excluded_ids=frozenset(claimed_forum_ids),
            )
            if forum_id is not None:
                claimed_forum_ids.add(forum_id)
                provisioned_forum_ids[forum_key] = forum_id
                project_changes.append((forum_key.removeprefix(PROJECT_FORUM_KEY_PREFIX), forum_id))
            elif stale_cleared:
                project_changes.append((forum_key.removeprefix(PROJECT_FORUM_KEY_PREFIX), None))

        if project_changes:
            await self._persist_project_forum_ids(project_changes)

        backed_forum_keys = frozenset(current_records) | frozenset(provisioned_forum_ids)
        if category_forums is None:
            return
        if backed_forum_keys != frozenset(checked_forum_keys):
            logger.info(_PRUNE_SKIPPED_EVENT, reason=_ProjectForumPruneSkip.UNRESOLVED_ENTRY.value)
            return
        unresolved_roots = catalog.list_unresolved_roots()
        if unresolved_roots:
            logger.info(
                _PRUNE_SKIPPED_EVENT,
                reason=_ProjectForumPruneSkip.UNRESOLVED_REGISTRY_FOLDER.value,
                folders=[str(root) for root in unresolved_roots],
            )
            return
        await self._prune_unbacked_project_forums(category_forums, frozenset(claimed_forum_ids), backed_forum_keys)

    async def _list_category_forums(self, guild: object, category: object) -> dict[int, object] | None:
        """Return the category's forums by ID from Discord's REST listing, or None when it is unavailable.

        The REST listing is the conclusive view of the category: the gateway cache
        and single-channel lookups can miss a forum that exists.
        """
        if self._parse_optional_int(getattr(category, _ID_ATTR, None)) is None:
            logger.info(_PRUNE_SKIPPED_EVENT, reason=_ProjectForumPruneSkip.CATEGORY_UNRESOLVED.value)
            return None
        fetch_fn = getattr(guild, _FETCH_CHANNELS_ATTR, None)
        if not callable(fetch_fn):
            logger.info(_PRUNE_SKIPPED_EVENT, reason=_ProjectForumPruneSkip.LISTING_UNAVAILABLE.value)
            return None
        try:
            fetched = await self._require_async_callable(fetch_fn, label=_FETCH_CHANNELS_LABEL)()
        except discord_operation_exceptions as exc:
            logger.warning(_PRUNE_SKIPPED_EVENT, reason=_ProjectForumPruneSkip.LISTING_FAILED.value, error=str(exc))
            return None
        if not isinstance(fetched, Iterable):
            logger.warning(_PRUNE_SKIPPED_EVENT, reason=_ProjectForumPruneSkip.LISTING_FAILED.value)
            return None
        forums: dict[int, object] = {}
        for channel in fetched:
            channel_id = self._parse_optional_int(getattr(channel, _ID_ATTR, None))
            if (
                channel_id is not None
                and self._is_forum_channel(channel)
                and self._channel_matches_category(channel, category)
            ):
                forums[channel_id] = channel
        return forums

    async def _stored_forum_verdict(
        self, forum_id: int, category: object, category_forums: Mapping[int, object] | None
    ) -> _StoredForumVerdict:
        """Decide whether a stored project forum is current, gone, or could not be verified."""
        if category_forums is not None:
            return _StoredForumVerdict.CURRENT if forum_id in category_forums else _StoredForumVerdict.GONE
        channel = await self._get_channel(forum_id)
        if channel is None:
            return _StoredForumVerdict.UNVERIFIED
        if self._is_forum_channel(channel) and self._channel_matches_category(channel, category):
            return _StoredForumVerdict.CURRENT
        return _StoredForumVerdict.GONE

    async def _prune_unbacked_project_forums(
        self,
        category_forums: Mapping[int, object],
        backed_forum_ids: frozenset[int],
        backed_forum_keys: frozenset[str],
    ) -> None:
        """Delete project-category forums and project-forum records that no registry entry backs.

        The catch-all forum is part of the category's desired shape and is kept.
        """
        catch_all_id = self._all_sessions_channel_id
        if catch_all_id is None:
            logger.info(_PRUNE_SKIPPED_EVENT, reason=_ProjectForumPruneSkip.CATCH_ALL_UNRESOLVED.value)
            return

        kept_forum_ids = backed_forum_ids | {catch_all_id}
        for forum_id, forum in category_forums.items():
            if forum_id not in kept_forum_ids:
                await self._delete_unbacked_project_forum(forum_id, forum)

        for record in await db.list_discord_reflections():
            if record.logical_key.startswith(PROJECT_FORUM_KEY_PREFIX) and record.logical_key not in backed_forum_keys:
                await db.delete_discord_reflection(record.logical_key)
                logger.info(_PRUNE_RECORD_CLEARED_EVENT, logical_key=record.logical_key, forum_id=record.provider_id)

    async def _delete_unbacked_project_forum(self, forum_id: int, forum: object) -> None:
        """Delete one unbacked forum and the launcher record that belonged to it."""
        forum_name = getattr(forum, _NAME_ATTR, None)
        try:
            await self._require_async_callable(getattr(forum, _DELETE_ATTR, None), label=_FORUM_DELETE_LABEL)()
        except discord_operation_exceptions as exc:
            logger.warning(_PRUNE_FORUM_FAILED_EVENT, forum_id=forum_id, forum_name=forum_name, error=str(exc))
            return
        await db.delete_discord_reflection(session_launcher_key(forum_id))
        logger.info(_PRUNE_FORUM_DELETED_EVENT, forum_id=forum_id, forum_name=forum_name)

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
                    fetch_guild = self._require_async_callable(fetch_guild_fn, label="fetch_guild")
                    guild = await fetch_guild(self._guild_id)
                except discord_operation_exceptions as exc:
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
            create_category = self._require_async_callable(create_fn, label="guild.create_category")
            category = await create_category(name=name)
            logger.info("Created Discord category: %s (id=%s)", name, getattr(category, "id", "?"))
            return category
        except discord_operation_exceptions as exc:
            logger.warning("Failed to create Discord category '%s': %s", name, exc)
            return None

    async def _find_or_create_forum(
        self,
        guild: object,
        category: object | None,
        name: str,
        topic: str,
        *,
        create: bool = True,
        excluded_ids: frozenset[int] | None = None,
    ) -> int | None:
        """Find an existing forum by name within the category, or create one under it.

        Scope is the set of forums in ``guild.channels`` whose ``category_id``
        matches the target category — the same projection ``CategoryChannel.channels``
        derives from. A same-name forum living in another category is invisible
        here and will not be reclaimed. When ``create`` is False, resolves in
        scope but never creates — shared forums are provisioned by the master
        computer only. A forum without a target category is never created;
        callers must supply the per-computer or shared category.
        """
        if category is None:
            logger.warning("Refusing to create forum '%s' without a target category", name)
            return None

        category_channels = getattr(category, "channels", None)
        guild_channels = getattr(guild, "channels", None)
        if category_channels is None and guild_channels is None:
            logger.warning("Guild channel cache not populated; refusing to create forum '%s'", name)
            return None

        category_scoped_read = category_channels is not None
        excluded_forum_ids = excluded_ids or frozenset()
        for ch in self._candidate_channels_for_category(guild, category):
            ch_name = getattr(ch, "name", None)
            if (
                isinstance(ch_name, str)
                and ch_name.lower() == name.lower()
                and self._is_forum_channel(ch)
                and (category_scoped_read or self._channel_matches_category(ch, category))
            ):
                found_id = self._parse_optional_int(getattr(ch, "id", None))
                if found_id is not None and found_id not in excluded_forum_ids:
                    logger.debug("Found existing Discord forum: %s (id=%s)", name, found_id)
                    return found_id

        if not create:
            return None

        create_fn = getattr(guild, "create_forum", None)
        if not callable(create_fn):
            logger.warning("Guild has no create_forum method; cannot create '%s'", name)
            return None

        try:
            create_forum = self._require_async_callable(create_fn, label="guild.create_forum")
            forum = await create_forum(name=name, topic=topic, category=category)
            forum_id = self._parse_optional_int(getattr(forum, "id", None))
            if forum_id is not None:
                logger.info("Created Discord forum: %s (id=%s)", name, forum_id)
            return forum_id
        except discord_operation_exceptions as exc:
            logger.warning("Failed to create Discord forum '%s': %s", name, exc)
            return None

    def _candidate_channels_for_category(self, guild: object, category: object | None) -> list[object]:
        """Return channels from the requested category when Discord exposes them."""
        if category is not None:
            category_channels = getattr(category, "channels", None)
            if category_channels is not None:
                return list(category_channels)
        channels = getattr(guild, "channels", None)
        return list(channels) if channels is not None else []

    def _channel_matches_category(self, channel: object, category: object | None) -> bool:
        """Return whether a channel belongs to the requested Discord category."""
        if category is None:
            return True

        category_id = self._parse_optional_int(getattr(category, "id", None))
        if category_id is None:
            return False

        channel_category_id = self._parse_optional_int(getattr(channel, "category_id", None))
        if channel_category_id is None:
            channel_category = getattr(channel, "category", None)
            channel_category_id = self._parse_optional_int(getattr(channel_category, "id", None))
        return channel_category_id == category_id

    async def _find_or_create_text_channel(
        self, guild: object, category: object | None, name: str, *, create: bool = True
    ) -> int | None:
        """Find an existing text channel by name, or create one under the category.

        Refuses to create when the guild channel cache is not populated. When
        ``create`` is False, resolves an existing channel by name but never
        creates — shared channels are provisioned by the master computer only.
        """
        existing_channel_id = find_existing_text_channel_id(guild, name, self._parse_optional_int)
        if existing_channel_id is not None:
            logger.debug("Found existing Discord text channel: %s (id=%s)", name, existing_channel_id)
            return existing_channel_id

        if not create:
            return None

        # Cache is populated and channel not found — safe to create.
        create_fn = getattr(guild, "create_text_channel", None)
        if not callable(create_fn):
            logger.warning("Guild has no create_text_channel method; cannot create '%s'", name)
            return None

        try:
            create_text_channel = self._require_async_callable(create_fn, label="guild.create_text_channel")
            if category is not None:
                channel = await create_text_channel(name=name, category=category)
            else:
                channel = await create_text_channel(name=name)
            ch_id = self._parse_optional_int(getattr(channel, "id", None))
            if ch_id is not None:
                logger.info("Created Discord text channel: %s (id=%s)", name, ch_id)
            return ch_id
        except discord_operation_exceptions as exc:
            logger.warning("Failed to create Discord text channel '%s': %s", name, exc)
            return None

    async def _persist_project_forum_ids(self, project_changes: list[tuple[str, int | None]]) -> None:
        """Persist project forum observations without returning provider state to config."""
        for identity, forum_id in project_changes:
            if forum_id is None:
                continue
            await self._upsert_reflection_id(project_forum_key(identity), forum_id, DiscordArtifactKind.FORUM)

    async def _persist_discord_channel_ids(self, changes: dict[str, int | dict[str, int]]) -> None:
        """Persist newly observed shared provider identifiers through reflection state."""
        for key, value in changes.items():
            if key == "categories" and isinstance(value, dict):
                for name, provider_id in value.items():
                    await self._upsert_reflection_id(
                        f"discord.categories.{name}", provider_id, DiscordArtifactKind.CATEGORY
                    )
                continue
            if isinstance(value, int):
                await self._upsert_reflection_id(f"discord.{key}", value, DiscordArtifactKind.TEXT_CHANNEL)

    @staticmethod
    async def _upsert_reflection_id(logical_key: str, provider_id: int, artifact_kind: DiscordArtifactKind) -> None:
        """Store one shared provider identifier without returning it to machine config."""
        await db.upsert_discord_reflection(
            DiscordReflectionRecord(
                provider=DiscordProvider.DISCORD,
                logical_key=logical_key,
                artifact_kind=artifact_kind,
                scope=DiscordReflectionScope(kind=DiscordScopeKind.SHARED, value="shared"),
                provider_id=provider_id,
                parent_provider_id=None,
                metadata_json="{}",
                verified_at=None,
            )
        )
