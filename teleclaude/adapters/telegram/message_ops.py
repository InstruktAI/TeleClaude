"""Message operations mixin for Telegram adapter.

Handles sending, editing, and deleting messages in Telegram topics.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from instrukt_ai_logging import get_logger
from telegram import (
    ForceReply,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut

from teleclaude.core.models import MessageMetadata
from teleclaude.utils import command_retry
from teleclaude.utils.markdown import _required_markdown_closers, truncate_markdown_v2

if TYPE_CHECKING:
    from telegram.ext import ExtBot

    from teleclaude.core.models import Session

logger = get_logger(__name__)


@dataclass
class EditContext:
    """Mutable context for message edits during rate limit retries.

    Allows the retry loop to always use the latest text, even if
    edit_message() was called again while waiting out a rate limit.
    """

    message_id: str
    text: str
    reply_markup: Optional[object] = None
    parse_mode: Optional[str] = None


class MessageOperationsMixin:
    """Mixin providing message operations for TelegramAdapter.

    Required from host class:
    - bot: ExtBot[None] (property)
    - supergroup_id: int (instance variable)
    - _ensure_started() -> None
    - _pending_edits: dict[str, EditContext]

    Required from ChannelOperationsMixin (via MRO):
    - _wait_for_topic_ready(topic_id: int, title: str) -> None
    """

    # Abstract properties - implemented by TelegramAdapter
    @property
    def bot(self) -> "ExtBot[None]":
        """Return the Telegram bot instance."""
        raise NotImplementedError

    # Abstract instance variables (declared for type hints)
    supergroup_id: int
    _pending_edits: dict[str, EditContext]

    def _ensure_started(self) -> None:
        """Ensure the adapter is started before operations."""
        raise NotImplementedError

    if TYPE_CHECKING:
        # Type stub for method provided by ChannelOperationsMixin via MRO
        async def _wait_for_topic_ready(self, topic_id: int, title: str) -> None:
            """Wait for forum topic to be ready (from ChannelOperationsMixin)."""
            ...

    # =========================================================================
    # Message Operations Implementation
    # =========================================================================

    def _truncate_for_platform(self, text: str, parse_mode: Optional[str], max_chars: int) -> str:
        """Truncate text to Telegram limits while preserving MarkdownV2 validity."""
        if len(text) <= max_chars:
            return text

        if parse_mode == "MarkdownV2":
            # Keep the leading portion and balance markdown entities.
            return truncate_markdown_v2(text, max_chars=max_chars, suffix="\n\n…")

        suffix = "\n[...truncated...]"
        if len(suffix) >= max_chars:
            return suffix[:max_chars]
        return f"{text[: max_chars - len(suffix)]}{suffix}"

    async def send_message(
        self,
        session: "Session",
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> str:
        """Send message to session's topic with automatic retry on rate limits and network errors."""
        self._ensure_started()
        metadata = metadata or MessageMetadata()

        # Gracefully skip if channel not ready yet (fire-and-forget channel creation)
        if not session.adapter_metadata or not session.adapter_metadata.telegram:
            logger.debug("send_message: skipping, telegram metadata not ready for session %s", session.session_id[:8])
            return ""
        topic_id = session.adapter_metadata.telegram.topic_id
        if not topic_id:
            logger.debug("send_message: skipping, topic_id not ready for session %s", session.session_id[:8])
            return ""

        # Extract reply_markup and parse_mode from metadata
        reply_markup = metadata.reply_markup
        parse_mode = metadata.parse_mode

        # Truncation is a platform constraint (Telegram max 4096)
        from teleclaude.constants import UI_MESSAGE_MAX_CHARS

        text = self._truncate_for_platform(text, parse_mode, UI_MESSAGE_MAX_CHARS)

        # Best-effort wait for topic readiness to avoid "thread not found" races.
        await self._wait_for_topic_ready(topic_id, session.title)

        # Send message with retry decorator handling errors
        # Note: we use MarkdownV2 by default for rich agent output
        message = await self._send_message_with_retry(topic_id, text, reply_markup, parse_mode)
        return str(message.message_id)

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _send_message_with_retry(
        self,
        topic_id: int,
        formatted_text: str,
        reply_markup: object,
        parse_mode: Optional[str],
    ) -> Message:
        """Internal method with retry logic for sending messages.

        guard: allow-string-compare
        """
        # Type guard for reply_markup
        if reply_markup is not None and not isinstance(
            reply_markup,
            (
                InlineKeyboardMarkup,
                ReplyKeyboardMarkup,
                ReplyKeyboardRemove,
                ForceReply,
            ),
        ):
            reply_markup = None
        try:
            return await self.bot.send_message(
                chat_id=self.supergroup_id,
                message_thread_id=topic_id,
                text=formatted_text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        except Exception as exc:
            if "message thread not found" in str(exc).lower():
                logger.warning("Topic %s not ready yet; retrying send", topic_id)
                raise TimeoutError("message thread not found") from exc
            raise

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _send_document_with_retry(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        chat_id: int,
        message_thread_id: int,
        file_path: str,
        filename: str,
        caption: Optional[str] = None,
    ) -> Message:
        """Internal method with retry logic for sending documents.

        guard: allow-string-compare
        """
        with open(file_path, "rb") as f:
            try:
                return await self.bot.send_document(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    document=f,
                    filename=filename,
                    caption=caption,
                    write_timeout=15.0,
                    read_timeout=15.0,
                )
            except Exception as exc:
                if "message thread not found" in str(exc).lower():
                    logger.warning("Topic %s not ready yet; retrying document send", message_thread_id)
                    raise TimeoutError("message thread not found") from exc
                raise

    async def edit_message(
        self, session: "Session", message_id: str, text: str, *, metadata: MessageMetadata | None = None
    ) -> bool:
        """Edit an existing message with automatic retry on rate limits and network errors.

        Uses mutable EditContext to prevent stale data during retries:
        - If edit already pending: updates context with latest text (prevents stale timestamps)
        - Otherwise: creates new context and starts retry flow

        Retry logic (via @command_retry decorator on _edit_message_with_retry):
        - Rate limits (RetryAfter): Uses Telegram's suggested delay, keeps retrying until 60s timeout

        guard: allow-string-compare
        """
        self._ensure_started()
        metadata = metadata or MessageMetadata()

        # CRITICAL: Handle None message_id (happens during daemon restart)
        if not message_id:
            logger.warning(
                "edit_message called with None message_id for session %s, ignoring",
                session.session_id[:8],
            )
            return False

        # Extract reply_markup + parse_mode from metadata
        reply_markup = metadata.reply_markup
        parse_mode = metadata.parse_mode

        # Apply the same platform-safe truncation rules used for send_message.
        from teleclaude.constants import UI_MESSAGE_MAX_CHARS

        text = self._truncate_for_platform(text, parse_mode, UI_MESSAGE_MAX_CHARS)

        # Platform-specific optimization: if an edit is already pending for this message,
        # just update the existing context with the latest text. The already-running
        # retry loop will use this updated text on its next attempt.
        if message_id in self._pending_edits:
            existing_ctx = self._pending_edits[message_id]
            existing_ctx.text = text
            existing_ctx.reply_markup = reply_markup
            existing_ctx.parse_mode = parse_mode
            logger.trace(
                "[TELEGRAM %s] Updated pending edit for message %s with latest content",
                session.session_id[:8],
                message_id,
            )
            return True

        # Create new edit context (mutable)
        ctx = EditContext(
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        self._pending_edits[message_id] = ctx

        try:
            start_time = time.time()
            logger.trace("[TELEGRAM %s] Starting edit_message API call", session.session_id[:8])
            await self._edit_message_with_retry(session, ctx)
            elapsed = time.time() - start_time
            logger.debug(
                "[TELEGRAM %s] edit_message completed in %.2fs",
                session.session_id[:8],
                elapsed,
            )
            return True
        except RetryAfter as e:
            logger.debug(
                "[TELEGRAM %s] Rate limited, edit_message deferred: %s",
                session.session_id[:8],
                e,
            )
            # Keep output_message_id so we can retry on next update without creating new messages.
            return True
        except BadRequest as e:
            # "Message is not modified" is benign - message exists, just unchanged
            # Return True to prevent clearing output_message_id (which would cause new messages)
            if "message is not modified" in str(e).lower():
                logger.trace(
                    "[TELEGRAM %s] Message not modified (content unchanged)",
                    session.session_id[:8],
                )
                return True
            if "can't parse entities" in str(e).lower():
                fence_count = text.count("```")
                closers = _required_markdown_closers(text)
                logger.error(
                    "[TELEGRAM %s] Markdown parse diagnostics: len=%d parse_mode=%s fences=%d needs_closers=%s suffix=%r",
                    session.session_id[:8],
                    len(text),
                    parse_mode,
                    fence_count,
                    bool(closers),
                    text[-40:],
                )
            # Other BadRequest errors (e.g., "Message to edit not found") are real failures
            logger.error("[TELEGRAM %s] edit_message failed: %s", session.session_id[:8], e)
            return False
        except Exception as e:
            logger.error(
                "[TELEGRAM %s] edit_message failed after retries: %s",
                session.session_id[:8],
                e,
            )
            return False
        finally:
            # Remove from pending edits regardless of outcome
            self._pending_edits.pop(message_id, None)

    @command_retry(max_retries=3, max_timeout=60.0)
    async def _edit_message_with_retry(self, _session: "Session", ctx: EditContext) -> None:
        """Internal method with retry logic for editing messages.

        Reads from mutable EditContext - always uses latest data even if updated during retry wait.
        """
        # Type guard for reply_markup (edits only support InlineKeyboardMarkup)
        markup = ctx.reply_markup
        if markup is not None and not isinstance(markup, InlineKeyboardMarkup):
            markup = None
        await self.bot.edit_message_text(
            chat_id=self.supergroup_id,
            message_id=int(ctx.message_id),
            text=ctx.text,  # ← Read latest text from mutable context
            parse_mode=ctx.parse_mode,
            reply_markup=markup,
        )

    async def delete_message(self, session: "Session", message_id: str) -> bool:
        """Delete a message in the session's topic."""
        self._ensure_started()

        try:
            logger.debug(
                "[TELEGRAM %s] delete_message: chat_id=%s message_id=%s",
                session.session_id[:8],
                self.supergroup_id,
                message_id,
            )
            await self._delete_message_with_retry(int(message_id))
            logger.debug("[TELEGRAM %s] delete_message: SUCCESS message_id=%s", session.session_id[:8], message_id)
            return True
        except BadRequest as e:
            logger.warning("Failed to delete message %s: %s", message_id, e)
            return False
        except RetryAfter as e:
            logger.debug("Rate limited deleting message %s: %s", message_id, e)
            return False
        except (NetworkError, TimedOut, ConnectionError, TimeoutError) as e:
            logger.error("Failed to delete message %s after retries: %s", message_id, e)
            return False
        except Exception as e:
            logger.error("Failed to delete message %s: %s", message_id, e)
            return False

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _delete_message_with_retry(self, message_id: int) -> None:
        """Delete message with retry logic."""
        await self.bot.delete_message(chat_id=self.supergroup_id, message_id=message_id)

    async def send_file(
        self,
        session: "Session",
        file_path: str,
        *,
        caption: str | None = None,
        metadata: MessageMetadata | None = None,  # noqa: ARG002 - Required by interface
    ) -> str:
        """Send file to session's topic."""
        self._ensure_started()

        # Gracefully skip if channel not ready yet (fire-and-forget channel creation)
        if not session.adapter_metadata or not session.adapter_metadata.telegram:
            logger.debug("send_file: skipping, telegram metadata not ready for session %s", session.session_id[:8])
            return ""
        topic_id = session.adapter_metadata.telegram.topic_id
        if not topic_id:
            logger.debug("send_file: skipping, topic_id not ready for session %s", session.session_id[:8])
            return ""

        with open(file_path, "rb") as f:
            message = await self.bot.send_document(
                chat_id=self.supergroup_id,
                message_thread_id=topic_id,
                document=f,
                caption=caption,
            )

        return str(message.message_id)

    async def send_general_message(self, text: str, *, metadata: MessageMetadata | None = None) -> str:
        """Send message to Telegram supergroup general topic."""
        self._ensure_started()
        metadata = metadata or MessageMetadata()

        message_thread_id = metadata.message_thread_id
        parse_mode = metadata.parse_mode

        result = await self.bot.send_message(
            chat_id=self.supergroup_id,
            message_thread_id=message_thread_id,
            text=text,
            parse_mode=parse_mode,
        )
        return str(result.message_id)
