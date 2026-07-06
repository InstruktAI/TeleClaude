"""Channel operations mixin for Telegram adapter.

Handles forum topic creation, updating, closing, reopening, deletion,
session-from-topic resolution, and output streaming.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger
from telegram import Message, Update
from telegram.error import TelegramError

from teleclaude.core.db import db
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.models import PeerInfo, Session

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

    # =========================================================================
    # Channel Operations Implementation
    # =========================================================================

    async def _wait_for_topic_ready(self, topic_id: int, title: str) -> None:
        """No-op: forum topics are obsolete."""
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

        # Give feedback regardless of thread_id presence — private chats never have a thread_id
        message = update.effective_message
        if not message:
            return None  # Can't send feedback without a message

        thread_id = message.message_thread_id
        if thread_id:
            logger.warning("No session found for thread_id %s", thread_id)
        else:
            logger.warning(
                "No session found for user %s (private chat)",
                update.effective_user.id if update.effective_user else "unknown",
            )

        try:
            await message.reply_text("❌ No active session found. The session may have ended.")
        except (TelegramError, TimeoutError, ConnectionError) as error:
            logger.error("Failed to send session error feedback: %s", error)

        return None

    # =========================================================================
    # Peer discovery and output streaming
    # =========================================================================

    async def discover_peers(self) -> list[PeerInfo]:
        """Discover peers via Telegram adapter (not supported)."""
        return []

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
