"""Input handlers mixin for Telegram adapter.

Handles user input: text messages, voice messages, file attachments,
topic lifecycle events, and error handling.
"""

from __future__ import annotations

import asyncio
import tempfile
import traceback
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from telegram import Document, Message, PhotoSize, Update
from telegram.ext import ContextTypes

from teleclaude.core.command_registry import get_command_service
from teleclaude.core.dates import ensure_utc
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionLifecycleContext, UiCommands
from teleclaude.core.models import CleanupTrigger, MessageMetadata
from teleclaude.core.session_utils import get_session_output_dir
from teleclaude.types.commands import HandleFileCommand, HandleVoiceCommand

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)


class IncomingFileType(str, Enum):
    """Supported inbound file types."""

    DOCUMENT = "document"
    PHOTO = "photo"


FILE_SUBDIR: dict[IncomingFileType, str] = {
    IncomingFileType.DOCUMENT: "files",
    IncomingFileType.PHOTO: "photos",
}


class InputHandlersMixin:
    """Mixin providing input handlers for TelegramAdapter.

    Required from host class:
    - client: AdapterClient
    - user_whitelist: set[int]
    - _topic_message_cache: dict[int | None, list[Message]]
    - _mcp_message_queues: dict[int, asyncio.Queue[Message]]
    - _processed_voice_messages: set[str]
    - _topic_ready_events: dict[int, asyncio.Event]
    - _topic_ready_cache: set[int]
    - _metadata(**kwargs: object) -> AdapterMetadata
    - _get_session_from_topic(update: Update) -> Optional[Session]
    - _topic_owned_by_this_bot(update: Update, topic_id: int) -> bool
    - _delete_orphan_topic(topic_id: int) -> None
    """

    # Abstract properties/attributes (declared for type hints)
    client: "AdapterClient"
    user_whitelist: set[int]
    _topic_message_cache: dict[int | None, list[Message]]
    _mcp_message_queues: dict[int, "asyncio.Queue[object]"]
    _processed_voice_messages: set[str]
    _topic_ready_events: dict[int, asyncio.Event]
    _topic_ready_cache: set[int]

    if TYPE_CHECKING:

        def _metadata(self, **kwargs: object) -> MessageMetadata:
            """Create adapter metadata."""
            ...

        async def _get_session_from_topic(self, update: Update) -> "Session | None":
            """Get session from update's topic."""
            ...

        async def _dispatch_command(
            self,
            session: "Session",
            message_id: str | None,
            metadata: MessageMetadata,
            command_name: str,
            payload: Mapping[str, object],
            handler: Callable[[], Awaitable[object]],
        ) -> None:
            """Dispatch command via UiAdapter hooks (type-check stub)."""
            ...

        def _topic_owned_by_this_bot(self, update: Update, topic_id: int) -> bool:
            """Check if topic is owned by this bot."""
            ...

        async def _delete_orphan_topic(self, topic_id: int) -> None:
            """Delete orphan topic."""
            ...

    # =========================================================================
    # Input Handler Implementation
    # =========================================================================

    async def _cache_command_message(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Cache command messages for registry polling.

        Commands like /registry_ping and /pong need to be cached so
        computer_registry can find them when polling.
        """
        message: Message | None = update.message or update.edited_message
        if message:
            # Use None for General topic, actual ID for forum topics
            topic_id = message.message_thread_id

            # Cache message for registry polling (get_topic_messages)
            if topic_id not in self._topic_message_cache:
                self._topic_message_cache[topic_id] = []

            # For edited messages, replace existing message with same ID
            if update.edited_message:
                # Remove old version of this message
                self._topic_message_cache[topic_id] = [
                    m for m in self._topic_message_cache[topic_id] if m.message_id != message.message_id
                ]

            self._topic_message_cache[topic_id].append(message)
            if len(self._topic_message_cache[topic_id]) > 100:
                self._topic_message_cache[topic_id].pop(0)

    async def _handle_help(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command - dynamically generates from UiCommands."""
        user = update.effective_user
        if not user or user.id not in self.user_whitelist:
            return

        # Build command list from UiCommands (sorted alphabetically)
        cmd_lines = [f"/{cmd} - {desc}" for cmd, desc in sorted(UiCommands.items())]
        commands_text = "\n".join(cmd_lines)

        help_text = f"""TeleClaude Bot Commands:

{commands_text}

Usage:
1. Use /new_session to create a tmux session
2. Send text messages in the session topic to execute commands
3. Use /cancel to interrupt a running command
4. Use /claude to start Claude Code
5. View output in real-time
        """

        message = update.effective_message
        if message:
            await message.reply_text(help_text)

    async def _handle_text_message(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle text messages in topics and General topic.

        Messages with message_thread_id are in specific topics.
        Messages without message_thread_id are in General topic (cached with key None).

        Also handles edited messages (for registry heartbeat updates).
        """
        # Handle both new messages and edited messages
        message: Message | None = update.message or update.edited_message
        if message:
            # Use None for General topic, actual ID for forum topics
            topic_id = message.message_thread_id

            # Cache message for registry polling (get_topic_messages)
            if topic_id not in self._topic_message_cache:
                self._topic_message_cache[topic_id] = []

            # For edited messages, replace existing message with same ID
            if update.edited_message:
                # Remove old version of this message
                self._topic_message_cache[topic_id] = [
                    m for m in self._topic_message_cache[topic_id] if m.message_id != message.message_id
                ]

            self._topic_message_cache[topic_id].append(message)
            if len(self._topic_message_cache[topic_id]) > 100:
                self._topic_message_cache[topic_id].pop(0)

            # ALSO push to MCP queue if registered (event-driven delivery for AI-to-AI)
            # Only push new messages, not edits (edits are not user input)
            if update.message and topic_id in self._mcp_message_queues:
                try:
                    self._mcp_message_queues[topic_id].put_nowait(update.message)
                    logger.debug("Pushed message to MCP queue for topic %s", topic_id)
                except asyncio.QueueFull:
                    logger.warning("MCP queue full for topic %s", topic_id)

        session = await self._get_session_from_topic(update)
        if not session:
            logger.warning(
                "Session lookup failed for message in topic %s (user: %s, text: %s)",
                (update.effective_message.message_thread_id if update.effective_message else None),
                update.effective_user.id if update.effective_user else None,
                (
                    update.effective_message.text[:50]
                    if update.effective_message and update.effective_message.text
                    else None
                ),
            )
            if (
                update.effective_user
                and update.effective_user.id in self.user_whitelist
                and update.effective_message
                and update.effective_message.message_thread_id
            ):
                thread_id = update.effective_message.message_thread_id
                if self._topic_owned_by_this_bot(update, thread_id):
                    await self._delete_orphan_topic(thread_id)
                else:
                    logger.info("Skipping orphan topic delete for topic %s (not owned by this bot)", thread_id)
            return
        if not update.effective_message or not update.effective_user:
            logger.warning("Missing effective_message or effective_user in update")
            return

        text = update.effective_message.text
        if not text:
            return

        # Strip leading // and replace with / (Telegram workaround - only at start of input)
        # Double slash bypasses Telegram command detection so raw command goes to Agent
        if text.startswith("//"):
            text = "/" + text[2:]
            logger.debug("Stripped leading // from user input (raw mode), result: %s", text[:50])

        from teleclaude.core.command_mapper import CommandMapper

        metadata = self._metadata()
        metadata.channel_metadata = metadata.channel_metadata or {}
        metadata.channel_metadata["message_id"] = str(update.effective_message.message_id)

        cmd = CommandMapper.map_telegram_input(
            event="message",
            args=[text],
            metadata=metadata,
            session_id=session.session_id,
        )
        await self._dispatch_command(
            session,
            str(update.effective_message.message_id),
            metadata,
            "send_message",
            cmd.to_payload(),
            lambda: get_command_service().send_message(cmd),
        )

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
        # For edited messages, use a different key to allow reprocessing
        is_edited = update.edited_message is not None
        dedup_key_str = f"{message.message_id}:{'edited' if is_edited else 'new'}"
        if dedup_key_str in self._processed_voice_messages:
            logger.debug("Skipping duplicate voice message: %s", dedup_key_str)
            return

        # Mark as processed
        self._processed_voice_messages.add(dedup_key_str)

        # Limit set size to prevent memory growth (keep last 1000 message IDs)
        if len(self._processed_voice_messages) > 1000:
            oldest_str = min(self._processed_voice_messages)
            self._processed_voice_messages.remove(oldest_str)

        session = await self._get_session_from_topic(update)
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

            await get_command_service().handle_voice(
                HandleVoiceCommand(
                    session_id=session.session_id,
                    file_path=str(temp_file_path),
                    message_id=str(message.message_id),
                    message_thread_id=message.message_thread_id,
                    origin=self._metadata().origin,
                )
            )
        except Exception as e:
            error_msg = str(e) if str(e).strip() else "Unknown error"
            logger.error("Failed to download voice message: %s", error_msg)
            await self.client.send_message(
                session,
                f"❌ Failed to download voice message: {error_msg}",
                metadata=self._metadata(),
                cleanup_trigger=CleanupTrigger.NEXT_NOTICE,
            )

    async def _handle_file_attachment(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle file attachments (documents, photos) in topics - both new and edited messages."""
        # Handle both regular messages and edited messages
        message = update.message or update.edited_message
        if not message or not update.effective_user:
            return

        session = await self._get_session_from_topic(update)
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
        except Exception as e:
            # Log detailed error for debugging
            logger.error("Failed to download %s: %s", file_type, str(e))

            # Send user-friendly error message
            message_id = await self.client.send_message(
                session,
                f"❌ Failed to upload {file_type}",
                metadata=self._metadata(),
            )
            if message_id:
                await db.add_pending_deletion(session.session_id, message_id)

    async def _handle_topic_created(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle forum topic created event (readiness signal)."""
        if not update.message or not update.message.message_thread_id:
            return

        topic_id = update.message.message_thread_id
        event = self._topic_ready_events.pop(topic_id, None)
        if event:
            event.set()
        self._topic_ready_cache.add(topic_id)

        topic_name = ""
        if update.message.forum_topic_created:
            topic_name = update.message.forum_topic_created.name
        logger.info("Topic created event received: %s (ID: %s)", topic_name, topic_id)

    async def _handle_topic_closed(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle forum topic end event."""
        if not update.message or not update.message.message_thread_id:
            return

        topic_id = update.message.message_thread_id

        sessions = await db.get_sessions_by_adapter_metadata("telegram", "topic_id", topic_id)

        if not sessions:
            logger.warning("No session found for topic %s", topic_id)
            if self._topic_owned_by_this_bot(update, topic_id):
                await self._delete_orphan_topic(topic_id)
            else:
                logger.info("Skipping orphan topic delete for topic %s (not owned by this bot)", topic_id)
            return

        session = sessions[0]
        if session.created_at:
            created_at = ensure_utc(session.created_at)
            session_age = (datetime.now(timezone.utc) - created_at).total_seconds()
            if session_age < 10.0:
                logger.warning(
                    "Ignoring topic_closed for new session %s (age=%.1fs)",
                    session.session_id[:8],
                    session_age,
                )
                return
        logger.info(
            "Topic %s ended by user, terminating session %s",
            topic_id,
            session.session_id[:8],
        )

        # Emit session_closed event to daemon for cleanup
        await event_bus.emit(
            "session_closed",
            SessionLifecycleContext(session_id=session.session_id),
        )

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
                msg_type = []
                if message.text:
                    msg_type.append(f"text: '{message.text[:50]}'")
                if message.voice:
                    msg_type.append("voice")
                if message.photo:
                    msg_type.append("photo")
                if message.document:
                    msg_type.append("document")
                if message.forum_topic_created:
                    msg_type.append("forum_topic_created")
                if message.forum_topic_closed:
                    msg_type.append("forum_topic_closed")
                if message.forum_topic_reopened:
                    msg_type.append("forum_topic_reopened")
                if message.forum_topic_edited:
                    msg_type.append("forum_topic_edited")
                if message.delete_chat_photo:
                    msg_type.append("delete_chat_photo")
                if message.new_chat_members:
                    msg_type.append("new_chat_members")
                if message.left_chat_member:
                    msg_type.append("left_chat_member")
                if msg_type:
                    log_parts.append(f"content: [{', '.join(msg_type)}]")

            # Check for other update types
            if update.callback_query:
                log_parts.append(f"callback_query: {update.callback_query.data}")
            if update.inline_query:
                log_parts.append(f"inline_query: {update.inline_query.query}")
            if update.poll:
                log_parts.append("poll update")
            if update.poll_answer:
                log_parts.append("poll_answer")
            if update.my_chat_member:
                log_parts.append("my_chat_member")
            if update.chat_member:
                log_parts.append("chat_member")
            if update.chat_join_request:
                log_parts.append("chat_join_request")

            logger.info(" | ".join(log_parts))

            # Always log full update dict for comprehensive event tracking
            # This ensures we can see ALL events including topic deletions
            logger.debug("Full update data: %s", update_dict)

        except Exception as e:
            logger.error("Error logging update: %s", e)

    async def _handle_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors that occur in handlers."""
        logger.error("Exception while handling update %s:", update, exc_info=context.error)

        # Log full traceback
        if context.error:
            logger.error(
                "Full traceback:\n%s",
                "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__)),
            )
