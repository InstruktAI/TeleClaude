"""Input handlers mixin for Telegram adapter.

Handles user input: voice messages, file attachments, and error handling.
"""

from __future__ import annotations

import asyncio
import tempfile
import traceback
from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger
from telegram import Document, Message, PhotoSize, Update
from telegram.ext import ContextTypes

from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata
from teleclaude.core.session_utils import get_session_output_dir
from teleclaude.types.commands import HandleFileCommand, HandleVoiceCommand

if TYPE_CHECKING:
    from typing import Protocol

    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

    class _InputHandlersHost(Protocol):
        client: AdapterClient
        _processed_voice_messages: set[str]
        _topic_ready_events: dict[int, asyncio.Event]
        _topic_ready_cache: set[int]
        _metadata: Callable[..., MessageMetadata]
        send_message: Callable[..., Awaitable[str | None]]
        _get_session_from_topic: Callable[[Update], Awaitable[Session | None]]
        _dispatch_command: Callable[
            [Session, str | None, MessageMetadata, str, Mapping[str, object], Callable[[], Awaitable[object]]],
            Awaitable[object],
        ]
        _send_general_message_with_retry: Callable[[int | None, str, str | None, object | None], Awaitable[Message]]
        task_registry: object


logger = get_logger(__name__)


class IncomingFileType(str, Enum):
    """Supported inbound file types."""

    DOCUMENT = "document"
    PHOTO = "photo"


FILE_SUBDIR: dict[IncomingFileType, str] = {
    IncomingFileType.DOCUMENT: "files",
    IncomingFileType.PHOTO: "photos",
}


def _describe_message_content(message: Message) -> list[str]:
    """Describe Telegram message content types for debug logging."""
    message_parts: list[str] = []
    if message.text:
        message_parts.append(f"text: '{message.text[:50]}'")
    if message.voice:
        message_parts.append("voice")
    if message.photo:
        message_parts.append("photo")
    if message.document:
        message_parts.append("document")
    if message.forum_topic_created:
        message_parts.append("forum_topic_created")
    if message.forum_topic_closed:
        message_parts.append("forum_topic_closed")
    if message.forum_topic_reopened:
        message_parts.append("forum_topic_reopened")
    if message.forum_topic_edited:
        message_parts.append("forum_topic_edited")
    if message.delete_chat_photo:
        message_parts.append("delete_chat_photo")
    if message.new_chat_members:
        message_parts.append("new_chat_members")
    if message.left_chat_member:
        message_parts.append("left_chat_member")
    return message_parts


def _describe_update_extras(update: Update) -> list[str]:
    """Describe non-message update types for debug logging."""
    extras: list[str] = []
    if update.callback_query:
        extras.append(f"callback_query: {update.callback_query.data}")
    if update.inline_query:
        extras.append(f"inline_query: {update.inline_query.query}")
    if update.poll:
        extras.append("poll update")
    if update.poll_answer:
        extras.append("poll_answer")
    if update.my_chat_member:
        extras.append("my_chat_member")
    if update.chat_member:
        extras.append("chat_member")
    if update.chat_join_request:
        extras.append("chat_join_request")
    return extras


