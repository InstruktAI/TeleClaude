"""Lifecycle mixin for Telegram adapter.

Handles bot initialization, startup, housekeeping, and shutdown.

Exports TelegramApp type alias for re-use in telegram_adapter.py.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import httpx
from instrukt_ai_logging import get_logger
from telegram import BotCommand, BotCommandScopeChat
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

from teleclaude.core.events import UiCommands

from ..base_adapter import AdapterError

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from telegram import Update

    from teleclaude.adapters.qos.output_scheduler import OutputQoSScheduler

logger = get_logger(__name__)

# Type alias for python-telegram-bot's Application generic.
# The library uses dict for user/chat/bot data storage — intentional design.
TelegramApp = Application[  # type: ignore[misc]
    ExtBot[None],
    ContextTypes.DEFAULT_TYPE,
    dict[object, object],  # User data storage
    dict[object, object],  # Chat data storage
    dict[object, object],  # Bot data storage
    JobQueue[ContextTypes.DEFAULT_TYPE],  # Job queue
]


class LifecycleMixin:
    """Mixin providing bot lifecycle (start/stop/housekeeping) for TelegramAdapter.

    Required from host class:
    - bot_token: str
    - supergroup_id: int
    - computer_name: str
    - is_master: bool
    - _qos_scheduler: OutputQoSScheduler
    - _startup_housekeeping_task: asyncio.Task[None] | None
    - _get_command_handlers() -> list[tuple[str, object]]
    - _get_command_handler_update_filter() -> filters.BaseFilter
    - _send_or_update_menu_message() -> None
    - _handle_private_start, _handle_private_text, _handle_text_message
    - _handle_callback_query, _handle_voice_message, _handle_file_attachment
    - _handle_topic_created, _handle_topic_closed, _log_all_updates, _handle_error
    """

    if TYPE_CHECKING:
        bot_token: str
        supergroup_id: int
        computer_name: str
        is_master: bool
        _qos_scheduler: OutputQoSScheduler
        _startup_housekeeping_task: asyncio.Task[None] | None

        def _get_command_handlers(self) -> list[tuple[str, object]]: ...

        def _get_command_handler_update_filter(self) -> filters.BaseFilter: ...

        async def _send_or_update_menu_message(self) -> None: ...

        async def _handle_private_start(
            self, update: Update, context: ContextTypes.DEFAULT_TYPE
        ) -> None: ...

        async def _handle_private_text(
            self, update: Update, context: ContextTypes.DEFAULT_TYPE
        ) -> None: ...

        async def _handle_text_message(
            self, update: Update, context: ContextTypes.DEFAULT_TYPE
        ) -> None: ...

        async def _handle_callback_query(
            self, update: Update, context: ContextTypes.DEFAULT_TYPE
        ) -> None: ...

        async def _handle_voice_message(
            self, update: Update, context: ContextTypes.DEFAULT_TYPE
        ) -> None: ...

        async def _handle_file_attachment(
            self, update: Update, context: ContextTypes.DEFAULT_TYPE
        ) -> None: ...

        async def _handle_topic_created(
            self, update: Update, context: ContextTypes.DEFAULT_TYPE
        ) -> None: ...

        async def _handle_topic_closed(
            self, update: Update, context: ContextTypes.DEFAULT_TYPE
        ) -> None: ...

        async def _log_all_updates(
            self, update: Update, context: ContextTypes.DEFAULT_TYPE
        ) -> None: ...

        async def _handle_error(
            self, update: object, context: ContextTypes.DEFAULT_TYPE
        ) -> None: ...

    # Set during start(); None before that.
    app: TelegramApp | None = None

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
            dict[str, object],  # guard: loose-dict - Telegram Bot API httpx kwargs
            {"transport": httpx.AsyncHTTPTransport(local_address="0.0.0.0")},
        )
        builder.request(HTTPXRequest(httpx_kwargs=httpx_kwargs))
        builder.concurrent_updates(True)  # Enable concurrent update processing

        # Enable PTB rate limiter as first-line transport-level flood control.
        # Requires python-telegram-bot[rate-limiter] (aiolimiter package).
        # If the dependency is missing, log a warning and continue without it.
        try:
            from telegram.ext import AIORateLimiter  # type: ignore[attr-defined]

            builder.rate_limiter(AIORateLimiter(max_retries=3))  # type: ignore[misc]
            logger.info("PTB AIORateLimiter enabled for Telegram transport-level rate control")
        except (ImportError, AttributeError):
            logger.warning(
                "PTB AIORateLimiter not available (install python-telegram-bot[rate-limiter]). "
                "Continuing without transport-level rate limiter; QoS scheduler remains active."
            )

        self.app = builder.build()

        # Start QoS scheduler (non-blocking background task).
        self._qos_scheduler.start()
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

        # Handle /start command in private chats (invite token binding)
        private_start_handler: object = CommandHandler(
            "start",
            self._handle_private_start,
            filters=filters.ChatType.PRIVATE,
        )
        self.app.add_handler(private_start_handler)  # type: ignore[arg-type]

        # Handle text messages in private chats (not commands) - bound users
        private_text_handler: object = MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            self._handle_private_text,
        )
        self.app.add_handler(private_text_handler)  # type: ignore[arg-type]

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
        logger.info("Whitelisted user IDs: %s", self.user_whitelist)  # type: ignore[attr-defined]
        # Non-critical startup housekeeping can involve Telegram rate limits and
        # should not block daemon/API readiness.
        self._startup_housekeeping_task = asyncio.create_task(self._run_startup_housekeeping(bot_id=bot_info.id))
        logger.debug("Scheduled Telegram startup housekeeping task")

    async def _run_startup_housekeeping(self, bot_id: int) -> None:
        """Run best-effort startup housekeeping without blocking adapter readiness."""
        try:
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
                bot_member = await self.bot.get_chat_member(self.supergroup_id, bot_id)
                logger.info("Bot status in group: %s", bot_member.status)
            except Exception as e:
                logger.error("Cannot access supergroup %s: %s", self.supergroup_id, e)
                logger.error("Make sure the bot is added to the group as a member!")

            # Send or update the menu message in the general topic
            try:
                await self._send_or_update_menu_message()
            except Exception as e:
                logger.error("Failed to send/update menu message: %s", e)
        except asyncio.CancelledError:
            logger.debug("Telegram startup housekeeping cancelled")
            raise
        except Exception:
            logger.error("Telegram startup housekeeping failed", exc_info=True)
        finally:
            # Clear task pointer only if this coroutine still owns it.
            current = asyncio.current_task()
            if self._startup_housekeeping_task is current:
                self._startup_housekeeping_task = None

    async def stop(self) -> None:
        """Stop Telegram bot."""
        await self._qos_scheduler.stop()

        if self._startup_housekeeping_task and not self._startup_housekeeping_task.done():
            self._startup_housekeeping_task.cancel()
            try:
                await self._startup_housekeeping_task
            except asyncio.CancelledError:
                pass
            self._startup_housekeeping_task = None

        if self.app and self.app.updater:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
