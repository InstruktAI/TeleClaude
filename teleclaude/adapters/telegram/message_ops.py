"""Message operations mixin for Telegram adapter.

Handles sending, editing, and deleting messages in Telegram topics.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from telegram import ForceReply, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.error import BadRequest, NetworkError, RetryAfter, TelegramError, TimedOut

from teleclaude.constants import TELEGRAM_MAX_MESSAGE_BYTES, UI_MESSAGE_MAX_CHARS
from teleclaude.core.delivery import Destination
from teleclaude.core.models import MessageMetadata
from teleclaude.utils import command_retry
from teleclaude.utils.markdown import (
    _required_markdown_closers_from_state,
    escape_markdown_v2,
    scan_markdown_v2_state,
    truncate_markdown_v2_by_bytes,
)

if TYPE_CHECKING:
    from telegram.ext import ExtBot

logger = get_logger(__name__)


@dataclass
class EditContext:
    """Mutable context for message edits during rate limit retries.

    Allows the retry loop to always use the latest text, even if
    edit_message() was called again while waiting out a rate limit.
    """

    message_id: str
    text: str
    reply_markup: object | None = None
    parse_mode: str | None = None


@dataclass(frozen=True)
class EditAttempt:
    """Immutable edit request details shared across helper methods."""

    session_id: str
    message_id: str
    text: str
    reply_markup: object | None
    parse_mode: str | None
    content_hash: str


class MessageOperationsMixin:
    """Mixin providing message operations for TelegramAdapter.

    Required from host class:
    - bot: ExtBot[None] (property)
    - supergroup_id: int (instance variable)
    - _ensure_started() -> None
    - _pending_edits: dict[str, EditContext]
    - _last_edit_hash: dict[str, str]

    Required from ChannelOperationsMixin (via MRO):
    - _wait_for_topic_ready(topic_id: int, title: str) -> None
    """

    # Abstract properties - implemented by TelegramAdapter
    @property
    def bot(self) -> ExtBot[None]:
        """Return the Telegram bot instance."""
        raise NotImplementedError

    # Abstract instance variables (declared for type hints)
    supergroup_id: int
    _pending_edits: dict[str, EditContext]
    _last_edit_hash: dict[str, str]

    if TYPE_CHECKING:
        _wait_for_topic_ready: Callable[[int, str], Awaitable[None]]

    def _ensure_started(self) -> None:
        """Ensure the adapter is started before operations."""
        raise NotImplementedError

    # =========================================================================
    # Message Operations Implementation
    # =========================================================================

    @staticmethod
    def _content_hash(text: str, parse_mode: str | None, reply_markup: object | None) -> str:
        """Fast content fingerprint for skipping no-op edits."""
        h = hashlib.sha256(text.encode())
        if parse_mode:
            h.update(parse_mode.encode())
        if reply_markup:
            h.update(str(reply_markup).encode())
        return h.hexdigest()

    def _truncate_for_platform(self, text: str, parse_mode: str | None, max_chars: int) -> str:
        """Last-mile safety net: enforce Telegram API byte/char limit.

        Upstream code (ui_adapter) fits content within a char budget.
        This method catches overflow from MarkdownV2 escaping or
        multi-byte Unicode that inflates byte count beyond the API limit.
        """
        if parse_mode == "MarkdownV2":
            byte_size = len(text.encode("utf-8"))
            if byte_size <= TELEGRAM_MAX_MESSAGE_BYTES:
                return text
            logger.warning(
                "Platform truncation fired: %d bytes > %d limit (chars=%d)",
                byte_size,
                TELEGRAM_MAX_MESSAGE_BYTES,
                len(text),
            )
            return truncate_markdown_v2_by_bytes(text, max_bytes=TELEGRAM_MAX_MESSAGE_BYTES, suffix="")

        if len(text) <= max_chars:
            return text
        return text[:max_chars]

    async def send_message(
        self,
        destination: Destination,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> str:
        """Send message to session's private chat."""
        self._ensure_started()
        metadata = metadata or MessageMetadata()
        if multi_message:
            logger.trace("send_message: multi_message requested for session %s", destination.session_id)

        # Telegram is an origin/input adapter only; it never renders admin reflections.
        if metadata.reflection_origin is not None:
            logger.debug("send_message: suppressing reflection for session %s", destination.session_id)
            return "0"

        if destination.chat_id is None:
            logger.warning("send_message: skipping, no chat_id resolved for session %s", destination.session_id)
            return ""

        chat_id = destination.chat_id

        # Extract reply_markup and parse_mode from metadata
        reply_markup = metadata.reply_markup
        parse_mode = metadata.parse_mode

        # Transcription: plain text, escape for MarkdownV2
        if metadata.is_transcription:
            text = escape_markdown_v2(text)
            parse_mode = "MarkdownV2"

        # Truncation is a platform constraint (Telegram max 4096)
        text = self._truncate_for_platform(text, parse_mode, UI_MESSAGE_MAX_CHARS)

        # Send message with retry decorator handling errors
        message = await self._send_message_with_retry(chat_id, text, reply_markup, parse_mode)
        return str(message.message_id)

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _send_message_with_retry(
        self,
        chat_id: int,
        formatted_text: str,
        reply_markup: object,
        parse_mode: str | None,
    ) -> Message:
        """Internal method with retry logic for sending messages.

        guard: allow-string-compare
        """
        # Type guard for reply_markup
        if reply_markup is not None and not isinstance(
            reply_markup,
            InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | ForceReply,
        ):
            reply_markup = None
        return await self.bot.send_message(
            chat_id=chat_id,
            text=formatted_text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _send_document_with_retry(
        self,
        chat_id: int,
        message_thread_id: int | None,
        file_path: str,
        filename: str,
        caption: str | None = None,
    ) -> Message:
        """Internal method with retry logic for sending documents.

        guard: allow-string-compare
        """
        with open(file_path, "rb") as file_handle:
            try:
                return await self.bot.send_document(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    document=file_handle,
                    filename=filename,
                    caption=caption,
                    write_timeout=15.0,
                    read_timeout=15.0,
                )
            except BadRequest as exc:
                if "message thread not found" in str(exc).lower():
                    logger.warning("Topic %s not ready yet; retrying document send", message_thread_id)
                    raise TimeoutError("message thread not found") from exc
                raise

    async def edit_message(
        self, destination: Destination, message_id: str, text: str, *, metadata: MessageMetadata | None = None
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
                destination.session_id,
            )
            return False

        if destination.chat_id is None:
            logger.warning("edit_message: skipping, no chat_id resolved for session %s", destination.session_id)
            return False

        # Extract reply_markup + parse_mode from metadata
        reply_markup = metadata.reply_markup
        parse_mode = metadata.parse_mode

        # Apply the same platform-safe truncation rules used for send_message.
        text = self._truncate_for_platform(text, parse_mode, UI_MESSAGE_MAX_CHARS)
        attempt = EditAttempt(
            session_id=destination.session_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            content_hash=self._content_hash(text, parse_mode, reply_markup),
        )
        if self._edit_already_satisfied(attempt):
            return True

        # Create new edit context (mutable)
        ctx = EditContext(
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        self._pending_edits[message_id] = ctx

        result = False
        try:
            start_time = time.time()
            logger.trace("[TELEGRAM %s] Starting edit_message API call", destination.session_id)
            await self._edit_message_with_retry(destination.chat_id, ctx)
            self._last_edit_hash[message_id] = attempt.content_hash
            elapsed = time.time() - start_time
            logger.debug(
                "[TELEGRAM %s] edit_message completed in %.2fs",
                destination.session_id,
                elapsed,
            )
            result = True
        except RetryAfter as error:
            logger.debug(
                "[TELEGRAM %s] Rate limited, edit_message deferred: %s",
                destination.session_id,
                error,
            )
            # Keep output_message_id so we can retry on next update without creating
            # new messages. The retry is the next natural poll-driven render, not an
            # internal loop here — it re-enters through OutputDeliveryMixin's
            # generation guard (delivery_mixin.py), so a retry that lands after the
            # session has since bound a later turn is dropped there rather than
            # applying this generation's content to what is now the wrong message.
            result = True
        except BadRequest as error:
            result = self._handle_edit_bad_request(attempt, error)
        except (NetworkError, TimedOut, TimeoutError, ConnectionError) as error:
            logger.warning(
                "[TELEGRAM %s] transient network error editing message %s; keeping message id and retrying later: %s",
                destination.session_id,
                message_id,
                error,
            )
            result = True
        except (TelegramError, TypeError, ValueError) as error:
            logger.error(
                "[TELEGRAM %s] edit_message failed after retries: %s",
                destination.session_id,
                error,
            )
        finally:
            # Remove from pending edits regardless of outcome
            self._pending_edits.pop(message_id, None)
        return result

    @command_retry(max_retries=3, max_timeout=60.0)
    async def _edit_message_with_retry(self, chat_id: int, ctx: EditContext) -> None:
        """Internal method with retry logic for editing messages.

        Reads from mutable EditContext - always uses latest data even if updated during retry wait.
        """
        # Type guard for reply_markup (edits only support InlineKeyboardMarkup)
        markup = ctx.reply_markup
        if markup is not None and not isinstance(markup, InlineKeyboardMarkup):
            markup = None
        await self.bot.edit_message_text(
            chat_id=chat_id,
            message_id=int(ctx.message_id),
            text=ctx.text,  # ← Read latest text from mutable context
            parse_mode=ctx.parse_mode,
            reply_markup=markup,
        )

    async def delete_message(self, destination: Destination, message_id: str) -> bool:
        """Delete a message in the session's private chat."""
        self._ensure_started()

        if destination.chat_id is None:
            logger.warning("delete_message: skipping, no chat_id resolved for session %s", destination.session_id)
            return False

        try:
            logger.debug(
                "[TELEGRAM %s] delete_message: message_id=%s",
                destination.session_id,
                message_id,
            )
            await self._delete_message_with_retry(destination.chat_id, int(message_id))
            self._last_edit_hash.pop(message_id, None)
            logger.debug("[TELEGRAM %s] delete_message: SUCCESS message_id=%s", destination.session_id, message_id)
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
        except (TelegramError, TypeError, ValueError) as e:
            logger.error("Failed to delete message %s: %s", message_id, e)
            return False

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _delete_message_with_retry(self, chat_id: int, message_id: int) -> None:
        """Delete message with retry logic."""
        await self.bot.delete_message(chat_id=chat_id, message_id=message_id)

    async def send_file(
        self,
        destination: Destination,
        file_path: str,
        *,
        caption: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> str:
        """Send file to session's private chat."""
        self._ensure_started()
        _ = metadata

        if destination.chat_id is None:
            logger.debug("send_file: skipping, no chat_id resolved for session %s", destination.session_id)
            return ""

        message = await self._send_document_with_retry(
            destination.chat_id,
            None,
            file_path,
            Path(file_path).name,
            caption,
        )

        return str(message.message_id)

    async def send_general_message(self, text: str, *, metadata: MessageMetadata | None = None) -> str:
        """Send message to Telegram supergroup general topic."""
        self._ensure_started()
        metadata = metadata or MessageMetadata()

        message_thread_id = metadata.message_thread_id
        parse_mode = metadata.parse_mode
        reply_markup = metadata.reply_markup

        # Type guard for reply_markup
        if reply_markup is not None and not isinstance(
            reply_markup,
            InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | ForceReply,
        ):
            reply_markup = None

        result = await self._send_general_message_with_retry(
            message_thread_id,
            text,
            parse_mode,
            reply_markup,
        )
        return str(result.message_id)

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _send_general_message_with_retry(
        self,
        message_thread_id: int | None,
        text: str,
        parse_mode: str | None,
        reply_markup: object | None,
    ) -> Message:
        """Internal method with retry logic for general-topic messages."""
        return await self.bot.send_message(
            chat_id=self.supergroup_id,
            message_thread_id=message_thread_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,  # type: ignore[arg-type]
        )

    def _edit_already_satisfied(self, attempt: EditAttempt) -> bool:
        """Return True when an edit can be skipped or folded into an in-flight retry."""
        if self._last_edit_hash.get(attempt.message_id) == attempt.content_hash:
            return True

        existing_ctx = self._pending_edits.get(attempt.message_id)
        if existing_ctx is None:
            return False

        existing_ctx.text = attempt.text
        existing_ctx.reply_markup = attempt.reply_markup
        existing_ctx.parse_mode = attempt.parse_mode
        logger.trace(
            "[TELEGRAM %s] Updated pending edit for message %s with latest content",
            attempt.session_id,
            attempt.message_id,
        )
        return True

    def _handle_edit_bad_request(self, attempt: EditAttempt, error: BadRequest) -> bool:
        """Translate Telegram bad-request edit failures into success/failure semantics."""
        message = str(error).lower()
        if "message is not modified" in message:
            logger.trace(
                "[TELEGRAM %s] Message not modified (content unchanged)",
                attempt.session_id,
            )
            self._last_edit_hash[attempt.message_id] = attempt.content_hash
            return True
        if "can't parse entities" in message:
            fence_count = attempt.text.count("```")
            state = scan_markdown_v2_state(attempt.text)
            closers = _required_markdown_closers_from_state(attempt.text, state)
            logger.error(
                ("[TELEGRAM %s] Markdown parse diagnostics: len=%d parse_mode=%s fences=%d needs_closers=%s suffix=%r"),
                attempt.session_id,
                len(attempt.text),
                attempt.parse_mode,
                fence_count,
                bool(closers),
                attempt.text[-40:],
            )
        logger.error("[TELEGRAM %s] edit_message failed: %s", attempt.session_id, error)
        return False
