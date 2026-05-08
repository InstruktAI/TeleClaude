"""Callback query handlers mixin for Telegram adapter.

Handles transcript download buttons emitted on session feedback messages.
"""

from __future__ import annotations

import tempfile
from collections.abc import Awaitable, Callable
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger
from telegram import CallbackQuery, InlineKeyboardMarkup, Message, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.utils import command_retry
from teleclaude.utils.transcript import get_transcript_parser_info, parse_session_transcript

if TYPE_CHECKING:
    from typing import Protocol

    class _CallbackHandlersHost(Protocol):
        _send_document_with_retry: Callable[..., Awaitable[Message]]


logger = get_logger(__name__)

CALLBACK_SEPARATOR = ":"


class CallbackAction(str, Enum):
    """Supported Telegram callback actions."""

    DOWNLOAD_FULL = "download_full"


class CallbackHandlersMixin:
    """Mixin providing callback query handlers for TelegramAdapter.

    Required from host class:
    - _send_document_with_retry(...) -> Message
    """

    # =========================================================================
    # Callback Query Handler Implementation
    # =========================================================================

    async def _handle_callback_query(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle button clicks from inline keyboards."""
        query = update.callback_query
        if not query:
            return
        await query.answer()

        data = query.data
        if not data or CALLBACK_SEPARATOR not in data:
            return

        action_raw, _, rest_raw = data.partition(CALLBACK_SEPARATOR)
        rest = rest_raw.split(CALLBACK_SEPARATOR) if rest_raw else []

        try:
            action = CallbackAction(action_raw)
        except ValueError:
            logger.debug("Unknown callback action: %s", action_raw)
            return

        if action is CallbackAction.DOWNLOAD_FULL:
            await self._handle_download_full(query, rest)

    async def _edit_callback_message(
        self,
        query: object,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        """Edit callback message with retry and benign-error tolerance."""
        if not isinstance(query, CallbackQuery):
            return

        try:
            await self._edit_callback_message_with_retry(query, text, parse_mode=parse_mode, reply_markup=reply_markup)
        except BadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
            raise

    @command_retry(max_retries=3, max_timeout=60.0)
    async def _edit_callback_message_with_retry(
        self,
        query: object,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        """Internal retry-protected callback message edit."""
        if not isinstance(query, CallbackQuery):
            return

        await query.edit_message_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )

    async def _handle_download_full(self, query: object, args: list[str]) -> None:
        """Handle download_full callback to download session transcript."""
        if not isinstance(query, CallbackQuery):
            return

        session_id = args[0] if args else None
        if not session_id or not query.message:
            return

        try:
            download_payload = await self._build_transcript_download_payload(query, session_id)
            if download_payload is None:
                return
            markdown_content, filename, caption = download_payload
            doc_message = await self._send_transcript_document(
                query,
                markdown_content,
                filename,
                caption,
            )
            await db.add_pending_deletion(session_id, str(doc_message.message_id), deletion_type="feedback")
        except (BadRequest, OSError, RuntimeError, TypeError, ValueError) as error:
            logger.error("Failed to send transcript document: %s", error)
            await self._edit_callback_message(query, f"❌ Error sending file: {error}", parse_mode="Markdown")

    async def _build_transcript_download_payload(
        self,
        query: CallbackQuery,
        session_id: str,
    ) -> tuple[str, str, str] | None:
        """Resolve transcript download inputs or notify the user when prerequisites are missing."""
        session = await db.get_session(session_id)
        if session is None:
            return None

        agent_value = session.active_agent
        if not agent_value:
            await self._edit_callback_message(
                query,
                "❌ Active agent unknown for this session",
                parse_mode="Markdown",
            )
            return None

        try:
            agent_name = AgentName.from_str(agent_value)
        except ValueError as error:
            await self._edit_callback_message(query, f"❌ {error}", parse_mode="Markdown")
            return None

        parser_info = get_transcript_parser_info(agent_name)
        native_log_file = session.native_log_file
        if not native_log_file:
            await self._edit_callback_message(
                query,
                f"❌ No {parser_info.display_name} session file found",
                parse_mode="Markdown",
            )
            return None

        markdown_content = parse_session_transcript(
            native_log_file,
            session.title,
            agent_name=agent_name,
            tail_chars=0,
        )
        filename = f"{parser_info.file_prefix}-{session_id:8}.md"
        caption = f"{parser_info.display_name} session transcript"
        return markdown_content, filename, caption

    async def _send_transcript_document(
        self,
        query: CallbackQuery,
        markdown_content: str,
        filename: str,
        caption: str,
    ) -> Message:
        """Write a transcript to a temporary file and upload it to the callback thread."""
        message = query.message
        if not isinstance(message, Message):
            raise TypeError("Callback query message missing")

        msg_thread_id = message.message_thread_id
        if not isinstance(msg_thread_id, int):
            raise TypeError("message_thread_id must be int")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tmp:
            tmp.write(markdown_content)
            tmp_path = tmp.name

        try:
            return await cast("_CallbackHandlersHost", self)._send_document_with_retry(
                chat_id=message.chat_id,
                message_thread_id=msg_thread_id,
                file_path=tmp_path,
                filename=filename,
                caption=caption,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
