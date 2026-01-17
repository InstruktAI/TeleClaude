"""Telegram adapter for TeleClaude."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import TYPE_CHECKING, AsyncIterator, Optional, TypedDict, cast

import httpx
from instrukt_ai_logging import get_logger

if TYPE_CHECKING:
    from telegram import Message as TelegramMessage

    from teleclaude.core.adapter_client import AdapterClient

from telegram import (
    BotCommand,
    BotCommandScopeChat,
    ForumTopic,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.error import BadRequest
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
from telegram.request import HTTPXRequest

from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.events import EventType, TeleClaudeEvents, UiCommands
from teleclaude.core.models import (
    MessageMetadata,
    PeerInfo,
    Session,
)
from teleclaude.core.ux_state import (
    get_system_ux_state,
    update_system_ux_state,
)

from .base_adapter import AdapterError
from .telegram.callback_handlers import CallbackHandlersMixin
from .telegram.channel_ops import ChannelOperationsMixin
from .telegram.command_handlers import CommandHandlersMixin
from .telegram.input_handlers import InputHandlersMixin
from .telegram.message_ops import EditContext, MessageOperationsMixin
from .ui_adapter import UiAdapter

# Status emoji mapping
STATUS_EMOJI = {
    "active": "🟢",
    "waiting": "🟡",
    "slow": "🟠",
    "stalled": "🔴",
    "idle": "⏸️",
    "dead": "❌",
}


# TypedDicts for JSON/dict structures with known schemas
class HandleEventResult(TypedDict, total=False):
    """Result from client.handle_event() calls."""

    status: str
    data: dict[str, object]  # noqa: loose-dict - Nested data structure varies by event type


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

logger = get_logger(__name__)


class TelegramAdapter(
    InputHandlersMixin,
    CommandHandlersMixin,
    CallbackHandlersMixin,
    MessageOperationsMixin,
    ChannelOperationsMixin,
    UiAdapter,
):  # pylint: disable=too-many-instance-attributes  # Telegram adapter manages many handlers and state
    """Telegram bot adapter using python-telegram-bot."""

    ADAPTER_KEY = "telegram"
    COMMAND_HANDLER_OVERRIDES = {"agent_resume": "_handle_agent_resume_command"}

    # Simple commands that just emit an event with session_id, args, and message_id.
    # These are generated dynamically via _handle_simple_command template.
    # Format: list of event constants from TeleClaudeEvents (event value = command name)
    SIMPLE_COMMAND_EVENTS: list[EventType] = [
        TeleClaudeEvents.CANCEL,
        TeleClaudeEvents.CANCEL_2X,
        TeleClaudeEvents.KILL,
        TeleClaudeEvents.TAB,
        TeleClaudeEvents.ENTER,
        TeleClaudeEvents.ESCAPE,
        TeleClaudeEvents.ESCAPE_2X,
        TeleClaudeEvents.CTRL,
        TeleClaudeEvents.SHIFT_TAB,
        TeleClaudeEvents.BACKSPACE,
        TeleClaudeEvents.KEY_UP,
        TeleClaudeEvents.KEY_DOWN,
        TeleClaudeEvents.KEY_LEFT,
        TeleClaudeEvents.KEY_RIGHT,
    ]

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
        self.user_whitelist = {int(uid.strip()) for uid in user_ids_str.split(",") if uid.strip()}

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
        self._topic_ready_events: dict[int, asyncio.Event] = {}  # topic_id -> readiness event
        self._topic_ready_cache: set[int] = set()  # topic_ids confirmed via forum_topic_created

        # Peer discovery state (heartbeat advertisement only)
        self.registry_message_id: Optional[int] = None  # Message ID for [REGISTRY] heartbeat message
        self.heartbeat_interval = 60  # Send heartbeat every 60s

        # Register simple command handlers dynamically
        self._register_simple_command_handlers()

    def _register_simple_command_handlers(self) -> None:
        """Create handler methods for simple commands dynamically.

        For each event in SIMPLE_COMMAND_EVENTS, creates a _handle_{command_name} method
        that calls the shared _handle_simple_command template.
        """
        for event in self.SIMPLE_COMMAND_EVENTS:
            command_name = event  # Event value IS the command name (e.g., "cancel", "kill")
            handler_name = f"_handle_{command_name}"

            # Create a closure that captures the event value
            def make_handler(
                evt: EventType,
            ) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[object, object, None]]:
                async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
                    await self._handle_simple_command(update, context, evt)

                return handler

            setattr(self, handler_name, make_handler(event))

    async def delete_message(self, session: "Session | str", message_id: str) -> bool:
        """Delete a message by session or session_id."""
        if isinstance(session, str):
            session_obj = await db.get_session(session)
            if not session_obj:
                return False
        else:
            session_obj = session
        return await MessageOperationsMixin.delete_message(self, session_obj, message_id)

    async def _handle_simple_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, event: EventType
    ) -> None:
        """Template method for simple session commands.

        Handles commands that just emit an event with session_id, args, and message_id.
        """
        session = await self._get_session_from_topic(update)
        if not session:
            return

        assert update.effective_user is not None
        assert update.effective_message is not None

        await self.client.handle_event(
            event=event,
            payload={
                "command": self._event_to_command(event),
                "args": context.args or [],
                "session_id": session.session_id,
                "message_id": str(update.effective_message.message_id),
            },
            metadata=self._metadata(),
        )

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

    def format_message(self, tmux_output: str, status_line: str) -> str:
        """Apply Telegram-specific formatting to shorten long separator lines.

        Overrides UiAdapter.format_message().
        Reduces sequences of 118 repeating chars to 47 chars.
        """
        message = super().format_message(tmux_output, status_line)

        lines = []
        for line in message.split("\n"):
            # Find sequences of exactly 118 repeating characters and reduce to 47
            # Pattern: captures any character repeated exactly 118 times
            modified_line = re.sub(r"(.)\1{117}", lambda m: m.group(1) * 47, line)  # type: ignore[misc]
            lines.append(modified_line)

        return "\n".join(lines)

    def _build_output_metadata(self, session: "Session", _is_truncated: bool) -> MessageMetadata:
        """Build Telegram-specific metadata with inline keyboard for downloads.

        Overrides UiAdapter._build_output_metadata().
        Shows download button only when there's an Agent session to download.
        """
        # Add download button if Agent session available
        if session.native_log_file:
            keyboard = [
                [
                    InlineKeyboardButton(
                        "📎 Download Agent session",
                        callback_data=f"download_full:{session.session_id}",
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
        # Force IPv4 for Telegram API calls. Some networks advertise IPv6 (AAAA) without
        # providing a working IPv6 route, which can cause connect timeouts inside httpx.
        httpx_kwargs = cast(
            dict[str, object],  # noqa: loose-dict - Telegram Bot API httpx kwargs
            {"transport": httpx.AsyncHTTPTransport(local_address="0.0.0.0")},
        )
        builder.request(HTTPXRequest(httpx_kwargs=httpx_kwargs))
        builder.concurrent_updates(True)  # Enable concurrent update processing
        self.app = builder.build()
        assert self.app is not None  # Help mypy - app is guaranteed non-None after build()
        assert self.app.updater is not None  # Updater is created by builder

        # Register command handlers
        # IMPORTANT: For commands, handle ONLY new messages.
        # Edited command updates can duplicate execution (MESSAGE + EDITED_MESSAGE).
        for command_name, handler in self._get_command_handlers():
            typed_handler = cast(
                Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[object, object, None]],
                handler,
            )
            cmd_handler: object = CommandHandler(
                command_name,
                typed_handler,
                filters=self._get_command_handler_update_filter(),
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

        # Handle forum topic created/closed events
        created_handler: object = MessageHandler(filters.StatusUpdate.FORUM_TOPIC_CREATED, self._handle_topic_created)
        closed_handler: object = MessageHandler(filters.StatusUpdate.FORUM_TOPIC_CLOSED, self._handle_topic_closed)
        self.app.add_handler(created_handler)  # type: ignore[arg-type]
        self.app.add_handler(closed_handler)  # type: ignore[arg-type]

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
        logger.info(
            "Telegram adapter started. Bot: @%s (ID: %s)",
            bot_info.username,
            bot_info.id,
        )
        logger.info("Configured supergroup ID: %s", self.supergroup_id)
        logger.info("Whitelisted user IDs: %s", self.user_whitelist)

        # Register bot commands with Telegram (only for master computer)
        if self.is_master:
            commands = [BotCommand(name, description) for name, description in UiCommands.items()]
            try:
                # Clear global commands first (removes old @BotName cached commands)
                await self.bot.set_my_commands([])
                # Set commands for the specific supergroup (not global)
                scope = BotCommandScopeChat(chat_id=self.supergroup_id)
                await self.bot.set_my_commands(commands, scope=scope)
                logger.info(
                    "Registered %d bot commands with Telegram for supergroup (master computer)",
                    len(commands),
                )
            except BadRequest as e:
                # Don't crash the daemon if the bot isn't in the group yet / chat_id is wrong.
                logger.error(
                    "Failed to register bot commands for supergroup %s: %s",
                    self.supergroup_id,
                    e,
                )
        else:
            # Non-master: Clear all commands (both global and supergroup)
            # This removes old cached commands that cause @BotName autocomplete
            try:
                await self.bot.set_my_commands([])  # Clear global commands
                scope = BotCommandScopeChat(chat_id=self.supergroup_id)
                await self.bot.set_my_commands([], scope=scope)  # Clear supergroup commands
                logger.info("Cleared all bot commands (non-master computer)")
            except BadRequest as e:
                logger.error(
                    "Failed to clear bot commands for supergroup %s: %s",
                    self.supergroup_id,
                    e,
                )

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
            logger.info(
                "Restored registry_message_id from system UX state: %s",
                self.registry_message_id,
            )

        # Start peer discovery heartbeat (advertisement only)
        logger.info("Starting peer discovery heartbeat loop")
        asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        """Stop Telegram bot."""
        if self.app and self.app.updater:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

    async def _pre_handle_user_input(self, session: "Session") -> None:
        """UI adapter pre-handler: Delete ephemeral messages from previous interaction.

        Called by AdapterClient BEFORE processing new user input.
        Cleans up UI state from previous interaction (all ephemeral messages).

        Unified design: All messages tracked via pending_deletions are cleaned here,
        including user input messages, feedback, errors, etc.

        Args:
            session: Session object
        """
        logger.info("PRE-HANDLER CALLED for session %s", session.session_id[:8])
        # Delete pending ephemeral messages from previous interaction
        pending = await db.get_pending_deletions(session.session_id)
        if pending:
            for msg_id in pending:
                try:
                    await self.delete_message(session, msg_id)
                    logger.debug(
                        "Deleted pending message %s for session %s",
                        msg_id,
                        session.session_id[:8],
                    )
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

    def _get_command_handler_update_filter(self) -> filters.BaseFilter:
        """Return UpdateType filter for command handlers."""
        return filters.UpdateType.MESSAGE

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

        sessions = await db.get_sessions_by_adapter_metadata("telegram", "topic_id", thread_id)

        if not sessions:
            logger.debug("_get_session_from_topic: no session found for topic_id %s", thread_id)
            return None

        return sessions[0]

    def _extract_topic_title(self, message: Message | None) -> Optional[str]:
        """Extract topic title from a Telegram message or its reply chain."""
        if not message:
            return None

        forum_created = message.forum_topic_created
        title = forum_created.name if forum_created else None
        if title:
            return str(title)

        reply = message.reply_to_message
        forum_created = reply.forum_topic_created if reply else None
        title = forum_created.name if forum_created else None
        if title:
            return str(title)

        return None

    def _topic_title_mentions_this_computer(self, title: str) -> bool:
        """Return True if the topic title includes this computer's identifier."""
        return f"@{self.computer_name}" in title or f"${self.computer_name}" in title

    def _topic_owned_by_this_bot(self, update: Update, topic_id: Optional[int]) -> bool:
        """Best-effort ownership check to avoid cross-bot deletions."""
        title = self._extract_topic_title(update.effective_message)
        if not title and topic_id is not None:
            cached = self._topic_message_cache.get(topic_id, [])
            for message in reversed(cached):
                title = self._extract_topic_title(message)
                if title:
                    break
        if not title:
            return False
        return self._topic_title_mentions_this_computer(title)

    async def _require_session_from_topic(self, update: Update) -> Optional[Session]:
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

        chat_id = message.chat_id
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

        if thread_id and update.effective_user and update.effective_user.id in self.user_whitelist:
            if self._topic_owned_by_this_bot(update, thread_id):
                await self._delete_orphan_topic(thread_id)
            else:
                logger.info("Skipping orphan topic delete for topic %s (not owned by this bot)", thread_id)
            return None

        try:
            await self.bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=error_msg,
            )
        except Exception as e:
            logger.error("Failed to send session error feedback: %s", e)

        return None

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
                logger.trace("Heartbeat sent for %s", self.computer_name)
            except Exception as e:
                logger.error("Heartbeat failed: %s", e)

    def _build_heartbeat_keyboard(self, bot_username: str) -> InlineKeyboardMarkup:
        """Build the standard heartbeat keyboard with session and Claude buttons.

        Using short callback codes to stay under Telegram's 64-byte limit:
        - ssel = session select
        - csel = claude select (new session)
        - crsel = claude resume select
        """
        keyboard = [
            [InlineKeyboardButton(text="🚀 Tmux Session", callback_data=f"ssel:{bot_username}")],
            [
                InlineKeyboardButton(text="🤖 New Claude", callback_data=f"csel:{bot_username}"),
                InlineKeyboardButton(text="🔄 Resume Claude", callback_data=f"crsel:{bot_username}"),
            ],
            [
                InlineKeyboardButton(text="✨ New Gemini", callback_data=f"gsel:{bot_username}"),
                InlineKeyboardButton(text="🔄 Resume Gemini", callback_data=f"grsel:{bot_username}"),
            ],
            [
                InlineKeyboardButton(text="💻 New Codex", callback_data=f"cxsel:{bot_username}"),
                InlineKeyboardButton(text="🔄 Resume Codex", callback_data=f"cxrsel:{bot_username}"),
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
                logger.info(
                    "Posted registry heartbeat with button: message_id=%s",
                    self.registry_message_id,
                )

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
                logger.trace(
                    "Updated registry heartbeat: message_id=%s",
                    self.registry_message_id,
                )
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

        Actual peer discovery must be handled by other adapters (e.g., RedisTransport)
        that support bot-to-bot communication.

        Returns:
            Empty list (Telegram doesn't support bot-to-bot discovery)
        """
        return []

    # === MCP Server Support Methods ===

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

    # UiAdapter methods inherited from base class (can override for Telegram-specific UX)
