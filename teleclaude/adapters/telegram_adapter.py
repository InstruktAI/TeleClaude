"""Telegram adapter for TeleClaude."""

import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .base_adapter import AdapterError, BaseAdapter

# Status emoji mapping
STATUS_EMOJI = {"active": "🟢", "waiting": "🟡", "slow": "🟠", "stalled": "🔴", "idle": "⏸️", "dead": "❌"}

logger = logging.getLogger(__name__)


class TelegramAdapter(BaseAdapter):
    """Telegram bot adapter using python-telegram-bot."""

    def __init__(self, config: Dict[str, Any], session_manager: Any) -> None:
        """Initialize Telegram adapter.

        Args:
            config: Telegram configuration
            session_manager: SessionManager instance for database queries
        """
        super().__init__(config)
        self.bot_token = config["bot_token"]
        self.supergroup_id = config["supergroup_id"]
        self.user_whitelist = config["user_whitelist"]
        self.trusted_dirs = config.get("trusted_dirs", [])
        self.session_manager = session_manager
        self.app: Optional[Application] = None
        self._processed_voice_messages: set[int] = set()  # Track processed voice message IDs

    def _ensure_started(self) -> None:
        """Ensure adapter is started."""
        if not self.app:
            raise AdapterError("Telegram adapter not started - call start() first")

    async def start(self) -> None:
        """Initialize and start Telegram bot."""
        # Create application
        self.app = Application.builder().token(self.bot_token).build()

        # Register command handlers
        # Note: By default CommandHandler only handles NEW messages, not edited ones
        # We need to add them separately to handle edited commands
        commands = [
            ("new_session", self._handle_new_session),
            ("list_sessions", self._handle_list_sessions),
            ("cancel", self._handle_cancel),
            ("cancel2x", self._handle_cancel2x),
            ("resize", self._handle_resize),
            ("rename", self._handle_rename),
            ("cd", self._handle_cd),
            ("claude", self._handle_claude),
            ("claude_resume", self._handle_claude_resume),
            ("help", self._handle_help),
        ]

        for command_name, handler in commands:
            # Handle both new messages and edited messages
            self.app.add_handler(CommandHandler(command_name, handler))
            self.app.add_handler(CommandHandler(command_name, handler, filters=filters.UpdateType.EDITED_MESSAGE))

        # Handle text messages in topics (not commands)
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.SUPERGROUP, self._handle_text_message)
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

        # Register bot commands with Telegram
        commands = [
            BotCommand("new_session", "Create a new terminal session"),
            BotCommand("list_sessions", "List all active sessions"),
            BotCommand("claude", "Start Claude Code in GOD mode"),
            BotCommand("claude_resume", "Resume last Claude Code session (GOD mode)"),
            BotCommand("cancel", "Send CTRL+C to interrupt current command"),
            BotCommand("cancel2x", "Send CTRL+C twice (for stubborn programs)"),
            BotCommand("cd", "Change directory or list trusted directories"),
            BotCommand("resize", "Resize terminal window"),
            BotCommand("rename", "Rename current session"),
            BotCommand("help", "Show help message"),
        ]
        await self.app.bot.set_my_commands(commands)
        logger.info("Registered %d bot commands with Telegram", len(commands))

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

    async def stop(self) -> None:
        """Stop Telegram bot."""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

    async def send_message(self, session_id: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Send message to session's topic."""
        # Get session to find channel_id (topic_id)
        session = await self.session_manager.get_session(session_id)
        if not session or not session.adapter_metadata:
            raise AdapterError(f"Session {session_id} not found or has no topic")

        self._ensure_started()

        # Use channel_id (new) or topic_id (legacy) for backward compatibility
        topic_id = session.adapter_metadata.get("channel_id") or session.adapter_metadata.get("topic_id")
        if not topic_id:
            raise AdapterError(f"Session {session_id} has no channel_id/topic_id")

        # Format message with code block (use 'bash' for better rendering)
        formatted_text = f"```\n{text}\n```" if text.strip() else text

        # Send message with error handling for deleted topics
        try:
            message = await self.app.bot.send_message(
                chat_id=self.supergroup_id, message_thread_id=topic_id, text=formatted_text, parse_mode="Markdown"
            )
            return str(message.message_id)
        except BadRequest as e:
            error_msg = str(e).lower()
            if any(
                phrase in error_msg for phrase in ["message thread not found", "thread not found", "topic not found"]
            ):
                logger.warning("Topic %s was deleted for session %s", topic_id, session_id[:8])
                # Emit topic deleted event
                await self._emit_topic_closed(session_id, {"topic_id": topic_id, "reason": "deleted"})
                return None
            raise

    async def edit_message(
        self, session_id: str, message_id: str, text: str, metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Edit an existing message."""
        self._ensure_started()

        try:
            formatted_text = f"```\n{text}\n```" if text.strip() else text

            await self.app.bot.edit_message_text(
                chat_id=self.supergroup_id, message_id=int(message_id), text=formatted_text, parse_mode="Markdown"
            )
            return True
        except BadRequest as e:
            error_msg = str(e).lower()
            if any(
                phrase in error_msg for phrase in ["message thread not found", "thread not found", "topic not found"]
            ):
                logger.warning("Topic was deleted for session %s during edit", session_id[:8])
                # Emit topic deleted event
                await self._emit_topic_closed(session_id, {"reason": "deleted"})
                return False
            logger.error("Failed to edit message: %s", e)
            return False
        except Exception as e:
            logger.error("Failed to edit message: %s", e)
            return False

    async def send_file(
        self, session_id: str, file_path: str, caption: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Send file to session's topic."""
        self._ensure_started()

        session = await self.session_manager.get_session(session_id)
        if not session or not session.adapter_metadata:
            raise AdapterError(f"Session {session_id} not found")

        # Use channel_id (new) or topic_id (legacy)
        topic_id = session.adapter_metadata.get("channel_id") or session.adapter_metadata.get("topic_id")

        with open(file_path, "rb") as f:
            message = await self.app.bot.send_document(
                chat_id=self.supergroup_id, message_thread_id=topic_id, document=f, caption=caption
            )

        return str(message.message_id)

    async def send_general_message(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Send message to Telegram supergroup general topic."""
        self._ensure_started()

        metadata = metadata or {}
        message_thread_id = metadata.get("message_thread_id")
        parse_mode = metadata.get("parse_mode", "Markdown")

        result = await self.app.bot.send_message(
            chat_id=self.supergroup_id, message_thread_id=message_thread_id, text=text, parse_mode=parse_mode
        )
        return str(result.message_id)

    async def create_channel(self, session_id: str, title: str, metadata: Optional[Dict[str, Any]] = None) -> str:
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
        sessions = await self.session_manager.get_sessions_by_adapter_metadata("telegram", "channel_id", channel_id)
        if not sessions:
            # Fallback to old topic_id format
            sessions = await self.session_manager.get_sessions_by_adapter_metadata(
                "telegram", "topic_id", int(channel_id)
            )

        if not sessions:
            return False

        session = sessions[0]
        emoji = STATUS_EMOJI.get(status, "")

        # Update title with emoji
        base_title = session.title or f"[{session.computer_name}] Session"
        new_title = f"{base_title} {emoji}".strip()

        return await self.update_channel_title(channel_id, new_title)

    # ==================== Helper Methods ====================

    async def _get_session_from_topic(self, update: Update) -> Any:
        """Get session from current topic.

        Returns:
            Session object or None if not found/not authorized
        """
        # Check authorization
        if update.effective_user.id not in self.user_whitelist:
            return None

        # Get message (handles both regular and edited messages)
        message = update.effective_message
        if not message or not message.message_thread_id:
            return None

        # Find session by channel_id (try both new and old format)
        thread_id = message.message_thread_id
        sessions = await self.session_manager.get_sessions_by_adapter_metadata("telegram", "channel_id", str(thread_id))
        if not sessions:
            # Fallback to old topic_id format
            sessions = await self.session_manager.get_sessions_by_adapter_metadata("telegram", "topic_id", thread_id)

        return sessions[0] if sessions else None

    # ==================== Message Handlers ====================

    async def _handle_new_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /new_session command."""
        logger.debug("Received /new_session from user %s", update.effective_user.id)

        # Check if authorized
        if update.effective_user.id not in self.user_whitelist:
            logger.warning("User %s not in whitelist: %s", update.effective_user.id, self.user_whitelist)
            return

        logger.debug("User authorized, emitting command with args: %s", context.args)

        # Emit command event to daemon
        await self._emit_command(
            "new-session",
            list(context.args) if context.args else [],
            {
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "chat_id": update.effective_chat.id,
                "message_thread_id": update.effective_message.message_thread_id if update.effective_message else None,
            },
        )

    async def _handle_list_sessions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /list_sessions command."""
        if update.effective_user.id not in self.user_whitelist:
            return

        await self._emit_command(
            "list-sessions",
            [],
            {
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "chat_id": update.effective_chat.id,
                "message_thread_id": update.effective_message.message_thread_id if update.effective_message else None,
            },
        )

    async def _handle_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /cancel command - sends CTRL+C to the session."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        await self._emit_command(
            "cancel",
            [],
            {
                "adapter_type": "telegram",
                "session_id": session.session_id,
                "user_id": update.effective_user.id,
            },
        )

    async def _handle_cancel2x(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /cancel2x command - sends CTRL+C twice (for stubborn programs like Claude Code)."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        await self._emit_command(
            "cancel2x",
            [],
            {
                "adapter_type": "telegram",
                "session_id": session.session_id,
                "user_id": update.effective_user.id,
            },
        )

    async def _handle_resize(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /resize command - resize terminal."""
        session = await self._get_session_from_topic(update)
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

        await self._emit_command(
            "resize",
            [size_arg],
            {
                "adapter_type": "telegram",
                "session_id": session.session_id,
                "user_id": update.effective_user.id,
            },
        )

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

        await self._emit_command(
            "rename",
            list(context.args),
            {
                "adapter_type": "telegram",
                "session_id": session.session_id,
                "user_id": update.effective_user.id,
            },
        )

    async def _handle_cd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /cd command - change directory or list trusted directories."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        # If args provided, change to that directory
        if context.args:
            await self._emit_command(
                "cd",
                list(context.args),
                {
                    "adapter_type": "telegram",
                    "session_id": session.session_id,
                    "user_id": update.effective_user.id,
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

        await self._emit_command(
            "claude",
            [],
            {
                "adapter_type": "telegram",
                "session_id": session.session_id,
                "user_id": update.effective_user.id,
            },
        )

    async def _handle_claude_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /claude_resume command - resume last Claude Code session."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        await self._emit_command(
            "claude_resume",
            [],
            {
                "adapter_type": "telegram",
                "session_id": session.session_id,
                "user_id": update.effective_user.id,
            },
        )

    async def _handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle button clicks from inline keyboards."""
        query = update.callback_query
        await query.answer()

        # Parse callback data
        data = query.data
        if not data or ":" not in data:
            return

        action, *args = data.split(":", 1)

        if action == "cd":
            # Find session from the message's thread
            if not query.message or not query.message.message_thread_id:
                return

            # Try both new and old format
            thread_id = query.message.message_thread_id
            sessions = await self.session_manager.get_sessions_by_adapter_metadata(
                "telegram", "channel_id", str(thread_id)
            )
            if not sessions:
                sessions = await self.session_manager.get_sessions_by_adapter_metadata(
                    "telegram", "topic_id", thread_id
                )

            if not sessions:
                return

            session = sessions[0]
            dir_path = args[0] if args else ""

            # Emit cd command
            await self._emit_command(
                "cd",
                [dir_path],
                {
                    "adapter_type": "telegram",
                    "session_id": session.session_id,
                    "user_id": query.from_user.id,
                },
            )

            # Update the message to show what was selected
            await query.edit_message_text(f"Changing directory to: `{dir_path}`", parse_mode="Markdown")

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        if update.effective_user.id not in self.user_whitelist:
            return

        help_text = """
**TeleClaude Bot Commands:**

/new_session [title] - Create a new terminal session
/list_sessions - List all active sessions
/cancel - Send CTRL+C to interrupt current command
/cancel2x - Send CTRL+C twice (for Claude Code, etc.)
/resize <size> - Resize terminal (shows presets if no size)
/rename <name> - Rename current session
/cd [path] - List trusted directories or change to specified path
/claude - Start Claude Code (cc)
/help - Show this help message

**Usage:**
1. Use /new_session to create a terminal session
2. Send text messages in the session topic to execute commands
3. Use /cancel to interrupt a running command
4. Use /cancel2x for stubborn programs (Claude Code)
5. Use /resize to change terminal size
6. Use /rename to rename the session
7. Use /claude to start Claude Code
8. View output in real-time
        """

        await update.effective_message.reply_text(help_text, parse_mode="Markdown")

    async def _handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle text messages in topics."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        await self._emit_message(
            session.session_id,
            update.effective_message.text,
            {
                "adapter_type": "telegram",
                "user_id": update.effective_user.id,
                "message_id": update.effective_message.message_id,
            },
        )

    async def _handle_voice_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle voice messages in topics."""
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
            return

        # Download voice file to temp location
        voice = update.message.voice
        voice_file = await voice.get_file()

        # Create temp file with .ogg extension (Telegram uses ogg/opus format)
        temp_dir = Path(tempfile.gettempdir()) / "teleclaude_voice"
        temp_dir.mkdir(exist_ok=True)
        temp_file_path = temp_dir / f"voice_{update.message.message_id}.ogg"

        try:
            # Download the file
            await voice_file.download_to_drive(temp_file_path)
            logger.info("Downloaded voice message to: %s", temp_file_path)

            # Emit voice event to daemon
            await self._emit_voice(
                session.session_id,
                str(temp_file_path),
                {
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
        sessions = await self.session_manager.get_sessions_by_adapter_metadata("telegram", "channel_id", str(topic_id))
        if not sessions:
            sessions = await self.session_manager.get_sessions_by_adapter_metadata("telegram", "topic_id", topic_id)

        if not sessions:
            logger.warning("No session found for closed topic %s", topic_id)
            return

        session = sessions[0]
        logger.info("Topic %s closed, cleaning up session %s", topic_id, session.session_id)

        # Emit topic closed event to daemon
        await self._emit_topic_closed(
            session.session_id,
            {
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
            message = update.message or update.edited_message

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
