"""Telegram adapter for TeleClaude."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import tempfile
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Optional, TypedDict, cast

if TYPE_CHECKING:
    from telegram import Message as TelegramMessage

    from teleclaude.core.adapter_client import AdapterClient

from telegram import (
    BotCommand,
    BotCommandScopeChat,
    Document,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    PhotoSize,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.error import BadRequest, NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ExtBot,
    JobQueue,
    MessageHandler,
    filters,
)

from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.events import TeleClaudeEvents, UiCommands
from teleclaude.core.models import ChannelMetadata, MessageMetadata, PeerInfo, Session
from teleclaude.core.session_utils import get_session_output_dir
from teleclaude.core.ux_state import (
    SessionUXState,
    get_system_ux_state,
    update_system_ux_state,
)
from teleclaude.utils import command_retry
from teleclaude.utils.claude_transcript import parse_claude_transcript

from .base_adapter import AdapterError
from .ui_adapter import UiAdapter

# Status emoji mapping
STATUS_EMOJI = {"active": "🟢", "waiting": "🟡", "slow": "🟠", "stalled": "🔴", "idle": "⏸️", "dead": "❌"}


# TypedDicts for JSON/dict structures with known schemas
class HandleEventResult(TypedDict, total=False):
    """Result from client.handle_event() calls."""

    status: str
    data: dict[str, object]  # Nested data structure varies by event type


class HandleEventData(TypedDict, total=False):
    """Data nested inside HandleEventResult."""

    session_id: str


# Type alias for python-telegram-bot's default Application type.
# The library uses dict for user/chat/bot data storage - this is intentional
# design since the library doesn't restrict what you can store.
TelegramApp = Application[  # type: ignore[misc]
    ExtBot[None],
    ContextTypes.DEFAULT_TYPE,
    dict[object, object],  # User data storage
    dict[object, object],  # Chat data storage
    dict[object, object],  # Bot data storage
    JobQueue[ContextTypes.DEFAULT_TYPE],  # Job queue (created by builder.build())
]

logger = logging.getLogger(__name__)


@dataclass
class EditContext:
    """Mutable context for message edits during rate limit retries.

    Allows updating message content while retry decorator is waiting,
    ensuring latest data is sent instead of stale payloads.
    """

    message_id: str
    text: str
    reply_markup: Optional[object] = None


class TelegramAdapter(
    UiAdapter
):  # pylint: disable=too-many-instance-attributes  # Telegram adapter manages many handlers and state
    """Telegram bot adapter using python-telegram-bot."""

    ADAPTER_KEY = "telegram"

    def __init__(self, client: "AdapterClient") -> None:
        """Initialize Telegram adapter.

        Args:
            client: AdapterClient instance for event emission
        """
        super().__init__(client)

        # Store client for event emission (already set by parent, but keep for clarity)
        self.client = client

        # Get global config singleton
        # config already imported

        # Extract values from environment
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")
        self.bot_token: str = bot_token  # Guaranteed non-None after check

        supergroup_id_str = os.getenv("TELEGRAM_SUPERGROUP_ID")
        if not supergroup_id_str:
            raise ValueError("TELEGRAM_SUPERGROUP_ID environment variable not set")
        self.supergroup_id = int(supergroup_id_str)

        user_ids_str = os.getenv("TELEGRAM_USER_IDS", "")
        self.user_whitelist = [int(uid.strip()) for uid in user_ids_str.split(",") if uid.strip()]

        # Extract from config singleton
        self.trusted_dirs = config.computer.get_all_trusted_dirs()
        self.trusted_bots = config.telegram.trusted_bots

        self.computer_name = config.computer.name
        if not self.computer_name:
            raise ValueError("computer.name is required in config.yml")
        self.is_master = config.computer.is_master
        self.app: Optional[TelegramApp] = None
        self._processed_voice_messages: set[str] = set()  # Track processed voice message IDs with edit state
        self._topic_message_cache: dict[int | None, list[TelegramMessage]] = {}  # Cache for registry polling
        self._mcp_message_queues: dict[int, asyncio.Queue[object]] = {}  #  Event-driven MCP delivery: topic_id -> queue
        self._pending_edits: dict[str, EditContext] = {}  # Track pending edits (message_id -> mutable context)
        self._topic_creation_locks: dict[str, asyncio.Lock] = {}  # Prevent duplicate topic creation per session_id

        # Peer discovery state (heartbeat advertisement only)
        self.registry_message_id: Optional[int] = None  # Message ID for [REGISTRY] heartbeat message
        self.heartbeat_interval = 60  # Send heartbeat every 60s

    def _ensure_started(self) -> None:
        """Ensure adapter is started."""
        if not self.app:
            raise AdapterError("Telegram adapter not started - call start() first")

    @property
    def bot(self) -> ExtBot[None]:
        """Get bot instance (guaranteed non-None after start).

        Returns:
            Bot instance

        Raises:
            AdapterError: If adapter not started
        """
        if not self.app:
            raise AdapterError("Telegram adapter not started - call start() first")
        return self.app.bot

    def _is_message_from_trusted_bot(self, message: "TelegramMessage") -> bool:
        """Check if message is from a trusted bot (for AI-to-AI communication).

        Args:
            message: Telegram message object

        Returns:
            True if message is from a trusted bot, False otherwise
        """
        if not message or not message.from_user:
            return False

        # Check if sender is a bot
        if not message.from_user.is_bot:
            return False

        # Check if bot username is in trusted list
        bot_username = message.from_user.username
        if bot_username in self.trusted_bots:
            logger.debug("Message from trusted bot: %s", bot_username)
            return True

        logger.warning("Message from untrusted bot: %s", bot_username)
        return False

    def format_message(self, terminal_output: str, status_line: str) -> str:
        """Apply Telegram-specific formatting to shorten long separator lines.

        Overrides UiAdapter.format_message().
        Reduces sequences of 118 repeating chars to 47 chars.
        """
        message = super().format_message(terminal_output, status_line)

        lines = []
        for line in message.split("\n"):
            # Find sequences of exactly 118 repeating characters and reduce to 47
            # Pattern: captures any character repeated exactly 118 times
            modified_line = re.sub(r"(.)\1{117}", lambda m: m.group(1) * 47, line)  # type: ignore[misc]
            lines.append(modified_line)

        return "\n".join(lines)

    def _build_output_metadata(
        self, session: "Session", _is_truncated: bool, ux_state: SessionUXState
    ) -> MessageMetadata:
        """Build Telegram-specific metadata with inline keyboard for downloads.

        Overrides UiAdapter._build_output_metadata().
        Shows download button only when there's a Claude Code session to download.
        """
        # Add download button if Claude session available
        if ux_state.claude_session_file:
            keyboard = [
                [
                    InlineKeyboardButton(
                        "📎 Download Claude session", callback_data=f"download_full:{session.session_id}"
                    )
                ]
            ]
            return MessageMetadata(reply_markup=InlineKeyboardMarkup(keyboard))

        # No buttons - return empty metadata
        return MessageMetadata()

    async def start(self) -> None:  # pylint: disable=too-many-locals
        """Initialize and start Telegram bot."""
        # Create application with concurrent updates enabled
        # CRITICAL: concurrent_updates must be > 0 or updates can be silently dropped
        # when handlers are busy (e.g., during active polling)
        builder = Application.builder()  # type: ignore[misc]
        builder.token(self.bot_token)
        builder.concurrent_updates(True)  # Enable concurrent update processing
        self.app = builder.build()
        assert self.app is not None  # Help mypy - app is guaranteed non-None after build()
        assert self.app.updater is not None  # Updater is created by builder

        # Register command handlers
        # IMPORTANT: python-telegram-bot filter behavior (applies to ALL handler types):
        # - WITHOUT UpdateType filter: By default handles MESSAGES (new) in most handlers, but behavior varies
        # - Filters can be combined using bitwise operators: & (AND), | (OR), ~ (NOT)
        # - To handle BOTH new AND edited: Use filters.UpdateType.MESSAGE | filters.UpdateType.EDITED_MESSAGE
        #
        # For clarity and to prevent double-processing bugs, we explicitly specify filters:
        # - Use filters.UpdateType.MESSAGE for ONLY new messages
        # - Use filters.UpdateType.EDITED_MESSAGE for ONLY edited messages
        # - Use filters.UpdateType.MESSAGE | filters.UpdateType.EDITED_MESSAGE for BOTH
        for command_name, handler in self._get_command_handlers():
            # Handle both new and edited commands (explicit OR filter)
            cmd_handler: object = CommandHandler(
                command_name, handler, filters=filters.UpdateType.MESSAGE | filters.UpdateType.EDITED_MESSAGE  # type: ignore[arg-type]
            )
            self.app.add_handler(cmd_handler)  # type: ignore[arg-type]

        # Cache all commands (for registry discovery) - both new and edited
        # Group 1 so it runs AFTER CommandHandlers (which are in group 0)
        cache_handler: object = MessageHandler(
            filters.COMMAND
            & filters.ChatType.SUPERGROUP
            & (filters.UpdateType.MESSAGE | filters.UpdateType.EDITED_MESSAGE),
            self._cache_command_message,
        )
        self.app.add_handler(cache_handler, group=1)  # type: ignore[arg-type]

        # Handle text messages in topics (not commands) - both new and edited
        text_handler: object = MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.ChatType.SUPERGROUP
            & (filters.UpdateType.MESSAGE | filters.UpdateType.EDITED_MESSAGE),
            self._handle_text_message,
        )
        self.app.add_handler(text_handler)  # type: ignore[arg-type]

        # Handle callback queries from inline keyboards
        callback_handler: object = CallbackQueryHandler(self._handle_callback_query)
        self.app.add_handler(callback_handler)  # type: ignore[arg-type]

        # Handle voice messages in topics - both new and edited
        # NOTE: Do NOT add filters.ChatType.SUPERGROUP - it doesn't match forum topic messages (Telegram quirk)
        # Authorization is handled inside _handle_voice_message via _get_session_from_topic
        voice_handler: object = MessageHandler(
            filters.VOICE & (filters.UpdateType.MESSAGE | filters.UpdateType.EDITED_MESSAGE),
            self._handle_voice_message,
        )
        self.app.add_handler(voice_handler)  # type: ignore[arg-type]

        # Handle file attachments (documents, photos, etc.) in topics - both new and edited
        # NOTE: Do NOT add filters.ChatType.SUPERGROUP - it doesn't match forum topic messages (Telegram quirk)
        file_handler: object = MessageHandler(
            (filters.Document.ALL | filters.PHOTO) & (filters.UpdateType.MESSAGE | filters.UpdateType.EDITED_MESSAGE),
            self._handle_file_attachment,
        )
        self.app.add_handler(file_handler)  # type: ignore[arg-type]

        # Handle forum topic closed events
        closed_handler: object = MessageHandler(filters.StatusUpdate.FORUM_TOPIC_CLOSED, self._handle_topic_closed)
        reopened_handler: object = MessageHandler(
            filters.StatusUpdate.FORUM_TOPIC_REOPENED, self._handle_topic_reopened
        )
        self.app.add_handler(closed_handler)  # type: ignore[arg-type]
        self.app.add_handler(reopened_handler)  # type: ignore[arg-type]

        # Add catch-all handler to log ALL updates (for debugging)
        log_handler: object = MessageHandler(filters.ALL, self._log_all_updates)
        self.app.add_handler(log_handler, group=999)  # type: ignore[arg-type]

        # Register error handler to catch all exceptions
        self.app.add_error_handler(self._handle_error)

        # Start the bot
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

        # Get bot info for diagnostics
        bot_info = await self.bot.get_me()
        logger.info("Telegram adapter started. Bot: @%s (ID: %s)", bot_info.username, bot_info.id)
        logger.info("Configured supergroup ID: %s", self.supergroup_id)
        logger.info("Whitelisted user IDs: %s", self.user_whitelist)

        # Register bot commands with Telegram (only for master computer)
        if self.is_master:
            commands = [BotCommand(name + "  ", description) for name, description in UiCommands.items()]
            # Clear global commands first (removes old @BotName cached commands)
            await self.bot.set_my_commands([])
            # Set commands for the specific supergroup (not global)
            scope = BotCommandScopeChat(chat_id=self.supergroup_id)
            await self.bot.set_my_commands(commands, scope=scope)
            logger.info("Registered %d bot commands with Telegram for supergroup (master computer)", len(commands))
        else:
            # Non-master: Clear all commands (both global and supergroup)
            # This removes old cached commands that cause @BotName autocomplete
            await self.bot.set_my_commands([])  # Clear global commands
            scope = BotCommandScopeChat(chat_id=self.supergroup_id)
            await self.bot.set_my_commands([], scope=scope)  # Clear supergroup commands
            logger.info("Cleared all bot commands (non-master computer)")

        # Try to get chat info to verify bot is in the group
        try:
            chat = await self.bot.get_chat(self.supergroup_id)
            logger.info("Supergroup found: %s", chat.title)

            # Check if bot is admin
            bot_member = await self.bot.get_chat_member(self.supergroup_id, bot_info.id)
            logger.info("Bot status in group: %s", bot_member.status)
        except Exception as e:
            logger.error("Cannot access supergroup %s: %s", self.supergroup_id, e)
            logger.error("Make sure the bot is added to the group as a member!")

        # Restore registry_message_id from system UX state (for clean UX after restart)
        if db._db:  # Check connection exists
            system_state = await get_system_ux_state(db._db)
        else:
            raise AdapterError("Database connection not available")
        if system_state.registry.ping_message_id:
            self.registry_message_id = system_state.registry.ping_message_id
            logger.info("Restored registry_message_id from system UX state: %s", self.registry_message_id)

        # Start peer discovery heartbeat (advertisement only)
        logger.info("Starting peer discovery heartbeat loop")
        asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        """Stop Telegram bot."""
        if self.app and self.app.updater:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

    async def send_message(self, session: "Session", text: str, metadata: MessageMetadata) -> str:
        """Send message to session's topic with automatic retry on rate limits and network errors."""
        self._ensure_started()

        # Get Telegram's topic_id from namespaced metadata (trust contract)
        if not session.adapter_metadata or not session.adapter_metadata.telegram:
            raise AdapterError("Session missing telegram metadata")
        topic_id = session.adapter_metadata.telegram.topic_id

        # Extract reply_markup and parse_mode from metadata
        reply_markup = metadata.reply_markup  # type: ignore[misc]
        parse_mode = metadata.parse_mode

        # topic_id must be int (validated above)
        assert isinstance(topic_id, int), "topic_id must be int"

        # Send message with retry decorator handling errors
        message = await self._send_message_with_retry(topic_id, text, reply_markup, parse_mode)  # type: ignore[misc]
        return str(message.message_id)

    @command_retry(max_retries=3)
    async def _send_message_with_retry(
        self, topic_id: int, formatted_text: str, reply_markup: object, parse_mode: Optional[str]
    ) -> Message:
        """Internal method with retry logic for sending messages."""
        # Type guard for reply_markup
        if reply_markup is not None and not isinstance(
            reply_markup, (InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, ForceReply)
        ):
            reply_markup = None
        return await self.bot.send_message(
            chat_id=self.supergroup_id,
            message_thread_id=topic_id,
            text=formatted_text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )

    @command_retry(max_retries=3, max_timeout=15.0)
    async def _send_document_with_retry(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        chat_id: int,
        message_thread_id: int,
        file_path: str,
        filename: str,
        caption: Optional[str] = None,
    ) -> Message:
        """Internal method with retry logic for sending documents."""
        with open(file_path, "rb") as f:
            return await self.bot.send_document(
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                document=f,
                filename=filename,
                caption=caption,
                write_timeout=15.0,
                read_timeout=15.0,
            )

    async def edit_message(self, session: "Session", message_id: str, text: str, metadata: MessageMetadata) -> bool:
        """Edit an existing message with automatic retry on rate limits and network errors.

        Uses mutable EditContext to prevent stale data during retries:
        - If edit already pending: updates context with latest text (prevents stale timestamps)
        - Otherwise: creates new context and starts retry flow

        Retry logic (via @command_retry decorator on _edit_message_with_retry):
        - Rate limits (RetryAfter): Uses Telegram's suggested delay, keeps retrying until 60s timeout
        """
        self._ensure_started()

        # CRITICAL: Handle None message_id (happens during daemon restart)
        if not message_id:
            logger.warning("edit_message called with None message_id for session %s, ignoring", session.session_id[:8])
            return False

        # Extract reply_markup from metadata
        reply_markup = metadata.reply_markup  # type: ignore[misc]

        # CRITICAL FIX: Remove pending edit optimization - it causes race conditions where
        # subsequent updates return True without actually sending, leading to stuck messages.
        # Instead, cancel the pending edit and start fresh with latest data.
        if message_id in self._pending_edits:
            logger.debug("Cancelling stale edit for message %s, starting fresh with latest content", message_id)
            self._pending_edits.pop(message_id)  # Remove stale edit

        # Create new edit context (mutable)
        ctx = EditContext(message_id=message_id, text=text, reply_markup=reply_markup)  # type: ignore[misc]
        self._pending_edits[message_id] = ctx

        try:
            start_time = time.time()
            logger.debug("[TELEGRAM %s] Starting edit_message API call", session.session_id[:8])
            await self._edit_message_with_retry(session, ctx)
            elapsed = time.time() - start_time
            logger.debug("[TELEGRAM %s] edit_message completed in %.2fs", session.session_id[:8], elapsed)
            return True
        except BadRequest as e:
            # "Message is not modified" is benign - message exists, just unchanged
            # Return True to prevent clearing output_message_id (which would cause new messages)
            if "message is not modified" in str(e).lower():
                logger.debug("[TELEGRAM %s] Message not modified (content unchanged)", session.session_id[:8])
                return True
            # Other BadRequest errors (e.g., "Message to edit not found") are real failures
            logger.error("[TELEGRAM %s] edit_message failed: %s", session.session_id[:8], e)
            return False
        except Exception as e:
            logger.error("[TELEGRAM %s] edit_message failed after retries: %s", session.session_id[:8], e)
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
            parse_mode="Markdown",
            reply_markup=markup,
        )

    async def delete_message(self, session: "Session", message_id: str) -> bool:
        """Delete a message in the session's topic."""
        self._ensure_started()

        try:
            await self._delete_message_with_retry(message_id)
            return True
        except BadRequest as e:
            logger.warning("Failed to delete message %s: %s", message_id, e)
            return False
        except (NetworkError, TimedOut, RetryAfter, ConnectionError, TimeoutError) as e:
            logger.error("Failed to delete message %s after retries: %s", message_id, e)
            return False
        except Exception as e:
            logger.error("Failed to delete message %s: %s", message_id, e)
            return False

    @command_retry(max_retries=3)
    async def _delete_message_with_retry(self, message_id: str) -> None:
        """Delete message with retry logic."""
        await self.bot.delete_message(chat_id=self.supergroup_id, message_id=int(message_id))

    async def _pre_handle_user_input(self, session: "Session") -> None:
        """UI adapter pre-handler: Delete messages from previous interaction.

        Called by AdapterClient BEFORE processing new user input.
        Cleans up UI state from previous interaction (pending messages, idle notifications).

        Note: Feedback messages (pending_feedback_deletions) are NOT cleaned here.
        They get cleaned up when new feedback arrives via send_feedback(persistent=False).
        This allows download messages to persist until summary arrives.

        Args:
            session: Session object
        """
        logger.info("PRE-HANDLER CALLED for session %s", session.session_id[:8])
        # Delete pending user input messages from previous interaction
        pending = await db.get_pending_deletions(session.session_id)
        if pending:
            for msg_id in pending:
                try:
                    await self.delete_message(session, msg_id)
                    logger.debug("Deleted pending message %s for session %s", msg_id, session.session_id[:8])
                except Exception as e:
                    # Resilient to already-deleted messages
                    logger.warning("Failed to delete message %s: %s", msg_id, e)
            await db.clear_pending_deletions(session.session_id)

    async def _post_handle_user_input(self, session: "Session", message_id: str) -> None:
        """UI adapter post-handler: Track current message for next cleanup.

        Called by AdapterClient AFTER processing user input.
        Tracks current message ID so it can be deleted on next interaction.

        Args:
            session: Session object
            message_id: Current message ID to track for deletion
        """
        await db.add_pending_deletion(session.session_id, message_id)
        logger.debug("Tracked message %s for deletion on next input", message_id)

    async def send_file(
        self,
        session: "Session",
        file_path: str,
        metadata: MessageMetadata,
        caption: Optional[str] = None,
    ) -> str:
        """Send file to session's topic."""
        self._ensure_started()

        # Get topic_id from telegram metadata
        # Trust contract: metadata exists
        if not session.adapter_metadata or not session.adapter_metadata.telegram:
            raise AdapterError("Session missing telegram metadata")
        topic_id = session.adapter_metadata.telegram.topic_id

        with open(file_path, "rb") as f:
            message = await self.bot.send_document(
                chat_id=self.supergroup_id, message_thread_id=topic_id, document=f, caption=caption
            )

        return str(message.message_id)

    async def send_general_message(self, text: str, metadata: MessageMetadata) -> str:
        """Send message to Telegram supergroup general topic."""
        self._ensure_started()

        message_thread_id = metadata.message_thread_id
        parse_mode = metadata.parse_mode

        result = await self.bot.send_message(
            chat_id=self.supergroup_id, message_thread_id=message_thread_id, text=text, parse_mode=parse_mode
        )
        return str(result.message_id)

    async def create_channel(self, session: "Session", title: str, metadata: ChannelMetadata) -> str:
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
            if fresh_session and fresh_session.adapter_metadata and fresh_session.adapter_metadata.telegram:
                existing_topic_id = fresh_session.adapter_metadata.telegram.topic_id
                if existing_topic_id:
                    logger.warning(
                        "Session %s already has topic_id %s, returning existing (prevented duplicate)",
                        session_id[:8],
                        existing_topic_id,
                    )
                    return str(existing_topic_id)

            # Create topic (only one concurrent call per session_id can reach here)
            topic = await self.bot.create_forum_topic(chat_id=self.supergroup_id, name=title)

            topic_id = topic.message_thread_id
            logger.info("Created topic: %s (ID: %s)", title, topic_id)

            return str(topic_id)

    async def update_channel_title(self, session: "Session", title: str) -> bool:
        """Update topic title."""
        self._ensure_started()

        # Trust contract: metadata exists
        if not session.adapter_metadata or not session.adapter_metadata.telegram:
            raise AdapterError("Session missing telegram metadata")
        topic_id = session.adapter_metadata.telegram.topic_id
        assert isinstance(topic_id, int), "topic_id must be int"

        try:
            await self.bot.edit_forum_topic(chat_id=self.supergroup_id, message_thread_id=topic_id, name=title)
            return True
        except (RetryAfter, NetworkError, TimedOut):
            raise  # Let decorator handle retry
        except TelegramError as e:
            logger.error("Failed to update topic title: %s", e)
            return False

    async def close_channel(self, session: "Session") -> bool:
        """Soft-close forum topic (can be reopened)."""
        self._ensure_started()

        # Trust contract: metadata exists
        if not session.adapter_metadata or not session.adapter_metadata.telegram:
            raise AdapterError("Session missing telegram metadata")
        topic_id = session.adapter_metadata.telegram.topic_id
        assert isinstance(topic_id, int), "topic_id must be int"

        try:
            await self.bot.close_forum_topic(chat_id=self.supergroup_id, message_thread_id=topic_id)
            logger.info("Closed topic %s for session %s", topic_id, session.session_id[:8])
            return True
        except (RetryAfter, NetworkError, TimedOut):
            raise  # Let decorator handle retry
        except TelegramError as e:
            logger.warning("Failed to close topic %s: %s", topic_id, e)
            return False

    async def reopen_channel(self, session: "Session") -> bool:
        """Reopen a closed forum topic."""
        self._ensure_started()

        # Trust contract: metadata exists
        if not session.adapter_metadata or not session.adapter_metadata.telegram:
            raise AdapterError("Session missing telegram metadata")
        topic_id = session.adapter_metadata.telegram.topic_id
        assert isinstance(topic_id, int), "topic_id must be int"

        try:
            await self.bot.reopen_forum_topic(chat_id=self.supergroup_id, message_thread_id=topic_id)
            logger.info("Reopened topic %s for session %s", topic_id, session.session_id[:8])
            return True
        except (RetryAfter, NetworkError, TimedOut):
            raise  # Let decorator handle retry
        except TelegramError as e:
            logger.warning("Failed to reopen topic %s: %s", topic_id, e)
            return False

    async def delete_channel(self, session: "Session") -> bool:
        """Delete forum topic (permanent)."""
        self._ensure_started()

        # Trust contract: metadata exists
        if not session.adapter_metadata or not session.adapter_metadata.telegram:
            raise AdapterError("Session missing telegram metadata")
        topic_id = session.adapter_metadata.telegram.topic_id
        assert isinstance(topic_id, int), "topic_id must be int"

        try:
            await self.bot.delete_forum_topic(chat_id=self.supergroup_id, message_thread_id=topic_id)
            logger.info("Deleted topic %s for session %s", topic_id, session.session_id[:8])
            return True
        except (RetryAfter, NetworkError, TimedOut):
            raise  # Let decorator handle retry
        except TelegramError as e:
            logger.warning("Failed to delete topic %s: %s", topic_id, e)
            return False

    # ==================== Platform-Specific Parameters ====================

    def get_max_message_length(self) -> int:
        """Telegram's max message length is 4096 chars."""
        return 4096

    def get_ai_session_poll_interval(self) -> float:
        """Telegram AI sessions poll faster than human sessions.

        Returns:
            0.5 seconds for real-time AI communication.
        """
        return 0.5

    # ==================== Helper Methods ====================

    def _validate_update_for_command(self, update: Update) -> bool:
        """Check if update has required fields for command handling.

        Returns:
            True if update.effective_user and update.effective_message exist, False otherwise
        """
        return update.effective_user is not None and update.effective_message is not None

    def _event_to_command(self, event_name: str) -> str:
        """Convert event name to command name (underscores to hyphens).

        Args:
            event_name: Event name like "new_session" or "key_up"

        Returns:
            Command name like "new-session" or "key-up"
        """
        return event_name.replace("_", "-")

    def _build_project_keyboard(self, callback_prefix: str) -> InlineKeyboardMarkup:
        """Build inline keyboard for project selection.

        Uses index-based callbacks to stay under Telegram's 64-byte limit.

        Args:
            callback_prefix: Prefix for callback_data (e.g., "cd", "c", "cr")

        Returns:
            InlineKeyboardMarkup with buttons for each trusted directory
        """
        keyboard = []
        for idx, trusted_dir in enumerate(self.trusted_dirs):
            button_text = f"{trusted_dir.name} - {trusted_dir.desc}" if trusted_dir.desc else trusted_dir.name
            keyboard.append([InlineKeyboardButton(text=button_text, callback_data=f"{callback_prefix}:{idx}")])
        return InlineKeyboardMarkup(keyboard)

    async def _get_session_from_topic(self, update: Update) -> Optional[Session]:
        """Get session from current topic.

        Returns:
            Session object or None if not found/not authorized
        """
        # Check preconditions
        if not self._validate_update_for_command(update):
            return None

        # Check authorization
        user = update.effective_user
        if not user or user.id not in self.user_whitelist:
            return None

        # Get message (handles both regular and edited messages)
        message = update.effective_message
        if not message or not message.message_thread_id:
            return None

        thread_id = message.message_thread_id

        sessions = await db.get_sessions_by_adapter_metadata("telegram", "topic_id", thread_id)

        return sessions[0] if sessions else None

    # ==================== Message Handlers ====================

    async def _handle_new_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /new_session command."""
        if not self._validate_update_for_command(update) or not update.effective_chat:
            return

        user = update.effective_user
        if not user:
            return

        logger.debug("Received /new_session from user %s", user.id)

        # Check if authorized
        if user.id not in self.user_whitelist:
            logger.warning("User %s not in whitelist: %s", user.id, self.user_whitelist)
            return

        logger.debug("User authorized, emitting command with args: %s", context.args)

        # Emit command event to daemon
        await self.client.handle_event(
            event=TeleClaudeEvents.NEW_SESSION,
            payload={
                "command": self._event_to_command("new_session"),
                "args": context.args or [],
            },
            metadata=self._metadata(),
        )

    async def _handle_cancel(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /cancel command - sends CTRL+C to the session."""
        session = await self._get_session_from_topic(update)

        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=TeleClaudeEvents.CANCEL,
            payload={
                "command": self._event_to_command("cancel"),
                "args": [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_cancel2x(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /cancel2x command - sends CTRL+C twice (for stubborn programs like Claude Code)."""
        session = await self._get_session_from_topic(update)

        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=TeleClaudeEvents.CANCEL_2X,
            payload={
                "command": self._event_to_command("cancel2x"),
                "args": [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_kill(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /kill command - force kill foreground process with SIGKILL."""
        session = await self._get_session_from_topic(update)

        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=TeleClaudeEvents.KILL,
            payload={
                "command": self._event_to_command("kill"),
                "args": [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_escape(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /escape command - sends ESC key to the session, optionally followed by text+ENTER."""
        session = await self._get_session_from_topic(update)

        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=TeleClaudeEvents.ESCAPE,
            payload={
                "command": self._event_to_command("escape"),
                "args": context.args or [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_escape2x(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /escape2x command - sends ESC twice (for nested Vim, etc.), optionally followed by text+ENTER."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=TeleClaudeEvents.ESCAPE_2X,
            payload={
                "command": self._event_to_command("escape2x"),
                "args": context.args or [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_ctrl(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /ctrl command - sends CTRL+key to the session."""
        session = await self._get_session_from_topic(update)

        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=TeleClaudeEvents.CTRL,
            payload={
                "command": self._event_to_command("ctrl"),
                "args": context.args or [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_tab(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /tab command - sends TAB key to the session."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=TeleClaudeEvents.TAB,
            payload={
                "command": self._event_to_command("tab"),
                "args": [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_shift_tab(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /shift_tab command - sends SHIFT+TAB key to the session with optional count."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=TeleClaudeEvents.SHIFT_TAB,
            payload={
                "command": self._event_to_command("shift_tab"),
                "args": context.args or [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_backspace(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /backspace command - sends BACKSPACE key to the session with optional count."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=TeleClaudeEvents.BACKSPACE,
            payload={
                "command": self._event_to_command("backspace"),
                "args": context.args or [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_claude_plan(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /claude_plan command - alias for /shift_tab 3 (navigate to Claude Code plan mode)."""
        context.args = ["3"]
        await self._handle_shift_tab(update, context)

    async def _handle_enter(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /enter command - sends ENTER key to the session."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=TeleClaudeEvents.ENTER,
            payload={
                "command": self._event_to_command("enter"),
                "args": [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_key_up(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /key_up command - sends UP arrow key to the session."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=TeleClaudeEvents.KEY_UP,
            payload={
                "command": self._event_to_command("key_up"),
                "args": context.args or [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_key_down(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /key_down command - sends DOWN arrow key to the session."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=TeleClaudeEvents.KEY_DOWN,
            payload={
                "command": self._event_to_command("key_down"),
                "args": context.args or [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_key_left(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /key_left command - sends LEFT arrow key to the session."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=TeleClaudeEvents.KEY_LEFT,
            payload={
                "command": self._event_to_command("key_left"),
                "args": context.args or [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_key_right(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /key_right command - sends RIGHT arrow key to the session."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=TeleClaudeEvents.KEY_RIGHT,
            payload={
                "command": self._event_to_command("key_right"),
                "args": context.args or [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_resize(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /resize command - resize terminal."""
        session = await self._get_session_from_topic(update)

        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        # Get size argument
        size_arg = context.args[0] if context.args else None

        if not size_arg:
            # Track command message for deletion and show available presets
            await self._pre_handle_user_input(session)
            await db.add_pending_deletion(session.session_id, str(update.effective_message.message_id))
            current_size = session.terminal_size or "80x24"
            presets_text = f"""
**Terminal Size Presets:**

/resize small - 80x24 (classic)
/resize medium - 120x40 (comfortable)
/resize large - 160x60 (spacious)
/resize wide - 200x80 (ultrawide)

Current size: {current_size}
            """
            await self.send_feedback(session, presets_text, MessageMetadata(parse_mode="Markdown"))
            return

        # resize is adapter-specific - handled internally, no daemon event needed

    async def _handle_rename(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /rename command - rename session."""
        logger.info("_handle_rename called with args: %s", context.args)
        session = await self._get_session_from_topic(update)
        if not session:
            logger.warning("_handle_rename: No session found")
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        # Check if name argument provided
        if not context.args:
            # Track command message for deletion
            await self._pre_handle_user_input(session)
            await db.add_pending_deletion(session.session_id, str(update.effective_message.message_id))
            await self.send_feedback(session, "Usage: /rename <new name>", MessageMetadata())
            return

        await self.client.handle_event(
            event=TeleClaudeEvents.RENAME,
            payload={
                "command": self._event_to_command("rename"),
                "args": context.args or [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_cd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /cd command - change directory or list trusted directories."""
        session = await self._get_session_from_topic(update)

        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        # If args provided, change to that directory
        if context.args:
            await self.client.handle_event(
                event=TeleClaudeEvents.CD,
                payload={
                    "command": self._event_to_command("cd"),
                    "args": context.args or [],
                    "session_id": session.session_id,
                    "message_id": str(update.effective_message.message_id),
                },
                metadata=self._metadata(),
            )
            return

        # No args - show trusted directories as buttons (track command message for deletion)
        await self._pre_handle_user_input(session)
        await db.add_pending_deletion(session.session_id, str(update.effective_message.message_id))
        reply_markup = self._build_project_keyboard("cd")
        await self.send_feedback(
            session, "**Select a directory:**", MessageMetadata(reply_markup=reply_markup, parse_mode="Markdown")
        )

    async def _handle_claude(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /claude command - start Claude Code with optional flags."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=TeleClaudeEvents.CLAUDE,
            payload={
                "command": self._event_to_command("claude"),
                "args": context.args or [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_claude_resume(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /claude_resume command - resume last Claude Code session."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=TeleClaudeEvents.CLAUDE_RESUME,
            payload={
                "command": self._event_to_command("claude_resume"),
                "args": [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_claude_restart(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /claude_restart command - restart Claude in this session."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        # Track user's command message for deletion (cleanup old pending first)
        await self._pre_handle_user_input(session)
        await db.add_pending_deletion(session.session_id, str(update.effective_message.message_id))

        # Get Claude session ID from ux_state
        ux_state = await db.get_ux_state(session.session_id)
        claude_session_id = ux_state.claude_session_id

        if not claude_session_id:
            await self.send_feedback(session, "❌ No Claude Code session found in this topic", MessageMetadata())
            return

        try:
            # Execute restart script via Python module
            project_root = Path(__file__).parent.parent.parent
            python_path = project_root / ".venv" / "bin" / "python"

            result = subprocess.run(
                [str(python_path), "-m", "teleclaude.restart_claude"],
                env={**os.environ, "TELECLAUDE_SESSION_ID": session.session_id},
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            if result.returncode == 0:
                await self.send_feedback(session, "✅ Claude Code restarted successfully", MessageMetadata())
            else:
                # Combine stdout and stderr for complete error context
                error_parts = []
                if result.stdout and result.stdout.strip():
                    error_parts.append(result.stdout.strip())
                if result.stderr and result.stderr.strip():
                    error_parts.append(result.stderr.strip())
                error_msg = "\n".join(error_parts) if error_parts else f"Exit code: {result.returncode}"
                await self.send_feedback(session, f"❌ Failed to restart:\n{error_msg}", MessageMetadata())
        except subprocess.TimeoutExpired:
            await self.send_feedback(session, "⏱️ Restart script timed out", MessageMetadata())
        except Exception as e:
            await self.send_feedback(session, f"❌ Error: {str(e)}", MessageMetadata())

    async def _handle_callback_query(
        self, update: Update, _context: ContextTypes.DEFAULT_TYPE
    ) -> None:  # pylint: disable=too-many-locals
        """Handle button clicks from inline keyboards."""
        query = update.callback_query
        if not query:
            return
        await query.answer()

        # Parse callback data
        data = query.data
        if not data or ":" not in data:
            return

        action, *args = data.split(":", 1)

        if action == "download_full":
            # Download full output (terminal or Claude Code session)
            session_id = args[0] if args else None
            if not session_id or not query.message:
                return

            try:
                # Check if there's a Claude Code session transcript
                ux_state = await db.get_ux_state(session_id)
                claude_session_file = ux_state.claude_session_file if ux_state else None

                # Get session for metadata
                session = await db.get_session(session_id)
                if not session:
                    return

                # Clean up previous feedback messages (notifications, etc.) before sending download
                await self.cleanup_feedback_messages(session)

                # Convert Claude transcript to markdown
                if not claude_session_file:
                    await query.edit_message_text("❌ No Claude session file found", parse_mode="Markdown")
                    return
                markdown_content = parse_claude_transcript(claude_session_file, session.title, tail_chars=0)
                filename = f"claude-{session_id:8}.md"
                caption = "Claude Code session transcript"

                # Create a temporary file to send
                with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tmp:
                    tmp.write(markdown_content)
                    tmp_path = tmp.name

                try:
                    # Send as document with retry logic (artifact - not tracked for deletion)
                    msg = query.message
                    if not isinstance(msg, Message):  # Type guard
                        return
                    msg_thread_id = msg.message_thread_id
                    assert isinstance(msg_thread_id, int), "message_thread_id must be int"
                    doc_message = await self._send_document_with_retry(
                        chat_id=msg.chat_id,
                        message_thread_id=msg_thread_id,
                        file_path=tmp_path,
                        filename=filename,
                        caption=caption,
                    )
                finally:
                    # Clean up temp file
                    Path(tmp_path).unlink()

                # Track download message for cleanup when next feedback arrives
                await db.add_pending_feedback_deletion(session_id, str(doc_message.message_id))
            except Exception as e:
                logger.error("Failed to send output file: %s", e)
                await query.edit_message_text(f"❌ Error sending file: {e}", parse_mode="Markdown")

        elif action == "ss":
            # Handle quick session start from heartbeat button
            # Short code: ss = start session
            if not query.from_user:
                return

            # Check if authorized
            if query.from_user.id not in self.user_whitelist:
                await query.answer("❌ Not authorized", show_alert=True)
                return

            # Emit NEW_SESSION event directly (no visible command message)
            result_obj = await self.client.handle_event(
                event=TeleClaudeEvents.NEW_SESSION,
                payload={
                    "args": [],
                },
                metadata=self._metadata(),
            )

            # Cast result to HandleEventResult for type checking
            result = cast(HandleEventResult, result_obj)

            # Acknowledge the button click
            await query.answer("Creating session...", show_alert=False)

            # Send confirmation message in General topic with link to new session
            if result.get("status") == "success":
                data_obj = result.get("data", {})
                if isinstance(data_obj, dict):
                    event_data = cast(HandleEventData, data_obj)
                    session_id_val = event_data.get("session_id")
                    if session_id_val and isinstance(session_id_val, str):
                        new_session = await db.get_session(session_id_val)
                        if new_session and new_session.adapter_metadata and new_session.adapter_metadata.telegram:
                            topic_id = new_session.adapter_metadata.telegram.topic_id
                            # Build deep link to the topic
                            # supergroup_id is negative, strip the -100 prefix for the link
                            chat_id_str = str(self.supergroup_id)
                            if chat_id_str.startswith("-100"):
                                chat_id_for_link = chat_id_str[4:]
                            else:
                                chat_id_for_link = chat_id_str.lstrip("-")
                            topic_url = f"https://t.me/c/{chat_id_for_link}/{topic_id}"
                            await self.bot.send_message(
                                chat_id=self.supergroup_id,
                                text=f"✅ Created: {new_session.title}",
                                reply_markup=InlineKeyboardMarkup(
                                    [[InlineKeyboardButton("Open Session", url=topic_url)]]
                                ),
                            )

        elif action == "cd":
            # Find session from the message's thread
            msg = query.message  # type: ignore[assignment]
            if not msg or not isinstance(msg, Message) or not query.from_user:
                return
            thread_id = msg.message_thread_id
            if not thread_id:
                return
            sessions = await db.get_sessions_by_adapter_metadata("telegram", "topic_id", thread_id)

            if not sessions:
                return

            session = sessions[0]

            # Get project by index (callbacks are now index-based for 64-byte limit)
            try:
                project_idx = int(args[0]) if args else -1
                if project_idx < 0 or project_idx >= len(self.trusted_dirs):
                    await query.answer("❌ Invalid directory", show_alert=True)
                    return
                dir_path = self.trusted_dirs[project_idx].path
            except (ValueError, IndexError):
                await query.answer("❌ Invalid directory selection", show_alert=True)
                return

            # Emit cd command
            await self.client.handle_event(
                event=TeleClaudeEvents.CD,
                payload={
                    "args": [dir_path],
                    "session_id": session.session_id,
                },
                metadata=self._metadata(),
            )

            # Update the message to show what was selected
            await query.edit_message_text(f"Changing directory to: `{dir_path}`", parse_mode="Markdown")

        elif action in ("csel", "crsel"):
            # Show project selection for Claude/Claude Resume
            # Short codes: csel = claude select, crsel = claude resume select
            if not query.from_user or not query.message:
                return

            # Check if authorized
            if query.from_user.id not in self.user_whitelist:
                await query.answer("❌ Not authorized", show_alert=True)
                return

            # Determine which Claude mode (new or resume)
            # Use short callback prefix: c = claude, cr = claude resume
            callback_prefix = "c" if action == "csel" else "cr"

            # Build keyboard with trusted directories using helper
            reply_markup = self._build_project_keyboard(callback_prefix)

            # Add cancel button to return to original view
            bot_info = await self.bot.get_me()
            keyboard: list[tuple[InlineKeyboardButton, ...]] = list(reply_markup.inline_keyboard)
            keyboard.append(
                tuple([InlineKeyboardButton(text="❌ Cancel", callback_data=f"ccancel:{bot_info.username}")])
            )

            reply_markup = InlineKeyboardMarkup(keyboard)
            mode_label = "Claude" if action == "csel" else "Claude Resume"
            await query.edit_message_text(
                f"**Select project for {mode_label}:**", reply_markup=reply_markup, parse_mode="Markdown"
            )

        elif action == "ccancel":
            # Return to original heartbeat view with all buttons
            # Short code: ccancel = claude cancel
            bot_username = args[0] if args else None
            if bot_username is None:
                return
            reply_markup = self._build_heartbeat_keyboard(bot_username)
            text = f"[REGISTRY] {self.computer_name} last seen at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            await query.edit_message_text(text, reply_markup=reply_markup)

        elif action in ("c", "cr"):
            # Create session in selected project and start Claude
            # Short codes: c = claude, cr = claude resume
            # Callback format: c:INDEX or cr:INDEX where INDEX is into trusted_dirs
            if not query.from_user:
                return

            # Check if authorized
            if query.from_user.id not in self.user_whitelist:
                await query.answer("❌ Not authorized", show_alert=True)
                return

            # Get project by index
            try:
                project_idx = int(args[0]) if args else -1
                if project_idx < 0 or project_idx >= len(self.trusted_dirs):
                    await query.answer("❌ Invalid project", show_alert=True)
                    return
                project_path = self.trusted_dirs[project_idx].path
            except (ValueError, IndexError):
                await query.answer("❌ Invalid project selection", show_alert=True)
                return

            # Acknowledge immediately
            mode_label = "Claude" if action == "c" else "Claude Resume"
            await query.answer(f"Creating session with {mode_label}...", show_alert=False)

            # Emit NEW_SESSION event with project_dir and auto_command in metadata
            # This creates session AND starts Claude in one flow
            claude_event = TeleClaudeEvents.CLAUDE if action == "c" else TeleClaudeEvents.CLAUDE_RESUME
            await self.client.handle_event(
                event=TeleClaudeEvents.NEW_SESSION,
                payload={
                    "args": [],
                },
                metadata=self._metadata(project_dir=project_path, auto_command=claude_event),
            )

    # ==================== Peer Discovery Methods ====================

    async def _heartbeat_loop(self) -> None:
        """Send heartbeat every N seconds to General topic."""
        # Send initial heartbeat
        try:
            await self._send_heartbeat()
        except Exception as e:
            logger.error("Initial heartbeat failed: %s", e)

        # Then send every heartbeat_interval seconds
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                await self._send_heartbeat()
                logger.debug("Heartbeat sent for %s", self.computer_name)
            except Exception as e:
                logger.error("Heartbeat failed: %s", e)

    def _build_heartbeat_keyboard(self, bot_username: str) -> InlineKeyboardMarkup:
        """Build the standard heartbeat keyboard with session and Claude buttons.

        Using short callback codes to stay under Telegram's 64-byte limit:
        - ss = start session
        - csel = claude select (new session)
        - crsel = claude resume select
        """
        keyboard = [
            [InlineKeyboardButton(text="🚀 Terminal Session", callback_data=f"ss:{bot_username}")],
            [
                InlineKeyboardButton(text="🤖 New Claude", callback_data=f"csel:{bot_username}"),
                InlineKeyboardButton(text="🔄 Resume Claude", callback_data=f"crsel:{bot_username}"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    async def _send_heartbeat(self) -> None:
        """Send or edit [REGISTRY] heartbeat message in General topic."""
        text = f"[REGISTRY] {self.computer_name} last seen at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        # Get bot info for @mention
        bot_info = await self.bot.get_me()
        bot_username = bot_info.username
        if bot_username is None:
            logger.error("Bot username is None, cannot build heartbeat keyboard")
            return

        reply_markup = self._build_heartbeat_keyboard(bot_username)

        if self.registry_message_id is None:
            # First time - post new message to General topic (thread_id=None) with button
            try:
                logger.debug(
                    "Attempting to send heartbeat - chat_id=%s, message_thread_id=None, text=%s",
                    self.supergroup_id,
                    text[:50],
                )
                msg = await self.bot.send_message(
                    chat_id=self.supergroup_id,
                    message_thread_id=None,  # General topic
                    text=text,
                    reply_markup=reply_markup,
                )
                self.registry_message_id = msg.message_id
                logger.info("Posted registry heartbeat with button: message_id=%s", self.registry_message_id)

                # Persist to system UX state (for clean UX after restart)
                if db._db:
                    await update_system_ux_state(db._db, registry_ping_message_id=self.registry_message_id)
            except BadRequest as e:
                logger.error("Failed to post heartbeat - Full error details: %s", e)
                logger.error("Error type: %s, Error message: %s", type(e).__name__, str(e))
                raise
            except Exception as e:
                logger.error("Failed to post heartbeat: %s", e)
                raise
        else:
            # Edit existing message (keep General topic clean)
            try:
                edited_message_result = await self.bot.edit_message_text(
                    chat_id=self.supergroup_id,
                    message_id=self.registry_message_id,
                    text=text,
                    reply_markup=reply_markup,
                )
                if not isinstance(edited_message_result, Message):
                    # If edit returns True (message unchanged), skip cache update
                    return
                edited_message = edited_message_result
                # Self-cache the edited message (bots don't get updates for their own edits)
                topic_id = None  # General topic
                if topic_id not in self._topic_message_cache:
                    self._topic_message_cache[topic_id] = []
                # Replace old version
                self._topic_message_cache[topic_id] = [
                    m for m in self._topic_message_cache[topic_id] if m.message_id != self.registry_message_id
                ]
                self._topic_message_cache[topic_id].append(edited_message)
                logger.debug("Updated registry heartbeat: message_id=%s", self.registry_message_id)
            except Exception as e:
                error_lower = str(e).lower()
                # If message was deleted, post new one
                if "message to edit not found" in error_lower or "message not found" in error_lower:
                    logger.warning("Registry message deleted, posting new one")
                    self.registry_message_id = None
                    await self._send_heartbeat()
                else:
                    logger.error("Failed to edit heartbeat: %s", e)
                    raise

    async def discover_peers(self) -> list[PeerInfo]:
        """Discover peers via Telegram adapter.

        NOTE: Due to Telegram Bot API restrictions, bots cannot see messages
        from other bots. Therefore, TelegramAdapter only ADVERTISES this computer's
        presence via heartbeat messages (visible to humans in Telegram UI), but
        cannot discover other computers.

        Actual peer discovery must be handled by other adapters (e.g., RedisAdapter)
        that support bot-to-bot communication.

        Returns:
            Empty list (Telegram doesn't support bot-to-bot discovery)
        """
        return []

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
1. Use /new_session to create a terminal session
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
                update.effective_message.message_thread_id if update.effective_message else None,
                update.effective_user.id if update.effective_user else None,
                (
                    update.effective_message.text[:50]
                    if update.effective_message and update.effective_message.text
                    else None
                ),
            )
            return
        if not update.effective_message or not update.effective_user:
            logger.warning("Missing effective_message or effective_user in update")
            return

        text = update.effective_message.text
        if not text:
            return

        # Strip leading // and replace with / (Telegram workaround - only at start of input)
        # Double slash bypasses Telegram command detection AND skips HUMAN: prefix
        # so the raw command goes directly to Claude Code
        skip_human_prefix = False
        if text.startswith("//"):
            text = "/" + text[2:]
            skip_human_prefix = True
            logger.debug("Stripped leading // from user input (raw mode), result: %s", text[:50])

        # Format with HUMAN: prefix unless bypassed via // prefix
        formatted_text = text if skip_human_prefix else self.format_user_input(text)

        await self.client.handle_event(
            event=TeleClaudeEvents.MESSAGE,
            payload={
                "session_id": session.session_id,
                "text": formatted_text,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

    async def _handle_voice_message(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle voice messages in topics - both new and edited messages."""
        # Handle both regular messages and edited messages
        message = update.effective_message
        if not message or not update.effective_user:
            return

        logger.info("=== VOICE MESSAGE HANDLER CALLED ===")
        logger.info("Message ID: %s (edited: %s)", message.message_id, update.edited_message is not None)
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
            logger.warning("No session found for voice message in thread %s", message.message_thread_id)
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

            # Delete the voice message from Telegram (keep UI clean)
            try:
                await message.delete()
                logger.debug("Deleted voice message %s from Telegram", message.message_id)
            except Exception as e:
                logger.warning("Failed to delete voice message %s: %s", message.message_id, e)

            # Emit voice event to daemon
            await self.client.handle_event(
                event=TeleClaudeEvents.VOICE,
                payload={"session_id": session.session_id, "file_path": str(temp_file_path)},
                metadata=self._metadata(),
            )
        except Exception as e:
            error_msg = str(e) if str(e).strip() else "Unknown error"
            logger.error("Failed to download voice message: %s", error_msg)
            await self.send_feedback(session, f"❌ Failed to download voice message: {error_msg}", MessageMetadata())

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
        file_type: str | None = None

        if message.document:
            file_obj = message.document
            file_name = message.document.file_name or f"document_{message.message_id}"
            file_type = "document"
        elif message.photo:
            # Photos come as array, get largest one
            file_obj = message.photo[-1]  # PhotoSize, not Document
            file_name = f"photo_{message.message_id}.jpg"
            file_type = "photo"

        if not file_obj:
            return

        # Determine subdirectory based on file type
        subdir = "photos" if file_type == "photo" else "files"
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

            # Emit file event to daemon (with optional caption)
            await self.client.handle_event(
                event=TeleClaudeEvents.FILE,
                payload={
                    "session_id": session.session_id,
                    "file_path": str(file_path),
                    "filename": file_name,
                    "file_type": file_type,
                    "file_size": file_obj.file_size if hasattr(file_obj, "file_size") else 0,
                    "caption": message.caption.strip() if message.caption else None,
                },
                metadata=self._metadata(),
            )
        except Exception as e:
            # Log detailed error for debugging
            logger.error("Failed to download %s: %s", file_type, str(e))

            # Send user-friendly error message (plain text, no Markdown parsing)
            message_id = await self.client.send_message(
                session,
                f"❌ Failed to upload {file_type}",
                metadata=self._metadata(parse_mode=""),
            )
            if message_id:
                await db.add_pending_deletion(session.session_id, message_id)

    async def _handle_topic_closed(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle forum topic closed event."""
        if not update.message or not update.message.message_thread_id:
            return

        topic_id = update.message.message_thread_id

        sessions = await db.get_sessions_by_adapter_metadata("telegram", "topic_id", topic_id)

        if not sessions:
            logger.warning("No session found for closed topic %s", topic_id)
            return

        session = sessions[0]
        logger.info("Topic %s closed by user, closing session %s", topic_id, session.session_id[:8])

        # Emit session_closed event to daemon for cleanup
        await self.client.handle_event(
            event="session_closed",
            payload={"session_id": session.session_id},
            metadata=self._metadata(),
        )

    async def _handle_topic_reopened(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle forum topic reopened event."""
        if not update.message or not update.message.message_thread_id:
            return

        topic_id = update.message.message_thread_id

        # Find session by topic ID (try both formats)
        sessions = await db.get_sessions_by_adapter_metadata("telegram", "topic_id", topic_id)

        if not sessions:
            logger.warning("No session found for reopened topic %s", topic_id)
            return

        session = sessions[0]
        logger.info("Topic %s reopened by user, reopening session %s", topic_id, session.session_id[:8])

        # Emit session_reopened event to daemon
        await self.client.handle_event(
            event="session_reopened",
            payload={"session_id": session.session_id},
            metadata=self._metadata(),
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

    # === MCP Server Support Methods ===

    async def create_topic(self, title: str) -> object:
        """Create a new forum topic and return the topic object."""
        self._ensure_started()
        topic = await self.bot.create_forum_topic(chat_id=self.supergroup_id, name=title)
        logger.info("Created topic: %s (ID: %s)", title, topic.message_thread_id)
        return topic

    async def get_all_topics(self) -> list[object]:
        """Get all forum topics in the supergroup.

        Note: Telegram Bot API doesn't have a direct method to list all forum topics.
        This implementation uses a workaround by searching through recent updates.
        For now, we return empty list and rely on database persistence instead.
        """
        self._ensure_started()

        # Workaround: Check if we have cached topic info in database
        # The registry will store its topic_id and reuse it across restarts
        # For MVP, we'll implement database-backed persistence instead of API polling

        return []

    async def send_message_to_topic(
        self, topic_id: Optional[int], text: str, parse_mode: Optional[str] = "Markdown"
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
        # Build kwargs with explicit typing
        if topic_id is not None:
            message = await self.bot.send_message(
                chat_id=self.supergroup_id,
                message_thread_id=topic_id,
                text=text,
                parse_mode=parse_mode,
            )
        else:
            message = await self.bot.send_message(
                chat_id=self.supergroup_id,
                text=text,
                parse_mode=parse_mode,
            )

        # Cache the message we just sent (for registry polling)
        # Messages we send ourselves won't appear in updates, so we cache them manually
        if topic_id not in self._topic_message_cache:
            self._topic_message_cache[topic_id] = []
        self._topic_message_cache[topic_id].append(message)
        if len(self._topic_message_cache[topic_id]) > 100:
            self._topic_message_cache[topic_id].pop(0)

        return message

    async def register_mcp_listener(self, topic_id: int) -> asyncio.Queue[object]:
        """Register MCP listener queue for instant message delivery.

        When messages arrive for this topic_id, they'll be pushed to the queue.
        This enables event-driven message delivery for MCP (zero latency).

        Args:
            topic_id: Telegram message_thread_id to listen to

        Returns:
            Queue that will receive Message objects as they arrive

        Note:
            Caller MUST call unregister_mcp_listener() when done to avoid leaks.
            Use try/finally pattern to ensure cleanup.
        """
        self._ensure_started()

        queue: asyncio.Queue[object] = asyncio.Queue()
        self._mcp_message_queues[topic_id] = queue
        logger.info("Registered MCP listener for topic %s", topic_id)
        return queue

    async def unregister_mcp_listener(self, topic_id: int) -> None:
        """Unregister MCP listener queue.

        Args:
            topic_id: Telegram message_thread_id to stop listening to
        """
        self._mcp_message_queues.pop(topic_id, None)
        logger.info("Unregistered MCP listener for topic %s", topic_id)

    async def get_topic_messages(self, topic_id: Optional[int], limit: int = 100) -> list[Message]:
        """Get recent messages from a specific topic or General topic using in-memory cache.

        Messages are cached in _handle_text_message as they arrive.
        This is used by computer_registry to poll the registry topic.

        For real-time MCP delivery, use register_mcp_listener() instead.

        Args:
            topic_id: Telegram message_thread_id. Use None for General topic.
            limit: Maximum number of messages to return (default: 100)

        Returns:
            List of Telegram Message objects from the cache (most recent first)
        """
        self._ensure_started()

        # Return cached messages for this topic (None = General topic)
        cached = self._topic_message_cache.get(topic_id, [])
        # Return last N messages (most recent first)
        return list(reversed(cached[-limit:]))

    # ==================== AI-to-AI Communication ====================

    async def poll_output_stream(  # type: ignore[override,misc]
        self,
        session: "Session",
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        """Poll for output chunks (not implemented for Telegram).

        Telegram doesn't support bidirectional streaming like Redis.
        This method is only implemented in RedisAdapter.

        Args:
            session: Session object
            timeout: Max seconds to wait

        Raises:
            NotImplementedError: Telegram doesn't support output streaming
        """
        raise NotImplementedError("Telegram adapter does not support poll_output_stream")
        # This yield is unreachable but satisfies mypy's async generator requirements
        yield ""  # pylint: disable=unreachable

    # UiAdapter methods inherited from base class (can override for Telegram-specific UX)
