"""Channel operations mixin for Discord adapter.

Handles thread/channel creation, title updates, open/close/delete lifecycle,
stale resource cleanup, and thread ownership classification.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from enum import StrEnum
from types import ModuleType
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.discord._runtime import AsyncDiscordCallable, cast_async_callable, recoverable_operation_errors
from teleclaude.adapters.discord.help_desk_categories import DeskForums
from teleclaude.config import machine as teleclaude_config
from teleclaude.core.db import db
from teleclaude.core.endpoints import DeskIdentifier
from teleclaude.core.identity import session_person_role
from teleclaude.core.integration.discord_admin_state import session_launcher_key
from teleclaude.core.models import ChannelMetadata, DiscordAdapterMetadata, DiscordMetadataField, EndpointStamp, Session
from teleclaude.core.models._adapter import session_is_unattended
from teleclaude.core.session_utils import get_short_project_name
from teleclaude.services.project_catalog import get_project_catalog_service

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

# A forum this adapter does not recognize.
_UNKNOWN_FORUM_TYPE = "unknown"
_UNRECOGNIZED_FORUM_WARNING = (
    "Unrecognized forum parent_id=%s; ignoring the message. Known forums: all_sessions=%s projects=%s"
)

DISCORD_THREAD_FETCH_MESSAGE_ATTRIBUTE = "fetch_message"
DISCORD_THREAD_ID_ATTRIBUTE = "id"
THREAD_CLEANUP_PACING_SECONDS = 0.5
THREAD_STARTER_FETCH_LABEL = "Discord thread fetch_message"


class ThreadMatchField(StrEnum):
    """Session field used to identify a forum thread's owner."""

    THREAD_ID = "thread_id"
    RELAY = "relay"


class ThreadOwnership(StrEnum):
    """Ownership states that decide whether stale-thread cleanup may delete a thread."""

    ACTIVE = "active"
    CLOSED = "closed"
    UNKNOWN = "unknown"


async def gather_forum_threads(
    forum: object, discord_module: ModuleType, *, forum_id: int
) -> tuple[list[object], bool]:
    """Enumerate a forum's active and archived threads.

    Returns ``(threads, conclusive)``. ``conclusive`` is False when the
    archived-thread fetch failed, meaning the returned set may be incomplete —
    callers that must not act on a partial set (e.g. launcher reconciliation)
    should skip rather than trust it.
    """
    threads: list[object] = []
    active_threads = getattr(forum, "threads", None)
    if isinstance(active_threads, list):
        threads.extend(active_threads)

    archived_fn = getattr(forum, "archived_threads", None)
    if not callable(archived_fn):
        return threads, True

    recoverable_errors = recoverable_operation_errors(discord_module)
    try:
        archived_iter = cast(AsyncIterator[object], archived_fn(limit=100))
        async for thread in archived_iter:
            threads.append(thread)
    except recoverable_errors as exc:
        logger.debug("Failed to fetch archived threads for forum %s: %s", forum_id, exc)
        return threads, False
    return threads, True


async def fetch_thread_starter_message(
    thread: object,
    discord_module: ModuleType,
    require_async_callable: Callable[..., AsyncDiscordCallable],
) -> tuple[bool, object | None]:
    """Return a forum thread's starter message when its fetch is conclusive."""
    thread_id = getattr(thread, DISCORD_THREAD_ID_ATTRIBUTE, None)
    fetch_message = getattr(thread, DISCORD_THREAD_FETCH_MESSAGE_ATTRIBUTE, None)
    if not isinstance(thread_id, int) or not callable(fetch_message):
        return True, None

    recoverable_errors = recoverable_operation_errors(discord_module)
    try:
        message = await require_async_callable(fetch_message, label=THREAD_STARTER_FETCH_LABEL)(thread_id)
    except recoverable_errors as exc:
        logger.warning("Could not resolve starter message for Discord thread %s: %s", thread_id, exc)
        return False, None
    return True, message


