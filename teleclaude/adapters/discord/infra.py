"""Infrastructure provisioning mixin for Discord adapter.

Handles auto-provisioning of Discord channels, categories, forums, launcher
messages, project forum mapping, team channels, and config persistence.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.discord._runtime import recoverable_operation_errors
from teleclaude.adapters.discord.channel_ops import gather_forum_threads
from teleclaude.adapters.discord.provisioning import ProvisioningMixin
from teleclaude.adapters.discord.team_channels import TeamChannelsMixin
from teleclaude.config import config

if TYPE_CHECKING:
    from types import ModuleType
from teleclaude.adapters.discord.session_launcher import SessionLauncherView
from teleclaude.config.loader import load_global_config
from teleclaude.core.db import db

logger = get_logger(__name__)


class InfrastructureMixin(TeamChannelsMixin, ProvisioningMixin):
    """Mixin providing Discord channel infrastructure provisioning for DiscordAdapter.

    Required host attributes:
    - _client: DiscordClientLike | None
    - _guild_id: int | None
    - _discord: ModuleType
    - _help_desk_channel_id: int | None
    - _all_sessions_channel_id: int | None
    - _escalation_channel_id: int | None
    - _operator_chat_channel_id: int | None
    - _announcements_channel_id: int | None
    - _general_channel_id: int | None
    - _project_forum_map: dict[str, int]
    - _forum_project_map: dict[int, str]
    - _team_channel_map: dict[int, str]
    - _require_async_callable(fn, *, label) -> Callable
    - _get_channel(channel_id) -> object | None (async)
    - _parse_optional_int(value) -> int | None
    - _is_forum_channel(channel) -> bool
    - _get_enabled_agents() -> list[str]
    - _multi_agent: bool
    - _handle_launcher_click(interaction, agent_name, launcher_forum_id) -> None (async)
    - _build_session_launcher_view(forum_id) -> object
    - _post_or_update_launcher(forum_id) -> None (async)
    """

    _project_forum_map: dict[str, int]
    _forum_project_map: dict[int, str]

    if TYPE_CHECKING:
        _discord: ModuleType
        _client: object
        _help_desk_channel_id: int | None
        _all_sessions_channel_id: int | None
        _escalation_channel_id: int | None
        _operator_chat_channel_id: int | None
        _announcements_channel_id: int | None
        _general_channel_id: int | None

        def _parse_optional_int(self, value: object) -> int | None: ...

        @staticmethod
        def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]: ...

        async def _get_channel(self, channel_id: int) -> object | None: ...

        @staticmethod
        def _is_forum_channel(channel: object) -> bool: ...

        def _get_enabled_agents(self) -> list[str]: ...

        @property
        def _multi_agent(self) -> bool: ...

        async def _handle_launcher_click(
            self,
            interaction: object,
            agent_name: str,
            launcher_forum_id: int | None = None,
        ) -> None: ...

        _launcher_registration_view: object | None

    # =========================================================================
    # Channel Validation
    # =========================================================================

    async def _validate_channel_id(self, channel_id: int | None) -> int | None:
        """Return channel_id if it resolves to a live Discord channel, None if stale."""
        if channel_id is None:
            return None
        ch = await self._get_channel(channel_id)
        if ch is None:
            logger.warning("Stored Discord channel ID %s is stale (not found), re-provisioning", channel_id)
            return None
        return channel_id

    async def _validate_forum_in_category(self, channel_id: int | None, category: object | None) -> int | None:
        """Return channel_id only if the forum still belongs to this computer's category.

        Per-computer forums are owned exclusively by their creating computer. A
        stored ID whose forum has moved to another category — or no longer exists
        — must be discarded so re-provisioning creates a fresh forum here.
        """
        if channel_id is None or category is None:
            return None
        category_id = self._parse_optional_int(getattr(category, "id", None))
        if category_id is None:
            return None
        ch = await self._get_channel(channel_id)
        if ch is None or not self._is_forum_channel(ch):
            return None
        ch_cat_id = self._parse_optional_int(getattr(ch, "category_id", None))
        if ch_cat_id is None:
            ch_category = getattr(ch, "category", None)
            ch_cat_id = self._parse_optional_int(getattr(ch_category, "id", None))
        if ch_cat_id != category_id:
            return None
        return channel_id

    # =========================================================================
    # Infrastructure Provisioning
    # =========================================================================

    async def _ensure_discord_infrastructure(self) -> None:
        """Auto-provision the Discord channel structure for this computer.

        Shared categories — Operations (#announcements, #general), Help Desk
        (#customer-sessions, #escalations, #operator-chat), and Team (per-person
        text channels) — are generic across the guild and provisioned by the
        master computer only. Non-master computers resolve these by name but
        never create them, so a shared Discord app cannot accrue duplicates.

        The per-computer category — Projects - {computer} (#unknown catch-all
        forum plus per-project forums ordered by trusted_dirs) — is always
        provisioned by every computer; its name is unique per machine.

        Idempotent: validates stored IDs before trusting them, then resolves by
        name. Creation, where allowed, happens only after a conclusive name-search
        finds nothing — so a stale cached ID never spawns a duplicate, and a
        non-master never creates a shared channel. Persists provisioned IDs to
        config.yml.
        """
        if self._client is None or self._guild_id is None:
            return

        guild = await self._resolve_guild()
        if guild is None:
            logger.warning("Cannot auto-provision Discord channels: guild %s not found", self._guild_id)
            return

        is_master = config.computer.is_master
        changes: dict[str, int | dict[str, int]] = {}
        cat_changes: dict[str, int] = {}
        existing_cats = config.discord.categories or {}

        # --- Category: Operations (shared — master provisions, others resolve) ---
        ops_cat = await self._ensure_category(guild, "Operations", existing_cats, cat_changes, create=is_master)

        self._announcements_channel_id = await self._validate_channel_id(self._announcements_channel_id)
        if self._announcements_channel_id is None:
            ch_id = await self._find_or_create_text_channel(guild, ops_cat, "announcements", create=is_master)
            if ch_id is not None:
                self._announcements_channel_id = ch_id
                changes["announcements_channel_id"] = ch_id

        self._general_channel_id = await self._validate_channel_id(self._general_channel_id)
        if self._general_channel_id is None:
            ch_id = await self._find_or_create_text_channel(guild, ops_cat, "general", create=is_master)
            if ch_id is not None:
                self._general_channel_id = ch_id
                changes["general_channel_id"] = ch_id

        # --- Category: Help Desk (shared — master provisions, others resolve) ---
        hd_cat = await self._ensure_category(guild, "Help Desk", existing_cats, cat_changes, create=is_master)

        self._help_desk_channel_id = await self._validate_channel_id(self._help_desk_channel_id)
        if self._help_desk_channel_id is None:
            forum_id = await self._find_or_create_forum(
                guild, hd_cat, "Customer Sessions", "Customer support sessions", create=is_master
            )
            if forum_id is not None:
                self._help_desk_channel_id = forum_id
                changes["help_desk_channel_id"] = forum_id

        self._escalation_channel_id = await self._validate_channel_id(self._escalation_channel_id)
        if self._escalation_channel_id is None:
            forum_id = await self._find_or_create_forum(
                guild, hd_cat, "Escalations", "Human-admin escalation relay threads", create=is_master
            )
            if forum_id is not None:
                self._escalation_channel_id = forum_id
                changes["escalation_channel_id"] = forum_id

        self._operator_chat_channel_id = await self._validate_channel_id(self._operator_chat_channel_id)
        if self._operator_chat_channel_id is None:
            ch_id = await self._find_or_create_text_channel(guild, hd_cat, "operator-chat", create=is_master)
            if ch_id is not None:
                self._operator_chat_channel_id = ch_id
                changes["operator_chat_channel_id"] = ch_id

        # --- Category: Projects - {computer} (per-computer, always enabled when Discord is configured) ---
        computer_name_slug = config.computer.name.lower().replace("-", "_").replace(" ", "_")
        proj_cat = await self._ensure_category(
            guild,
            f"Projects - {config.computer.name}",
            existing_cats,
            cat_changes,
            key=f"projects_{computer_name_slug}",
        )

        if proj_cat is None:
            logger.warning("Skipping project forum routing: Projects category is unavailable")
            self._all_sessions_channel_id = None
            self._project_forum_map = {}
            self._forum_project_map = {}
        else:
            # "Unknown" is the catch-all forum for sessions that don't match any project
            self._all_sessions_channel_id = await self._validate_project_forum_id(
                self._all_sessions_channel_id, proj_cat
            )
            if self._all_sessions_channel_id is None:
                forum_id = await self._find_or_create_forum(
                    guild, proj_cat, "Unknown", "Sessions from unrecognized project paths"
                )
                if forum_id is not None:
                    self._all_sessions_channel_id = forum_id
                    changes["all_sessions_channel_id"] = forum_id

            await self._ensure_project_forums(guild, proj_cat)
            await self._sync_project_forum_positions(proj_cat)

            # Build project-path-to-forum mapping for session routing
            self._build_project_forum_map()

        # --- Category: Team (shared — master provisions, others resolve) ---
        try:
            global_cfg = load_global_config()
            if global_cfg.people:
                team_cat = await self._ensure_category(guild, "Team", existing_cats, cat_changes, create=is_master)
                await self._ensure_team_channels(guild, team_cat, global_cfg.people, create=is_master)  # type: ignore[arg-type]
                logger.info("Team channels provisioned: %d entries in _team_channel_map", len(self._team_channel_map))
            else:
                logger.info("No people in global config — skipping team channel provisioning")
        # Team provisioning is best-effort: it runs after the shared and per-computer
        # categories are already provisioned, and its failure (e.g. a malformed people
        # config) must not abort that completed work or crash the daemon on startup.
        except Exception as exc:
            logger.warning("Failed to provision team category: %s", exc, exc_info=True)

        # Persist all changes
        if cat_changes:
            changes["categories"] = cat_changes
        if changes:
            self._persist_discord_channel_ids(changes)
            logger.info("Discord infrastructure provisioned: %s", list(changes.keys()))

    async def _ensure_category(
        self,
        guild: object,
        name: str,
        existing: dict[str, int],
        cat_changes: dict[str, int],
        *,
        key: str | None = None,
        create: bool = True,
    ) -> object | None:
        """Resolve a category idempotently: cached ID, then name search, then create.

        Always searches by name before creating. Creation only happens when a
        conclusive search confirms the category genuinely does not exist in Discord.
        If the search is inconclusive (cache empty, API unavailable), refuses to
        create to prevent duplicates. When ``create`` is False, resolves an
        existing category by name but never creates — shared categories are
        provisioned by the master computer only.
        """
        key = key if key is not None else name.lower().replace(" ", "_")

        # 1. Try the cached ID from config.yml
        cached_id = existing.get(key)
        if cached_id is not None:
            cat = await self._get_channel(cached_id)
            if cat is not None:
                return cat
            logger.warning("Cached category ID %s for '%s' is stale", cached_id, name)

        # 2. Always search by name before considering creation.
        #    Returns (category_or_None, conclusive: bool).
        cat, conclusive = await self._find_category_by_name_robust(guild, name)
        if cat is not None:
            cat_id = self._parse_optional_int(getattr(cat, "id", None))
            if cat_id is not None:
                cat_changes[key] = cat_id
            return cat

        if not create:
            return None

        # 3. If lookup was inconclusive, refuse to create — we can't confirm absence.
        if not conclusive:
            logger.warning("Category '%s' lookup inconclusive; skipping to prevent duplicates", name)
            return None

        # 4. Lookup was conclusive and category doesn't exist — safe to create.
        cat = await self._find_or_create_category(guild, name)
        cat_id = self._parse_optional_int(getattr(cat, "id", None)) if cat else None
        if cat_id is not None:
            cat_changes[key] = cat_id
        return cat

    async def _find_category_by_name_robust(self, guild: object, name: str) -> tuple[object | None, bool]:
        """Find a category by name using guild cache, falling back to API fetch.

        Returns (category, conclusive) where conclusive=True means the search
        reliably determined whether the category exists. If conclusive=False,
        the caller must NOT create to avoid duplicates.
        """
        # Try guild cache first
        categories = getattr(guild, "categories", None)
        if categories is not None:
            for cat in categories:
                cat_name = getattr(cat, "name", None)
                if isinstance(cat_name, str) and cat_name.lower() == name.lower():
                    logger.debug("Found category by name (cache): %s (id=%s)", name, getattr(cat, "id", "?"))
                    return cat, True
            # Check if cache has entries — if so, the search is conclusive
            has_entries = False
            for _ in categories:
                has_entries = True
                break
            if has_entries:
                return None, True

        # Cache is empty or None — might not be populated yet.
        # Fall back to REST API fetch_channels to be safe.
        fetch_fn = getattr(guild, "fetch_channels", None)
        if not callable(fetch_fn):
            logger.warning("Guild cache empty and no fetch_channels; cannot verify category '%s'", name)
            return None, False

        try:
            fetched = await self._require_async_callable(fetch_fn, label="guild.fetch_channels")()
            channels_list = list(fetched) if fetched is not None else []  # type: ignore[call-overload]
            for ch in channels_list:
                ch_type = getattr(ch, "type", None)
                is_category = ch_type is not None and getattr(ch_type, "value", ch_type) == 4
                if not is_category:
                    continue
                ch_name = getattr(ch, "name", None)
                if isinstance(ch_name, str) and ch_name.lower() == name.lower():
                    logger.debug("Found category by name (API): %s (id=%s)", name, getattr(ch, "id", "?"))
                    return ch, True
            # API returned results but category not found — conclusive absence
            return None, True
        except Exception as exc:
            logger.warning("Failed to fetch channels for category lookup '%s': %s", name, exc)
            return None, False

    def _build_project_forum_map(self) -> None:
        """Build project_path -> forum_id mapping from trusted dirs.

        Sorted by path length descending so most-specific paths match first
        during prefix lookup (e.g. ~/Workspace/InstruktAI before ~).
        """
        entries = [
            (td.path, td.discord_forum)
            for td in config.computer.get_all_trusted_dirs()
            if td.discord_forum is not None and td.path
        ]
        entries.sort(key=lambda e: len(e[0]), reverse=True)
        self._project_forum_map = dict(entries)
        self._forum_project_map = {forum_id: project_path for project_path, forum_id in entries}
        logger.info("Discord project forum map: %d entries", len(self._project_forum_map))

    def _resolve_project_from_forum(self, forum_id: int) -> str | None:
        return self._forum_project_map.get(forum_id)

    def _resolve_parent_forum_id(self, channel: object | None) -> int | None:
        if channel is None:
            return None
        parent_id = self._parse_optional_int(getattr(channel, "parent_id", None))
        if parent_id is not None:
            return parent_id
        parent = getattr(channel, "parent", None)
        return self._parse_optional_int(getattr(parent, "id", None))

    @staticmethod
    def _extract_forum_thread_result(create_result: object) -> tuple[object | None, object | None]:
        thread = getattr(create_result, "thread", None)
        starter_message = getattr(create_result, "message", None)
        if thread is None and isinstance(create_result, tuple) and create_result:
            thread = create_result[0]
            if len(create_result) > 1:
                starter_message = create_result[1]
        if thread is None:
            thread = create_result
        return thread, starter_message

    def _build_session_launcher_view(self, *, forum_id: int | None = None) -> object:
        return SessionLauncherView(
            enabled_agents=self._get_enabled_agents(),
            on_launch=self._handle_launcher_click,
            launcher_forum_id=forum_id,
        )

    def _register_session_launcher_view(self, *, forum_id: int | None, message_id: int | None) -> None:
        if self._client is None:
            return
        add_view = getattr(self._client, "add_view", None)
        if not callable(add_view):
            return

        view = self._build_session_launcher_view(forum_id=forum_id)
        try:
            if message_id is None:
                add_view(view)
                self._launcher_registration_view = view
                return
            add_view(view, message_id=message_id)
        except Exception as exc:
            logger.warning(
                "Failed to register persistent Discord launcher view for forum %s message %s: %s",
                forum_id,
                message_id,
                exc,
            )

    async def _post_or_update_launcher(self, forum_id: int) -> None:
        """Converge a forum to exactly one current, pinned, registered launcher thread.

        Identity-based, idempotent: discovers every existing launcher thread by
        its durable ``launch:`` button marker, keeps exactly one survivor, and
        deletes the rest — mirroring the resolve-by-identity discipline the
        forum/category layer already has. A candidate whose launcher status
        cannot be determined (fetch failure) makes the whole pass inconclusive
        for this forum: no create, no delete, no pin, retried on the next
        on_ready.
        """
        if self._client is None or not self._multi_agent:
            return

        if forum_id == self._help_desk_channel_id and not config.computer.is_master:
            logger.debug("Skipping shared Help Desk launcher reconciliation on non-master computer")
            return

        forum_channel = await self._get_channel(forum_id)
        if forum_channel is None:
            logger.warning("Cannot post launcher for forum %s: channel not found", forum_id)
            return

        if not self._is_forum_channel(forum_channel):
            logger.warning("Cannot post launcher for forum %s: channel is not a forum", forum_id)
            return

        threads, conclusive = await gather_forum_threads(forum_channel, self._discord, forum_id=forum_id)
        if not conclusive:
            logger.warning(
                "Discord thread discovery inconclusive for forum %s; skipping launcher reconciliation", forum_id
            )
            return

        candidates: list[tuple[object, object]] = []
        for thread in threads:
            resolved, message = await self._resolve_launcher_starter_message(thread)
            if not resolved:
                logger.warning(
                    "Launcher status of thread %s in forum %s could not be determined; skipping reconciliation",
                    getattr(thread, "id", None),
                    forum_id,
                )
                return
            if message is not None:
                candidates.append((thread, message))

        setting_prefix = f"discord_launcher:{forum_id}"
        legacy_message_key = setting_prefix
        thread_key = f"{setting_prefix}:thread_id"
        message_key = f"{setting_prefix}:message_id"

        stored_thread_id = self._parse_optional_int(await db.get_system_setting(thread_key))
        if stored_thread_id is None:
            stored_thread_id = self._parse_optional_int(await db.get_system_setting(legacy_message_key))

        survivor = self._select_launcher_survivor(candidates, stored_thread_id)
        survivor_thread = survivor[0] if survivor is not None else None
        stale_threads = [thread for thread, _ in candidates if thread is not survivor_thread]
        await self._delete_stale_launcher_threads(stale_threads, forum_id=forum_id)

        view = self._build_session_launcher_view(forum_id=forum_id)
        if survivor is not None:
            launcher_thread, launcher_message = survivor
            if not await self._update_launcher_message(launcher_message, view=view, forum_id=forum_id):
                return
        else:
            created = await self._create_launcher_thread(forum_channel, view=view, forum_id=forum_id)
            if created is None:
                return
            launcher_thread, launcher_message = created

        launcher_thread_id = self._parse_optional_int(getattr(launcher_thread, "id", None))
        if launcher_thread_id is None:
            logger.warning("Discord launcher thread for forum %s has no resolvable id", forum_id)
            return
        launcher_message_id = self._parse_optional_int(getattr(launcher_message, "id", None))
        if launcher_message_id is None:
            launcher_message_id = launcher_thread_id

        await self._pin_launcher_message(launcher_message, forum_id=forum_id)
        await self._pin_launcher_thread(launcher_thread, forum_id=forum_id)

        await db.set_system_setting(thread_key, str(launcher_thread_id))
        await db.set_system_setting(message_key, str(launcher_message_id))
        await db.set_system_setting(legacy_message_key, str(launcher_message_id))
        self._register_session_launcher_view(forum_id=forum_id, message_id=launcher_message_id)

    async def _resolve_launcher_starter_message(self, thread: object) -> tuple[bool, object | None]:
        """Return ``(conclusive, message)``; ``message`` is set iff the thread is a launcher.

        A forum thread's starter message shares the thread's id, so it is
        fetched directly rather than trusted from cache. ``conclusive`` is
        False only when the fetch itself fails — the caller must then treat
        the whole forum's launcher set as indeterminate.
        """
        thread_id = self._parse_optional_int(getattr(thread, "id", None))
        fetch_fn = getattr(thread, "fetch_message", None)
        if thread_id is None or not callable(fetch_fn):
            return True, None

        recoverable_errors = recoverable_operation_errors(self._discord)
        try:
            message = await self._require_async_callable(fetch_fn, label="Discord thread fetch_message")(thread_id)
        except recoverable_errors as exc:
            logger.warning("Could not resolve starter message for Discord thread %s: %s", thread_id, exc)
            return False, None

        return True, (message if self._is_launcher_message(message) else None)

    def _is_launcher_message(self, message: object) -> bool:
        """A launcher's starter message is bot-authored and carries a ``launch:`` button."""
        author_id = self._parse_optional_int(getattr(getattr(message, "author", None), "id", None))
        client_user_id = self._parse_optional_int(getattr(getattr(self._client, "user", None), "id", None))
        if client_user_id is None or author_id != client_user_id:
            return False

        for row in getattr(message, "components", None) or []:
            for child in getattr(row, "children", None) or []:
                custom_id = getattr(child, "custom_id", None)
                if isinstance(custom_id, str) and custom_id.startswith("launch:"):
                    return True
        return False

    @staticmethod
    def _select_launcher_survivor(
        candidates: list[tuple[object, object]], stored_thread_id: int | None
    ) -> tuple[object, object] | None:
        """Prefer the stored-record thread, else the currently pinned one, else the newest."""
        if not candidates:
            return None

        if stored_thread_id is not None:
            for thread, message in candidates:
                if getattr(thread, "id", None) == stored_thread_id:
                    return thread, message

        for thread, message in candidates:
            if getattr(getattr(thread, "flags", None), "pinned", False):
                return thread, message

        return max(candidates, key=lambda candidate: getattr(candidate[0], "id", 0) or 0)

    async def _delete_stale_launcher_threads(self, threads: list[object], *, forum_id: int) -> None:
        """Delete every launcher thread that lost survivor selection, isolating per-thread failures."""
        recoverable_errors = recoverable_operation_errors(self._discord)
        for thread in threads:
            thread_id = self._parse_optional_int(getattr(thread, "id", None))
            delete_fn = getattr(thread, "delete", None)
            if callable(delete_fn):
                try:
                    await self._require_async_callable(delete_fn, label="Discord thread delete")()
                    logger.info("Deleted stale Discord launcher thread %s in forum %s", thread_id, forum_id)
                except recoverable_errors as exc:
                    logger.warning(
                        "Failed to delete stale Discord launcher thread %s in forum %s: %s", thread_id, forum_id, exc
                    )
            await asyncio.sleep(0.5)

    async def _update_launcher_message(self, message: object, *, view: object, forum_id: int) -> bool:
        edit_fn = getattr(message, "edit", None)
        if not callable(edit_fn):
            logger.warning("Launcher message %s in forum %s cannot be edited", getattr(message, "id", None), forum_id)
            return False

        recoverable_errors = recoverable_operation_errors(self._discord)
        try:
            await self._require_async_callable(edit_fn, label="Discord message edit")(
                content="Start a session", view=view
            )
        except recoverable_errors as exc:
            logger.warning(
                "Failed to update Discord launcher message %s in forum %s: %s",
                getattr(message, "id", None),
                forum_id,
                exc,
            )
            return False
        return True

    async def _create_launcher_thread(
        self, forum_channel: object, *, view: object, forum_id: int
    ) -> tuple[object, object] | None:
        create_thread_fn = getattr(forum_channel, "create_thread", None)
        if not callable(create_thread_fn):
            logger.warning("Forum channel %s does not support create_thread(); launcher not posted", forum_id)
            return None

        recoverable_errors = recoverable_operation_errors(self._discord)
        try:
            created = await self._require_async_callable(create_thread_fn, label="Discord forum create_thread")(
                name="Start a session",
                content="Start a session",
                view=view,
            )
        except recoverable_errors as exc:
            logger.warning("Failed to create Discord launcher thread in forum %s: %s", forum_id, exc)
            return None

        launcher_thread, launcher_message = self._extract_forum_thread_result(created)
        if launcher_thread is None:
            logger.warning("Discord launcher create_thread returned no thread for forum %s", forum_id)
            return None
        return launcher_thread, launcher_message

    async def _resolve_interaction_forum_id(self, interaction: object) -> int | None:
        channel = getattr(interaction, "channel", None)
        parent_forum_id = self._resolve_parent_forum_id(channel)
        if parent_forum_id is not None:
            return parent_forum_id

        message = getattr(interaction, "message", None)
        message_channel = getattr(message, "channel", None)
        message_parent_forum_id = self._resolve_parent_forum_id(message_channel)
        if message_parent_forum_id is not None:
            return message_parent_forum_id
        message_channel_id = self._parse_optional_int(getattr(message_channel, "id", None))
        if message_channel_id is not None and message_channel is not None and self._is_forum_channel(message_channel):
            return message_channel_id

        interaction_channel_id = self._parse_optional_int(getattr(interaction, "channel_id", None))
        if interaction_channel_id is None:
            return None

        if channel is not None and self._is_forum_channel(channel):
            return interaction_channel_id

        resolved_channel = await self._get_channel(interaction_channel_id)
        resolved_parent_forum_id = self._resolve_parent_forum_id(resolved_channel)
        if resolved_parent_forum_id is not None:
            return resolved_parent_forum_id
        if resolved_channel is not None and self._is_forum_channel(resolved_channel):
            return interaction_channel_id
        return interaction_channel_id

    async def _pin_launcher_message(self, message: object, *, forum_id: int) -> None:
        message_id = getattr(message, "id", None)
        pin_fn = getattr(message, "pin", None)
        if not callable(pin_fn):
            logger.debug("Launcher message %s in forum %s cannot be pinned", message_id, forum_id)
            return

        try:
            await self._require_async_callable(pin_fn, label="Discord message pin")()
        except Exception as exc:
            logger.warning(
                "Failed to pin Discord launcher message %s in forum %s: %s",
                message_id,
                forum_id,
                exc,
            )

    async def _pin_launcher_thread(self, thread: object, *, forum_id: int) -> None:
        """Pin the launcher thread in the forum so it stays at the top."""
        thread_id = getattr(thread, "id", None)
        edit_fn = getattr(thread, "edit", None)
        if not callable(edit_fn):
            logger.debug("Launcher thread %s in forum %s cannot be edited for pinning", thread_id, forum_id)
            return

        try:
            await self._require_async_callable(edit_fn, label="Discord thread edit (pin)")(pinned=True)
        except Exception as exc:
            if self._is_thread_pin_limit_error(exc):
                logger.info(
                    "Skipped pinning Discord launcher thread %s in forum %s: forum pin limit already reached",
                    thread_id,
                    forum_id,
                )
                return
            logger.warning(
                "Failed to pin Discord launcher thread %s in forum %s: %s",
                thread_id,
                forum_id,
                exc,
            )

    def _is_thread_pin_limit_error(self, exc: Exception) -> bool:
        """Return True when Discord rejects pinning because the forum already has its one pinned thread."""
        code = getattr(exc, "code", None)
        if code == 30047:
            return True
        return "Maximum number pinned threads in this channel reached" in str(exc)

    async def _validate_project_forum_id(self, forum_id: int | None, category: object) -> int | None:
        """Return a stored project forum ID only when it belongs to this computer's category."""
        if forum_id is None:
            return None
        if await self._trusted_dir_forum_is_current(forum_id, category):
            return forum_id
        return None

    async def _trusted_dir_forum_is_current(self, forum_id: int, category: object) -> bool:
        """Validate that a stored forum ID still points at this computer's project category."""
        channel = await self._get_channel(forum_id)
        return (
            channel is not None
            and self._is_forum_channel(channel)
            and self._channel_matches_category(channel, category)
        )

    async def _ensure_project_forums(self, guild: object, category: object | None) -> None:
        """Create a forum for each trusted dir that lacks a valid discord_forum ID."""
        if category is None:
            logger.warning("Skipping project forum provisioning: Projects category is unavailable")
            return

        trusted_dirs = config.computer.get_all_trusted_dirs()
        project_changes: list[tuple[str, int | None]] = []

        for td in trusted_dirs:
            stale_cleared = False
            if td.discord_forum is not None:
                if await self._trusted_dir_forum_is_current(td.discord_forum, category):
                    continue
                td.discord_forum = None
                stale_cleared = True
            forum_id = await self._find_or_create_forum(guild, category, td.name, td.desc or f"Sessions for {td.name}")
            if forum_id is not None:
                td.discord_forum = forum_id
                project_changes.append((td.name, forum_id))
            elif stale_cleared:
                project_changes.append((td.name, None))

        if project_changes:
            self._persist_project_forum_ids(project_changes)

    async def _sync_project_forum_positions(self, category: object | None) -> None:
        """Reorder project forums within this computer's category to match trusted_dirs.

        Touches only forums that already live in our category. Foreign-category
        forums are skipped — placement is owned exclusively by ``_ensure_project_forums``.
        """
        if category is None:
            return

        category_id = self._parse_optional_int(getattr(category, "id", None))
        if category_id is None:
            return

        trusted_dirs = config.computer.get_all_trusted_dirs()
        position = 0
        for td in trusted_dirs:
            if td.discord_forum is None:
                continue
            channel = await self._get_channel(td.discord_forum)
            if channel is None:
                continue

            ch_cat_id = self._parse_optional_int(getattr(channel, "category_id", None))
            if ch_cat_id != category_id:
                continue

            edit_fn = getattr(channel, "edit", None)
            if not callable(edit_fn):
                position += 1
                continue

            current_pos = getattr(channel, "position", None)
            if current_pos != position:
                try:
                    await self._require_async_callable(edit_fn, label="forum sync")(position=position)
                    logger.debug("Reordered forum '%s' to position %d", td.name, position)
                except Exception as exc:
                    logger.debug("Failed to reorder forum '%s': %s", td.name, exc)
            position += 1
