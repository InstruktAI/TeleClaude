"""Infrastructure provisioning mixin for Discord adapter.

Handles auto-provisioning of Discord channels, categories, forums, launcher
messages, project forum mapping, team channels, and config persistence.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.discord.provisioning import ProvisioningMixin
from teleclaude.adapters.discord.team_channels import TeamChannelsMixin
from teleclaude.config import config

if TYPE_CHECKING:
    from types import ModuleType

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
    - _handle_launcher_click(interaction, agent_name) -> None (async)
    - _build_session_launcher_view() -> object
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

        def _is_forum_channel(self, channel: object) -> bool: ...

        def _get_enabled_agents(self) -> list[str]: ...

        @property
        def _multi_agent(self) -> bool: ...

        async def _handle_launcher_click(self, interaction: object, agent_name: str) -> None: ...

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

    # =========================================================================
    # Infrastructure Provisioning
    # =========================================================================

    async def _ensure_discord_infrastructure(self) -> None:
        """Auto-provision the full Discord channel structure.

        Creates categories with their channels:
        - Operations: #announcements (text), #general (text)
        - Help Desk: #customer-sessions (forum), #escalations (forum), #operator-chat (text)
        - Projects - {computer}: #unknown (catch-all forum), per-project forums (ordered by trusted_dirs)
        - Team: per-person text channels (from people config)

        Idempotent: validates stored IDs before trusting them. When a cached ID
        is stale, only searches by name — never creates — to prevent duplicates.
        Persists all created IDs to config.yml.
        """
        if self._client is None or self._guild_id is None:
            return

        guild = await self._resolve_guild()
        if guild is None:
            logger.warning("Cannot auto-provision Discord channels: guild %s not found", self._guild_id)
            return

        changes: dict[str, int | dict[str, int]] = {}
        cat_changes: dict[str, int] = {}
        existing_cats = config.discord.categories or {}

        # --- Category: Operations ---
        ops_cat = await self._ensure_category(guild, "Operations", existing_cats, cat_changes)

        self._announcements_channel_id = await self._validate_channel_id(self._announcements_channel_id)
        if self._announcements_channel_id is None:
            ch_id = await self._find_or_create_text_channel(guild, ops_cat, "announcements")
            if ch_id is not None:
                self._announcements_channel_id = ch_id
                changes["announcements_channel_id"] = ch_id

        self._general_channel_id = await self._validate_channel_id(self._general_channel_id)
        if self._general_channel_id is None:
            ch_id = await self._find_or_create_text_channel(guild, ops_cat, "general")
            if ch_id is not None:
                self._general_channel_id = ch_id
                changes["general_channel_id"] = ch_id

        # --- Category: Help Desk ---
        hd_cat = await self._ensure_category(guild, "Help Desk", existing_cats, cat_changes)

        self._help_desk_channel_id = await self._validate_channel_id(self._help_desk_channel_id)
        if self._help_desk_channel_id is None:
            forum_id = await self._find_or_create_forum(guild, hd_cat, "Customer Sessions", "Customer support sessions")
            if forum_id is not None:
                self._help_desk_channel_id = forum_id
                changes["help_desk_channel_id"] = forum_id

        self._escalation_channel_id = await self._validate_channel_id(self._escalation_channel_id)
        if self._escalation_channel_id is None:
            forum_id = await self._find_or_create_forum(
                guild, hd_cat, "Escalations", "Human-admin escalation relay threads"
            )
            if forum_id is not None:
                self._escalation_channel_id = forum_id
                changes["escalation_channel_id"] = forum_id

        self._operator_chat_channel_id = await self._validate_channel_id(self._operator_chat_channel_id)
        if self._operator_chat_channel_id is None:
            ch_id = await self._find_or_create_text_channel(guild, hd_cat, "operator-chat")
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

        # "Unknown" is the catch-all forum for sessions that don't match any project
        self._all_sessions_channel_id = await self._validate_channel_id(self._all_sessions_channel_id)
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

        # --- Category: Team (from people config) ---
        try:
            from teleclaude.config.loader import load_global_config

            global_cfg = load_global_config()
            if global_cfg.people:
                team_cat = await self._ensure_category(guild, "Team", existing_cats, cat_changes)
                await self._ensure_team_channels(guild, team_cat, global_cfg.people)  # type: ignore[arg-type]
        except Exception as exc:
            logger.warning("Failed to provision team category: %s", exc)

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
    ) -> object | None:
        """Resolve a category idempotently: cached ID, then name search, then create.

        Always searches by name before creating. Creation only happens when a
        conclusive search confirms the category genuinely does not exist in Discord.
        If the search is inconclusive (cache empty, API unavailable), refuses to
        create to prevent duplicates.
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

    def _build_session_launcher_view(self) -> object:
        from teleclaude.adapters.discord.session_launcher import SessionLauncherView

        return SessionLauncherView(enabled_agents=self._get_enabled_agents(), on_launch=self._handle_launcher_click)

    async def _post_or_update_launcher(self, forum_id: int) -> None:
        if self._client is None or not self._multi_agent:
            return

        forum_channel = await self._get_channel(forum_id)
        if forum_channel is None:
            logger.warning("Cannot post launcher for forum %s: channel not found", forum_id)
            return

        if not self._is_forum_channel(forum_channel):
            logger.warning("Cannot post launcher for forum %s: channel is not a forum", forum_id)
            return

        setting_prefix = f"discord_launcher:{forum_id}"
        legacy_message_key = setting_prefix
        thread_key = f"{setting_prefix}:thread_id"
        message_key = f"{setting_prefix}:message_id"
        launcher_title = "Start a session"
        launcher_text = "Start a session"

        from teleclaude.core.db import db

        existing_thread_id = await db.get_system_setting(thread_key)
        existing_message_id = await db.get_system_setting(message_key)
        if existing_message_id is None:
            existing_message_id = await db.get_system_setting(legacy_message_key)

        if (
            existing_thread_id
            and existing_thread_id.isdigit()
            and existing_message_id
            and existing_message_id.isdigit()
        ):
            launcher_thread = await self._get_channel(int(existing_thread_id))
            if launcher_thread is not None and self._resolve_parent_forum_id(launcher_thread) == forum_id:
                try:
                    fetch_fn = self._require_async_callable(
                        getattr(launcher_thread, "fetch_message", None),
                        label="Discord thread fetch_message",
                    )
                    message = await fetch_fn(int(existing_message_id))
                    edit_fn = self._require_async_callable(getattr(message, "edit", None), label="Discord message edit")
                    await edit_fn(content=launcher_text, view=self._build_session_launcher_view())
                    await self._pin_launcher_message(message, forum_id=forum_id)
                    await self._pin_launcher_thread(launcher_thread, forum_id=forum_id)
                    return
                except Exception as exc:
                    logger.warning(
                        "Failed to update Discord launcher message %s in forum %s (thread %s): %s",
                        existing_message_id,
                        forum_id,
                        existing_thread_id,
                        exc,
                    )

        create_thread_fn = getattr(forum_channel, "create_thread", None)
        if not callable(create_thread_fn):
            logger.warning("Forum channel %s does not support create_thread(); launcher not posted", forum_id)
            return

        created = await self._require_async_callable(create_thread_fn, label="Discord forum create_thread")(
            name=launcher_title,
            content=launcher_text,
            view=self._build_session_launcher_view(),
        )
        launcher_thread, launcher_message = self._extract_forum_thread_result(created)
        launcher_thread_id = self._parse_optional_int(getattr(launcher_thread, "id", None))
        if launcher_thread_id is None:
            logger.warning("Discord launcher create_thread returned invalid thread id for forum %s", forum_id)
            return
        launcher_message_id_raw = getattr(launcher_message, "id", None)
        launcher_message_id = self._parse_optional_int(launcher_message_id_raw)
        if launcher_message is not None:
            await self._pin_launcher_message(launcher_message, forum_id=forum_id)
        if launcher_thread is not None:
            await self._pin_launcher_thread(launcher_thread, forum_id=forum_id)
        if launcher_message_id is None:
            launcher_message_id = launcher_thread_id

        await db.set_system_setting(thread_key, str(launcher_thread_id))
        await db.set_system_setting(message_key, str(launcher_message_id))
        await db.set_system_setting(legacy_message_key, str(launcher_message_id))

    async def _resolve_interaction_forum_id(self, interaction: object) -> int | None:
        channel = getattr(interaction, "channel", None)
        parent_forum_id = self._resolve_parent_forum_id(channel)
        if parent_forum_id is not None:
            return parent_forum_id

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
            logger.warning(
                "Failed to pin Discord launcher thread %s in forum %s: %s",
                thread_id,
                forum_id,
                exc,
            )

    async def _ensure_project_forums(self, guild: object, category: object | None) -> None:
        """Create a forum for each trusted dir that lacks a valid discord_forum ID."""
        trusted_dirs = config.computer.get_all_trusted_dirs()
        project_changes: list[tuple[str, int | None]] = []

        for td in trusted_dirs:
            stale_cleared = False
            if td.discord_forum is not None:
                if await self._validate_channel_id(td.discord_forum) is None:
                    td.discord_forum = None
                    stale_cleared = True
                else:
                    continue
            forum_id = await self._find_or_create_forum(guild, category, td.name, td.desc or f"Sessions for {td.name}")
            if forum_id is not None:
                td.discord_forum = forum_id
                project_changes.append((td.name, forum_id))
            elif stale_cleared:
                # Re-provisioning failed; persist None so the stale ID is removed from config.yml
                # and the restart cycle (reload stale → clear → fail → repeat) is broken.
                project_changes.append((td.name, None))

        if project_changes:
            self._persist_project_forum_ids(project_changes)

    # guard: loose-dict-func - kwargs is a heterogeneous discord.py channel edit dict; a TypedDict would need discord-py types
    async def _sync_project_forum_positions(self, category: object | None) -> None:
        """Move forums into the category and set positions to match trusted_dirs order.

        Ensures all project forums belong to the correct category and that
        most important projects (first in trusted_dirs) appear at the top.
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

            edit_fn = getattr(channel, "edit", None)
            if not callable(edit_fn):
                continue

            ch_cat_id = self._parse_optional_int(getattr(channel, "category_id", None))
            current_pos = getattr(channel, "position", None)

            needs_move = ch_cat_id != category_id
            needs_reorder = current_pos != position

            if needs_move or needs_reorder:
                try:
                    # guard: loose-dict - dynamic kwargs; category key conditionally added
                    kwargs: dict[str, object] = {"position": position}
                    if needs_move:
                        kwargs["category"] = category
                    await self._require_async_callable(edit_fn, label="forum sync")(**kwargs)
                    if needs_move:
                        logger.info("Moved forum '%s' into category %s at position %d", td.name, category_id, position)
                    elif needs_reorder:
                        logger.debug("Reordered forum '%s' to position %d", td.name, position)
                except Exception as exc:
                    logger.debug("Failed to sync forum '%s': %s", td.name, exc)
            position += 1