class ChannelOperationsMixin:
    """Mixin providing channel/thread lifecycle methods for DiscordAdapter.

    Required host attributes:
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
    - _get_managed_forum_ids() -> set[int]
    """

    _all_sessions_channel_id: int | None
    _project_forum_map: dict[str, int]
    _desk_forums: dict[str, DeskForums]
    _team_channel_map: dict[int, str]
    _guild_id: int | None

    _discord: ModuleType
    _client: object
    _parse_optional_int: Callable[[object], int | None]
    _require_async_callable: Callable[..., AsyncDiscordCallable]
    _get_channel: Callable[[int], Awaitable[object | None]]
    _resolve_parent_forum_id: Callable[[object | None], int | None]

    if TYPE_CHECKING:
        # Provided by UiAdapter base; declared here so pyright resolves it
        # when methods on this mixin call self.display_title(session).
        def display_title(self, session: Session) -> str: ...

        def _get_managed_forum_ids(self) -> set[int]: ...

    # =========================================================================
    # ensure_channel
    # =========================================================================

    async def ensure_channel(self, session: Session) -> Session:
        """Ensure a session has its Discord destination channel or thread provisioned."""
        fresh = await db.get_session(session.session_id)
        if fresh:
            session = fresh

        discord_meta = DiscordAdapterMetadata.from_dict(session.get_origin_section("discord"))
        if discord_meta.thread_id is not None:
            return session

        if discord_meta.channel_id is not None and discord_meta.channel_id in self._team_channel_map:
            return session

        target_forum_id = self._resolve_target_forum(session)
        if target_forum_id is None:
            return session

        title = self.display_title(session)
        await self.create_channel(session, title, ChannelMetadata())
        refreshed = await db.get_session(session.session_id)
        return refreshed or session

    def _resolve_target_forum(self, session: Session) -> int | None:
        """Determine which Discord forum this session's thread belongs in.

        A help desk session belongs in its own desk's customer-sessions forum and
        in no other forum, its project's own and the catch-all included. A desk whose
        forum is not provisioned yet gets no thread. An unattended procedure agent
        belongs in no forum: people do not look at it.
        """
        if session_is_unattended(session):
            return None
        endpoint = EndpointStamp.from_session(session)
        if endpoint is not None and endpoint.is_help_desk:
            return self._desk_customer_sessions_forum(endpoint)
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

    def _desk_customer_sessions_forum(self, endpoint: EndpointStamp) -> int | None:
        """The customer-sessions forum of the desk an endpoint stamp names, when it is provisioned."""
        if endpoint.desk_kind is None or endpoint.slug is None:
            return None
        forums = self._desk_forums.get(DeskIdentifier(endpoint.desk_kind, endpoint.slug).render())
        return forums.customer_sessions if forums is not None else None

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
        'project', 'all_sessions', 'team', 'unknown'. An unknown forum names no
        project path.
        """
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

        if parent_id is not None and parent_id == self._all_sessions_channel_id:
            entries = get_project_catalog_service().list_entries()
            return "all_sessions", str(entries[0].root) if entries else None

        for path, forum_id in self._project_forum_map.items():
            if parent_id == forum_id:
                return "project", path

        if parent_id is not None:
            logger.warning(
                _UNRECOGNIZED_FORUM_WARNING,
                parent_id,
                self._all_sessions_channel_id,
                list(self._project_forum_map.values()),
            )
        return _UNKNOWN_FORUM_TYPE, None

    def title_body(self, session: Session) -> str:
        """Discord-specific decoration: prefix the project short-name for the catch-all forum.

        Per-project forum: bare session description — forum implies the project.
        Catch-all forum: prefixed with project short-name so admins can distinguish
        sessions from different projects sharing the forum.

        The universal headless marker is applied by UiAdapter.display_title; this
        method returns only the body it wraps.
        """
        description = session.title or "Untitled"
        target_forum_id = self._resolve_target_forum(session)
        if target_forum_id is None or target_forum_id != self._all_sessions_channel_id:
            return description
        short_name = get_short_project_name(session.project_path, session.subdir)
        return f"{short_name}: {description}"

    @staticmethod
    def _is_customer_session(session: Session) -> bool:
        """Check if the session's current person role is customer."""
        return session_person_role(session) == "customer"

    def _build_thread_topper(self, session: Session) -> str:
        """Build metadata header for the first message in a Discord thread."""
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
        """Create or reuse the Discord destination channel or thread for a session."""
        _ = metadata
        if self._client is None:
            raise AdapterError("Discord adapter not started")

        discord_meta = DiscordAdapterMetadata.from_dict(session.get_origin_section("discord"))

        if discord_meta.thread_id is not None:
            return str(discord_meta.thread_id)

        # Team text channels — no thread creation, output goes to the channel directly
        if discord_meta.channel_id is not None and discord_meta.channel_id in self._team_channel_map:
            return str(discord_meta.channel_id)

        # DM-bound personal-assistant sessions — no guild, deliver to the DM channel directly.
        if discord_meta.channel_id is not None and discord_meta.guild_id is None:
            return str(discord_meta.channel_id)

        target_forum_id = self._resolve_target_forum(session)
        if target_forum_id is not None:
            forum = await self._get_channel(target_forum_id)
            if forum is None:
                raise AdapterError(f"Discord forum channel {target_forum_id} not found")
            if not self._is_forum_channel(forum):
                raise AdapterError(f"Discord channel {target_forum_id} is not a Forum Channel")

            topper = self._build_thread_topper(session)
            thread_id, topper_message_id = await self._create_forum_thread(  # type: ignore[attr-defined]
                forum,
                title=title,
                content=topper,
            )
            await db.update_origin_metadata(
                session.session_id,
                "discord",
                {
                    DiscordMetadataField.CHANNEL_ID: target_forum_id,
                    DiscordMetadataField.THREAD_ID: thread_id,
                    DiscordMetadataField.THREAD_TOPPER_MESSAGE_ID: topper_message_id,
                },
            )
            return str(thread_id)

        if discord_meta.channel_id is not None:
            return str(discord_meta.channel_id)

        raise AdapterError("Discord session has no mapped destination channel")

    async def update_channel_title(self, session: Session) -> bool:
        """Rename the Discord thread to match the current session state.

        The display title is derived from session via UiAdapter.display_title
        (universal headless marker + Discord title_body for forum routing).
        Caller does not pass a formatted string.
        """
        discord_meta = DiscordAdapterMetadata.from_dict(session.get_origin_section("discord"))
        if discord_meta.thread_id is None:
            return False
        thread = await self._get_channel(discord_meta.thread_id)
        if thread is None:
            return False
        raw_edit_fn = getattr(thread, "edit", None)
        if raw_edit_fn is None:
            return False
        edit_fn = cast_async_callable(self._require_async_callable, raw_edit_fn, label="Discord thread edit")
        recoverable_errors = recoverable_operation_errors(self._discord)
        title = self.display_title(session)
        try:
            await edit_fn(name=title)
            return True
        except recoverable_errors as exc:
            logger.warning("Failed to rename Discord thread %s: %s", discord_meta.thread_id, exc)
            return False

    async def delete_channel(self, session: Session) -> bool:
        """Delete the Discord thread associated with a session."""
        discord_meta = DiscordAdapterMetadata.from_dict(session.get_origin_section("discord"))
        if discord_meta.thread_id is None:
            return False
        thread = await self._get_channel(discord_meta.thread_id)
        if thread is None:
            return False
        raw_delete_fn = getattr(thread, "delete", None)
        if raw_delete_fn is None:
            return False
        delete_fn = cast_async_callable(self._require_async_callable, raw_delete_fn, label="Discord thread delete")
        recoverable_errors = recoverable_operation_errors(self._discord)
        try:
            await delete_fn()
            return True
        except recoverable_errors as exc:
            logger.warning("Failed to delete Discord thread %s: %s", discord_meta.thread_id, exc)
            return False

    @staticmethod
    def _is_forum_channel(channel: object) -> bool:
        return "forum" in type(channel).__name__.lower()

    # =========================================================================
    # Stale Thread Cleanup
    # =========================================================================

    async def cleanup_stale_resources(self) -> int:
        """Scan Discord forums and clean up orphan/stale threads.

        A help desk's forums are swept on the master alone, which is the one
        computer that hosts desk sessions.
        """
        if self._client is None:
            return 0

        cleaned = 0
        for forum_id in self._get_managed_forum_ids():
            cleaned += await self._cleanup_forum_threads(forum_id, ThreadMatchField.THREAD_ID)
        if teleclaude_config.config.computer.is_master:
            for forums in self._desk_forums.values():
                if forums.customer_sessions is not None:
                    cleaned += await self._cleanup_forum_threads(
                        forums.customer_sessions, ThreadMatchField.THREAD_ID, desk_forum=True
                    )
                if forums.escalations is not None:
                    cleaned += await self._cleanup_forum_threads(
                        forums.escalations, ThreadMatchField.RELAY, desk_forum=True
                    )

        return cleaned

    async def _cleanup_forum_threads(
        self, forum_id: int, match_type: ThreadMatchField, *, desk_forum: bool = False
    ) -> int:
        """Scan a single forum for orphan/stale threads and delete them.

        Collects both active and archived threads, then deletes any
        that have no corresponding active session in the database. A desk
        forum has no launcher thread to spare; a project forum's launcher
        identity must resolve before anything in it is deleted.
        """
        forum = await self._get_channel(forum_id)
        if forum is None or not self._is_forum_channel(forum):
            return 0

        all_threads, conclusive = await gather_forum_threads(forum, self._discord, forum_id=forum_id)
        if not conclusive:
            logger.warning("Skipping Discord thread cleanup for forum %s because discovery is incomplete", forum_id)
            return 0

        launcher_thread_id: int | None = None
        if not desk_forum:
            launcher = await db.get_discord_reflection(session_launcher_key(forum_id))
            launcher_thread_id = launcher.provider_id if launcher is not None else None
            if launcher_thread_id is None:
                logger.warning(
                    "Skipping Discord session cleanup for forum %s because launcher identity is unresolved", forum_id
                )
                return 0

        cleaned = 0
        for thread in all_threads:
            thread_id = self._parse_optional_int(getattr(thread, "id", None))
            if thread_id is None:
                continue

            if thread_id == launcher_thread_id:
                continue

            ownership = await self._thread_ownership(thread_id, match_type)
            if ownership == ThreadOwnership.ACTIVE:
                continue

            recoverable_errors = recoverable_operation_errors(self._discord)
            try:
                delete_fn = cast_async_callable(
                    self._require_async_callable,
                    getattr(thread, "delete", None),
                    label="thread delete",
                )
                await delete_fn()
                cleaned += 1
                logger.info("Deleted orphan Discord thread %s in forum %s", thread_id, forum_id)
            except recoverable_errors as exc:
                logger.warning("Failed to delete thread %s: %s", thread_id, exc)

            await asyncio.sleep(THREAD_CLEANUP_PACING_SECONDS)

        return cleaned

    async def _thread_ownership(self, thread_id: int, match_type: ThreadMatchField) -> ThreadOwnership:
        """Classify a Discord thread's ownership.

        Returns:
            ACTIVE  — thread belongs to a live session, keep it
            CLOSED  — thread belongs to a closed session, safe to delete
            UNKNOWN — no session record found; caller may classify durable thread-side identity
        """
        if match_type == ThreadMatchField.RELAY:
            session = await db.get_session_by_field("relay_channel_id", str(thread_id), include_initializing=True)
            if session is None:
                return ThreadOwnership.UNKNOWN
            return ThreadOwnership.ACTIVE if session.relay_status == ThreadOwnership.ACTIVE else ThreadOwnership.CLOSED

        sessions = await db.get_sessions_by_origin_metadata("discord", "thread_id", thread_id, include_closed=True)
        if not sessions:
            return ThreadOwnership.UNKNOWN
        if any(s.closed_at is None for s in sessions):
            return ThreadOwnership.ACTIVE
        return ThreadOwnership.CLOSED
