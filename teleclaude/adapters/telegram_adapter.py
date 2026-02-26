"""Telegram adapter for TeleClaude."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING, AsyncIterator, Optional, cast

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
from telegram.constants import ChatAction
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
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.events import SessionStatusContext, UiCommands
from teleclaude.core.models import (
    ChannelMetadata,
    MessageMetadata,
    PeerInfo,
    Session,
)
from teleclaude.core.session_utils import get_display_title_for_session
from teleclaude.types.commands import CloseSessionCommand, KeysCommand

from .base_adapter import AdapterError
from .telegram.callback_handlers import CallbackAction, CallbackHandlersMixin
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
    COMMAND_HANDLER_OVERRIDES = {
        "agent_resume": "_handle_agent_resume_command",
        "cancel": "_handle_cancel_command",
    }

    # Simple commands that just emit an event with session_id, args, and message_id.
    # These are generated dynamically via _handle_simple_command template.
    # Format: list of command names (string)
    SIMPLE_COMMAND_EVENTS: list[str] = [
        "cancel2x",
        "kill",
        "tab",
        "enter",
        "escape",
        "escape2x",
        "ctrl",
        "shift_tab",
        "backspace",
        "key_up",
        "key_down",
        "key_left",
        "key_right",
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
        self._pending_edits: dict[str, EditContext] = {}  # Track pending edits (message_id -> mutable context)
        self._last_edit_hash: dict[str, str] = {}  # message_id -> content hash (skip no-op edits)
        self._topic_creation_locks: dict[str, asyncio.Lock] = {}  # Prevent duplicate topic creation per session_id
        self._topic_ready_events: dict[int, asyncio.Event] = {}  # topic_id -> readiness event
        self._topic_ready_cache: set[int] = set()  # topic_ids confirmed via forum_topic_created
        self._startup_housekeeping_task: asyncio.Task[None] | None = None

        # Register simple command handlers dynamically
        self._register_simple_command_handlers()

    # --- Per-adapter output message tracking ---
    # Telegram uses adapter_metadata instead of the shared DB column
    # to prevent cross-adapter races with Discord.

    async def _get_output_message_id(self, session: "Session") -> str | None:
        fresh = await db.get_session(session.session_id)
        if fresh:
            return fresh.get_metadata().get_ui().get_telegram().output_message_id
        return session.get_metadata().get_ui().get_telegram().output_message_id

    async def _store_output_message_id(self, session: "Session", message_id: str) -> None:
        meta = session.get_metadata().get_ui().get_telegram()
        meta.output_message_id = message_id
        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        logger.debug("Stored telegram output_message_id: session=%s message_id=%s", session.session_id[:8], message_id)

    async def _clear_output_message_id(self, session: "Session") -> None:
        meta = session.get_metadata().get_ui().get_telegram()
        meta.output_message_id = None
        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)

    async def _handle_session_status(self, _event: str, context: SessionStatusContext) -> None:
        """Update Telegram topic footer with canonical lifecycle status."""
        session = await db.get_session(context.session_id)
        if not session:
            return
        telegram_meta = session.get_metadata().get_ui().get_telegram()
        if not telegram_meta.topic_id:
            return  # No Telegram topic for this session
        status_line = self._format_lifecycle_status(context.status)
        try:
            await self._send_footer(session, status_line=status_line)
        except Exception as exc:
            logger.debug(
                "Telegram status footer update failed for session %s: %s",
                context.session_id[:8],
                exc,
            )

    async def send_typing_indicator(self, session: "Session") -> None:
        """Send typing indicator to Telegram topic."""
        topic_id = session.get_metadata().get_ui().get_telegram().topic_id
        if not topic_id:
            return
        await self.bot.send_chat_action(
            chat_id=self.supergroup_id,
            action=ChatAction.TYPING,
            message_thread_id=topic_id,
        )

    async def ensure_channel(self, session: Session) -> Session:
        # Telegram is admin/member only — skip customer sessions entirely.
        if session.human_role == "customer":
            return session

        # Re-read from DB to prevent stale in-memory metadata from concurrent lanes
        fresh = await db.get_session(session.session_id)
        if fresh:
            session = fresh

        telegram_meta = session.get_metadata().get_ui().get_telegram()
        logger.debug(
            "[TG_ENSURE] session=%s telegram_meta=present topic_id=%s",
            session.session_id[:8],
            telegram_meta.topic_id if telegram_meta.topic_id else "N/A",
        )
        if telegram_meta.topic_id:
            logger.debug("[TG_ENSURE] Topic exists, returning session %s", session.session_id[:8])
            return session

        title = await get_display_title_for_session(session)
        logger.info(
            "[TG_ENSURE] No topic_id for session %s, creating channel (title=%s)",
            session.session_id[:8],
            title,
        )
        try:
            await self.create_channel(session, title, metadata=ChannelMetadata())
            logger.info("[TG_ENSURE] Channel created successfully for session %s", session.session_id[:8])
        except Exception as exc:
            logger.error(
                "[TG_ENSURE] Telegram ensure_channel FAILED for session %s; retrying: %s",
                session.session_id[:8],
                exc,
            )
            current = await db.get_session(session.session_id)
            if current:
                current_meta = current.get_metadata().get_ui().get_telegram()
                current_meta.topic_id = None
                current_meta.output_message_id = None
                await db.update_session(current.session_id, adapter_metadata=current.adapter_metadata)
            await self.create_channel(current or session, title, metadata=ChannelMetadata())

        refreshed = await db.get_session(session.session_id)
        logger.debug("[TG_ENSURE] Refreshed session from DB for %s", session.session_id[:8])
        return refreshed or session

    async def recover_lane_error(
        self,
        session: Session,
        error: Exception,
        task_factory: Callable[[UiAdapter, Session], Awaitable[object]],
        display_title: str,
    ) -> object | None:
        """Recover from missing Telegram thread by resetting topic metadata and retrying."""
        message = str(error).lower()
        if (
            "message thread not found" not in message
            and "topic_deleted" not in message
            and "telegram topic_id missing" not in message
        ):
            raise error

        logger.warning(
            "[TG_RECOVER] Missing thread detected for session %s (error=%s); resetting channel metadata",
            session.session_id[:8],
            error,
        )
        refreshed = await db.get_session(session.session_id)
        recovery_session = refreshed or session

        telegram_meta = recovery_session.get_metadata().get_ui().get_telegram()
        telegram_meta.topic_id = None
        telegram_meta.output_message_id = None
        telegram_meta.footer_message_id = None
        telegram_meta.char_offset = 0

        await db.update_session(
            recovery_session.session_id,
            adapter_metadata=recovery_session.adapter_metadata,
            last_output_digest=None,
        )

        try:
            retry_session = await self.ensure_channel(recovery_session)
            result = await task_factory(self, retry_session)
            logger.info(
                "[TG_RECOVER] Recovered lane after missing thread for session %s",
                session.session_id[:8],
            )
            return result
        except Exception as retry_exc:
            logger.error(
                "[TG_RECOVER] Recovery retry failed for session %s: initial=%s retry=%s",
                session.session_id[:8],
                error,
                retry_exc,
            )
            return None

    def store_channel_id(self, adapter_metadata: object, channel_id: str) -> None:
        """Store Telegram topic_id into session adapter metadata."""
        from teleclaude.core.models import SessionAdapterMetadata

        if not isinstance(adapter_metadata, SessionAdapterMetadata):
            return

        telegram_meta = adapter_metadata.get_ui().get_telegram()
        telegram_meta.topic_id = int(channel_id)

    def _register_simple_command_handlers(self) -> None:
        """Create handler methods for simple commands dynamically.

        For each event in SIMPLE_COMMAND_EVENTS, creates a _handle_{command_name} method
        that calls the shared _handle_simple_command template.
        """
        for event in self.SIMPLE_COMMAND_EVENTS:
            command_name = event  # Event value IS the command name (e.g., "cancel", "kill")
            handler_name = f"_handle_{command_name}"
            if hasattr(self, handler_name):
                logger.debug("Skipping dynamic handler registration for %s (already defined)", handler_name)
                continue

            # Create a closure that captures the event value
            def make_handler(
                evt: str,
            ) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[object, object, None]]:
                async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
                    await self._handle_simple_command(update, context, evt)

                return handler

            setattr(self, handler_name, make_handler(event))

    async def _handle_cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /cancel command without colliding with callback cancel handler."""
        await self._handle_simple_command(update, context, "cancel")

    async def _handle_private_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command in private chats (invite token binding)."""
        assert update.effective_user is not None
        assert update.effective_message is not None

        # Extract payload from /start command
        payload = context.args[0] if context.args else None

        # Check if payload is an invite token
        if not payload or not payload.startswith("inv_"):
            await update.effective_message.reply_text(
                "Send me your invite token to get started, or contact your admin for an invite link."
            )
            return

        # Look up person by invite token
        from teleclaude.cli.config_handlers import find_person_by_invite_token, save_person_config

        result = find_person_by_invite_token(payload)
        if not result:
            await update.effective_message.reply_text("I don't recognize this invite. Please contact your admin.")
            return

        person_name, person_config = result
        user_id = str(update.effective_user.id)
        user_name = update.effective_user.username or update.effective_user.first_name or "unknown"

        # Check if credentials are already bound
        existing_user_id = person_config.creds.telegram.user_id if person_config.creds.telegram else None

        if existing_user_id:
            if str(existing_user_id) == user_id:
                # Same user - proceed to session (already bound)
                pass
            else:
                # Different user - reject
                await update.effective_message.reply_text("This invite is already associated with another account.")
                return
        else:
            # Bind credentials
            from teleclaude.config.schema import TelegramCreds

            person_config.creds.telegram = TelegramCreds(user_id=int(user_id), user_name=user_name)
            save_person_config(person_name, person_config)
            logger.info("Bound Telegram user %s to person %s", user_id, person_name)

        # Scaffold personal workspace and create session
        from teleclaude.invite import scaffold_personal_workspace

        workspace_path = scaffold_personal_workspace(person_name)

        # Create session in personal workspace
        from teleclaude.core.command_registry import get_command_service
        from teleclaude.core.origins import InputOrigin
        from teleclaude.types.commands import CreateSessionCommand

        create_cmd = CreateSessionCommand(
            project_path=str(workspace_path),
            title=f"Telegram: {person_name}",
            origin=InputOrigin.TELEGRAM.value,
            channel_metadata={
                "user_id": int(user_id),
                "telegram_user_id": int(user_id),
                "human_role": "member",
                "platform": "telegram",
                "chat_type": "private",
            },
            auto_command="agent claude",
        )
        result_dict = await get_command_service().create_session(create_cmd)
        session_id = str(result_dict.get("session_id", ""))
        if not session_id:
            logger.error("Private chat session creation returned empty session_id for %s", person_name)
            await update.effective_message.reply_text("Failed to create session. Please contact your admin.")
            return

        session = await db.get_session(session_id)
        if not session:
            logger.error("Session %s not found after creation for %s", session_id, person_name)
            return

        # Send greeting
        await update.effective_message.reply_text(
            f"Hi {person_name}, I'm your personal assistant. What would you like to work on?"
        )

    async def _handle_private_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle text messages in private chats from bound users."""
        assert update.effective_user is not None
        assert update.effective_message is not None

        user_id = str(update.effective_user.id)

        # Resolve identity
        from teleclaude.core.identity import get_identity_resolver

        identity = get_identity_resolver().resolve("telegram", {"user_id": user_id, "telegram_user_id": user_id})

        if not identity or not identity.person_name:
            # Unknown user
            await update.effective_message.reply_text(
                "I don't recognize your account. Use an invite link to get started."
            )
            return

        # Find or create session in personal workspace
        # Check if there's an active session for this user (private chat)
        sessions = await db.list_sessions(last_input_origin="telegram", include_closed=False)
        session = None
        for s in sessions:
            telegram_meta = s.get_metadata().get_ui().get_telegram()
            # In private chats, user_id is the unique identifier
            if telegram_meta.user_id == int(user_id):
                session = s
                break

        if not session:
            # Create new session
            from teleclaude.core.command_registry import get_command_service
            from teleclaude.core.origins import InputOrigin
            from teleclaude.invite import scaffold_personal_workspace
            from teleclaude.types.commands import CreateSessionCommand

            workspace_path = scaffold_personal_workspace(identity.person_name)

            create_cmd = CreateSessionCommand(
                project_path=str(workspace_path),
                title=f"Telegram: {identity.person_name}",
                origin=InputOrigin.TELEGRAM.value,
                channel_metadata={
                    "user_id": int(user_id),
                    "telegram_user_id": int(user_id),
                    "human_role": identity.person_role or "member",
                    "platform": "telegram",
                    "chat_type": "private",
                },
                auto_command="agent claude",
            )
            result_dict = await get_command_service().create_session(create_cmd)
            session_id = str(result_dict.get("session_id", ""))
            if not session_id:
                logger.error("Private chat session creation failed for %s", identity.person_name)
                return

            session = await db.get_session(session_id)
            if not session:
                logger.error("Session %s not found after creation for %s", session_id, identity.person_name)
                return

        # Process message
        text = update.effective_message.text or ""

        from teleclaude.core.command_registry import get_command_service as gcs
        from teleclaude.types.commands import ProcessMessageCommand

        cmd = ProcessMessageCommand(
            session_id=session.session_id,
            text=text,
            origin="telegram",
            actor_id=f"telegram:{user_id}",
            actor_name=identity.person_name or f"telegram:{user_id}",
            request_id=str(update.effective_message.message_id),
        )

        # Dispatch without metadata since ProcessMessageCommand doesn't accept it
        await gcs().process_message(cmd)

    async def delete_message(self, session: "Session | str", message_id: str) -> bool:
        """Delete a message by session or session_id."""
        if isinstance(session, str):
            session_obj = await db.get_session(session)
            if not session_obj:
                return False
        else:
            session_obj = session
        return await MessageOperationsMixin.delete_message(self, session_obj, message_id)

    async def _handle_simple_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE, event: str) -> None:
        """Template method for simple session commands.

        Handles commands that map to explicit command objects and dispatch via CommandService.
        """
        session = await self._get_session_from_topic(update)
        if not session:
            return

        assert update.effective_user is not None
        assert update.effective_message is not None

        args = context.args or []
        metadata = self._metadata()
        # MessageMetadata from _metadata() doesn't have project_path yet,
        # but _handle_simple_command is for session-specific commands.
        metadata.channel_metadata = metadata.channel_metadata or {}
        metadata.channel_metadata["message_id"] = str(update.effective_message.message_id)

        # Normalize via mapper
        cmds = get_command_service()
        cmd = CommandMapper.map_telegram_input(
            event=event,
            args=args,
            metadata=metadata,
            session_id=session.session_id,
        )
        cmd.request_id = str(update.effective_message.message_id)
        if isinstance(cmd, KeysCommand):
            await self._dispatch_command(
                session,
                str(update.effective_message.message_id),
                metadata,
                cmd.key,
                cmd.to_payload(),
                lambda: cmds.keys(cmd),
            )
            return

        if isinstance(cmd, CloseSessionCommand):
            await self._dispatch_command(
                session,
                str(update.effective_message.message_id),
                metadata,
                "close_session",
                cmd.to_payload(),
                lambda: cmds.close_session(cmd),
            )
            return

        raise ValueError(f"Unsupported simple command type: {type(cmd).__name__}")

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

    def _topic_owned_by_this_bot(self, update: Update, topic_id: int) -> bool:  # noqa: ARG002
        """Check if a forum topic was created by this bot.

        Uses the reply_to_message on the topic close event, which references
        the original forum_topic_created message and its author.
        """
        message = update.message
        if not message or not message.reply_to_message:
            return False
        creator = message.reply_to_message.from_user
        if not creator:
            return False
        return creator.id == self.bot.id

    async def _delete_orphan_topic(self, topic_id: int) -> None:
        """Delete a forum topic that has no session in the database."""
        try:
            await self._delete_forum_topic_with_retry(topic_id)
            logger.info("Deleted orphan topic %s", topic_id)
        except Exception as e:
            logger.warning("Failed to delete orphan topic %s: %s", topic_id, e)

    def format_output(self, tmux_output: str) -> str:
        """Format tmux output with Telegram MarkdownV2 escaping and line shortening."""
        from teleclaude.utils.markdown import escape_markdown_v2_preformatted

        if not tmux_output:
            return ""

        sanitized = escape_markdown_v2_preformatted(tmux_output)
        result = f"```\n{sanitized}\n```"

        # Shorten long separator lines (118 repeating chars → 47)
        lines = []
        for line in result.split("\n"):
            modified_line = re.sub(r"(.)\1{117}", lambda m: m.group(1) * 47, line)  # type: ignore[misc]
            lines.append(modified_line)
        return "\n".join(lines)

    def _convert_markdown_for_platform(self, text: str) -> str:
        """Convert markdown to Telegram MarkdownV2 format."""
        from teleclaude.utils.markdown import telegramify_markdown

        return telegramify_markdown(text)

    def _build_metadata_for_thread(self) -> MessageMetadata:
        """Build metadata for threaded content with MarkdownV2 parse mode."""
        return MessageMetadata(parse_mode="MarkdownV2")

    def _fit_output_to_limit(self, tmux_output: str) -> str:
        """Fit output within Telegram's 4096 byte limit with MarkdownV2 escaping."""
        from teleclaude.constants import TELEGRAM_MAX_MESSAGE_BYTES
        from teleclaude.utils.markdown import truncate_markdown_v2

        display_output = self.format_output(tmux_output)
        if self._fits_budget(display_output, TELEGRAM_MAX_MESSAGE_BYTES):
            return display_output

        trimmed_output = tmux_output
        while trimmed_output and not self._fits_budget(display_output, TELEGRAM_MAX_MESSAGE_BYTES):
            overflow = len(display_output) - self.max_message_size
            drop = max(overflow, 32)
            trimmed_output = trimmed_output[drop:] if drop < len(trimmed_output) else ""
            display_output = self.format_output(trimmed_output)

        if not self._fits_budget(display_output, TELEGRAM_MAX_MESSAGE_BYTES):
            display_output = truncate_markdown_v2(display_output, self.max_message_size, "")
        return display_output

    def _build_output_metadata(self, _session: "Session", _is_truncated: bool) -> MessageMetadata:
        """Build Telegram output metadata with MarkdownV2 parse_mode."""
        return MessageMetadata(parse_mode="MarkdownV2")

    def _build_footer_metadata(self, session: "Session") -> MessageMetadata:
        """Build Telegram footer metadata with download button when applicable."""
        metadata = MessageMetadata(parse_mode=None)
        if session.native_log_file:
            keyboard = [
                [
                    InlineKeyboardButton(
                        "📎 Download Agent session",
                        callback_data=f"download_full:{session.session_id}",
                    )
                ]
            ]
            metadata.reply_markup = InlineKeyboardMarkup(keyboard)
        return metadata

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
        logger.info("Whitelisted user IDs: %s", self.user_whitelist)
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
        logger.debug(
            "Pre-handler pending deletions: session=%s count=%d",
            session.session_id[:8],
            len(pending),
        )
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
        logger.debug(
            "Tracked message %s for deletion on next input (session %s)",
            message_id,
            session.session_id[:8],
        )

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
            callback_prefix: Prefix for callback_data (e.g., "c", "cr")

        Returns:
            InlineKeyboardMarkup with buttons for each trusted directory
        """
        keyboard = []
        for idx, trusted_dir in enumerate(self.trusted_dirs):
            button_text = f"{trusted_dir.name} - {trusted_dir.desc}" if trusted_dir.desc else trusted_dir.name
            keyboard.append([InlineKeyboardButton(text=button_text, callback_data=f"{callback_prefix}:{idx}")])
        return InlineKeyboardMarkup(keyboard)

    def _build_heartbeat_keyboard(self, bot_username: str) -> InlineKeyboardMarkup:
        """Build the heartbeat keyboard with session and agent launch actions."""
        keyboard = [
            [
                InlineKeyboardButton(
                    text="🚀 Tmux Session",
                    callback_data=f"{CallbackAction.SESSION_SELECT.value}:{bot_username}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🤖 New Claude",
                    callback_data=f"{CallbackAction.CLAUDE_SELECT.value}:{bot_username}",
                ),
                InlineKeyboardButton(
                    text="🔄 Resume Claude",
                    callback_data=f"{CallbackAction.CLAUDE_RESUME_SELECT.value}:{bot_username}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✨ New Gemini",
                    callback_data=f"{CallbackAction.GEMINI_SELECT.value}:{bot_username}",
                ),
                InlineKeyboardButton(
                    text="🔄 Resume Gemini",
                    callback_data=f"{CallbackAction.GEMINI_RESUME_SELECT.value}:{bot_username}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💻 New Codex",
                    callback_data=f"{CallbackAction.CODEX_SELECT.value}:{bot_username}",
                ),
                InlineKeyboardButton(
                    text="🔄 Resume Codex",
                    callback_data=f"{CallbackAction.CODEX_RESUME_SELECT.value}:{bot_username}",
                ),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    async def _send_or_update_menu_message(self) -> None:
        """Send or update the menu message in the general topic.

        On daemon startup, checks for an existing menu message ID in system_settings.
        If found, attempts to edit it. If edit fails (message deleted), creates a new one.
        If not found, creates a new message.

        The menu message shows a registry line with the heartbeat keyboard.
        """
        from datetime import datetime

        from teleclaude.core.models import MessageMetadata

        setting_key = f"menu_message_id:{self.computer_name}"
        bot_info = await self.bot.get_me()
        bot_username = bot_info.username or "unknown"

        # Build menu content (parse_mode=None to avoid MarkdownV2 escaping issues)
        reply_markup = self._build_heartbeat_keyboard(bot_username)
        text = f"[REGISTRY] {self.computer_name} last seen at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        metadata = MessageMetadata(reply_markup=reply_markup, parse_mode=None)

        # Check for existing message ID
        existing_msg_id = await db.get_system_setting(setting_key)

        if existing_msg_id:
            # Try to edit existing message
            success = await self.edit_general_message(existing_msg_id, text, metadata=metadata)
            if success:
                logger.info("Updated menu message %s in general topic", existing_msg_id)
                return
            # Edit failed (message deleted), fall through to create new

        # Create new message
        new_msg_id = await self.send_general_message(text, metadata=metadata)
        await db.set_system_setting(setting_key, new_msg_id)
        logger.info("Created new menu message %s in general topic", new_msg_id)

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

        sessions = await db.get_sessions_by_adapter_metadata(
            "telegram",
            "topic_id",
            thread_id,
            include_closed=True,
        )

        if not sessions:
            logger.debug("_get_session_from_topic: no session found for topic_id %s", thread_id)
            return None

        session = sessions[0]
        # TODO(core): keep treating "closing" as terminal here until lifecycle transitions
        # are strictly enforced at query-time across all adapters.
        if session.closed_at or session.lifecycle_status in {"closed", "closing"}:
            logger.debug(
                "_get_session_from_topic: topic_id %s maps to terminal session %s",
                thread_id,
                session.session_id[:8],
            )
            return None

        return session

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

        try:
            await self._send_general_message_with_retry(
                thread_id,
                error_msg,
                None,
                None,
            )
        except Exception as e:
            logger.error("Failed to send session error feedback: %s", e)

        return None

    async def discover_peers(self) -> list[PeerInfo]:
        """Discover peers via Telegram adapter.

        NOTE: Due to Telegram Bot API restrictions, bots cannot see messages
        from other bots, so this adapter does not support peer discovery.

        Actual peer discovery is handled by other adapters (e.g., RedisTransport)
        that support bot-to-bot communication.

        Returns:
            Empty list (Telegram doesn't support bot-to-bot discovery)
        """
        return []

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
            message = await self._send_general_message_with_retry(
                topic_id,
                text,
                parse_mode,
                None,
            )
        else:
            message = await self._send_general_message_with_retry(
                None,
                text,
                parse_mode,
                None,
            )

        return message

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
