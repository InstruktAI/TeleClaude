"""Channel operations mixin for Telegram adapter.

Handles forum topic creation, updating, closing, reopening, deletion,
session-from-topic resolution, and output streaming.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger
from telegram import ForumTopic, Message, Update
from telegram.error import TelegramError

from teleclaude.core.db import db
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.models import ChannelMetadata, PeerInfo, Session
from teleclaude.utils import command_retry

if TYPE_CHECKING:
    from typing import Protocol

    from telegram.ext import ExtBot

    from teleclaude.adapters.qos.output_scheduler import OutputQoSScheduler
    from teleclaude.adapters.telegram.private_handlers import PrivateHandlersMixin

    class _ChannelOperationsHost(Protocol):
        computer_name: str
        _qos_scheduler: OutputQoSScheduler
        _validate_update_for_command: Callable[[Update], bool]
        _send_general_message_with_retry: Callable[
            [int | None, str, str | None, object | None],
            Awaitable[Message],
        ]
        edit_general_message: Callable[..., Awaitable[bool]]
        send_general_message: Callable[..., Awaitable[str]]


logger = get_logger(__name__)

TOPIC_READY_TIMEOUT_S = 5.0


class ChannelOperationsMixin:
    """Mixin providing channel (forum topic) operations for TelegramAdapter.

    Required from host class:
    - bot: ExtBot[None] (property)
    - _ensure_started() -> None
    - _topic_creation_locks: dict[str, asyncio.Lock]
    - _topic_ready_events: dict[int, asyncio.Event]
    - _topic_ready_cache: set[int]
    """

    # Abstract properties - implemented by TelegramAdapter
    @property
    def bot(self) -> ExtBot[None]:
        """Return the Telegram bot instance."""
        raise NotImplementedError

    # Abstract instance variables (declared for type hints)
    computer_name: str
    _qos_scheduler: OutputQoSScheduler
    _topic_creation_locks: dict[str, asyncio.Lock]
    _topic_ready_events: dict[int, asyncio.Event]
    _topic_ready_cache: set[int]

    def _ensure_started(self) -> None:
        """Ensure the adapter is started before operations."""
        raise NotImplementedError

    if TYPE_CHECKING:
        # Provided by UiAdapter base; declared here so pyright resolves it
        # when methods on this mixin call self.display_title(session).
        def display_title(self, session: Session) -> str: ...

    # =========================================================================
    # Channel Operations Implementation
    # =========================================================================

    async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
        """Channel creation is obsolete for the Telegram non-admin adapter.

        Always returns an empty topic_id to signal private-chat-only mode.
        """
        self._ensure_started()
        return ""

    async def _wait_for_topic_ready(self, topic_id: int, title: str) -> None:
        """No-op: forum topics are obsolete."""
        return

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _create_forum_topic_with_retry(self, title: str) -> ForumTopic:
        """Obsolete."""
        raise NotImplementedError("Forum topics are obsolete")

    async def update_channel_title(self, session: Session) -> bool:
        """Rename the Telegram topic. No-op (obsolete)."""
        return True

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _edit_forum_topic_with_retry(self, topic_id: int, title: str) -> None:
        """Obsolete."""
        return

    async def close_channel(self, session: Session) -> bool:
        """Soft-close forum topic. No-op (obsolete)."""
        return True

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _close_forum_topic_with_retry(self, topic_id: int) -> None:
        """Obsolete."""
        return

    async def reopen_channel(self, session: Session) -> bool:
        """Reopen a closed forum topic. No-op (obsolete)."""
        return True

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _reopen_forum_topic_with_retry(self, topic_id: int) -> None:
        """Obsolete."""
        return

    async def delete_channel(self, session: Session) -> bool:
        """Delete forum topic. No-op (obsolete)."""
        return True

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _delete_forum_topic_with_retry(self, topic_id: int) -> None:
        """Obsolete."""
        return

    # =========================================================================
    # Session resolution
    # =========================================================================

    async def _get_session_from_topic(self, update: Update) -> Session | None:
        """Get session from current update (silent - no feedback on failure).

        Returns:
            Session object or None if not found/not authorized
        """
        # Check preconditions
        if not cast("_ChannelOperationsHost", self)._validate_update_for_command(update):
            logger.debug("_get_session_from_topic: invalid update (no user or message)")
            return None

        # Check authorization via identity resolver
        user = update.effective_user
        if not user:
            return None

        identity = get_identity_resolver().resolve(
            "telegram",
            {"user_id": str(user.id), "telegram_user_id": str(user.id)},
        )

        if not identity or not identity.person_name:
            logger.debug("_get_session_from_topic: user %s not authorized", user.id)
            return None

        # Get message (handles both regular and edited messages)
        message = update.effective_message
        if not message:
            return None

        # Try to find session via private chat first
        session = await cast("PrivateHandlersMixin", self)._find_private_session(str(user.id))
        if session:
            return session

        # Fallback: check topic_id (legacy or supergroup)
        thread_id = message.message_thread_id
        if not thread_id:
            return None

        sessions = await db.get_sessions_by_origin_metadata(
            "telegram",
            "topic_id",
            thread_id,
            include_closed=True,
        )

        if not sessions:
            logger.debug("_get_session_from_topic: no session found for topic_id %s", thread_id)
            return None

        session = sessions[0]
        # TODO(core): keep treating "closing" as terminal here until lifecycle transitions
        # are strictly enforced at query-time across all adapters.
        if session.closed_at or session.lifecycle_status in {"closed", "closing"}:
            logger.debug(
                "_get_session_from_topic: topic_id %s maps to terminal session %s",
                thread_id,
                session.session_id,
            )
            return None

        return session

    async def _require_session_from_topic(self, update: Update) -> Session | None:
        """Get session from update, with error feedback if not found.

        Use this for commands that MUST have a session context.
        Sends error message to user if session not found.

        Returns:
            Session object or None (after sending error feedback)
        """
        session = await self._get_session_from_topic(update)
        if session:
            return session

        # Determine the reason and give feedback
        message = update.effective_message
        if not message:
            return None  # Can't send feedback without a message

        thread_id = message.message_thread_id

        if not thread_id:
            # Command used outside of a session context
            error_msg = "❌ This command must be used in a session."
            logger.warning(
                "Command used outside session context by user %s",
                update.effective_user.id if update.effective_user else "unknown",
            )
        else:
            # Session not found for this topic/chat
            error_msg = "❌ No session found. The session may have ended."
            logger.warning("No session found for thread_id %s", thread_id)

        try:
            # Fallback to direct reply if thread_id is missing or topic failed
            await message.reply_text(error_msg)
        except (TelegramError, TimeoutError, ConnectionError) as error:
            logger.error("Failed to send session error feedback: %s", error)

        return None

    # =========================================================================
    # Peer discovery and output streaming
    # =========================================================================

    async def discover_peers(self) -> list[PeerInfo]:
        """Discover peers via Telegram adapter (not supported)."""
        return []

    async def create_topic(self, title: str) -> ForumTopic:
        """Create a new forum topic (obsolete)."""
        raise NotImplementedError("Forum topics are obsolete")

    async def get_all_topics(self) -> list[object]:
        """Get all forum topics (obsolete)."""
        return []

    async def send_message_to_topic(
        self, topic_id: int | None, text: str, parse_mode: str | None = "Markdown"
    ) -> Message:
        """Send a message to a specific topic or private chat."""
        self._ensure_started()
        # In non-admin mode, we always reply to the user if no topic_id
        raise NotImplementedError("Use send_message instead")

    async def poll_output_stream(
        self,
        session: Session,
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        """Poll for output chunks (not implemented for Telegram)."""
        raise NotImplementedError("Telegram adapter does not support poll_output_stream")
        # This yield is unreachable but satisfies mypy's async generator requirements
        yield ""

    def drop_pending_output(self, session_id: str) -> int:
        """Drop pending QoS payloads for a session to prevent stale output after turn break."""
        return self._qos_scheduler.drop_pending(session_id)