class InputHandlersMixin:
    """Mixin providing input handlers for TelegramAdapter.

    Required from host class:
    - client: AdapterClient
    - _processed_voice_messages: set[str]
    - _topic_ready_events: dict[int, asyncio.Event]
    - _topic_ready_cache: set[int]
    - _metadata(**kwargs: object) -> AdapterMetadata
    - _get_session_from_topic(update: Update) -> Optional[Session]
    """

    # Abstract properties/attributes (declared for type hints)
    client: AdapterClient
    _processed_voice_messages: set[str]
    _topic_ready_events: dict[int, asyncio.Event]
    _topic_ready_cache: set[int]

    async def _handle_voice_message(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle voice messages in topics - both new and edited messages."""
        # Handle both regular messages and edited messages
        message = update.effective_message
        if not message or not update.effective_user:
            return

        logger.info("=== VOICE MESSAGE HANDLER CALLED ===")
        logger.info(
            "Message ID: %s (edited: %s)",
            message.message_id,
            update.edited_message is not None,
        )
        logger.info("User: %s", update.effective_user.id)
        logger.info("Thread ID: %s", message.message_thread_id)

        # Check if we've already processed this message
        # For edited messages, include edit_date so each edit is unique
        is_edited = update.edited_message is not None
        edit_suffix = (
            f"edited:{message.edit_date}" if is_edited and message.edit_date else ("edited" if is_edited else "new")
        )
        dedup_key_str = f"{message.message_id}:{edit_suffix}"
        if dedup_key_str in self._processed_voice_messages:
            logger.debug("Skipping duplicate voice message: %s", dedup_key_str)
            return

        # Mark as processed
        self._processed_voice_messages.add(dedup_key_str)

        # Limit set size to prevent memory growth (keep last 1000 message IDs)
        if len(self._processed_voice_messages) > 1000:
            oldest_str = min(self._processed_voice_messages)
            self._processed_voice_messages.remove(oldest_str)

        host = cast("_InputHandlersHost", self)
        session = await host._get_session_from_topic(update)
        if not session:
            logger.warning(
                "No session found for voice message in thread %s",
                message.message_thread_id,
            )
            return

        # Download voice file to temp location
        voice = message.voice
        if not voice:
            return
        voice_file = await voice.get_file()

        # Create temp file with .ogg extension (Telegram uses ogg/opus format)
        temp_dir = Path(tempfile.gettempdir()) / "teleclaude_voice"
        temp_dir.mkdir(exist_ok=True)
        temp_file_path = temp_dir / f"voice_{message.message_id}.ogg"

        try:
            # Download the file
            await voice_file.download_to_drive(temp_file_path)
            logger.info("Downloaded voice message to: %s", temp_file_path)

            cmd = HandleVoiceCommand(
                session_id=session.session_id,
                file_path=str(temp_file_path),
                duration=(
                    voice.duration.total_seconds() if isinstance(voice.duration, timedelta) else float(voice.duration)
                ),
                message_id=str(message.message_id),
                message_thread_id=message.message_thread_id,
                origin=cast("_InputHandlersHost", self)._metadata().origin,
                actor_id=f"telegram:{update.effective_user.id}",
                actor_name=(
                    update.effective_user.username
                    or update.effective_user.full_name
                    or update.effective_user.first_name
                    or f"telegram:{update.effective_user.id}"
                ),
            )
            registry = getattr(self, "task_registry", None)
            if registry is None:
                raise RuntimeError("Telegram voice handling requires task_registry")
            registry.spawn(get_command_service().handle_voice(cmd), name=f"voice-{message.message_id}")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            error_msg = str(error) if str(error).strip() else "Unknown error"
            logger.error("Failed to download voice message: %s", error_msg)
            host = cast("_InputHandlersHost", self)
            await host.send_message(
                session,
                f"❌ Failed to download voice message: {error_msg}",
                metadata=MessageMetadata(parse_mode=None),
            )

    async def _handle_file_attachment(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle file attachments (documents, photos) in topics - both new and edited messages."""
        # Handle both regular messages and edited messages
        message = update.message or update.edited_message
        if not message or not update.effective_user:
            return

        host = cast("_InputHandlersHost", self)
        session = await host._get_session_from_topic(update)
        if not session:
            return

        # Get file object (either document or photo)
        file_obj: Document | PhotoSize | None = None
        file_name: str | None = None
        file_type: IncomingFileType | None = None

        if message.document:
            file_obj = message.document
            file_name = message.document.file_name or f"document_{message.message_id}"
            file_type = IncomingFileType.DOCUMENT
        elif message.photo:
            # Photos come as array, get largest one
            file_obj = message.photo[-1]  # PhotoSize, not Document
            file_name = f"photo_{message.message_id}.jpg"
            file_type = IncomingFileType.PHOTO

        if not file_obj:
            return

        if file_type is None:
            logger.error("file_type is None, cannot route file attachment")
            return
        # Determine subdirectory based on file type
        subdir = FILE_SUBDIR.get(file_type, "files")
        session_workspace = get_session_output_dir(session.session_id) / subdir
        session_workspace.mkdir(parents=True, exist_ok=True)
        if file_name is None:
            logger.error("file_name is None, cannot save file")
            return
        file_path = session_workspace / file_name

        try:
            # Download file to session workspace
            telegram_file = await file_obj.get_file()
            await telegram_file.download_to_drive(file_path)
            logger.info("Downloaded %s to: %s", file_type, file_path)

            await get_command_service().handle_file(
                HandleFileCommand(
                    session_id=session.session_id,
                    file_path=str(file_path),
                    filename=file_name,
                    caption=message.caption.strip() if message.caption else None,
                    file_size=(file_obj.file_size if hasattr(file_obj, "file_size") else 0),
                )
            )
        except (OSError, RuntimeError, TypeError, ValueError) as e:
            # Log detailed error for debugging
            logger.error("Failed to download %s: %s", file_type, str(e))

            # Send user-friendly error message
            message_id = await host.send_message(
                session,
                f"❌ Failed to upload {file_type}",
                metadata=host._metadata(),
            )
            if message_id:
                await db.add_pending_deletion(session.session_id, message_id)

    async def _log_all_updates(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log all Telegram updates for debugging (catch-all handler).

        This helps discover events like pull-to-refresh, scroll events, etc.
        """
        try:
            update_dict = update.to_dict()

            # Extract key info
            update_id = update.update_id
            user = update.effective_user
            chat = update.effective_chat
            message: Message | None = update.message or update.edited_message

            log_parts = [f"📩 Telegram Update #{update_id}"]

            if user:
                log_parts.append(f"from user {user.id} (@{user.username})")

            if chat:
                log_parts.append(f"in chat {chat.id} ({chat.type})")

            if message:
                msg_type = _describe_message_content(message)
                if msg_type:
                    log_parts.append(f"content: [{', '.join(msg_type)}]")

            log_parts.extend(_describe_update_extras(update))

            logger.info(" | ".join(log_parts))

            # Always log full update dict for comprehensive event tracking
            # This ensures we can see ALL events including topic deletions
            logger.debug("Full update data: %s", update_dict)

        except (TypeError, ValueError, AttributeError) as error:
            logger.error("Error logging update: %s", error)

    async def _handle_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors that occur in handlers."""
        logger.error("Exception while handling update %s:", update, exc_info=context.error)

        # Log full traceback
        if context.error:
            logger.error(
                "Full traceback:\n%s",
                "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__)),
            )

    async def handle_file_attachment(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Public wrapper for inbound file routing."""
        await self._handle_file_attachment(update, context)
