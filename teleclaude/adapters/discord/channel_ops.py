"""Channel operations mixin for Discord adapter.

Handles thread/channel creation, title updates, open/close/delete lifecycle,
stale resource cleanup, and thread ownership classification.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.core.db import db

if TYPE_CHECKING:
    from teleclaude.core.models import ChannelMetadata, Session

logger = get_logger(__name__)


class ChannelOperationsMixin:
    """Mixin providing channel/thread lifecycle methods for DiscordAdapter.

    Required host attributes:
    - _help_desk_channel_id: int | None
    - _all_sessions_channel_id: int | None
    - _project_forum_map: dict[str, int]
    - _team_channel_map: dict[int, str]
    - _discord: ModuleType
    - _guild_id: int | None
    - _client: DiscordClientLike | None
    - _require_async_callable(fn, *, label) -> Callable
    - _get_channel(channel_id) -> object | None (async)
    - _parse_optional_int(value) -> int | None
    - _resolve_parent_forum_id(channel) -> int | None
    """

    _help_desk_channel_id: int | None
    _all_sessions_channel_id: int | None
    _project_forum_map: dict[str, int]
    _team_channel_map: dict[int, str]
    _guild_id: int | None

    if TYPE_CHECKING:
        from types import ModuleType

        _discord: ModuleType
        _client: object

        def _parse_optional_int(self, value: object) -> int | None: ...

        @staticmethod
        def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]: ...

        async def _get_channel(self, channel_id: int) -> object | None: ...

        def _resolve_parent_forum_id(self, channel: object | None) -> int | None: ...

    # =========================================================================
    # store_channel_id / ensure_channel
    # =========================================================================

    def store_channel_id(self, adapter_metadata: object, channel_id: str) -> None:
        from teleclaude.core.models import SessionAdapterMetadata

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

    async def ensure_channel(self, session: Session) -> Session:
        # Re-read from DB to prevent stale in-memory metadata from concurrent lanes
        fresh = await db.get_session(session.session_id)
        if fresh:
            session = fresh

        discord_meta = session.get_metadata().get_ui().get_discord()
        if discord_meta.thread_id is not None:
            return session

        # Team text channels don't use forum threads — messages go directly
        # to the channel. The channel_id is already set from the incoming message.
        if discord_meta.channel_id is not None and discord_meta.channel_id in self._team_channel_map:
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

    def _resolve_target_forum(self, session: Session) -> int | None:
        """Determine which Discord forum this session's thread belongs in."""
        if self._is_customer_session(session):
            return self._help_desk_channel_id
        # Check project-specific forums
        forum_id = self._match_project_forum(session)
        if forum_id is not None:
            logger.debug(
                "[DISCORD_ROUTE] session=%s project=%s -> project forum %s",
                session.session_id,
                session.project_path,
                forum_id,
            )
            return forum_id
        logger.debug(
            "[DISCORD_ROUTE] session=%s project=%s -> catch-all (map has %d entries)",
            session.session_id,
            session.project_path,
            len(self._project_forum_map),
        )
        return self._all_sessions_channel_id

    def _match_project_forum(self, session: Session) -> int | None:
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
        'help_desk', 'project', 'all_sessions', 'team'.
        """
        from teleclaude.config import config

        channel = getattr(message, "channel", None)
        channel_id = self._parse_optional_int(getattr(channel, "id", None))

        # Team text channel — route to the person's folder
        if channel_id is not None and channel_id in self._team_channel_map:
            return "team", self._team_channel_map[channel_id]

        # Prefer explicit parent_id attribute, then parent.id, then channel.id
        parent_id = self._parse_optional_int(getattr(channel, "parent_id", None))
        if parent_id is None:
            parent_obj = getattr(channel, "parent", None)
            parent_id = self._parse_optional_int(getattr(parent_obj, "id", None))
        if parent_id is None:
            parent_id = channel_id

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

    def _build_thread_title(self, session: Session, target_forum_id: int) -> str:
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
    def _is_customer_session(session: Session) -> bool:
        """Check if session is customer-facing. Based solely on human_role."""
        return session.human_role == "customer"

    def _build_thread_topper(self, session: Session) -> str:
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
    # Channel CRUD
    # =========================================================================

    async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
        _ = metadata
        if self._client is None:
            raise AdapterError("Discord adapter not started")

        discord_meta = session.get_metadata().get_ui().get_discord()

        if discord_meta.thread_id is not None:
            return str(discord_meta.thread_id)

        # Team text channels — no thread creation, output goes to the channel directly
        if discord_meta.channel_id is not None and discord_meta.channel_id in self._team_channel_map:
            return str(discord_meta.channel_id)

        target_forum_id = self._resolve_target_forum(session)
        if target_forum_id is not None:
            forum = await self._get_channel(target_forum_id)
            if forum is None:
                raise AdapterError(f"Discord forum channel {target_forum_id} not found")
            if not self._is_forum_channel(forum):
                raise AdapterError(f"Discord channel {target_forum_id} is not a Forum Channel")

            topper = self._build_thread_topper(session)
            thread_id, topper_message_id = await self._create_forum_thread(forum, title=title, content=topper)  # type: ignore[attr-defined]
            discord_meta.channel_id = target_forum_id
            discord_meta.thread_id = thread_id
            discord_meta.thread_topper_message_id = topper_message_id
            await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
            return str(thread_id)

        if discord_meta.channel_id is not None:
            return str(discord_meta.channel_id)

        raise AdapterError("Discord session has no mapped destination channel")

    async def update_channel_title(self, session: Session, title: str) -> bool:
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

    async def close_channel(self, session: Session) -> bool:
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

    async def reopen_channel(self, session: Session) -> bool:
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

    async def delete_channel(self, session: Session) -> bool:
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
            (self._escalation_channel_id, "relay"),  # type: ignore[attr-defined]
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
