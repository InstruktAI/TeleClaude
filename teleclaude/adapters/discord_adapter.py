"""Discord adapter for TeleClaude."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import os
import tempfile
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Callable, Protocol, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionLifecycleContext, SessionStatusContext, SessionUpdatedContext
from teleclaude.core.models import SessionAdapterMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_utils import get_session_output_dir
from teleclaude.types.commands import (
    CreateSessionCommand,
    HandleFileCommand,
    HandleVoiceCommand,
    KeysCommand,
    ProcessMessageCommand,
)

if TYPE_CHECKING:
    from datetime import datetime

    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import ChannelMetadata, MessageMetadata, PeerInfo, Session
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)


class DiscordClientLike(Protocol):
    """Minimal discord.py client surface used by the adapter."""

    user: object | None

    def event(self, coro: Callable[..., Awaitable[None]]) -> object: ...

    async def start(self, token: str) -> None: ...

    async def close(self) -> None: ...


class DiscordAdapter(UiAdapter):
    """Discord bot adapter using discord.py."""

    ADAPTER_KEY = "discord"
    max_message_size = 2000
    _TRUNCATION_SUFFIX = "\n[...truncated...]"

    def __init__(self, client: "AdapterClient", *, task_registry: "TaskRegistry | None" = None) -> None:
        super().__init__(client)
        self.client = client
        self.task_registry = task_registry
        self._discord: ModuleType = importlib.import_module("discord")
        configured_token = config.discord.token.strip() if config.discord.token else ""
        self._token = configured_token or os.getenv("DISCORD_BOT_TOKEN", "").strip()
        self._guild_id = config.discord.guild_id or self._parse_optional_int(os.getenv("DISCORD_GUILD_ID"))
        self._help_desk_channel_id = config.discord.help_desk_channel_id or self._parse_optional_int(
            os.getenv("DISCORD_HELP_DESK_CHANNEL_ID")
        )
        self._all_sessions_channel_id = config.discord.all_sessions_channel_id or self._parse_optional_int(
            os.getenv("DISCORD_ALL_SESSIONS_CHANNEL_ID")
        )
        self._escalation_channel_id: int | None = config.discord.escalation_channel_id or self._parse_optional_int(
            os.getenv("DISCORD_ESCALATION_CHANNEL_ID")
        )
        self._operator_chat_channel_id: int | None = config.discord.operator_chat_channel_id
        self._announcements_channel_id: int | None = config.discord.announcements_channel_id
        self._general_channel_id: int | None = config.discord.general_channel_id
        self._gateway_task: asyncio.Task[object] | None = None
        self._ready_event = asyncio.Event()
        self._client: DiscordClientLike | None = None
        # project_path -> discord_forum_id mapping, built at startup
        self._project_forum_map: dict[str, int] = {}
        # discord_forum_id -> project_path mapping, built at startup
        self._forum_project_map: dict[int, str] = {}
        # forum-channel-id -> webhook cache for actor-based reflection delivery
        self._reflection_webhook_cache: dict[int, object] = {}
        self._tree: object | None = None
        self._launcher_registration_view: object | None = None

    async def start(self) -> None:
        """Initialize Discord client and start gateway task."""
        if not self._token:
            raise ValueError("DISCORD_BOT_TOKEN is required to start Discord adapter")

        intents = self._discord.Intents.default()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True

        self._client = self._discord.Client(intents=intents)
        self._register_cancel_slash_command()
        self._register_gateway_handlers()
        self._ready_event.clear()

        if self.task_registry:
            self._gateway_task = self.task_registry.spawn(self._client.start(self._token), name="discord-gateway")
        else:
            self._gateway_task = asyncio.create_task(self._client.start(self._token), name="discord-gateway")

        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=20.0)
        except asyncio.TimeoutError as exc:
            if self._gateway_task and self._gateway_task.done():
                task_exc = self._gateway_task.exception()
                if task_exc:
                    raise RuntimeError(f"Discord gateway failed to start: {task_exc}") from task_exc
            raise RuntimeError("Discord adapter did not become ready within 20 seconds") from exc

    async def stop(self) -> None:
        """Stop Discord client and gateway task."""
        self._tree = None
        self._launcher_registration_view = None
        if self._client is not None:
            await self._client.close()
        if self._gateway_task and not self._gateway_task.done():
            self._gateway_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._gateway_task

    def _get_enabled_agents(self) -> list[str]:
        return [name for name, agent_cfg in config.agents.items() if agent_cfg.enabled]

    @property
    def _multi_agent(self) -> bool:
        return len(self._get_enabled_agents()) > 1

    @property
    def _default_agent(self) -> str:
        enabled_agents = self._get_enabled_agents()
        if enabled_agents:
            return enabled_agents[0]
        logger.warning("No enabled agents configured for Discord; defaulting to claude")
        return "claude"

    def store_channel_id(self, adapter_metadata: object, channel_id: str) -> None:
        if not isinstance(adapter_metadata, SessionAdapterMetadata):
            return
        parsed = self._parse_optional_int(channel_id)
        if parsed is None:
            return

        discord_meta = adapter_metadata.get_ui().get_discord()
        if self._help_desk_channel_id is not None and parsed != self._help_desk_channel_id:
            discord_meta.thread_id = parsed
            if discord_meta.channel_id is None:
                discord_meta.channel_id = self._help_desk_channel_id
            return

        discord_meta.channel_id = parsed

    @staticmethod
    def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]:
        if not callable(fn):
            raise AdapterError(f"{label} is not callable")
        return cast(Callable[..., Awaitable[object]], fn)

    async def ensure_channel(self, session: "Session") -> "Session":
        # Re-read from DB to prevent stale in-memory metadata from concurrent lanes
        fresh = await db.get_session(session.session_id)
        if fresh:
            session = fresh

        discord_meta = session.get_metadata().get_ui().get_discord()
        if discord_meta.thread_id is not None:
            return session

        # Route to the correct forum based on session type.
        # Infrastructure provisioning runs at startup (_handle_on_ready);
        # if channels are still missing here, skip silently.
        target_forum_id = self._resolve_target_forum(session)
        if target_forum_id is None:
            return session

        title = self._build_thread_title(session, target_forum_id)

        from teleclaude.core.models import ChannelMetadata

        await self.create_channel(session, title, ChannelMetadata())
        refreshed = await db.get_session(session.session_id)
        return refreshed or session

    def _resolve_target_forum(self, session: "Session") -> int | None:
        """Determine which Discord forum this session's thread belongs in."""
        if self._is_customer_session(session):
            return self._help_desk_channel_id
        # Check project-specific forums
        forum_id = self._match_project_forum(session)
        if forum_id is not None:
            logger.debug(
                "[DISCORD_ROUTE] session=%s project=%s -> project forum %s",
                session.session_id[:8],
                session.project_path,
                forum_id,
            )
            return forum_id
        logger.debug(
            "[DISCORD_ROUTE] session=%s project=%s -> catch-all (map has %d entries)",
            session.session_id[:8],
            session.project_path,
            len(self._project_forum_map),
        )
        return self._all_sessions_channel_id

    def _match_project_forum(self, session: "Session") -> int | None:
        """Match session project_path to a trusted dir with a discord_forum ID."""
        project_path = session.project_path
        if not project_path:
            return None
        for path, forum_id in self._project_forum_map.items():
            if project_path == path or project_path.startswith(path + "/"):
                return forum_id
        return None

    def _resolve_forum_context(self, message: object) -> tuple[str, str | None]:
        """Determine forum type and project path for an incoming message.

        Returns (forum_type, project_path) where forum_type is one of:
        'help_desk', 'project', 'all_sessions'.
        """
        channel = getattr(message, "channel", None)
        # Prefer explicit parent_id attribute, then parent.id, then channel.id
        parent_id = self._parse_optional_int(getattr(channel, "parent_id", None))
        if parent_id is None:
            parent_obj = getattr(channel, "parent", None)
            parent_id = self._parse_optional_int(getattr(parent_obj, "id", None))
        if parent_id is None:
            parent_id = self._parse_optional_int(getattr(channel, "id", None))

        if parent_id is not None and parent_id == self._help_desk_channel_id:
            return "help_desk", config.computer.help_desk_dir

        if parent_id is not None and parent_id == self._all_sessions_channel_id:
            trusted = config.computer.get_all_trusted_dirs()
            project_path = trusted[0].path if trusted else config.computer.help_desk_dir
            return "all_sessions", project_path

        for path, forum_id in self._project_forum_map.items():
            if parent_id == forum_id:
                return "project", path

        if parent_id is not None:
            logger.warning(
                "Unrecognized forum parent_id=%s; routing to help_desk. "
                "Known forums: help_desk=%s all_sessions=%s projects=%s",
                parent_id,
                self._help_desk_channel_id,
                self._all_sessions_channel_id,
                list(self._project_forum_map.values()),
            )
        return "help_desk", config.computer.help_desk_dir

    def _build_thread_title(self, session: "Session", target_forum_id: int) -> str:
        """Build Discord thread title based on routing target.

        Per-project forum: just the session description (project context is implicit).
        Catch-all fallback: prefixed with short project name for discoverability.
        """
        from teleclaude.core.session_utils import get_short_project_name

        description = session.title or "Untitled"
        # If routing to a project-specific forum, use description only
        if target_forum_id != self._all_sessions_channel_id:
            return description
        # Catch-all: prefix with project name
        short_name = get_short_project_name(session.project_path, session.subdir)
        return f"{short_name}: {description}"

    @staticmethod
    def _is_customer_session(session: "Session") -> bool:
        """Check if session is customer-facing. Based solely on human_role."""
        return session.human_role == "customer"

    def _build_thread_topper(self, session: "Session") -> str:
        """Build metadata header for the first message in a Discord thread."""
        from teleclaude.core.session_utils import get_short_project_name

        project = get_short_project_name(session.project_path, session.subdir)
        parts = [f"project: {project}"]
        agent = session.active_agent or "pending"
        speed = session.thinking_mode or "default"
        parts.append(f"agent: {agent}/{speed}")
        header = " | ".join(parts)
        lines = [header, f"tc: {session.session_id}"]
        if session.native_session_id:
            lines.append(f"ai: {session.native_session_id}")
        return "\n".join(lines)

    # =========================================================================
    # Discord Infrastructure Auto-Provisioning
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

    async def _ensure_discord_infrastructure(self) -> None:
        """Auto-provision the full Discord channel structure.

        Creates three categories with their channels:
        - Operations: #announcements (text), #general (text)
        - Help Desk: #customer-sessions (forum), #escalations (forum), #operator-chat (text)
        - Projects - {computer}: #unknown (catch-all forum), per-project forums for session routing

        Idempotent: validates stored IDs before trusting them; clears stale IDs and re-provisions.
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

        # Build project-path-to-forum mapping for session routing
        self._build_project_forum_map()

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
        """Resolve a category: from config cache, by name search, or create new."""
        key = key if key is not None else name.lower().replace(" ", "_")

        # Check if we already have the ID cached
        cached_id = existing.get(key)
        if cached_id is not None:
            cat = await self._get_channel(cached_id)
            if cat is not None:
                return cat

        # Find or create
        cat = await self._find_or_create_category(guild, name)
        cat_id = self._parse_optional_int(getattr(cat, "id", None)) if cat else None
        if cat_id is not None:
            cat_changes[key] = cat_id
        return cat

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

        setting_key = f"discord_launcher:{forum_id}"
        launcher_text = "Start a session"
        existing_message_id = await db.get_system_setting(setting_key)
        if existing_message_id and existing_message_id.isdigit():
            fetch_fn = getattr(forum_channel, "fetch_message", None)
            if callable(fetch_fn):
                try:
                    message = await self._require_async_callable(fetch_fn, label="Discord forum fetch_message")(
                        int(existing_message_id)
                    )
                    edit_fn = self._require_async_callable(getattr(message, "edit", None), label="Discord message edit")
                    await edit_fn(content=launcher_text, view=self._build_session_launcher_view())
                    await self._pin_launcher_message(message, forum_id=forum_id)
                    return
                except Exception as exc:
                    logger.warning(
                        "Failed to update Discord launcher message %s in forum %s: %s",
                        existing_message_id,
                        forum_id,
                        exc,
                    )

        send_fn = getattr(forum_channel, "send", None)
        if not callable(send_fn):
            logger.warning("Forum channel %s does not support send(); launcher not posted", forum_id)
            return

        sent = await self._require_async_callable(send_fn, label="Discord forum send")(
            launcher_text,
            view=self._build_session_launcher_view(),
        )
        await self._pin_launcher_message(sent, forum_id=forum_id)
        launcher_message_id = getattr(sent, "id", None)
        if launcher_message_id is not None:
            await db.set_system_setting(setting_key, str(launcher_message_id))

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

        return guild

    async def _find_or_create_category(self, guild: object, name: str) -> object | None:
        """Find an existing category by name, or create one."""
        # Search existing categories
        categories = getattr(guild, "categories", None)
        if isinstance(categories, list):
            for cat in categories:
                cat_name = getattr(cat, "name", None)
                if isinstance(cat_name, str) and cat_name.lower() == name.lower():
                    logger.debug("Found existing Discord category: %s (id=%s)", name, getattr(cat, "id", "?"))
                    return cat

        # Create new category
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
        """Find an existing forum by name, or create one under the category."""
        # Search existing channels for a matching forum
        channels = getattr(guild, "channels", None)
        if isinstance(channels, list):
            for ch in channels:
                ch_name = getattr(ch, "name", None)
                if isinstance(ch_name, str) and ch_name.lower() == name.lower() and self._is_forum_channel(ch):
                    found_id = self._parse_optional_int(getattr(ch, "id", None))
                    if found_id is not None:
                        logger.debug("Found existing Discord forum: %s (id=%s)", name, found_id)
                        return found_id

        # Create new forum
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
        """Find an existing text channel by name, or create one under the category."""
        channels = getattr(guild, "channels", None)
        if isinstance(channels, list):
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

    # --- Per-adapter output message tracking ---
    # Discord uses adapter_metadata instead of the shared DB column
    # to prevent cross-adapter races with Telegram.

    async def _get_output_message_id(self, session: "Session") -> str | None:
        fresh = await db.get_session(session.session_id)
        if fresh:
            return fresh.get_metadata().get_ui().get_discord().output_message_id
        return session.get_metadata().get_ui().get_discord().output_message_id

    async def _store_output_message_id(self, session: "Session", message_id: str) -> None:
        meta = session.get_metadata().get_ui().get_discord()
        meta.output_message_id = message_id
        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        logger.debug("Stored discord output_message_id: session=%s message_id=%s", session.session_id[:8], message_id)

    async def _clear_output_message_id(self, session: "Session") -> None:
        meta = session.get_metadata().get_ui().get_discord()
        meta.output_message_id = None
        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        logger.debug("Cleared discord output_message_id: session=%s", session.session_id[:8])

    async def send_typing_indicator(self, session: "Session") -> None:
        """Send typing indicator to Discord thread."""
        discord_meta = session.get_metadata().get_ui().get_discord()
        if discord_meta.thread_id is None:
            return
        thread = await self._get_channel(discord_meta.thread_id)
        if thread is None:
            return
        trigger_typing_fn = getattr(thread, "trigger_typing", None)
        if trigger_typing_fn and callable(trigger_typing_fn):
            typing_fn = self._require_async_callable(trigger_typing_fn, label="Discord thread trigger_typing")
            await typing_fn()

    async def _handle_session_status(self, _event: str, context: SessionStatusContext) -> None:
        """Send or edit the tracked status message in the Discord thread."""
        session = await db.get_session(context.session_id)
        if not session:
            return
        discord_meta = session.get_metadata().get_ui().get_discord()
        if discord_meta.thread_id is None:
            return  # No Discord thread for this session
        status_text = self._format_lifecycle_status(context.status)
        existing_id = discord_meta.status_message_id
        if existing_id:
            edited = await self.edit_message(session, existing_id, status_text)
            if edited:
                return
            # Edit failed (message deleted?) — clear and fall through to send
            discord_meta.status_message_id = None
            await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        try:
            new_id = await self.send_message(session, status_text)
            discord_meta.status_message_id = new_id
            await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        except Exception as exc:
            logger.debug(
                "Discord status message update failed for session %s: %s",
                context.session_id[:8],
                exc,
            )

    async def _handle_session_updated(self, _event: str, context: SessionUpdatedContext) -> None:
        """Handle generic updates plus Discord topper refresh on native ID binding."""
        await super()._handle_session_updated(_event, context)

        updated_fields = context.updated_fields or {}
        if "native_session_id" not in updated_fields:
            return

        session = await db.get_session(context.session_id)
        if not session or not session.native_session_id:
            return

        discord_meta = session.get_metadata().get_ui().get_discord()
        if discord_meta.thread_id is None:
            return

        topper_message_id = discord_meta.thread_topper_message_id
        if not topper_message_id:
            topper_message_id = str(discord_meta.thread_id)
            discord_meta.thread_topper_message_id = topper_message_id
            await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)

        topper = self._build_thread_topper(session)
        edited = await self.edit_message(session, topper_message_id, topper)
        if not edited:
            logger.debug(
                "Discord topper refresh failed for session %s (msg=%s)",
                session.session_id[:8],
                topper_message_id,
            )

    async def create_channel(self, session: "Session", title: str, metadata: "ChannelMetadata") -> str:
        _ = metadata
        if self._client is None:
            raise AdapterError("Discord adapter not started")

        discord_meta = session.get_metadata().get_ui().get_discord()

        if discord_meta.thread_id is not None:
            return str(discord_meta.thread_id)

        target_forum_id = self._resolve_target_forum(session)
        if target_forum_id is not None:
            forum = await self._get_channel(target_forum_id)
            if forum is None:
                raise AdapterError(f"Discord forum channel {target_forum_id} not found")
            if not self._is_forum_channel(forum):
                raise AdapterError(f"Discord channel {target_forum_id} is not a Forum Channel")

            topper = self._build_thread_topper(session)
            thread_id, topper_message_id = await self._create_forum_thread(forum, title=title, content=topper)
            discord_meta.channel_id = target_forum_id
            discord_meta.thread_id = thread_id
            discord_meta.thread_topper_message_id = topper_message_id
            await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
            return str(thread_id)

        if discord_meta.channel_id is not None:
            return str(discord_meta.channel_id)

        raise AdapterError("Discord session has no mapped destination channel")

    async def update_channel_title(self, session: "Session", title: str) -> bool:
        discord_meta = session.get_metadata().get_ui().get_discord()
        if discord_meta.thread_id is None:
            return False
        thread = await self._get_channel(discord_meta.thread_id)
        if thread is None:
            return False
        raw_edit_fn = getattr(thread, "edit", None)
        if raw_edit_fn is None:
            return False
        edit_fn = self._require_async_callable(raw_edit_fn, label="Discord thread edit")
        # Recompute Discord-specific title (same logic as thread creation)
        target_forum_id = self._resolve_target_forum(session)
        discord_title = self._build_thread_title(session, target_forum_id)
        try:
            await edit_fn(name=discord_title)
            return True
        except Exception as exc:
            logger.warning("Failed to rename Discord thread %s: %s", discord_meta.thread_id, exc)
            return False

    async def close_channel(self, session: "Session") -> bool:
        discord_meta = session.get_metadata().get_ui().get_discord()
        if discord_meta.thread_id is None:
            return False
        thread = await self._get_channel(discord_meta.thread_id)
        if thread is None:
            return False
        raw_delete_fn = getattr(thread, "delete", None)
        if raw_delete_fn is None:
            return False
        delete_fn = self._require_async_callable(raw_delete_fn, label="Discord thread delete")
        try:
            await delete_fn()
            return True
        except Exception as exc:
            logger.warning("Failed to delete Discord thread %s: %s", discord_meta.thread_id, exc)
            return False

    async def reopen_channel(self, session: "Session") -> bool:
        discord_meta = session.get_metadata().get_ui().get_discord()
        if discord_meta.thread_id is None:
            return False
        thread = await self._get_channel(discord_meta.thread_id)
        if thread is None:
            return False
        raw_edit_fn = getattr(thread, "edit", None)
        if raw_edit_fn is None:
            return False
        edit_fn = self._require_async_callable(raw_edit_fn, label="Discord thread edit")
        try:
            await edit_fn(archived=False, locked=False)
            return True
        except Exception as exc:
            logger.warning("Failed to reopen Discord thread %s: %s", discord_meta.thread_id, exc)
            return False

    async def delete_channel(self, session: "Session") -> bool:
        discord_meta = session.get_metadata().get_ui().get_discord()
        if discord_meta.thread_id is None:
            return False
        thread = await self._get_channel(discord_meta.thread_id)
        if thread is None:
            return False
        raw_delete_fn = getattr(thread, "delete", None)
        if raw_delete_fn is None:
            return False
        delete_fn = self._require_async_callable(raw_delete_fn, label="Discord thread delete")
        try:
            await delete_fn()
            return True
        except Exception as exc:
            logger.warning("Failed to delete Discord thread %s: %s", discord_meta.thread_id, exc)
            return False

    async def send_message(
        self,
        session: "Session",
        text: str,
        *,
        metadata: "MessageMetadata | None" = None,
        multi_message: bool = False,
    ) -> str:
        _ = multi_message

        # Format transcribed text with delimiters (Discord compaction workaround)
        if metadata and metadata.is_transcription:
            prefix = 'Transcribed text:\n\n"'
            if text.startswith(prefix) and text.endswith('"'):
                content = text[len(prefix) : -1]
                computer_name = config.computer.name
                # Bold header, plain content (no italics), bottom dash
                text = f'**DISCORD@{computer_name}:**\n\n"{content}"\n'

        text = self._fit_message_text(text, context="send_message")
        logger.debug("[DISCORD SEND] text=%r", text[:100])

        destination = await self._resolve_destination_channel(session, metadata=metadata)
        if metadata and metadata.reflection_actor_name:
            webhook_message_id = await self._send_reflection_via_webhook(destination, text, metadata)
            if webhook_message_id:
                return webhook_message_id

        send_fn = self._require_async_callable(getattr(destination, "send", None), label="Discord channel send")
        sent = await send_fn(text)
        message_id = getattr(sent, "id", None)
        if message_id is None:
            raise AdapterError("Discord send_message returned message without id")
        return str(message_id)

    async def _send_reflection_via_webhook(
        self,
        destination: object,
        text: str,
        metadata: "MessageMetadata",
    ) -> str | None:
        actor_name = (metadata.reflection_actor_name or "").strip()
        if not actor_name:
            return None

        thread = destination if self._is_thread_channel(destination) else None
        webhook_channel = getattr(destination, "parent", None) if thread is not None else destination
        channel_id = self._parse_optional_int(getattr(webhook_channel, "id", None))
        if channel_id is None:
            return None

        webhook = await self._get_or_create_reflection_webhook(webhook_channel, channel_id)
        if webhook is None:
            return None

        send_fn = self._require_async_callable(getattr(webhook, "send", None), label="Discord webhook send")
        text = self._fit_message_text(text, context="reflection_webhook")
        try:
            if thread is not None and metadata.reflection_actor_avatar_url:
                sent = await send_fn(
                    content=text,
                    username=actor_name,
                    wait=True,
                    avatar_url=metadata.reflection_actor_avatar_url,
                    thread=thread,
                )
            elif thread is not None:
                sent = await send_fn(
                    content=text,
                    username=actor_name,
                    wait=True,
                    thread=thread,
                )
            elif metadata.reflection_actor_avatar_url:
                sent = await send_fn(
                    content=text,
                    username=actor_name,
                    wait=True,
                    avatar_url=metadata.reflection_actor_avatar_url,
                )
            else:
                sent = await send_fn(
                    content=text,
                    username=actor_name,
                    wait=True,
                )
        except Exception as exc:
            logger.warning("Discord reflection webhook send failed: %s", exc)
            return None

        message_id = getattr(sent, "id", None)
        return str(message_id) if message_id is not None else None

    async def _get_or_create_reflection_webhook(self, channel: object, channel_id: int) -> object | None:
        cached = self._reflection_webhook_cache.get(channel_id)
        if cached is not None:
            return cached

        webhooks_fn = getattr(channel, "webhooks", None)
        if callable(webhooks_fn):
            try:
                webhooks = await self._require_async_callable(webhooks_fn, label="Discord channel webhooks")()
                if isinstance(webhooks, list):
                    for webhook in webhooks:
                        if getattr(webhook, "name", None) == "TeleClaude Reflections":
                            self._reflection_webhook_cache[channel_id] = webhook
                            return webhook
            except Exception as exc:
                logger.debug("Failed to list Discord webhooks for channel %s: %s", channel_id, exc)

        create_fn = getattr(channel, "create_webhook", None)
        if not callable(create_fn):
            return None
        try:
            webhook = await self._require_async_callable(create_fn, label="Discord channel create_webhook")(
                name="TeleClaude Reflections"
            )
            self._reflection_webhook_cache[channel_id] = webhook
            return webhook
        except Exception as exc:
            logger.warning("Failed to create Discord reflection webhook for channel %s: %s", channel_id, exc)
            return None

    @staticmethod
    def _discord_actor_name(author: object, user_id: str) -> str:
        display_name = getattr(author, "display_name", None)
        global_name = getattr(author, "global_name", None)
        username = getattr(author, "name", None)
        for candidate in (display_name, global_name, username):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return f"discord:{user_id}"

    @staticmethod
    def _discord_actor_avatar_url(author: object) -> str | None:
        avatar = getattr(author, "display_avatar", None)
        avatar_url = getattr(avatar, "url", None) if avatar is not None else None
        if isinstance(avatar_url, str) and avatar_url.strip():
            return avatar_url
        return None

    async def edit_message(
        self,
        session: "Session",
        message_id: str,
        text: str,
        *,
        metadata: "MessageMetadata | None" = None,
    ) -> bool:
        text = self._fit_message_text(text, context="edit_message")
        logger.debug("[DISCORD EDIT] text=%r", text[:100])
        try:
            message = await self._fetch_destination_message(session, message_id, metadata=metadata)
        except AdapterError:
            return False
        edit_fn = self._require_async_callable(getattr(message, "edit", None), label="Discord message edit")
        try:
            await edit_fn(content=text)
            return True
        except Exception as exc:
            logger.warning("Failed to edit Discord message %s: %s", message_id, exc)
            return False

    async def delete_message(self, session: "Session", message_id: str) -> bool:
        try:
            message = await self._fetch_destination_message(session, message_id)
        except AdapterError:
            return False
        delete_fn = self._require_async_callable(getattr(message, "delete", None), label="Discord message delete")
        try:
            await delete_fn()
            return True
        except Exception as exc:
            logger.warning("Failed to delete Discord message %s: %s", message_id, exc)
            return False

    async def send_file(
        self,
        session: "Session",
        file_path: str,
        *,
        caption: str | None = None,
        metadata: "MessageMetadata | None" = None,
    ) -> str:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        destination = await self._resolve_destination_channel(session, metadata=metadata)
        send_fn = self._require_async_callable(getattr(destination, "send", None), label="Discord channel send")
        discord_file = self._discord.File(file_path)
        safe_caption = self._fit_message_text(caption, context="send_file_caption") if caption else None
        sent = await send_fn(content=safe_caption, file=discord_file)
        message_id = getattr(sent, "id", None)
        if message_id is None:
            raise AdapterError("Discord send_file returned message without id")
        return str(message_id)

    def _fit_message_text(self, text: str, *, context: str) -> str:
        """Clamp message text to Discord's hard message-size limit."""
        if len(text) <= self.max_message_size:
            return text

        suffix = self._TRUNCATION_SUFFIX
        reserve = max(self.max_message_size - len(suffix), 0)
        if reserve == 0:
            clipped = text[: self.max_message_size]
        else:
            clipped = f"{text[:reserve]}{suffix}"

        logger.debug(
            "Truncated Discord %s content from %d to %d characters",
            context,
            len(text),
            len(clipped),
        )
        return clipped

    def _build_metadata_for_thread(self) -> "MessageMetadata":
        from teleclaude.core.models import MessageMetadata

        return MessageMetadata(parse_mode=None)

    async def discover_peers(self) -> list["PeerInfo"]:
        return []

    async def poll_output_stream(  # type: ignore[override,misc]
        self,
        session: "Session",
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        _ = (session, timeout)
        raise NotImplementedError("Discord adapter does not support poll_output_stream")
        yield ""  # pragma: no cover

    def _fit_output_to_limit(self, tmux_output: str) -> str:
        """Build output message within Discord's 2000-char limit.

        The base class truncates raw output to max_message_size, but format_output()
        wraps it in triple backticks (adding 8 chars). Account for that overhead.
        """
        formatted = self.format_output(tmux_output)
        if len(formatted) <= self.max_message_size:
            return formatted
        overhead = len("```\n\n```")
        max_body = self.max_message_size - overhead
        return self.format_output(tmux_output[-max_body:]) if max_body > 0 else ""

    def get_max_message_length(self) -> int:
        return self.max_message_size

    def get_ai_session_poll_interval(self) -> float:
        return 0.5

    @staticmethod
    def _parse_optional_int(value: object) -> int | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)
        return None

    def _register_cancel_slash_command(self) -> None:
        if self._client is None:
            return
        app_commands = getattr(self._discord, "app_commands", None)
        command_tree_cls = getattr(app_commands, "CommandTree", None) if app_commands else None
        command_cls = getattr(app_commands, "Command", None) if app_commands else None
        object_cls = getattr(self._discord, "Object", None)
        if not callable(command_tree_cls) or not callable(command_cls):
            logger.warning("Discord app_commands unavailable; /cancel slash command not registered")
            return

        self._tree = command_tree_cls(self._client)
        cancel_command = command_cls(
            name="cancel",
            description="Send CTRL+C to interrupt the current agent",
            callback=self._handle_cancel_slash,
        )
        if self._guild_id is None or not callable(object_cls):
            logger.warning("DISCORD_GUILD_ID missing or invalid; skipping guild-scoped /cancel registration")
            return
        add_command = getattr(self._tree, "add_command", None)
        if callable(add_command):
            add_command(cancel_command, guild=object_cls(id=self._guild_id))

    def _register_gateway_handlers(self) -> None:
        if self._client is None:
            raise AdapterError("Discord client not initialized")

        async def on_ready() -> None:
            await self._handle_on_ready()

        async def on_message(message: object) -> None:
            await self._handle_on_message(message)

        async def on_raw_thread_delete(payload: object) -> None:
            await self._handle_thread_delete(payload)

        self._client.event(on_ready)
        self._client.event(on_message)
        self._client.event(on_raw_thread_delete)

    async def _handle_on_ready(self) -> None:
        if self._client is None:
            return
        user = getattr(self._client, "user", None)
        logger.info("Discord adapter ready as %s", user)

        # Auto-provision Discord infrastructure (category + forums)
        try:
            await self._ensure_discord_infrastructure()
        except Exception as exc:
            logger.warning("Discord infrastructure provisioning failed: %s", exc)

        if self._tree is not None and self._guild_id is not None:
            sync_fn = getattr(self._tree, "sync", None)
            object_cls = getattr(self._discord, "Object", None)
            if callable(sync_fn) and callable(object_cls):
                try:
                    await self._require_async_callable(sync_fn, label="Discord command tree sync")(
                        guild=object_cls(id=self._guild_id)
                    )
                except Exception as exc:
                    logger.warning("Failed to sync Discord slash commands: %s", exc)

        if self._multi_agent:
            add_view = getattr(self._client, "add_view", None)
            if callable(add_view):
                try:
                    self._launcher_registration_view = self._build_session_launcher_view()
                    add_view(self._launcher_registration_view)
                except Exception as exc:
                    logger.warning("Failed to register persistent Discord launcher view: %s", exc)

            for forum_id in self._project_forum_map.values():
                try:
                    await self._post_or_update_launcher(forum_id)
                except Exception as exc:
                    logger.warning("Failed to post launcher for forum %s: %s", forum_id, exc)

        self._ready_event.set()

    async def _handle_discord_dm(self, message: object) -> None:
        """Handle Direct Message (no guild) — invite token binding or bound user messaging."""
        author = getattr(message, "author", None)
        if not author:
            return

        user_id = str(getattr(author, "id", ""))
        text = getattr(message, "content", None)

        if not isinstance(text, str) or not text.strip():
            return

        text = text.strip()

        # Check if message is an invite token
        if text.startswith("inv_"):
            await self._handle_discord_invite_token(message, user_id, text)
            return

        # Resolve identity
        from teleclaude.core.identity import get_identity_resolver

        identity = get_identity_resolver().resolve("discord", {"user_id": user_id, "discord_user_id": user_id})

        if not identity or not identity.person_name:
            # Unknown user
            channel = getattr(message, "channel", None)
            if channel:
                await channel.send(
                    "I don't recognize your account. Send me your invite token to get started, or contact your admin."
                )
            return

        # Find or create session for this user
        sessions = await db.list_sessions(last_input_origin="discord", include_closed=False)
        session = None
        for s in sessions:
            discord_meta = s.get_metadata().get_ui().get_discord()
            if discord_meta.user_id == user_id:
                session = s
                break

        if not session:
            # Create new session in personal workspace
            from teleclaude.invite import scaffold_personal_workspace

            workspace_path = scaffold_personal_workspace(identity.person_name)

            create_cmd = CreateSessionCommand(
                project_path=str(workspace_path),
                title=f"Discord: {identity.person_name}",
                origin=InputOrigin.DISCORD.value,
                channel_metadata={
                    "user_id": user_id,
                    "discord_user_id": user_id,
                    "human_role": identity.person_role or "member",
                    "platform": "discord",
                },
                auto_command="agent claude",
            )
            result = await get_command_service().create_session(create_cmd)
            session_id = str(result.get("session_id", ""))
            if not session_id:
                logger.error("Discord DM session creation failed for %s", identity.person_name)
                return

            session = await db.get_session(session_id)
            if not session:
                logger.error("Session %s not found after creation for %s", session_id, identity.person_name)
                return

        # Process message
        actor_name = (identity.person_name or "").strip() or self._discord_actor_name(author, user_id)
        actor_avatar_url = self._discord_actor_avatar_url(author)
        cmd = ProcessMessageCommand(
            session_id=session.session_id,
            text=text,
            origin=InputOrigin.DISCORD.value,
            actor_id=f"discord:{user_id}",
            actor_name=actor_name,
            actor_avatar_url=actor_avatar_url,
        )
        await get_command_service().process_message(cmd)

    async def _handle_discord_invite_token(self, message: object, user_id: str, token: str) -> None:
        """Handle invite token binding in Discord DM."""
        from teleclaude.cli.config_handlers import find_person_by_invite_token

        result = find_person_by_invite_token(token)
        if not result:
            channel = getattr(message, "channel", None)
            if channel:
                await channel.send("I don't recognize this invite. Please contact your admin.")
            return

        person_name, person_config = result

        # Check if credentials are already bound
        existing_user_id = person_config.creds.discord.user_id if person_config.creds.discord else None

        if existing_user_id:
            if existing_user_id == user_id:
                # Same user - proceed to session (already bound)
                pass
            else:
                # Different user - reject
                channel = getattr(message, "channel", None)
                if channel:
                    await channel.send("This invite is already associated with another account.")
                return
        else:
            # Bind credentials
            from teleclaude.invite import bind_discord_credentials

            bind_discord_credentials(person_name, user_id)
            logger.info("Bound Discord user %s to person %s", user_id, person_name)

        # Scaffold personal workspace and create session
        from teleclaude.invite import scaffold_personal_workspace

        workspace_path = scaffold_personal_workspace(person_name)

        # Create session
        create_cmd = CreateSessionCommand(
            project_path=str(workspace_path),
            title=f"Discord: {person_name}",
            origin=InputOrigin.DISCORD.value,
            channel_metadata={
                "user_id": user_id,
                "discord_user_id": user_id,
                "human_role": "member",
                "platform": "discord",
            },
            auto_command="agent claude",
        )
        result = await get_command_service().create_session(create_cmd)
        session_id = str(result.get("session_id", ""))
        if not session_id:
            logger.error("Discord DM session creation failed for %s", person_name)
            channel = getattr(message, "channel", None)
            if channel:
                await channel.send("Failed to create session. Please contact your admin.")
            return

        # Send greeting
        channel = getattr(message, "channel", None)
        if channel:
            await channel.send(f"Hi {person_name}, I'm your personal assistant. What would you like to work on?")

    async def _handle_on_message(self, message: object) -> None:
        author = getattr(message, "author", None)
        channel = getattr(message, "channel", None)
        logger.debug(
            "[DISCORD MSG] channel_id=%s author_id=%s is_bot=%s",
            self._parse_optional_int(getattr(channel, "id", None)),
            getattr(author, "id", "?"),
            bool(getattr(author, "bot", False)),
        )

        if self._is_bot_message(message):
            return

        # Guild verification: drop messages from other guilds
        if self._guild_id is not None:
            msg_guild_id = self._parse_optional_int(getattr(getattr(message, "guild", None), "id", None))
            if msg_guild_id is not None and msg_guild_id != self._guild_id:
                logger.debug("Ignoring message from guild %s (expected %s)", msg_guild_id, self._guild_id)
                return

        # Handle DMs (no guild)
        if getattr(message, "guild", None) is None:
            await self._handle_discord_dm(message)
            return

        # Check if this message is in a relay thread (escalation forum)
        channel = getattr(message, "channel", None)
        parent_id = self._parse_optional_int(getattr(channel, "parent_id", None))
        if parent_id and parent_id == self._escalation_channel_id:
            text = getattr(message, "content", None)
            if isinstance(text, str) and text.strip():
                await self._handle_relay_thread_message(message, text)
            return

        # Channel gating: only process messages from managed forums
        if not self._is_managed_message(message):
            logger.debug("Ignoring message from non-managed channel")
            return

        # Voice/audio attachment — handle before the text guard
        audio_attachment = self._extract_audio_attachment(message)
        if audio_attachment is not None:
            await self._handle_voice_attachment(message, audio_attachment)
            return

        # Handle image/file attachments (non-audio)
        file_attachments = self._extract_file_attachments(message)
        if file_attachments:
            await self._handle_file_attachments(message, file_attachments)

        text = getattr(message, "content", None)
        if not isinstance(text, str) or not text.strip():
            return  # No text — if attachments existed, they were already handled above

        try:
            session = await self._resolve_or_create_session(message)
        except Exception as exc:
            logger.error("Discord session resolution failed: %s", exc, exc_info=True)
            return
        if not session:
            return

        # Role-based authorization: customers only accepted from help desk threads
        if self._is_customer_session(session) and not self._is_help_desk_thread(message):
            logger.debug("Ignoring customer message from non-help-desk channel")
            return

        # Relay mode: divert customer messages to the relay thread instead of the AI session
        if session.relay_status == "active" and session.relay_discord_channel_id:
            await self._forward_to_relay_thread(session, text, message)
            return

        message_id = str(getattr(message, "id", ""))
        channel_metadata = {
            "message_id": message_id,
            "user_id": str(getattr(getattr(message, "author", None), "id", "")),
            "discord_user_id": str(getattr(getattr(message, "author", None), "id", "")),
        }
        author_obj = getattr(message, "author", None)
        if author_obj is not None:
            channel_metadata["user_name"] = self._discord_actor_name(
                author_obj,
                str(getattr(author_obj, "id", "")),
            )
        metadata = self._metadata(channel_metadata=channel_metadata)
        actor_user_id = str(getattr(getattr(message, "author", None), "id", "")).strip() or "unknown"
        actor_name = self._discord_actor_name(getattr(message, "author", None), actor_user_id)
        actor_avatar_url = self._discord_actor_avatar_url(getattr(message, "author", None))
        cmd = ProcessMessageCommand(
            session_id=session.session_id,
            text=text,
            origin=InputOrigin.DISCORD.value,
            actor_id=f"discord:{actor_user_id}",
            actor_name=actor_name,
            actor_avatar_url=actor_avatar_url,
        )
        await self._dispatch_command(
            session,
            message_id,
            metadata,
            "process_message",
            cmd.to_payload(),
            lambda: get_command_service().process_message(cmd),
        )

    async def _handle_thread_delete(self, payload: object) -> None:
        """Handle a Discord thread being deleted externally.

        When a user deletes a thread from Discord, look up the session
        that owns it and emit session_closed so the daemon terminates it.
        """
        thread_id = self._parse_optional_int(getattr(payload, "thread_id", None))
        if thread_id is None:
            return

        # Guild check
        if self._guild_id is not None:
            payload_guild_id = self._parse_optional_int(getattr(payload, "guild_id", None))
            if payload_guild_id is not None and payload_guild_id != self._guild_id:
                return

        sessions = await db.get_sessions_by_adapter_metadata("discord", "thread_id", thread_id, include_closed=True)
        if not sessions:
            logger.debug("No session found for deleted Discord thread %s", thread_id)
            return

        session = sessions[0]
        if session.closed_at or session.lifecycle_status in {"closed", "closing"}:
            logger.debug(
                "Thread %s deleted for already-closed session %s",
                thread_id,
                session.session_id[:8],
            )
            return

        logger.info(
            "Discord thread %s deleted by user, terminating session %s",
            thread_id,
            session.session_id[:8],
        )
        event_bus.emit(
            "session_closed",
            SessionLifecycleContext(session_id=session.session_id),
        )

    def _is_bot_message(self, message: object) -> bool:
        author = getattr(message, "author", None)
        if not author:
            return True
        if bool(getattr(author, "bot", False)):
            return True
        if self._client is not None and getattr(self._client, "user", None) is not None:
            self_user_id = getattr(getattr(self._client, "user", None), "id", None)
            if self_user_id is not None and self_user_id == getattr(author, "id", None):
                return True
        return False

    def _is_managed_message(self, message: object) -> bool:
        """Check if a message originates from a managed forum.

        Managed forums include: help desk, all-sessions, and all project forums.
        When ``_help_desk_channel_id`` is not configured, all messages are
        accepted (dev/test mode).  Otherwise the message must come from
        a managed forum or a thread whose parent is a managed forum.
        """
        if self._help_desk_channel_id is None:
            return True

        managed_ids = self._get_managed_forum_ids()

        channel = getattr(message, "channel", None)
        channel_id = self._parse_optional_int(getattr(channel, "id", None))
        if channel_id in managed_ids:
            return True

        parent_id = self._parse_optional_int(getattr(channel, "parent_id", None))
        if parent_id in managed_ids:
            return True

        parent_obj = getattr(channel, "parent", None)
        parent_obj_id = self._parse_optional_int(getattr(parent_obj, "id", None))
        if parent_obj_id in managed_ids:
            return True

        return False

    def _get_managed_forum_ids(self) -> set[int]:
        """Build the set of all managed Discord forum IDs."""
        ids: set[int] = set()
        if self._help_desk_channel_id is not None:
            ids.add(self._help_desk_channel_id)
        if self._all_sessions_channel_id is not None:
            ids.add(self._all_sessions_channel_id)
        ids.update(self._project_forum_map.values())
        return ids

    def _is_help_desk_thread(self, message: object) -> bool:
        """Check if a message originates from the help desk forum or a thread within it."""
        if self._help_desk_channel_id is None:
            return True
        channel = getattr(message, "channel", None)
        channel_id = self._parse_optional_int(getattr(channel, "id", None))
        if channel_id == self._help_desk_channel_id:
            return True
        parent_id = self._parse_optional_int(getattr(channel, "parent_id", None))
        if parent_id == self._help_desk_channel_id:
            return True
        parent_obj = getattr(channel, "parent", None)
        parent_obj_id = self._parse_optional_int(getattr(parent_obj, "id", None))
        return parent_obj_id == self._help_desk_channel_id

    # =========================================================================
    # Voice / Audio Handling
    # =========================================================================

    @staticmethod
    def _extract_audio_attachment(message: object) -> object | None:
        """Return the first audio attachment from a Discord message, or None."""
        attachments = getattr(message, "attachments", None)
        if not attachments:
            return None
        for attachment in attachments:
            content_type = getattr(attachment, "content_type", None) or ""
            if content_type.startswith("audio/"):
                return attachment
        return None

    @staticmethod
    def _extract_file_attachments(message: object) -> list[object]:
        """Return all non-audio attachments from a Discord message."""
        attachments = getattr(message, "attachments", None)
        if not attachments:
            return []
        result = []
        for attachment in attachments:
            content_type = getattr(attachment, "content_type", None) or ""
            if not content_type.startswith("audio/"):
                result.append(attachment)
        return result

    async def _handle_voice_attachment(self, message: object, attachment: object) -> None:
        """Download a voice/audio attachment and dispatch it for transcription."""
        try:
            session = await self._resolve_or_create_session(message)
        except Exception as exc:
            logger.error("Discord session resolution failed for voice: %s", exc, exc_info=True)
            return
        if not session:
            return

        message_id = str(getattr(message, "id", ""))

        # Derive file extension from the attachment filename or default to .ogg
        filename = getattr(attachment, "filename", None) or "voice.ogg"
        ext = Path(filename).suffix or ".ogg"

        temp_dir = Path(tempfile.gettempdir()) / "teleclaude_voice"
        temp_dir.mkdir(exist_ok=True)
        temp_file_path = temp_dir / f"voice_{message_id}{ext}"

        try:
            save_fn = self._require_async_callable(getattr(attachment, "save", None), label="Discord attachment save")
            await save_fn(temp_file_path)
            logger.info("Downloaded Discord voice message to: %s", temp_file_path)

            # Discord exposes duration (seconds) on audio attachments
            raw_duration = getattr(attachment, "duration", None)
            duration = float(raw_duration) if raw_duration is not None else None

            await get_command_service().handle_voice(
                HandleVoiceCommand(
                    session_id=session.session_id,
                    file_path=str(temp_file_path),
                    duration=duration,
                    message_id=message_id,
                    origin=InputOrigin.DISCORD.value,
                    actor_id=f"discord:{getattr(getattr(message, 'author', None), 'id', 'unknown')}",
                    actor_name=self._discord_actor_name(
                        getattr(message, "author", None),
                        str(getattr(getattr(message, "author", None), "id", "unknown")),
                    ),
                    actor_avatar_url=self._discord_actor_avatar_url(getattr(message, "author", None)),
                )
            )
        except Exception as exc:
            error_msg = str(exc) if str(exc).strip() else "Unknown error"
            logger.error("Failed to process Discord voice message: %s", error_msg, exc_info=True)

    async def _handle_file_attachments(self, message: object, attachments: list[object]) -> None:
        """Download file/image attachments and dispatch them for processing."""
        try:
            session = await self._resolve_or_create_session(message)
        except Exception as exc:
            logger.error("Discord session resolution failed for file attachments: %s", exc, exc_info=True)
            return
        if not session:
            return

        # Get text caption for the first attachment only (to avoid duplication)
        caption = getattr(message, "content", None)
        if not isinstance(caption, str) or not caption.strip():
            caption = None

        for i, attachment in enumerate(attachments):
            filename = f"file_{i}.dat"  # Default fallback
            try:
                # Determine file type and subdirectory
                content_type = getattr(attachment, "content_type", None) or ""
                is_image = content_type.startswith("image/")
                subdir = "photos" if is_image else "files"

                # Derive filename
                filename = getattr(attachment, "filename", None)
                if not filename:
                    ext = ".jpg" if is_image else ".dat"
                    filename = f"file_{i}{ext}"

                # Download to session workspace
                output_dir = get_session_output_dir(session.session_id) / subdir
                output_dir.mkdir(parents=True, exist_ok=True)
                file_path = output_dir / filename

                save_fn = self._require_async_callable(
                    getattr(attachment, "save", None), label="Discord attachment save"
                )
                await save_fn(file_path)
                logger.info("Downloaded Discord %s to: %s", "image" if is_image else "file", file_path)

                # Dispatch via command service
                # Only include caption for the first attachment
                attachment_caption = caption if i == 0 else None
                await get_command_service().handle_file(
                    HandleFileCommand(
                        session_id=session.session_id,
                        file_path=str(file_path),
                        filename=filename,
                        caption=attachment_caption,
                    )
                )
            except Exception as exc:
                error_msg = str(exc) if str(exc).strip() else "Unknown error"
                logger.error(
                    "Failed to process Discord attachment %s: %s", filename if filename else i, error_msg, exc_info=True
                )
                # Continue to next attachment

    async def _resolve_or_create_session(self, message: object) -> "Session | None":
        user_id = str(getattr(getattr(message, "author", None), "id", ""))
        if not user_id:
            return None

        channel_id, thread_id = self._extract_channel_ids(message)
        guild_id = self._parse_optional_int(getattr(getattr(message, "guild", None), "id", None))

        session = await self._find_session(channel_id=channel_id, thread_id=thread_id, user_id=user_id)
        if session is None:
            forum_type, project_path = self._resolve_forum_context(message)
            session = await self._create_session_for_message(
                message, user_id, forum_type=forum_type, project_path=project_path
            )
            if session is None:
                return None

        return await self._update_session_discord_metadata(
            session,
            user_id=user_id,
            guild_id=guild_id,
            channel_id=channel_id,
            thread_id=thread_id,
        )

    @staticmethod
    def _is_thread_channel(channel: object) -> bool:
        type_name = type(channel).__name__.lower()
        return "thread" in type_name

    def _extract_channel_ids(self, message: object) -> tuple[int | None, int | None]:
        channel = getattr(message, "channel", None)
        if not self._is_thread_channel(channel):
            return (self._parse_optional_int(getattr(channel, "id", None)), None)

        thread_id = self._parse_optional_int(getattr(channel, "id", None))
        parent = getattr(channel, "parent", None)
        parent_id = self._parse_optional_int(getattr(parent, "id", None))
        return (parent_id or thread_id, thread_id)

    async def _find_session(
        self,
        *,
        channel_id: int | None,
        thread_id: int | None,
        user_id: str,
    ) -> "Session | None":
        if thread_id is not None:
            thread_sessions = await db.get_sessions_by_adapter_metadata("discord", "thread_id", thread_id)
            if thread_sessions:
                return thread_sessions[0]

        if channel_id is None:
            return None

        channel_sessions = await db.get_sessions_by_adapter_metadata("discord", "channel_id", channel_id)
        for session in channel_sessions:
            if session.get_metadata().get_ui().get_discord().user_id == user_id:
                return session
        return None

    async def _handle_launcher_click(self, interaction: object, agent_name: str) -> None:
        response = getattr(interaction, "response", None)
        response_defer = getattr(response, "defer", None)
        if callable(response_defer):
            await self._require_async_callable(response_defer, label="Discord interaction response.defer")(
                ephemeral=True
            )

        forum_id = self._parse_optional_int(getattr(interaction, "channel_id", None))
        project_path = self._resolve_project_from_forum(forum_id) if forum_id is not None else None
        if project_path is None:
            followup = getattr(interaction, "followup", None)
            followup_send = getattr(followup, "send", None)
            if callable(followup_send):
                await self._require_async_callable(followup_send, label="Discord interaction followup.send")(
                    "Unable to resolve project for this forum.",
                    ephemeral=True,
                )
            return

        create_cmd = CreateSessionCommand(
            project_path=project_path,
            auto_command=f"agent {agent_name}",
            origin=InputOrigin.DISCORD.value,
        )
        result = await get_command_service().create_session(create_cmd)
        session_id = str(result.get("session_id", ""))

        followup = getattr(interaction, "followup", None)
        followup_send = getattr(followup, "send", None)
        if not callable(followup_send):
            return
        if session_id:
            await self._require_async_callable(followup_send, label="Discord interaction followup.send")(
                f"Starting {agent_name}...",
                ephemeral=True,
            )
            return
        await self._require_async_callable(followup_send, label="Discord interaction followup.send")(
            f"Failed to start {agent_name}.",
            ephemeral=True,
        )

    async def _handle_cancel_slash(self, interaction: object) -> None:
        channel = getattr(interaction, "channel", None)
        response = getattr(interaction, "response", None)
        response_send = getattr(response, "send_message", None)
        if not callable(response_send):
            return
        if not self._is_thread_channel(channel):
            await self._require_async_callable(response_send, label="Discord interaction response.send_message")(
                "No active session in this thread.",
                ephemeral=True,
            )
            return

        thread_id = self._parse_optional_int(getattr(channel, "id", None))
        parent = getattr(channel, "parent", None)
        parent_id = self._parse_optional_int(getattr(parent, "id", None))
        channel_id = parent_id or thread_id

        user_obj = getattr(interaction, "user", None)
        user_id = str(getattr(user_obj, "id", "")).strip()
        session = await self._find_session(channel_id=channel_id, thread_id=thread_id, user_id=user_id)
        if session is None:
            await self._require_async_callable(response_send, label="Discord interaction response.send_message")(
                "No active session in this thread.",
                ephemeral=True,
            )
            return

        cmd = KeysCommand(session_id=session.session_id, key="cancel", args=[])
        await self._require_async_callable(response_send, label="Discord interaction response.send_message")(
            "Sent CTRL+C",
            ephemeral=True,
        )
        await get_command_service().keys(cmd)

    async def _create_session_for_message(
        self,
        message: object,
        user_id: str,
        *,
        forum_type: str = "help_desk",
        project_path: str | None = None,
    ) -> "Session | None":
        author = getattr(message, "author", None)
        display_name = str(
            getattr(author, "display_name", None) or getattr(author, "name", None) or f"discord-{user_id}"
        )
        channel_metadata: dict[str, str] = {
            "user_id": user_id,
            "discord_user_id": user_id,
            "platform": "discord",
        }

        if forum_type == "help_desk":
            channel_metadata["human_role"] = "customer"
            effective_path = project_path or config.computer.help_desk_dir
            auto_command = "agent claude"
        else:
            forum_id, _ = self._extract_channel_ids(message)
            forum_project_path = self._resolve_project_from_forum(forum_id) if forum_id is not None else None
            effective_path = forum_project_path or project_path or config.computer.help_desk_dir
            auto_command = f"agent {self._default_agent}"

        create_cmd = CreateSessionCommand(
            project_path=effective_path,
            title=f"Discord: {display_name}",
            origin=InputOrigin.DISCORD.value,
            channel_metadata=channel_metadata,
            auto_command=auto_command,
        )
        result = await get_command_service().create_session(create_cmd)
        session_id = str(result.get("session_id", ""))
        if not session_id:
            logger.error("Discord session creation returned empty session_id")
            return None
        return await db.get_session(session_id)

    async def _update_session_discord_metadata(
        self,
        session: "Session",
        *,
        user_id: str,
        guild_id: int | None,
        channel_id: int | None,
        thread_id: int | None,
    ) -> "Session":
        discord_meta = session.get_metadata().get_ui().get_discord()
        changed = False

        if discord_meta.user_id != user_id:
            discord_meta.user_id = user_id
            changed = True
        if guild_id is not None and discord_meta.guild_id != guild_id:
            discord_meta.guild_id = guild_id
            changed = True
        if channel_id is not None and discord_meta.channel_id != channel_id:
            discord_meta.channel_id = channel_id
            changed = True
        if thread_id is not None and discord_meta.thread_id != thread_id:
            discord_meta.thread_id = thread_id
            changed = True

        if not changed:
            return session

        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        return (await db.get_session(session.session_id)) or session

    async def _resolve_destination_channel(
        self,
        session: "Session",
        *,
        metadata: "MessageMetadata | None" = None,
    ) -> object:
        if self._client is None:
            raise AdapterError("Discord adapter not started")

        metadata_channel_id = (
            self._parse_optional_int(metadata.channel_id) if metadata and metadata.channel_id else None
        )
        discord_meta = session.get_metadata().get_ui().get_discord()
        destination_id = metadata_channel_id or discord_meta.thread_id or discord_meta.channel_id
        if destination_id is None:
            raise AdapterError(f"Session {session.session_id} missing discord channel mapping")

        channel = await self._get_channel(destination_id)
        if channel is None:
            # Channel was deleted from Discord — clear stale metadata so we stop retrying
            logger.warning(
                "Discord channel %s not found for session %s, clearing stale metadata",
                destination_id,
                session.session_id[:8],
            )
            discord_meta.thread_id = None
            discord_meta.channel_id = None
            discord_meta.output_message_id = None
            discord_meta.thread_topper_message_id = None
            await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
            raise AdapterError(f"Discord channel {destination_id} not found (metadata cleared)")
        return channel

    async def _fetch_destination_message(
        self,
        session: "Session",
        message_id: str,
        *,
        metadata: "MessageMetadata | None" = None,
    ) -> object:
        channel = await self._resolve_destination_channel(session, metadata=metadata)
        fetch_fn = self._require_async_callable(
            getattr(channel, "fetch_message", None), label="Discord channel fetch_message"
        )
        if not message_id.isdigit():
            raise AdapterError(f"Discord message_id must be numeric, got {message_id!r}")
        return await fetch_fn(int(message_id))

    async def _get_channel(self, channel_id: int) -> object | None:
        if self._client is None:
            return None

        get_fn = getattr(self._client, "get_channel", None)
        if callable(get_fn):
            cached = get_fn(channel_id)
            if cached is not None:
                return cached

        fetch_fn = getattr(self._client, "fetch_channel", None)
        if callable(fetch_fn):
            try:
                return await self._require_async_callable(fetch_fn, label="Discord client fetch_channel")(channel_id)
            except Exception as exc:
                logger.debug("Discord fetch_channel(%s) failed: %s", channel_id, exc)
        return None

    async def _create_forum_thread(
        self, forum_channel: object, *, title: str, content: str = "Initializing Help Desk session..."
    ) -> tuple[int, str]:
        create_thread_fn = self._require_async_callable(
            getattr(forum_channel, "create_thread", None), label="Discord forum create_thread"
        )

        # Discord channel names must be 1-100 characters
        if len(title) > 100:
            title = title[:97] + "..."
        result = await create_thread_fn(name=title, content=self._fit_message_text(content, context="thread_starter"))
        thread = getattr(result, "thread", None)
        starter_message = getattr(result, "message", None)
        if thread is None and isinstance(result, tuple) and result:
            thread = result[0]
            if len(result) > 1:
                starter_message = result[1]
        if thread is None:
            thread = result

        thread_id = self._parse_optional_int(getattr(thread, "id", None))
        if thread_id is None:
            raise AdapterError("Discord create_thread() returned invalid thread id")
        starter_message_id_raw = getattr(starter_message, "id", None)
        starter_message_id = str(starter_message_id_raw) if starter_message_id_raw is not None else str(thread_id)
        return thread_id, starter_message_id

    async def create_escalation_thread(
        self,
        *,
        customer_name: str,
        reason: str,
        context_summary: str | None,
        session_id: str,
    ) -> int:
        """Create a thread in the escalation forum channel for admin relay."""
        escalation_channel_id = self._escalation_channel_id
        if not escalation_channel_id:
            raise AdapterError("escalation_channel_id not configured")

        forum = await self._get_channel(escalation_channel_id)
        if forum is None:
            raise AdapterError(f"Escalation channel {escalation_channel_id} not found")
        if not self._is_forum_channel(forum):
            raise AdapterError(f"Escalation channel {escalation_channel_id} is not a Forum Channel")

        body = f"**Reason:** {reason}"
        if context_summary:
            body += f"\n\n**Context:** {context_summary}"
        body += f"\n\n*Session: {session_id}*"

        thread_id, _topper_message_id = await self._create_forum_thread(forum, title=customer_name, content=body)
        return thread_id

    @staticmethod
    def _is_forum_channel(channel: object) -> bool:
        return "forum" in type(channel).__name__.lower()

    # =========================================================================
    # Stale Thread Cleanup
    # =========================================================================

    async def cleanup_stale_resources(self) -> int:
        """Scan Discord forums and clean up orphan/stale threads."""
        if self._client is None:
            return 0

        cleaned = 0
        for forum_id, match_field in [
            (self._help_desk_channel_id, "thread_id"),
            (self._all_sessions_channel_id, "thread_id"),
            (self._escalation_channel_id, "relay"),
        ]:
            if forum_id is None:
                continue
            cleaned += await self._cleanup_forum_threads(forum_id, match_field)

        return cleaned

    async def _cleanup_forum_threads(self, forum_id: int, match_type: str) -> int:
        """Scan a single forum for orphan/stale threads and delete them.

        Collects both active and archived threads, then deletes any
        that have no corresponding active session in the database.
        """
        forum = await self._get_channel(forum_id)
        if forum is None or not self._is_forum_channel(forum):
            return 0

        # Collect active threads
        all_threads: list[object] = []
        active_threads = getattr(forum, "threads", None)
        if isinstance(active_threads, list):
            all_threads.extend(active_threads)

        # Collect archived threads
        archived_fn = getattr(forum, "archived_threads", None)
        if callable(archived_fn):
            try:
                archived_iter = cast(AsyncIterator[object], archived_fn(limit=100))
                async for thread in archived_iter:
                    all_threads.append(thread)
            except Exception as exc:
                logger.debug("Failed to fetch archived threads for forum %s: %s", forum_id, exc)

        cleaned = 0
        for thread in all_threads:
            thread_id = self._parse_optional_int(getattr(thread, "id", None))
            if thread_id is None:
                continue

            ownership = await self._thread_ownership(thread_id, match_type)
            if ownership != "closed":
                # "active" → keep, "unknown" → not ours, skip
                continue

            try:
                delete_fn = self._require_async_callable(getattr(thread, "delete", None), label="thread delete")
                await delete_fn()
                cleaned += 1
                logger.info("Deleted orphan Discord thread %s in forum %s", thread_id, forum_id)
            except Exception as exc:
                logger.warning("Failed to delete thread %s: %s", thread_id, exc)

            await asyncio.sleep(0.5)

        return cleaned

    async def _thread_ownership(self, thread_id: int, match_type: str) -> str:
        """Classify a Discord thread's ownership.

        Returns:
            "active"  — thread belongs to a live session, keep it
            "closed"  — thread belongs to a closed session, safe to delete
            "unknown" — no session record found, not ours, leave it alone
        """
        if match_type == "relay":
            session = await db.get_session_by_field("relay_discord_channel_id", str(thread_id))
            if session is None:
                return "unknown"
            return "active" if session.relay_status == "active" else "closed"

        sessions = await db.get_sessions_by_adapter_metadata("discord", "thread_id", thread_id, include_closed=True)
        if not sessions:
            return "unknown"
        if any(s.closed_at is None for s in sessions):
            return "active"
        return "closed"

    # =========================================================================
    # Relay Methods
    # =========================================================================

    async def _forward_to_relay_thread(self, session: "Session", text: str, message: object) -> None:
        """Forward a customer message to the relay Discord thread (relay diversion)."""
        relay_channel_id = session.relay_discord_channel_id
        if not relay_channel_id:
            return
        try:
            thread = await self._get_channel(int(relay_channel_id))
            if thread is None:
                logger.error("Relay thread %s not found", relay_channel_id)
                return

            author = getattr(message, "author", None)
            name = getattr(author, "display_name", None) or "Customer"
            origin = session.last_input_origin or "discord"

            send_fn = self._require_async_callable(getattr(thread, "send", None), label="relay thread send")
            await send_fn(f"**{name}** ({origin}): {text}")
        except Exception:  # noqa: BLE001 - best-effort relay forwarding
            logger.warning("Failed to forward message to relay thread %s", relay_channel_id)

    async def _handle_relay_thread_message(self, message: object, text: str) -> None:
        """Handle an admin message in a relay thread — forward to customer or handback."""
        channel = getattr(message, "channel", None)
        thread_id = str(getattr(channel, "id", ""))

        session = await db.get_session_by_field("relay_discord_channel_id", thread_id)
        if not session:
            return  # Orphaned thread or relay already closed

        if self._is_agent_tag(text):
            await self._handle_agent_handback(session, text, thread_id)
            return

        # Forward admin message to customer via their originating adapter
        author = getattr(message, "author", None)
        admin_name = getattr(author, "display_name", None) or "Admin"
        await self._deliver_to_customer(session, f"{admin_name}: {text}")

    async def _deliver_to_customer(self, session: "Session", text: str) -> None:
        """Deliver a message to the customer via all UI adapters."""
        from teleclaude.core.models import MessageMetadata

        metadata = MessageMetadata()
        try:
            await self.client.send_message(session=session, text=text, metadata=metadata, ephemeral=False)
        except Exception:  # noqa: BLE001 - best-effort delivery
            logger.warning("Failed to deliver relay message to customer session %s", session.session_id[:8])

    def _is_agent_tag(self, text: str) -> bool:
        """Check if a message contains an @agent handback tag."""
        if "@agent" in text.lower():
            return True
        if self._client and getattr(self._client, "user", None):
            bot_id = getattr(getattr(self._client, "user", None), "id", None)
            if bot_id and f"<@{bot_id}>" in text:
                return True
        return False

    async def _handle_agent_handback(self, session: "Session", _text: str, thread_id: str) -> None:
        """Collect relay messages and inject context back into the AI session."""
        messages = await self._collect_relay_messages(thread_id, session.relay_started_at)
        context_block = self._compile_relay_context(messages)

        # Inject context into the AI session's tmux
        from teleclaude.core.tmux_bridge import send_keys_existing_tmux

        await send_keys_existing_tmux(session.tmux_session_name, context_block, send_enter=True)

        # Clear relay state
        await db.update_session(
            session.session_id,
            relay_status=None,
            relay_discord_channel_id=None,
            relay_started_at=None,
        )

        logger.info("Agent handback completed for session %s (thread %s)", session.session_id[:8], thread_id)

    _FORWARDING_PATTERN: str = r"^\*\*(.+?)\*\* \((\w+)\): (.+)"

    async def _collect_relay_messages(self, thread_id: str, since: "datetime | None") -> list[dict[str, str]]:
        """Read all messages from a relay thread since the given timestamp."""
        import re

        thread = await self._get_channel(int(thread_id))
        if not thread:
            return []

        history_fn = getattr(thread, "history", None)
        if not callable(history_fn):
            return []

        messages: list[dict[str, str]] = []
        history_iter = cast(AsyncIterator[object], history_fn(after=since, limit=200))
        async for msg in history_iter:
            content = getattr(msg, "content", "") or ""
            author = getattr(msg, "author", None)
            is_bot = bool(getattr(author, "bot", False))

            if is_bot:
                # Bot-forwarded customer message: **Name** (platform): text
                match = re.match(self._FORWARDING_PATTERN, content, re.DOTALL)
                if match:
                    messages.append(
                        {
                            "role": "Customer",
                            "name": match.group(1),
                            "content": match.group(3),
                        }
                    )
                # Non-matching bot messages (system/notifications) are skipped
                continue

            # Non-bot messages in the relay thread are from admins
            name = getattr(author, "display_name", None) or "Unknown"
            messages.append(
                {
                    "role": "Admin",
                    "name": name,
                    "content": content,
                }
            )
        return messages

    @staticmethod
    def _sanitize_relay_text(text: str) -> str:
        """Strip control characters and ANSI escape sequences from relay text."""
        import re

        # Remove ANSI escape sequences
        text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
        # Remove other control characters (keep newlines and tabs)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        return text

    @staticmethod
    def _compile_relay_context(messages: list[dict[str, str]]) -> str:
        """Compile relay messages into a context block for AI injection."""
        lines = [
            "[Admin Relay Conversation]",
            "The admin spoke directly with the customer. Here is the full exchange:",
            "",
        ]
        for msg in messages:
            content = DiscordAdapter._sanitize_relay_text(msg["content"])
            lines.append(f"{msg['role']} ({msg['name']}): {content}")

        lines.extend(
            [
                "",
                "The admin has handed the conversation back to you. Continue naturally,",
                "acknowledging what was discussed.",
            ]
        )
        return "\n".join(lines)
