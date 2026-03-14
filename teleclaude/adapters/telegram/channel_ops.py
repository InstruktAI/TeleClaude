"""Channel operations mixin for Telegram adapter.

Handles forum topic creation, updating, closing, reopening, deletion,
session-from-topic resolution, menu message management, and output streaming.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from telegram import ForumTopic, Message, Update
from telegram.error import BadRequest, TelegramError

from teleclaude.core.db import db
from teleclaude.core.models import ChannelMetadata, MessageMetadata, PeerInfo, Session
from teleclaude.utils import command_retry

from ..base_adapter import AdapterError

if TYPE_CHECKING:
    from telegram import InlineKeyboardMarkup
    from telegram.ext import ExtBot

    from teleclaude.adapters.qos.output_scheduler import OutputQoSScheduler

logger = get_logger(__name__)

TOPIC_READY_TIMEOUT_S = 5.0


class ChannelOperationsMixin:
    """Mixin providing channel (forum topic) operations for TelegramAdapter.

    Required from host class:
    - bot: ExtBot[None] (property)
    - supergroup_id: int (instance variable)
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
    supergroup_id: int
    _topic_creation_locks: dict[str, asyncio.Lock]
    _topic_ready_events: dict[int, asyncio.Event]
    _topic_ready_cache: set[int]

    def _ensure_started(self) -> None:
        """Ensure the adapter is started before operations."""
        raise NotImplementedError

    # =========================================================================
    # Channel Operations Implementation
    # =========================================================================

    async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
        """Create a new topic in the supergroup.

        Uses per-session lock to prevent duplicate topic creation on concurrent calls
        or retries. This is critical because createForumTopic is NOT idempotent -
        each call creates a new topic even with identical title.
        """
        self._ensure_started()
        session_id = session.session_id

        # Get or create lock for this session_id
        if session_id not in self._topic_creation_locks:
            self._topic_creation_locks[session_id] = asyncio.Lock()

        async with self._topic_creation_locks[session_id]:
            # Check if session already has a topic_id (from a previous successful call)
            # Re-fetch session inside lock to get latest metadata
            fresh_session = await db.get_session(session_id)
            if fresh_session:
                existing_topic_id = fresh_session.get_metadata().get_ui().get_telegram().topic_id
                if existing_topic_id:
                    logger.warning(
                        "Session %s already has topic_id %s, returning existing (prevented duplicate)",
                        session_id,
                        existing_topic_id,
                    )
                    return str(existing_topic_id)

            # Create topic (only one concurrent call per session_id can reach here)
            topic = await self._create_forum_topic_with_retry(title)

            topic_id = topic.message_thread_id
            logger.info("Created topic: %s (ID: %s)", title, topic_id)

            # NOTE: We don't wait for forum_topic_created here anymore.
            # Channel creation is fire-and-forget, and send_message will wait
            # for topic readiness when it actually tries to send.

            # Persist topic_id inside the lock so concurrent callers see it.
            updated_session = await db.get_session(session_id)
            if updated_session:
                # Use new accessor chain to set topic_id
                telegram_meta = updated_session.get_metadata().get_ui().get_telegram()
                telegram_meta.topic_id = int(topic_id)
                await db.update_session(session_id, adapter_metadata=updated_session.adapter_metadata)

            return str(topic_id)

    async def _wait_for_topic_ready(self, topic_id: int, title: str) -> None:
        """Wait for forum_topic_created event for a topic."""
        if topic_id in self._topic_ready_cache:
            return

        event = self._topic_ready_events.get(topic_id)
        if not event:
            event = asyncio.Event()
            self._topic_ready_events[topic_id] = event

        try:
            await asyncio.wait_for(event.wait(), timeout=TOPIC_READY_TIMEOUT_S)
        except TimeoutError:
            self._topic_ready_events.pop(topic_id, None)
            logger.warning(
                "Topic %s (ID: %s) did not emit forum_topic_created within %.1fs; proceeding anyway",
                title,
                topic_id,
                TOPIC_READY_TIMEOUT_S,
            )
            self._topic_ready_cache.add(topic_id)
            return

        self._topic_ready_cache.add(topic_id)

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _create_forum_topic_with_retry(self, title: str) -> ForumTopic:
        """Internal method with retry logic for creating forum topics."""
        return await self.bot.create_forum_topic(chat_id=self.supergroup_id, name=title)

    async def update_channel_title(self, session: Session, title: str) -> bool:
        """Update topic title."""
        self._ensure_started()

        topic_id = session.get_metadata().get_ui().get_telegram().topic_id
        if topic_id is None:
            raise AdapterError("Session missing telegram topic_id")

        try:
            await self._edit_forum_topic_with_retry(topic_id, title)
            return True
        except TelegramError as e:
            logger.error("Failed to update topic title: %s", e)
            return False

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _edit_forum_topic_with_retry(self, topic_id: int, title: str) -> None:
        """Internal method with retry logic for editing forum topics."""
        await self.bot.edit_forum_topic(chat_id=self.supergroup_id, message_thread_id=topic_id, name=title)

    async def close_channel(self, session: Session) -> bool:
        """Soft-close forum topic (can be reopened)."""
        self._ensure_started()

        topic_id = session.get_metadata().get_ui().get_telegram().topic_id
        if topic_id is None:
            logger.debug(
                "Skipping Telegram close_channel for session %s: topic_id missing",
                session.session_id,
            )
            return False

        try:
            await self._close_forum_topic_with_retry(topic_id)
            logger.info("Closed topic %s for session %s", topic_id, session.session_id)
            return True
        except TelegramError as e:
            logger.warning("Failed to close topic %s: %s", topic_id, e)
            return False

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _close_forum_topic_with_retry(self, topic_id: int) -> None:
        """Internal method with retry logic for closing forum topics."""
        await self.bot.close_forum_topic(chat_id=self.supergroup_id, message_thread_id=topic_id)

    async def reopen_channel(self, session: Session) -> bool:
        """Reopen a closed forum topic."""
        self._ensure_started()

        topic_id = session.get_metadata().get_ui().get_telegram().topic_id
        if topic_id is None:
            raise AdapterError("Session missing telegram topic_id")

        try:
            await self._reopen_forum_topic_with_retry(topic_id)
            logger.info("Reopened topic %s for session %s", topic_id, session.session_id)
            return True
        except TelegramError as e:
            logger.warning("Failed to reopen topic %s: %s", topic_id, e)
            return False

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _reopen_forum_topic_with_retry(self, topic_id: int) -> None:
        """Internal method with retry logic for reopening forum topics."""
        await self.bot.reopen_forum_topic(chat_id=self.supergroup_id, message_thread_id=topic_id)

    async def delete_channel(self, session: Session) -> bool:
        """Delete forum topic (permanent)."""
        self._ensure_started()

        topic_id = session.get_metadata().get_ui().get_telegram().topic_id
        if topic_id is None:
            logger.debug(
                "Skipping Telegram delete_channel for session %s: topic_id missing",
                session.session_id,
            )
            return False

        try:
            await self._delete_forum_topic_with_retry(topic_id)
            logger.info("Deleted topic %s for session %s", topic_id, session.session_id)
        except BadRequest as e:
            if "topic_id_invalid" in str(e).lower():
                # Topic was already deleted (e.g. by a prior cleanup pass). Treat as success.
                logger.info(
                    "Topic %s for session %s already deleted (Topic_id_invalid); treating as success",
                    topic_id,
                    session.session_id,
                )
            else:
                logger.warning("Failed to delete topic %s: %s", topic_id, e)
                return False
        except TelegramError as e:
            logger.warning("Failed to delete topic %s: %s", topic_id, e)
            return False

        # Clear persisted topic_id so maintenance replay does not retry this session.
        fresh_session = await db.get_session(session.session_id)
        if fresh_session:
            telegram_meta = fresh_session.get_metadata().get_ui().get_telegram()
            telegram_meta.topic_id = None
            await db.update_session(session.session_id, adapter_metadata=fresh_session.adapter_metadata)
            logger.debug("Cleared topic_id for session %s", session.session_id)

        return True

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _delete_forum_topic_with_retry(self, topic_id: int) -> None:
        """Internal method with retry logic for deleting forum topics."""
        await self.bot.delete_forum_topic(chat_id=self.supergroup_id, message_thread_id=topic_id)

    # =========================================================================
    # TYPE_CHECKING stubs for methods provided by other mixins
    # =========================================================================

    if TYPE_CHECKING:
        user_whitelist: set[int]
        computer_name: str
        _qos_scheduler: OutputQoSScheduler

        def _validate_update_for_command(self, update: Update) -> bool: ...

        def _build_heartbeat_keyboard(self, bot_username: str) -> InlineKeyboardMarkup: ...

        async def edit_general_message(
            self, message_id: str, text: str, *, metadata: MessageMetadata | None = None
        ) -> bool: ...

        async def send_general_message(self, text: str, *, metadata: MessageMetadata | None = None) -> str: ...

        async def _send_general_message_with_retry(
            self,
            thread_id: int | None,
            text: str,
            parse_mode: str | None,
            reply_markup: object,
        ) -> Message: ...

    # =========================================================================
    # Session-from-topic resolution
    # =========================================================================

    async def _get_session_from_topic(self, update: Update) -> Session | None:
        """Get session from current topic (silent - no feedback on failure).

        Returns:
            Session object or None if not found/not authorized
        """
        # Check preconditions
        if not self._validate_update_for_command(update):
            logger.debug("_get_session_from_topic: invalid update (no user or message)")
            return None

        # Check authorization
        user = update.effective_user
        if not user or user.id not in self.user_whitelist:
            logger.debug("_get_session_from_topic: user %s not in whitelist", user.id if user else None)
            return None

        # Get message (handles both regular and edited messages)
        message = update.effective_message
        if not message or not message.message_thread_id:
            logger.debug("_get_session_from_topic: no message_thread_id")
            return None

        thread_id = message.message_thread_id

        sessions = await db.get_sessions_by_adapter_metadata(
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
        """Get session from topic, with error feedback if not found.

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
            # Command used outside of a session topic
            error_msg = "❌ This command must be used in a session topic, not in General."
            logger.warning(
                "Command used outside session topic by user %s",
                update.effective_user.id if update.effective_user else "unknown",
            )
        else:
            # Session not found for this topic
            error_msg = "❌ No session found for this topic. The session may have ended."
            logger.warning("No session found for topic_id %s", thread_id)

        try:
            await self._send_general_message_with_retry(
                thread_id,
                error_msg,
                None,
                None,
            )
        except Exception as e:
            logger.error("Failed to send session error feedback: %s", e)

        return None

    # =========================================================================
    # Menu message management
    # =========================================================================

    async def _send_or_update_menu_message(self) -> None:
        """Send or update the menu message in the general topic.

        On daemon startup, checks for an existing menu message ID in system_settings.
        If found, attempts to edit it. If edit fails (message deleted), creates a new one.
        If not found, creates a new message.

        The menu message shows a registry line with the heartbeat keyboard.
        """
        setting_key = f"menu_message_id:{self.computer_name}"
        bot_info = await self.bot.get_me()
        bot_username = bot_info.username or "unknown"

        # Build menu content (parse_mode=None to avoid MarkdownV2 escaping issues)
        reply_markup = self._build_heartbeat_keyboard(bot_username)
        text = f"[REGISTRY] {self.computer_name} last seen at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        metadata = MessageMetadata(reply_markup=reply_markup, parse_mode=None)

        # Check for existing message ID
        existing_msg_id = await db.get_system_setting(setting_key)

        if existing_msg_id:
            # Try to edit existing message
            success = await self.edit_general_message(existing_msg_id, text, metadata=metadata)
            if success:
                logger.info("Updated menu message %s in general topic", existing_msg_id)
                return
            # Edit failed (message deleted), fall through to create new

        # Create new message
        new_msg_id = await self.send_general_message(text, metadata=metadata)
        await db.set_system_setting(setting_key, new_msg_id)
        logger.info("Created new menu message %s in general topic", new_msg_id)

    # =========================================================================
    # Peer discovery and output streaming
    # =========================================================================

    async def discover_peers(self) -> list[PeerInfo]:
        """Discover peers via Telegram adapter.

        NOTE: Due to Telegram Bot API restrictions, bots cannot see messages
        from other bots, so this adapter does not support peer discovery.

        Actual peer discovery is handled by other adapters (e.g., RedisTransport)
        that support bot-to-bot communication.

        Returns:
            Empty list (Telegram doesn't support bot-to-bot discovery)
        """
        return []

    async def create_topic(self, title: str) -> ForumTopic:
        """Create a new forum topic and return the topic object."""
        self._ensure_started()
        topic = await self._create_forum_topic_with_retry(title)
        logger.info("Created topic: %s (ID: %s)", title, topic.message_thread_id)
        return topic

    async def get_all_topics(self) -> list[object]:
        """Get all forum topics in the supergroup.

        Note: Telegram Bot API doesn't have a direct method to list all forum topics.
        This implementation uses a workaround by searching through recent updates.
        For now, we return empty list and rely on database persistence instead.
        """
        self._ensure_started()

        return []

    async def send_message_to_topic(
        self, topic_id: int | None, text: str, parse_mode: str | None = "Markdown"
    ) -> Message:
        """Send a message to a specific topic or General topic.

        Args:
            topic_id: Topic ID (message_thread_id). Use None for General topic.
            text: Message text
            parse_mode: Parse mode (Markdown, HTML, or None for plain text)

        Returns:
            Message object
        """
        self._ensure_started()
        if topic_id is not None:
            message = await self._send_general_message_with_retry(
                topic_id,
                text,
                parse_mode,
                None,
            )
        else:
            message = await self._send_general_message_with_retry(
                None,
                text,
                parse_mode,
                None,
            )

        return message

    async def poll_output_stream(
        self,
        session: Session,
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        """Poll for output chunks (not implemented for Telegram).

        Telegram doesn't support bidirectional streaming like Redis.
        This method is only implemented in RedisTransport.

        Args:
            session: Session object
            timeout: Max seconds to wait

        Raises:
            NotImplementedError: Telegram doesn't support output streaming
        """
        raise NotImplementedError("Telegram adapter does not support poll_output_stream")
        # This yield is unreachable but satisfies mypy's async generator requirements
        yield ""  # pylint: disable=unreachable

    def drop_pending_output(self, session_id: str) -> int:
        """Drop pending QoS payloads for a session to prevent stale output after turn break."""
        return self._qos_scheduler.drop_pending(session_id)
