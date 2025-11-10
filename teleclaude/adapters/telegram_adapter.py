"""Telegram adapter for TeleClaude."""

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Optional

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from telegram import Message as TelegramMessage

from telegram import (
    BotCommand,
    BotCommandScopeChat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.events import TeleClaudeEvents
from teleclaude.core.models import Session
from teleclaude.core.ux_state import get_system_ux_state, update_system_ux_state
from teleclaude.utils import command_retry

from .base_adapter import AdapterError
from .ui_adapter import UiAdapter

# Status emoji mapping
STATUS_EMOJI = {"active": "🟢", "waiting": "🟡", "slow": "🟠", "stalled": "🔴", "idle": "⏸️", "dead": "❌"}

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


class TelegramAdapter(UiAdapter):
    """Telegram bot adapter using python-telegram-bot."""

    def __init__(self, client: "AdapterClient") -> None:
        """Initialize Telegram adapter.

        Args:
            client: AdapterClient instance for event emission
        """
        super().__init__()

        # Store client for event emission
        self.client = client

        # Get global config singleton
        # config already imported

        # Extract values from environment
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")

        supergroup_id_str = os.getenv("TELEGRAM_SUPERGROUP_ID")
        if not supergroup_id_str:
            raise ValueError("TELEGRAM_SUPERGROUP_ID environment variable not set")
        self.supergroup_id = int(supergroup_id_str)

        user_ids_str = os.getenv("TELEGRAM_USER_IDS", "")
        self.user_whitelist = [int(uid.strip()) for uid in user_ids_str.split(",") if uid.strip()]

        # Extract from config singleton
        self.trusted_dirs = config.computer.trusted_dirs
        self.trusted_bots = config.telegram.trusted_bots

        self.computer_name = config.computer.name
        if not self.computer_name:
            raise ValueError("computer.name is required in config.yml")
        self.is_master = config.computer.is_master
        self.app: Optional[Application] = None
        self._processed_voice_messages: set[int] = set()  # Track processed voice message IDs
        self._topic_message_cache: dict[int | None, list[TelegramMessage]] = {}  # Cache for registry polling
        self._mcp_message_queues: dict[int, asyncio.Queue[object]] = {}  #  Event-driven MCP delivery: topic_id -> queue
        self._pending_edits: dict[str, EditContext] = {}  # Track pending edits (message_id -> mutable context)

        # Peer discovery state (heartbeat advertisement only)
        self.registry_message_id: Optional[int] = None  # Message ID for [REGISTRY] heartbeat message
        self.heartbeat_interval = 60  # Send heartbeat every 60s

    def _ensure_started(self) -> None:
        """Ensure adapter is started."""
        if not self.app:
            raise AdapterError("Telegram adapter not started - call start() first")

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

    async def start(self) -> None:
        """Initialize and start Telegram bot."""
        # Create application with concurrent updates enabled
        # CRITICAL: concurrent_updates must be > 0 or updates can be silently dropped
        # when handlers are busy (e.g., during active polling)
        self.app = (
            Application.builder()
            .token(self.bot_token)
            .concurrent_updates(True)  # Enable concurrent update processing
            .build()
        )

        # Register command handlers
        # Note: By default CommandHandler only handles NEW messages, not edited ones
        # We need to add them separately to handle edited commands
        for command_name, handler in self._get_command_handlers():
            # Handle both new messages and edited messages
            self.app.add_handler(CommandHandler(command_name, handler))
            self.app.add_handler(CommandHandler(command_name, handler, filters=filters.UpdateType.EDITED_MESSAGE))

        # Cache all commands (for registry discovery)
        # Group 1 so it runs AFTER CommandHandlers (which are in group 0)
        self.app.add_handler(
            MessageHandler(filters.COMMAND & filters.ChatType.SUPERGROUP, self._cache_command_message), group=1
        )
        self.app.add_handler(
            MessageHandler(
                filters.COMMAND & filters.ChatType.SUPERGROUP & filters.UpdateType.EDITED_MESSAGE,
                self._cache_command_message,
            ),
            group=1,
        )

        # Handle text messages in topics (not commands)
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.SUPERGROUP, self._handle_text_message)
        )

        # Handle edited text messages (for registry heartbeat updates)
        self.app.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & filters.ChatType.SUPERGROUP & filters.UpdateType.EDITED_MESSAGE,
                self._handle_text_message,
            )
        )

        # Handle callback queries from inline keyboards
        self.app.add_handler(CallbackQueryHandler(self._handle_callback_query))

        # Handle voice messages in topics
        self.app.add_handler(MessageHandler(filters.VOICE, self._handle_voice_message))

        # Handle forum topic closed events
        self.app.add_handler(MessageHandler(filters.StatusUpdate.FORUM_TOPIC_CLOSED, self._handle_topic_closed))

        # Add catch-all handler to log ALL updates (for debugging)
        self.app.add_handler(MessageHandler(filters.ALL, self._log_all_updates), group=999)

        # Register error handler to catch all exceptions
        self.app.add_error_handler(self._handle_error)

        # Start the bot
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

        # Get bot info for diagnostics
        bot_info = await self.app.bot.get_me()
        logger.info("Telegram adapter started. Bot: @%s (ID: %s)", bot_info.username, bot_info.id)
        logger.info("Configured supergroup ID: %s", self.supergroup_id)
        logger.info("Whitelisted user IDs: %s", self.user_whitelist)

        # Register bot commands with Telegram (only for master computer)
        if self.is_master:
            commands = [
                BotCommand("new_session ", "Create a new terminal session"),
                BotCommand("list_sessions ", "List all active sessions"),
                BotCommand("list_projects ", "List trusted project directories (JSON)"),
                BotCommand("claude ", "Start Claude Code in GOD mode"),
                BotCommand("claude_resume ", "Resume last Claude Code session (GOD mode)"),
                BotCommand("cancel ", "Send CTRL+C to interrupt current command"),
                BotCommand("cancel2x ", "Send CTRL+C twice (for stubborn programs)"),
                BotCommand("kill ", "Force kill current process (SIGKILL)"),
                BotCommand("escape ", "Send ESC key (exit Vim insert mode, etc.)"),
                BotCommand("escape2x ", "Send ESC twice (for Claude Code, etc.)"),
                BotCommand("ctrl ", "Send CTRL+key (e.g., /ctrl d for CTRL+D)"),
                BotCommand("tab ", "Send TAB key"),
                BotCommand("shift_tab ", "Send SHIFT+TAB key"),
                BotCommand("key_up ", "Send UP arrow key (optional repeat count)"),
                BotCommand("key_down ", "Send DOWN arrow key (optional repeat count)"),
                BotCommand("key_left ", "Send LEFT arrow key (optional repeat count)"),
                BotCommand("key_right ", "Send RIGHT arrow key (optional repeat count)"),
                BotCommand("cd ", "Change directory or list trusted directories"),
                BotCommand("resize ", "Resize terminal window"),
                BotCommand("rename ", "Rename current session"),
                BotCommand("help ", "Show help message"),
            ]
            # Clear global commands first (removes old @BotName cached commands)
            await self.app.bot.set_my_commands([])
            # Set commands for the specific supergroup (not global)
            scope = BotCommandScopeChat(chat_id=self.supergroup_id)
            await self.app.bot.set_my_commands(commands, scope=scope)
            logger.info("Registered %d bot commands with Telegram for supergroup (master computer)", len(commands))
        else:
            # Non-master: Clear all commands (both global and supergroup)
            # This removes old cached commands that cause @BotName autocomplete
            await self.app.bot.set_my_commands([])  # Clear global commands
            scope = BotCommandScopeChat(chat_id=self.supergroup_id)
            await self.app.bot.set_my_commands([], scope=scope)  # Clear supergroup commands
            logger.info("Cleared all bot commands (non-master computer)")

        # Try to get chat info to verify bot is in the group
        try:
            chat = await self.app.bot.get_chat(self.supergroup_id)
            logger.info("Supergroup found: %s", chat.title)

            # Check if bot is admin
            bot_member = await self.app.bot.get_chat_member(self.supergroup_id, bot_info.id)
            logger.info("Bot status in group: %s", bot_member.status)
        except Exception as e:
            logger.error("Cannot access supergroup %s: %s", self.supergroup_id, e)
            logger.error("Make sure the bot is added to the group as a member!")

        # Restore registry_message_id from system UX state (for clean UX after restart)
        system_state = await get_system_ux_state(db._db)
        if system_state.registry.ping_message_id:
            self.registry_message_id = system_state.registry.ping_message_id
            logger.info("Restored registry_message_id from system UX state: %s", self.registry_message_id)

        # Start peer discovery heartbeat (advertisement only)
        logger.info("Starting peer discovery heartbeat loop")
        asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        """Stop Telegram bot."""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

    async def send_message(self, session_id: str, text: str, metadata: Optional[dict[str, object]] = None) -> str:
        """Send message to session's topic with automatic retry on rate limits and network errors."""
        # Get session to find channel_id (topic_id)
        session = await db.get_session(session_id)
        if not session or not session.adapter_metadata:
            raise AdapterError(f"Session {session_id} not found or has no topic")

        self._ensure_started()

        # Look for telegram-specific channel_id first (for observer sessions),
        # then fall back to top-level channel_id (for origin sessions) or topic_id (legacy)
        telegram_meta = session.adapter_metadata.get("telegram", {})
        telegram_meta = telegram_meta if isinstance(telegram_meta, dict) else {}
        topic_id_obj = (
            telegram_meta.get("channel_id")
            or session.adapter_metadata.get("channel_id")
            or session.adapter_metadata.get("topic_id")
        )
        if not topic_id_obj:
            raise AdapterError(f"Session {session_id} has no channel_id/topic_id in metadata")
        # Type narrowing: we know this is an int from the database
        topic_id: int = int(str(topic_id_obj))

        # Extract reply_markup if present
        reply_markup = (metadata or {}).get("reply_markup")

        # Send message with error handling for deleted topics
        try:
            message = await self._send_message_with_retry(topic_id, text, reply_markup)
            return str(message.message_id)
        except BadRequest as e:
            error_msg = str(e).lower()
            if any(
                phrase in error_msg for phrase in ["message thread not found", "thread not found", "topic not found"]
            ):
                logger.warning("Topic %s was deleted for session %s", topic_id, session_id[:8])
                # Emit topic deleted event
                await self.client.handle_event(
                    event=TeleClaudeEvents.TOPIC_CLOSED,
                    payload={"session_id": session_id},
                    metadata={"adapter_type": "telegram", "topic_id": topic_id, "reason": "deleted"},
                )
                return None
            raise
        except (NetworkError, TimedOut, RetryAfter, ConnectionError, TimeoutError) as e:
            # Network/rate limit errors - already retried by decorator, still failed
            logger.error("Failed to send message after retries: %s", e)
            return None

    @command_retry(max_retries=3)
    async def _send_message_with_retry(self, topic_id: int, formatted_text: str, reply_markup: object) -> Message:
        """Internal method with retry logic for sending messages."""
        return await self.app.bot.send_message(
            chat_id=self.supergroup_id,
            message_thread_id=topic_id,
            text=formatted_text,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )

    async def edit_message(
        self, session_id: str, message_id: str, text: str, metadata: Optional[dict[str, object]] = None
    ) -> bool:
        """Edit an existing message with automatic retry on rate limits and network errors.

        Uses mutable EditContext to prevent stale data during retries:
        - If edit already pending: updates context with latest text (prevents stale timestamps)
        - Otherwise: creates new context and starts retry flow

        Retry logic (via @command_retry decorator on _edit_message_with_retry):
        - Rate limits (RetryAfter): Uses Telegram's suggested delay, keeps retrying until 60s timeout
        - Network errors: Exponential backoff (1s, 2s, 4s), max 3 attempts OR 60 second timeout
        """
        self._ensure_started()

        # CRITICAL: Handle None message_id (happens during daemon restart)
        if not message_id:
            logger.warning("edit_message called with None message_id for session %s, ignoring", session_id[:8])
            return False

        # Extract reply_markup if present
        reply_markup = (metadata or {}).get("reply_markup")

        # Check if edit already pending for this message
        if message_id in self._pending_edits:
            # UPDATE the pending edit's payload (mutable!)
            logger.debug("Updating pending edit for message %s with latest content", message_id)
            self._pending_edits[message_id].text = text
            self._pending_edits[message_id].reply_markup = reply_markup
            return True  # Don't start new retry, existing one will use updated data

        # Create new edit context (mutable)
        ctx = EditContext(message_id=message_id, text=text, reply_markup=reply_markup)
        self._pending_edits[message_id] = ctx

        try:
            await self._edit_message_with_retry(session_id, ctx)
            return True
        except BadRequest as e:
            error_msg = str(e).lower()
            if any(
                phrase in error_msg for phrase in ["message thread not found", "thread not found", "topic not found"]
            ):
                logger.warning("Topic was deleted for session %s during edit", session_id[:8])
                # Emit topic deleted event
                await self.client.handle_event(
                    event=TeleClaudeEvents.TOPIC_CLOSED,
                    payload={"session_id": session_id},
                    metadata={"adapter_type": "telegram", "reason": "deleted"},
                )
                return False
            if "can't parse entities" in error_msg or "can't find end of" in error_msg:
                # Parse error - transient issue with complex output, continue polling
                logger.warning("Markdown parse error editing message %s (continuing polling): %s", message_id, e)
                return True
            logger.error("Failed to edit message: %s", e)
            return False
        except (NetworkError, TimedOut, RetryAfter, ConnectionError, TimeoutError) as e:
            # Network/rate limit errors - already retried by decorator, still failed
            logger.error("Failed to edit message after retries: %s", e)
            return False
        except Exception as e:
            logger.error("Failed to edit message: %s", e)
            return False
        finally:
            # Remove from pending edits regardless of outcome
            self._pending_edits.pop(message_id, None)

    @command_retry(max_retries=3, max_timeout=60.0)
    async def _edit_message_with_retry(self, session_id: str, ctx: EditContext) -> None:
        """Internal method with retry logic for editing messages.

        Reads from mutable EditContext - always uses latest data even if updated during retry wait.
        """
        await self.app.bot.edit_message_text(
            chat_id=self.supergroup_id,
            message_id=int(ctx.message_id),
            text=ctx.text,  # ← Read latest text from mutable context
            parse_mode="Markdown",
            reply_markup=ctx.reply_markup,  # ← Read latest reply_markup from mutable context
        )

    async def delete_message(self, session_id: str, message_id: str) -> bool:
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
        await self.app.bot.delete_message(chat_id=self.supergroup_id, message_id=int(message_id))

    async def _pre_handle_user_input(self, session_id: str) -> None:
        """UI adapter pre-handler: Delete messages from previous interaction.

        Called by AdapterClient BEFORE processing new user input.
        Cleans up UI state from previous interaction (pending messages, idle notifications).

        Args:
            session_id: Session identifier
        """
        # Delete pending messages from previous interaction
        pending = await db.get_pending_deletions(session_id)
        if pending:
            for msg_id in pending:
                try:
                    await self.delete_message(session_id, msg_id)
                    logger.debug("Deleted pending message %s for session %s", msg_id, session_id[:8])
                except Exception as e:
                    # Resilient to already-deleted messages
                    logger.warning("Failed to delete message %s: %s", msg_id, e)
            await db.clear_pending_deletions(session_id)

        # Delete idle notification if present
        if await db.has_idle_notification(session_id):
            try:
                idle_msg = await db.remove_idle_notification(session_id)
                if idle_msg:
                    await self.delete_message(session_id, idle_msg)
                    logger.debug("Deleted idle notification %s for session %s", idle_msg, session_id[:8])
            except Exception as e:
                logger.warning("Failed to delete idle notification: %s", e)

    async def _post_handle_user_input(self, session_id: str, message_id: str) -> None:
        """UI adapter post-handler: Track current message for next cleanup.

        Called by AdapterClient AFTER processing user input.
        Tracks current message ID so it can be deleted on next interaction.

        Args:
            session_id: Session identifier
            message_id: Current message ID to track for deletion
        """
        await db.add_pending_deletion(session_id, message_id)
        logger.debug("Tracked message %s for deletion on next input", message_id)

    async def send_file(
        self,
        session_id: str,
        file_path: str,
        caption: Optional[str] = None,
        metadata: Optional[dict[str, object]] = None,
    ) -> str:
        """Send file to session's topic."""
        self._ensure_started()

        session = await db.get_session(session_id)
        if not session or not session.adapter_metadata:
            raise AdapterError(f"Session {session_id} not found")

        # Use channel_id (new) or topic_id (legacy)
        topic_id_obj = session.adapter_metadata.get("channel_id") or session.adapter_metadata.get("topic_id")
        # Type narrowing: we know this is an int from the database
        topic_id: int | None = int(str(topic_id_obj)) if topic_id_obj else None

        with open(file_path, "rb") as f:
            message = await self.app.bot.send_document(
                chat_id=self.supergroup_id, message_thread_id=topic_id, document=f, caption=caption
            )

        return str(message.message_id)

    async def send_general_message(self, text: str, metadata: Optional[dict[str, object]] = None) -> str:
        """Send message to Telegram supergroup general topic."""
        self._ensure_started()

        metadata = metadata or {}
        message_thread_id = metadata.get("message_thread_id")
        parse_mode = metadata.get("parse_mode", "Markdown")

        result = await self.app.bot.send_message(
            chat_id=self.supergroup_id, message_thread_id=message_thread_id, text=text, parse_mode=parse_mode
        )
        return str(result.message_id)

    async def create_channel(self, session_id: str, title: str, metadata: Optional[dict[str, object]] = None) -> str:
        """Create a new topic in the supergroup."""
        self._ensure_started()

        # Create topic
        topic = await self.app.bot.create_forum_topic(chat_id=self.supergroup_id, name=title)

        topic_id = topic.message_thread_id
        logger.info("Created topic: %s (ID: %s)", title, topic_id)

        return str(topic_id)

    async def update_channel_title(self, channel_id: str, title: str) -> bool:
        """Update topic title."""
        self._ensure_started()

        try:
            await self.app.bot.edit_forum_topic(
                chat_id=self.supergroup_id, message_thread_id=int(channel_id), name=title
            )
            return True
        except Exception as e:
            logger.error("Failed to update topic title: %s", e)
            return False

    async def set_channel_status(self, channel_id: str, status: str) -> bool:
        """Update status emoji in topic title."""
        # Get current title from database (try both new and old format)
        sessions = await db.get_sessions_by_adapter_metadata("telegram", "channel_id", channel_id)
        if not sessions:
            # Fallback to old topic_id format
            sessions = await db.get_sessions_by_adapter_metadata("telegram", "topic_id", int(channel_id))

        if not sessions:
            return False

        session = sessions[0]
        emoji = STATUS_EMOJI.get(status, "")

        # Update title with emoji
        base_title = session.title or f"[{session.computer_name}] Session"
        new_title = f"{base_title} {emoji}".strip()

        return await self.update_channel_title(channel_id, new_title)

    async def delete_channel(self, channel_id: str) -> bool:
        """Delete/close a forum topic."""
        self._ensure_started()

        try:
            await self.app.bot.delete_forum_topic(chat_id=self.supergroup_id, message_thread_id=int(channel_id))
            return True
        except BadRequest as e:
            logger.warning("Failed to delete topic %s: %s", channel_id, e)
            return False
        except Exception as e:
            logger.error("Failed to delete topic %s: %s", channel_id, e)
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

    async def _get_session_from_topic(self, update: Update) -> Optional[Session]:
        """Get session from current topic.

        Returns:
            Session object or None if not found/not authorized
        """
        # Check preconditions
        if not self._validate_update_for_command(update):
            return None

        # Check authorization
        if update.effective_user.id not in self.user_whitelist:
            return None

        # Get message (handles both regular and edited messages)
        message = update.effective_message
        if not message.message_thread_id:
            return None

        # Find session by channel_id (try both new and old format)
        thread_id = message.message_thread_id
        sessions = await db.get_sessions_by_adapter_metadata("telegram", "channel_id", str(thread_id))
        if not sessions:
            # Fallback to old topic_id format
            sessions = await db.get_sessions_by_adapter_metadata("telegram", "topic_id", thread_id)

        return sessions[0] if sessions else None

    # ==================== Message Handlers ====================

    async def _handle_new_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /new_session command."""
        if not self._validate_update_for_command(update) or not update.effective_chat:
            return

        logger.debug("Received /new_session from user %s", update.effective_user.id)

        # Check if authorized
        if update.effective_user.id not in self.user_whitelist:
            logger.warning("User %s not in whitelist: %s", update.effective_user.id, self.user_whitelist)
            return

        logger.debug("User authorized, emitting command with args: %s", context.args)

        # Emit command event to daemon
        await self.client.handle_event(
            event=TeleClaudeEvents.NEW_SESSION,
            payload={
                "command": self._event_to_command("new_session"),
                "args": list(context.args) if context.args else [],
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "chat_id": update.effective_chat.id,
                "topic_id": update.effective_message.message_thread_id if update.effective_message else None,
            },
        )

    async def _handle_list_sessions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /list_sessions command."""
        if not self._validate_update_for_command(update) or not update.effective_chat:
            return

        if update.effective_user.id not in self.user_whitelist:
            return

        await self.client.handle_event(
            event=TeleClaudeEvents.LIST_SESSIONS,
            payload={
                "command": self._event_to_command("list_sessions"),
                "args": [],
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "chat_id": update.effective_chat.id,
                "topic_id": update.effective_message.message_thread_id if update.effective_message else None,
            },
        )

    async def _handle_list_projects(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /list_projects command - returns trusted_dirs as JSON."""
        if not update.effective_message or not update.effective_chat:
            return

        import json
        import os
        from pathlib import Path

        # Get trusted_dirs and default_working_dir from config
        trusted_dirs = config.computer.trusted_dirs
        default_working_dir = config.computer.default_working_dir

        # Expand environment variables and filter existing paths
        all_dirs = []

        # Always include default_working_dir first if it exists
        if default_working_dir:
            expanded_default = os.path.expanduser(os.path.expandvars(default_working_dir))
            if Path(expanded_default).exists():
                all_dirs.append(expanded_default)

        # Add trusted_dirs (skip duplicates and non-existent paths)
        for dir_path in trusted_dirs:
            expanded = os.path.expanduser(os.path.expandvars(dir_path))
            if Path(expanded).exists() and expanded not in all_dirs:
                all_dirs.append(expanded)

        # Send as JSON array
        await update.effective_message.reply_text(json.dumps(all_dirs), parse_mode=None)

    async def _handle_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /cancel command - sends CTRL+C to the session."""
        session = await self._get_session_from_topic(update)

        # Master bot: schedule cleanup for ALL command messages (even if session not owned)
        if self.is_master and update.effective_message:
            asyncio.create_task(self._cleanup_command_message_delayed(update.effective_message))

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
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
        )

    async def _handle_cancel2x(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /cancel2x command - sends CTRL+C twice (for stubborn programs like Claude Code)."""
        session = await self._get_session_from_topic(update)

        # Master bot: schedule cleanup for ALL command messages (even if session not owned)
        if self.is_master and update.effective_message:
            asyncio.create_task(self._cleanup_command_message_delayed(update.effective_message))

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
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
        )

    async def _handle_kill(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /kill command - force kill foreground process with SIGKILL."""
        session = await self._get_session_from_topic(update)

        # Master bot: schedule cleanup for ALL command messages (even if session not owned)
        if self.is_master and update.effective_message:
            asyncio.create_task(self._cleanup_command_message_delayed(update.effective_message))

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
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
        )

    async def _handle_escape(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /escape command - sends ESC key to the session, optionally followed by text+ENTER."""
        session = await self._get_session_from_topic(update)

        # Master bot: schedule cleanup for ALL command messages (even if session not owned)
        if self.is_master and update.effective_message:
            asyncio.create_task(self._cleanup_command_message_delayed(update.effective_message))

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
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
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
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
        )

    async def _handle_ctrl(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /ctrl command - sends CTRL+key to the session."""
        session = await self._get_session_from_topic(update)

        # Master bot: schedule cleanup for ALL command messages (even if session not owned)
        if self.is_master and update.effective_message:
            asyncio.create_task(self._cleanup_command_message_delayed(update.effective_message))

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
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
        )

    async def _handle_tab(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
        )

    async def _handle_shift_tab(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /shift_tab command - sends SHIFT+TAB key to the session."""
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
                "args": [],
                "session_id": session.session_id,
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
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
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
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
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
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
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
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
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
        )

    async def _handle_resize(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /resize command - resize terminal."""
        session = await self._get_session_from_topic(update)

        # Master bot: schedule cleanup for ALL command messages (even if session not owned)
        if self.is_master and update.effective_message:
            asyncio.create_task(self._cleanup_command_message_delayed(update.effective_message))

        if not session:
            return

        # Get size argument
        size_arg = context.args[0] if context.args else None

        if not size_arg:
            # Show available presets
            presets_text = """
**Terminal Size Presets:**

/resize small - 80x24 (classic)
/resize medium - 120x40 (comfortable)
/resize large - 160x60 (spacious)
/resize wide - 200x80 (ultrawide)

Current size: {}
            """.format(
                session.terminal_size or "80x24"
            )
            await update.effective_message.reply_text(presets_text, parse_mode="Markdown")
            return

        # resize is adapter-specific - handled internally, no daemon event needed

    async def _handle_rename(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /rename command - rename session."""
        logger.info("_handle_rename called with args: %s", context.args)
        session = await self._get_session_from_topic(update)
        if not session:
            logger.warning("_handle_rename: No session found")
            return

        # Check if name argument provided
        if not context.args:
            await update.effective_message.reply_text("Usage: /rename <new name>")
            return

        await self.client.handle_event(
            event=TeleClaudeEvents.RENAME,
            payload={
                "command": self._event_to_command("rename"),
                "args": list(context.args),
                "session_id": session.session_id,
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
        )

    async def _handle_cd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /cd command - change directory or list trusted directories."""
        session = await self._get_session_from_topic(update)

        # Master bot: schedule cleanup for ALL command messages (even if session not owned)
        if self.is_master and update.effective_message:
            asyncio.create_task(self._cleanup_command_message_delayed(update.effective_message))

        if not session:
            return

        # If args provided, change to that directory
        if context.args:
            await self.client.handle_event(
                event=TeleClaudeEvents.CD,
                payload={
                    "command": self._event_to_command("cd"),
                    "args": list(context.args),
                    "session_id": session.session_id,
                },
                metadata={
                    "adapter_type": "telegram",
                    "user_id": update.effective_user.id,
                    "message_id": update.effective_message.message_id,
                },
            )
            return

        # No args - show trusted directories as buttons (always include TC WORKDIR)
        all_dirs = ["TC WORKDIR"] + self.trusted_dirs

        # Create inline keyboard with directory buttons
        keyboard = []
        for dir_path in all_dirs:
            keyboard.append([InlineKeyboardButton(text=dir_path, callback_data=f"cd:{dir_path}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.effective_message.reply_text(
            "**Select a directory:**", reply_markup=reply_markup, parse_mode="Markdown"
        )

    async def _handle_claude(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /claude command - start Claude Code."""
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
                "args": [],
                "session_id": session.session_id,
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
        )

    async def _handle_claude_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            },
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
        )

    async def _handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            # Download full output
            session_id = args[0] if args else None
            if not session_id or not query.message:
                return

            # Read output from file
            output_dir = Path("session_output")
            output_file = output_dir / f"{session_id[:8]}.txt"

            if not output_file.exists():
                await query.edit_message_text("Output file not found", parse_mode="Markdown")
                return

            try:
                # Read the full output
                output_content = output_file.read_text()

                # Create a temporary file to send
                with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
                    tmp.write(output_content)
                    tmp_path = tmp.name

                try:
                    # Send as document
                    with open(tmp_path, "rb") as f:
                        await self.app.bot.send_document(
                            chat_id=query.message.chat_id,
                            message_thread_id=query.message.message_thread_id,
                            document=f,
                            filename=f"output_{session_id[:8]}.txt",
                            caption="Full terminal output",
                        )
                finally:
                    # Clean up temp file
                    Path(tmp_path).unlink()

                await query.edit_message_text("✅ Full output sent as file", parse_mode="Markdown")
            except Exception as e:
                logger.error("Failed to send output file: %s", e)
                await query.edit_message_text(f"❌ Error sending file: {e}", parse_mode="Markdown")

        elif action == "start_session_here":
            # Handle quick session start from heartbeat button
            if not query.from_user:
                return

            # Check if authorized
            if query.from_user.id not in self.user_whitelist:
                await query.answer("❌ Not authorized", show_alert=True)
                return

            # Emit NEW_SESSION event directly (no visible command message)
            await self.client.handle_event(
                event=TeleClaudeEvents.NEW_SESSION,
                payload={
                    "args": [],
                },
                metadata={
                    "adapter_type": "telegram",
                    "user_id": query.from_user.id,
                    "chat_id": self.supergroup_id,
                    "topic_id": None,  # Will create in General topic
                },
            )

            # Acknowledge the button click
            await query.answer("Creating session...", show_alert=False)

        elif action == "cd":
            # Find session from the message's thread
            if not query.message or not query.message.message_thread_id or not query.from_user:
                return

            # Try both new and old format
            thread_id = query.message.message_thread_id
            sessions = await db.get_sessions_by_adapter_metadata("telegram", "channel_id", str(thread_id))
            if not sessions:
                sessions = await db.get_sessions_by_adapter_metadata("telegram", "topic_id", thread_id)

            if not sessions:
                return

            session = sessions[0]
            dir_path = args[0] if args else ""

            # Emit cd command
            await self.client.handle_event(
                event=TeleClaudeEvents.CD,
                payload={
                    "args": [dir_path],
                    "session_id": session.session_id,
                },
                metadata={
                    "adapter_type": "telegram",
                    "user_id": query.from_user.id,
                    "message_id": query.message.message_id,
                },
            )

            # Update the message to show what was selected
            await query.edit_message_text(f"Changing directory to: `{dir_path}`", parse_mode="Markdown")

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

    async def _send_heartbeat(self) -> None:
        """Send or edit [REGISTRY] heartbeat message in General topic."""
        from datetime import datetime

        text = f"[REGISTRY] {self.computer_name} last seen at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        # Get bot info for @mention
        bot_info = await self.app.bot.get_me()
        bot_username = bot_info.username

        # Create button for quick session start (only needs to be set once, persists through edits)
        keyboard = [[InlineKeyboardButton(text="🚀 Start Session", callback_data=f"start_session_here:{bot_username}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if self.registry_message_id is None:
            # First time - post new message to General topic (thread_id=None) with button
            try:
                logger.debug(
                    "Attempting to send heartbeat - chat_id=%s, message_thread_id=None, text=%s",
                    self.supergroup_id,
                    text[:50],
                )
                msg = await self.app.bot.send_message(
                    chat_id=self.supergroup_id,
                    message_thread_id=None,  # General topic
                    text=text,
                    reply_markup=reply_markup,
                )
                self.registry_message_id = msg.message_id
                logger.info("Posted registry heartbeat with button: message_id=%s", self.registry_message_id)

                # Persist to system UX state (for clean UX after restart)
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
                edited_message: Message = await self.app.bot.edit_message_text(
                    chat_id=self.supergroup_id,
                    message_id=self.registry_message_id,
                    text=text,
                    reply_markup=reply_markup,
                )
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

    async def discover_peers(self) -> list[dict[str, object]]:
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

    async def _cache_command_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    async def _cleanup_command_message_delayed(self, message: Message) -> None:
        """Master bot cleanup: Delete command message after delay (backup for session owner deletion).

        This ensures clean UX even when commands are sent to sessions owned by other bots.
        The master bot (which has commands registered) acts as cleanup coordinator.

        Args:
            message: Command message to delete
        """
        # Wait for session owner bot to process and delete
        await asyncio.sleep(3)

        # Try to delete (fails silently if already deleted by session owner)
        try:
            await self.app.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
            logger.debug(
                "Master bot cleaned up command message %s in topic %s", message.message_id, message.message_thread_id
            )
        except Exception as e:
            # Expected if session owner already deleted it (idempotent)
            logger.debug("Master bot cleanup: message %s already deleted or inaccessible: %s", message.message_id, e)

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        if update.effective_user.id not in self.user_whitelist:
            return

        help_text = """TeleClaude Bot Commands:

/new_session [title] - Create a new terminal session
/list_sessions - List all active sessions
/cancel - Send CTRL+C to interrupt current command
/cancel2x - Send CTRL+C twice (for Claude Code, etc.)
/escape - Send ESC key (exit Vim insert mode, etc.)
/escape2x - Send ESC twice (for nested Vim, etc.)
/ctrl <key> - Send CTRL+key (e.g., /ctrl d for CTRL+D, /ctrl z for CTRL+Z)
/resize <size> - Resize terminal (shows presets if no size)
/rename <name> - Rename current session
/cd [path] - List trusted directories or change to specified path
/claude - Start Claude Code (cc)
/help - Show this help message

Usage:
1. Use /new_session to create a terminal session
2. Send text messages in the session topic to execute commands
3. Use /cancel to interrupt a running command
4. Use /cancel2x for stubborn programs (Claude Code)
5. Use /escape to exit insert mode in Vim
6. Use /resize to change terminal size
7. Use /rename to rename the session
8. Use /claude to start Claude Code
9. View output in real-time
        """

        await update.effective_message.reply_text(help_text)

    async def _handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        if not session or not update.effective_message or not update.effective_user:
            return

        text = update.effective_message.text
        if not text:
            return

        await self.client.handle_event(
            event=TeleClaudeEvents.MESSAGE,
            payload={"session_id": session.session_id, "text": text},
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
        )

    async def _handle_voice_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle voice messages in topics."""
        if not update.message or not update.effective_user:
            return

        logger.info("=== VOICE MESSAGE HANDLER CALLED ===")
        logger.info("Message ID: %s", update.message.message_id)
        logger.info("User: %s", update.effective_user.id)
        logger.info("Thread ID: %s", update.message.message_thread_id)

        # Check if we've already processed this message
        message_id = update.message.message_id
        if message_id in self._processed_voice_messages:
            logger.debug("Skipping duplicate voice message: %s", message_id)
            return

        # Mark as processed
        self._processed_voice_messages.add(message_id)

        # Limit set size to prevent memory growth (keep last 1000 message IDs)
        if len(self._processed_voice_messages) > 1000:
            oldest = min(self._processed_voice_messages)
            self._processed_voice_messages.remove(oldest)

        session = await self._get_session_from_topic(update)
        if not session:
            logger.warning("No session found for voice message in thread %s", update.message.message_thread_id)
            return

        # Download voice file to temp location
        voice = update.message.voice
        if not voice:
            return
        voice_file = await voice.get_file()

        # Create temp file with .ogg extension (Telegram uses ogg/opus format)
        temp_dir = Path(tempfile.gettempdir()) / "teleclaude_voice"
        temp_dir.mkdir(exist_ok=True)
        temp_file_path = temp_dir / f"voice_{update.message.message_id}.ogg"

        try:
            # Download the file
            await voice_file.download_to_drive(temp_file_path)
            logger.info("Downloaded voice message to: %s", temp_file_path)

            # Delete the voice message from Telegram (keep UI clean)
            try:
                await update.message.delete()
                logger.debug("Deleted voice message %s from Telegram", update.message.message_id)
            except Exception as e:
                logger.warning("Failed to delete voice message %s: %s", update.message.message_id, e)

            # Emit voice event to daemon
            await self.client.handle_event(
                event=TeleClaudeEvents.VOICE,
                payload={"session_id": session.session_id, "file_path": str(temp_file_path)},
                metadata={
                    "adapter_type": "telegram",
                    "user_id": update.effective_user.id,
                    "message_id": update.message.message_id,
                    "duration": voice.duration,
                },
            )
        except Exception as e:
            error_msg = str(e) if str(e).strip() else "Unknown error"
            logger.error("Failed to download voice message: %s", error_msg)
            await update.message.reply_text(f"❌ Failed to download voice message: {error_msg}")

    async def _handle_topic_closed(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle forum topic closed event."""
        if not update.message or not update.message.message_thread_id:
            return

        topic_id = update.message.message_thread_id

        # Find session by topic ID (try both formats)
        sessions = await db.get_sessions_by_adapter_metadata("telegram", "channel_id", str(topic_id))
        if not sessions:
            sessions = await db.get_sessions_by_adapter_metadata("telegram", "topic_id", topic_id)

        if not sessions:
            logger.warning("No session found for closed topic %s", topic_id)
            return

        session = sessions[0]
        logger.info("Topic %s closed, deleting it and cleaning up session %s", topic_id, session.session_id)

        # Delete topic immediately (force sync across all Telegram clients)
        try:
            await self.app.bot.delete_forum_topic(
                chat_id=self.supergroup_id,
                message_thread_id=topic_id,
            )
            logger.info("Deleted forum topic %s for session %s", topic_id, session.session_id[:8])
        except Exception as e:
            logger.warning("Failed to delete forum topic %s: %s", topic_id, e)

        # Emit topic closed event to daemon for cleanup
        await self.client.handle_event(
            event=TeleClaudeEvents.TOPIC_CLOSED,
            payload={"session_id": session.session_id},
            metadata={
                "adapter_type": "telegram",
                "user_id": update.effective_user.id if update.effective_user else None,
                "topic_id": topic_id,
            },
        )

    async def _log_all_updates(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            logger.info("Full update data: %s", update_dict)

        except Exception as e:
            logger.error("Error logging update: %s", e)

    async def _handle_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors that occur in handlers."""
        import traceback

        logger.error("Exception while handling update %s:", update, exc_info=context.error)

        # Log full traceback
        logger.error(
            "Full traceback:\n%s",
            "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__)),
        )

    # === MCP Server Support Methods ===

    async def create_topic(self, title: str) -> object:
        """Create a new forum topic and return the topic object."""
        self._ensure_started()
        topic = await self.app.bot.create_forum_topic(chat_id=self.supergroup_id, name=title)
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
        kwargs = {"chat_id": self.supergroup_id, "text": text}

        # Only add message_thread_id for specific topics, not for General topic (None)
        if topic_id is not None:
            kwargs["message_thread_id"] = topic_id

        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode

        message = await self.app.bot.send_message(**kwargs)

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

    async def poll_output_stream(
        self,
        session_id: str,
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        """Poll for output chunks (not implemented for Telegram).

        Telegram doesn't support bidirectional streaming like Redis.
        This method is only implemented in RedisAdapter.

        Args:
            session_id: Session ID
            timeout: Max seconds to wait

        Raises:
            NotImplementedError: Telegram doesn't support output streaming
        """
        raise NotImplementedError("Telegram adapter does not support poll_output_stream")
        yield  # Make this an async generator

    # UiAdapter methods inherited from base class (can override for Telegram-specific UX)
