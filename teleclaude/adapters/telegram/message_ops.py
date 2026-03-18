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
from telegram import (
    ForceReply,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.error import BadRequest, NetworkError, RetryAfter, TelegramError, TimedOut

from teleclaude.constants import TELEGRAM_MAX_MESSAGE_BYTES, UI_MESSAGE_MAX_CHARS
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
        session: Session,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> str:
        """Send message to session's topic with automatic retry on rate limits and network errors."""
        self._ensure_started()
        metadata = metadata or MessageMetadata()
        if multi_message:
            logger.trace("send_message: multi_message requested for session %s", session.session_id)

        # Reflection suppression: drop own-user reflections; format cross-source ones.
        if metadata.reflection_origin is not None:
            if metadata.reflection_origin == "telegram":
                logger.debug("send_message: suppressing own-user reflection for session %s", session.session_id)
                return "0"
            # Cross-source reflection: prepend attribution header and separator.
            actor_name = (metadata.reflection_actor_name or "").strip()
            origin_label = metadata.reflection_origin.upper() or "UNKNOWN"
            if actor_name:
                header = f"{actor_name} @ {origin_label}:\n\n"
                if not text.startswith(header):
                    text = f"{header}{text}"
                if not text.endswith("---\n"):
                    text = f"{text}\n\n---\n"

        # Skip when topic_id absent (channel still creating, or headless session without a topic).
        telegram_meta = session.get_metadata().get_ui().get_telegram()
        topic_id = telegram_meta.topic_id
        if not topic_id:
            logger.debug("send_message: skipping, topic_id not ready for session %s", session.session_id)
            return ""

        # Extract reply_markup and parse_mode from metadata
        reply_markup = metadata.reply_markup
        parse_mode = metadata.parse_mode

        # Transcription: plain text, escape for MarkdownV2
        if metadata.is_transcription:
            text = escape_markdown_v2(text)
            parse_mode = "MarkdownV2"

        # Truncation is a platform constraint (Telegram max 4096)
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
        parse_mode: str | None,
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
        except BadRequest as exc:
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
        self, session: Session, message_id: str, text: str, *, metadata: MessageMetadata | None = None
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
                session.session_id,
            )
            return False

        # Extract reply_markup + parse_mode from metadata
        reply_markup = metadata.reply_markup
        parse_mode = metadata.parse_mode

        # Apply the same platform-safe truncation rules used for send_message.
        text = self._truncate_for_platform(text, parse_mode, UI_MESSAGE_MAX_CHARS)
        attempt = EditAttempt(
            session_id=session.session_id,
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
            logger.trace("[TELEGRAM %s] Starting edit_message API call", session.session_id)
            await self._edit_message_with_retry(session, ctx)
            self._last_edit_hash[message_id] = attempt.content_hash
            elapsed = time.time() - start_time
            logger.debug(
                "[TELEGRAM %s] edit_message completed in %.2fs",
                session.session_id,
                elapsed,
            )
            result = True
        except RetryAfter as error:
            logger.debug(
                "[TELEGRAM %s] Rate limited, edit_message deferred: %s",
                session.session_id,
                error,
            )
            # Keep output_message_id so we can retry on next update without creating new messages.
            result = True
        except BadRequest as error:
            result = self._handle_edit_bad_request(attempt, error)
        except (NetworkError, TimedOut, TimeoutError, ConnectionError) as error:
            logger.warning(
                "[TELEGRAM %s] transient network error editing message %s; keeping message id and retrying later: %s",
                session.session_id,
                message_id,
                error,
            )
            result = True
        except (TelegramError, TypeError, ValueError) as error:
            logger.error(
                "[TELEGRAM %s] edit_message failed after retries: %s",
                session.session_id,
                error,
            )
        finally:
            # Remove from pending edits regardless of outcome
            self._pending_edits.pop(message_id, None)
        return result

    @command_retry(max_retries=3, max_timeout=60.0)
    async def _edit_message_with_retry(self, _session: Session, ctx: EditContext) -> None:
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

    async def delete_message(self, session: Session, message_id: str) -> bool:
        """Delete a message in the session's topic."""
        self._ensure_started()

        try:
            logger.debug(
                "[TELEGRAM %s] delete_message: chat_id=%s message_id=%s",
                session.session_id,
                self.supergroup_id,
                message_id,
            )
            await self._delete_message_with_retry(int(message_id))
            self._last_edit_hash.pop(message_id, None)
            logger.debug("[TELEGRAM %s] delete_message: SUCCESS message_id=%s", session.session_id, message_id)
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
    async def _delete_message_with_retry(self, message_id: int) -> None:
        """Delete message with retry logic."""
        await self.bot.delete_message(chat_id=self.supergroup_id, message_id=message_id)

    async def send_file(
        self,
        session: Session,
        file_path: str,
        *,
        caption: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> str:
        """Send file to session's topic."""
        self._ensure_started()
        _ = metadata

        # Skip when topic_id absent (channel still creating, or headless session without a topic).
        telegram_meta = session.get_metadata().get_ui().get_telegram()
        topic_id = telegram_meta.topic_id
        if not topic_id:
            logger.debug("send_file: skipping, topic_id not ready for session %s", session.session_id)
            return ""

        message = await self._send_document_with_retry(
            self.supergroup_id,
            topic_id,
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
            (
                InlineKeyboardMarkup,
                ReplyKeyboardMarkup,
                ReplyKeyboardRemove,
                ForceReply,
            ),
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

    async def edit_general_message(
        self, message_id: str, text: str, *, metadata: MessageMetadata | None = None
    ) -> bool:
        """Edit an existing message in the general topic.

        Returns:
            True when edit succeeded or encountered a transient/retryable error.
            False only when the message is definitely gone/not editable.
        """
        self._ensure_started()
        metadata = metadata or MessageMetadata()

        parse_mode = metadata.parse_mode
        reply_markup = metadata.reply_markup

        # Type guard for reply_markup (edits only support InlineKeyboardMarkup)
        if reply_markup is not None and not isinstance(reply_markup, InlineKeyboardMarkup):
            reply_markup = None

        # Skip no-op edits.
        content_hash = self._content_hash(text, parse_mode, reply_markup)
        if self._last_edit_hash.get(message_id) == content_hash:
            return True

        result = True
        try:
            await self._edit_general_message_with_retry(message_id, text, parse_mode, reply_markup)
            self._last_edit_hash[message_id] = content_hash
        except RetryAfter as e:
            logger.debug(
                "Rate limited editing general message %s; keeping existing id and retrying later: %s",
                message_id,
                e,
            )
        except BadRequest as e:
            result = self._handle_general_edit_bad_request(message_id, content_hash, e)
        except (NetworkError, TimedOut, TimeoutError, ConnectionError) as e:
            logger.warning(
                "Transient network error editing general message %s; keeping existing id and retrying later: %s",
                message_id,
                e,
            )
        except (TelegramError, TypeError, ValueError) as e:
            logger.error("Failed to edit general message %s: %s", message_id, e)
            # Avoid creating duplicate menu messages on unknown transient failures.
        return result

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

    def _handle_general_edit_bad_request(
        self,
        message_id: str,
        content_hash: str,
        error: BadRequest,
    ) -> bool:
        """Translate general-topic edit failures into keep/recreate decisions."""
        message = str(error).lower()
        if "message is not modified" in message:
            self._last_edit_hash[message_id] = content_hash
            return True
        if "message to edit not found" in message:
            logger.debug("Menu message %s not found, will recreate", message_id)
            return False
        if "message can't be edited" in message:
            logger.debug("Menu message %s cannot be edited, will recreate", message_id)
            return False
        logger.error("Failed to edit general message %s: %s", message_id, error)
        # Non-not-found BadRequest is often transient under Telegram load.
        return True

    @command_retry(max_retries=3, max_timeout=60.0)
    async def _edit_general_message_with_retry(
        self,
        message_id: str,
        text: str,
        parse_mode: str | None,
        reply_markup: InlineKeyboardMarkup | None,
    ) -> None:
        """Internal method with retry logic for general-topic edits."""
        await self.bot.edit_message_text(
            chat_id=self.supergroup_id,
            message_id=int(message_id),
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
