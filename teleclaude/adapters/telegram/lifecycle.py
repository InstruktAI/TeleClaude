"""Lifecycle mixin for Telegram adapter.

Handles bot initialization, startup, housekeeping, and shutdown.

Exports TelegramApp type alias for re-use in telegram_adapter.py.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, cast

import httpx
from instrukt_ai_logging import get_logger
from telegram import Update
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

try:
    from telegram.ext import AIORateLimiter as _AIORateLimiter
except ImportError:
    AIORateLimiter: Any = None
else:
    AIORateLimiter = _AIORateLimiter

from ..base_adapter import AdapterError

if TYPE_CHECKING:
    from typing import Protocol

    from teleclaude.adapters.qos.output_scheduler import OutputQoSScheduler

    class _LifecycleHost(Protocol):
        bot_token: str
        supergroup_id: int
        computer_name: str
        is_master: bool
        user_whitelist: set[int]
        _qos_scheduler: OutputQoSScheduler
        _startup_housekeeping_task: asyncio.Task[None] | None
        _get_command_handlers: Callable[[], list[tuple[str, object]]]
        _get_command_handler_update_filter: Callable[[], filters.BaseFilter]
        _handle_private_start: Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[object, object, None]]
        _handle_private_text: Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[object, object, None]]
        _handle_text_message: Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[object, object, None]]
        _handle_callback_query: Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[object, object, None]]
        _handle_voice_message: Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[object, object, None]]
        _handle_file_attachment: Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[object, object, None]]
        _handle_topic_created: Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[object, object, None]]
        _handle_topic_closed: Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[object, object, None]]
        _log_all_updates: Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[object, object, None]]
        _handle_error: Callable[[object, ContextTypes.DEFAULT_TYPE], Coroutine[object, object, None]]


logger = get_logger(__name__)

# Type alias for python-telegram-bot's Application generic.
# The library uses dict for user/chat/bot data storage — intentional design.
TelegramApp = Application[
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
    - _handle_private_start, _handle_private_text, _handle_text_message
    - _handle_callback_query, _handle_voice_message, _handle_file_attachment
    - _handle_topic_created, _handle_topic_closed, _log_all_updates, _handle_error
    """

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

    async def start(self) -> None:
        """Initialize and start Telegram bot."""
        host = cast("_LifecycleHost", self)
        # Create application with concurrent updates enabled
        # CRITICAL: concurrent_updates must be > 0 or updates can be silently dropped
        # when handlers are busy (e.g., during active polling)
        builder = Application.builder()
        builder.token(host.bot_token)
        # Force IPv4 for Telegram API calls. Some networks advertise IPv6 (AAAA) without
        # providing a working IPv6 route, which can cause connect timeouts inside httpx.
        # Pool limits must be passed directly to the transport — httpx ignores the top-level
        # `limits` kwarg when a custom transport is provided, which causes unbounded connection
        # accumulation (each connection leaks anyio TLS/memory stream tasks).
        httpx_kwargs = cast(
            dict[str, object],  # guard: loose-dict - Telegram Bot API httpx kwargs
            {
                "transport": httpx.AsyncHTTPTransport(
                    local_address="0.0.0.0",
                    limits=httpx.Limits(
                        max_connections=20,
                        max_keepalive_connections=5,
                        keepalive_expiry=30.0,
                    ),
                    retries=1,
                ),
            },
        )
        builder.request(HTTPXRequest(httpx_kwargs=httpx_kwargs))
        builder.concurrent_updates(True)  # Enable concurrent update processing

        # Enable PTB rate limiter as first-line transport-level flood control.
        # Requires python-telegram-bot[rate-limiter] (aiolimiter package).
        # If the dependency is missing, log a warning and continue without it.
        if AIORateLimiter is not None:
            builder.rate_limiter(AIORateLimiter(max_retries=3))
            logger.info("PTB AIORateLimiter enabled for Telegram transport-level rate control")
        else:
            logger.warning(
                "PTB AIORateLimiter not available (install python-telegram-bot[rate-limiter]). "
                "Continuing without transport-level rate limiter; QoS scheduler remains active."
            )

        self.app = builder.build()

        # Start QoS scheduler (non-blocking background task).
        host._qos_scheduler.start()
        assert self.app is not None  # Help mypy - app is guaranteed non-None after build()
        assert self.app.updater is not None  # Updater is created by builder

        # Register command handlers
        # IMPORTANT: For commands, handle ONLY new messages.
        # Edited command updates can duplicate execution (MESSAGE + EDITED_MESSAGE).
        for command_name, handler in host._get_command_handlers():
            typed_handler = cast(
                Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[object, object, None]],
                handler,
            )
            cmd_handler: object = CommandHandler(
                command_name,
                typed_handler,
                filters=host._get_command_handler_update_filter(),
            )
            self.app.add_handler(cmd_handler)  # type: ignore[arg-type]

        # Handle /start command in private chats (invite token binding)
        private_start_handler: object = CommandHandler(
            "start",
            host._handle_private_start,
            filters=filters.ChatType.PRIVATE,
        )
        self.app.add_handler(private_start_handler)  # type: ignore[arg-type]

        # Handle text messages in private chats (not commands) - bound users
        private_text_handler: object = MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            host._handle_private_text,
        )
        self.app.add_handler(private_text_handler)  # type: ignore[arg-type]

        # Handle text messages in topics (not commands) - both new and edited
        text_handler: object = MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.ChatType.SUPERGROUP
            & (filters.UpdateType.MESSAGE | filters.UpdateType.EDITED_MESSAGE),
            host._handle_text_message,
        )
        self.app.add_handler(text_handler)  # type: ignore[arg-type]

        # Handle callback queries from inline keyboards
        callback_handler: object = CallbackQueryHandler(host._handle_callback_query)
        self.app.add_handler(callback_handler)  # type: ignore[arg-type]

        # Handle voice messages in topics - both new and edited
        # NOTE: Do NOT add filters.ChatType.SUPERGROUP - it doesn't match forum topic messages (Telegram quirk)
        # Authorization is handled inside _handle_voice_message via _get_session_from_topic
        voice_handler: object = MessageHandler(
            filters.VOICE & (filters.UpdateType.MESSAGE | filters.UpdateType.EDITED_MESSAGE),
            host._handle_voice_message,
        )
        self.app.add_handler(voice_handler)  # type: ignore[arg-type]

        # Handle file attachments (documents, photos, etc.) in topics - both new and edited
        # NOTE: Do NOT add filters.ChatType.SUPERGROUP - it doesn't match forum topic messages (Telegram quirk)
        file_handler: object = MessageHandler(
            (filters.Document.ALL | filters.PHOTO) & (filters.UpdateType.MESSAGE | filters.UpdateType.EDITED_MESSAGE),
            host._handle_file_attachment,
        )
        self.app.add_handler(file_handler)  # type: ignore[arg-type]

        # Handle forum topic created/closed events
        created_handler: object = MessageHandler(
            filters.StatusUpdate.FORUM_TOPIC_CREATED,
            host._handle_topic_created,
        )
        closed_handler: object = MessageHandler(
            filters.StatusUpdate.FORUM_TOPIC_CLOSED,
            host._handle_topic_closed,
        )
        self.app.add_handler(created_handler)  # type: ignore[arg-type]
        self.app.add_handler(closed_handler)  # type: ignore[arg-type]

        # Add catch-all handler to log ALL updates (for debugging)
        log_handler: object = MessageHandler(
            filters.ALL,
            host._log_all_updates,
        )
        self.app.add_handler(log_handler, group=999)  # type: ignore[arg-type]

        # Register error handler to catch all exceptions
        self.app.add_error_handler(host._handle_error)

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

    async def stop(self) -> None:
        """Stop Telegram bot."""
        host = cast("_LifecycleHost", self)
        await host._qos_scheduler.stop()

        startup_task = host._startup_housekeeping_task
        if startup_task and not startup_task.done():
            startup_task.cancel()
            try:
                await startup_task
            except asyncio.CancelledError:
                pass
            host._startup_housekeeping_task = None

        if self.app and self.app.updater:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
