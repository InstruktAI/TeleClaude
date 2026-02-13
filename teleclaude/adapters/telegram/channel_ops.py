"""Channel operations mixin for Telegram adapter.

Handles forum topic creation, updating, closing, reopening, and deletion.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from telegram import ForumTopic
from telegram.error import TelegramError

from teleclaude.core.db import db
from teleclaude.core.models import ChannelMetadata, Session
from teleclaude.utils import command_retry

from ..base_adapter import AdapterError

if TYPE_CHECKING:
    from telegram.ext import ExtBot

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
    def bot(self) -> "ExtBot[None]":
        """Return the Telegram bot instance."""
        raise NotImplementedError

    # Abstract instance variables (declared for type hints)
    supergroup_id: int
    _topic_creation_locks: dict[str, asyncio.Lock]
    _topic_ready_events: dict[int, asyncio.Event]
    _topic_ready_cache: set[int]
    _failed_delete_attempts: dict[int, float]

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
                        session_id[:8],
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
        except asyncio.TimeoutError:
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
            raise AdapterError("Session missing telegram topic_id")

        try:
            await self._close_forum_topic_with_retry(topic_id)
            logger.info("Closed topic %s for session %s", topic_id, session.session_id[:8])
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
            logger.info("Reopened topic %s for session %s", topic_id, session.session_id[:8])
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
            raise AdapterError("Session missing telegram topic_id")

        try:
            await self._delete_forum_topic_with_retry(topic_id)
            logger.info("Deleted topic %s for session %s", topic_id, session.session_id[:8])
            return True
        except TelegramError as e:
            logger.warning("Failed to delete topic %s: %s", topic_id, e)
            return False

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _delete_forum_topic_with_retry(self, topic_id: int) -> None:
        """Internal method with retry logic for deleting forum topics."""
        await self.bot.delete_forum_topic(chat_id=self.supergroup_id, message_thread_id=topic_id)

    async def _delete_orphan_topic(self, topic_id: int) -> None:
        """Delete a topic that no longer maps to a session.

        Suppresses repeated attempts for invalid topics to prevent API storms.
        """
        # Check suppression
        now = time.time()
        last_attempt = self._failed_delete_attempts.get(topic_id, 0.0)
        # 5 minute cooldown for failed deletes
        if now - last_attempt < 300:
            logger.debug("Suppressing delete for invalid/failed topic %s (cooldown active)", topic_id)
            return

        try:
            await self._delete_forum_topic_with_retry(topic_id)
            logger.info("Deleted orphan topic %s (no session)", topic_id)
            # Success - clear any failure record
            self._failed_delete_attempts.pop(topic_id, None)
        except TelegramError as e:
            # Mark as failed to suppress immediate retries
            self._failed_delete_attempts[topic_id] = now

            # Special handling for "invalid" or "not found" which implies it's already gone
            msg = str(e).lower()
            if "topic_id_invalid" in msg or "topic not found" in msg:
                logger.info(
                    "Orphan topic %s already invalid/gone; suppressing future deletes for 5m: %s",
                    topic_id,
                    e,
                )
            else:
                logger.warning("Failed to delete orphan topic %s: %s", topic_id, e)
