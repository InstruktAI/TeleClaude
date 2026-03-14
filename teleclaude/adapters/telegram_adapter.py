"""Telegram adapter for TeleClaude."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

if TYPE_CHECKING:
    from telegram import Message as TelegramMessage

    from teleclaude.core.adapter_client import AdapterClient

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction
from telegram.ext import filters

from teleclaude.adapters.qos.output_scheduler import OutputQoSScheduler
from teleclaude.adapters.qos.policy import telegram_policy
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.events import SessionStatusContext
from teleclaude.core.models import (
    ChannelMetadata,
    MessageMetadata,
    Session,
)
from teleclaude.core.session_utils import get_display_title_for_session

from .telegram.callback_handlers import CallbackAction, CallbackHandlersMixin
from .telegram.channel_ops import ChannelOperationsMixin
from .telegram.command_handlers import CommandHandlersMixin
from .telegram.input_handlers import InputHandlersMixin
from .telegram.lifecycle import LifecycleMixin, TelegramApp
from .telegram.message_ops import EditContext, MessageOperationsMixin
from .telegram.private_handlers import PrivateHandlersMixin
from .ui_adapter import UiAdapter

logger = get_logger(__name__)


class TelegramAdapter(  # pyright: ignore[reportIncompatibleMethodOverride]  # type: ignore[misc]
    PrivateHandlersMixin,
    LifecycleMixin,
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

    def __init__(self, client: AdapterClient) -> None:
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
        self.app: TelegramApp | None = None
        self._processed_voice_messages: set[str] = set()  # Track processed voice message IDs with edit state
        self._pending_edits: dict[str, EditContext] = {}  # Track pending edits (message_id -> mutable context)
        self._last_edit_hash: dict[str, str] = {}  # message_id -> content hash (skip no-op edits)
        self._topic_creation_locks: dict[str, asyncio.Lock] = {}  # Prevent duplicate topic creation per session_id
        self._topic_ready_events: dict[int, asyncio.Event] = {}  # topic_id -> readiness event
        self._topic_ready_cache: set[int] = set()  # topic_ids confirmed via forum_topic_created
        self._startup_housekeeping_task: asyncio.Task[None] | None = None

        # Output QoS scheduler: coalesces stale payloads and enforces pacing budget.
        qos_policy = telegram_policy(config.telegram.qos)
        self._qos_scheduler: OutputQoSScheduler = OutputQoSScheduler(qos_policy)

        # Register simple command handlers dynamically
        self._register_simple_command_handlers()

    # --- Per-adapter output message tracking ---
    # Telegram uses adapter_metadata instead of the shared DB column
    # to prevent cross-adapter races with Discord.

    async def _get_output_message_id(self, session: Session) -> str | None:
        fresh = await db.get_session(session.session_id)
        if fresh:
            return fresh.get_metadata().get_ui().get_telegram().output_message_id
        return session.get_metadata().get_ui().get_telegram().output_message_id

    async def _store_output_message_id(self, session: Session, message_id: str) -> None:
        meta = session.get_metadata().get_ui().get_telegram()
        meta.output_message_id = message_id
        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        logger.debug("Stored telegram output_message_id: session=%s message_id=%s", session.session_id, message_id)

    async def _clear_output_message_id(self, session: Session) -> None:
        meta = session.get_metadata().get_ui().get_telegram()
        meta.output_message_id = None
        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)

    async def _handle_session_status(self, _event: str, context: SessionStatusContext) -> None:
        """Update Telegram topic footer with canonical lifecycle status and fire typing on active."""
        # Base class fires typing indicator on active/accepted
        await super()._handle_session_status(_event, context)

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
                context.session_id,
                exc,
            )

    async def send_typing_indicator(self, session: Session) -> None:
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
            session.session_id,
            telegram_meta.topic_id if telegram_meta.topic_id else "N/A",
        )
        if telegram_meta.topic_id:
            logger.debug("[TG_ENSURE] Topic exists, returning session %s", session.session_id)
            return session

        title = await get_display_title_for_session(session)
        logger.info(
            "[TG_ENSURE] No topic_id for session %s, creating channel (title=%s)",
            session.session_id,
            title,
        )
        try:
            await self.create_channel(session, title, metadata=ChannelMetadata())
            logger.info("[TG_ENSURE] Channel created successfully for session %s", session.session_id)
        except Exception as exc:
            logger.error(
                "[TG_ENSURE] Telegram ensure_channel FAILED for session %s; retrying: %s",
                session.session_id,
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
        logger.debug("[TG_ENSURE] Refreshed session from DB for %s", session.session_id)
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
            session.session_id,
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
                session.session_id,
            )
            return result
        except Exception as retry_exc:
            logger.error(
                "[TG_RECOVER] Recovery retry failed for session %s: initial=%s retry=%s",
                session.session_id,
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

    def _is_message_from_trusted_bot(self, message: TelegramMessage) -> bool:
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

    def _topic_owned_by_this_bot(self, update: Update, topic_id: int) -> bool:
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

    def _build_output_metadata(self, _session: Session, _is_truncated: bool) -> MessageMetadata:
        """Build Telegram output metadata with MarkdownV2 parse_mode."""
        return MessageMetadata(parse_mode="MarkdownV2")

    def _build_footer_metadata(self, session: Session) -> MessageMetadata:
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

    async def _pre_handle_user_input(self, session: Session) -> None:
        """UI adapter pre-handler: Delete ephemeral messages from previous interaction.

        Called by AdapterClient BEFORE processing new user input.
        Cleans up UI state from previous interaction (all ephemeral messages).

        Unified design: All messages tracked via pending_deletions are cleaned here,
        including user input messages, feedback, errors, etc.

        Args:
            session: Session object
        """
        logger.info("PRE-HANDLER CALLED for session %s", session.session_id)
        # Delete pending ephemeral messages from previous interaction
        pending = await db.get_pending_deletions(session.session_id)
        logger.debug(
            "Pre-handler pending deletions: session=%s count=%d",
            session.session_id,
            len(pending),
        )
        if pending:
            for msg_id in pending:
                try:
                    await self.delete_message(session, msg_id)
                    logger.debug(
                        "Deleted pending message %s for session %s",
                        msg_id,
                        session.session_id,
                    )
                except Exception as e:
                    # Resilient to already-deleted messages
                    logger.warning("Failed to delete message %s: %s", msg_id, e)
            await db.clear_pending_deletions(session.session_id)

    async def _post_handle_user_input(self, session: Session, message_id: str) -> None:
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
            session.session_id,
        )

    # ==================== Output QoS Integration ====================

    async def send_output_update(  # type: ignore[override]  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        session: Session,
        output: str,
        started_at: float,
        last_output_changed_at: float,
        is_final: bool = False,
        exit_code: int | None = None,
        render_markdown: bool = False,
    ) -> str | None:
        """Route Telegram output update through the QoS scheduler.

        When QoS is off, delegates directly to the parent implementation.
        When QoS is active, enqueues the payload for paced dispatch and returns None
        immediately. The scheduler's background loop calls the parent at the computed
        cadence, storing the output_message_id via _store_output_message_id as usual.

        Final (is_final=True) payloads are placed in the priority queue and dispatched
        in the next available scheduler slot without bypassing ordering invariants.
        """
        from teleclaude.adapters.ui_adapter import UiAdapter

        if self._qos_scheduler._policy.mode == "off":
            return await UiAdapter.send_output_update(
                self, session, output, started_at, last_output_changed_at, is_final, exit_code, render_markdown
            )

        # Capture args for the dispatch closure (coalescing replaces old closures).
        _self = self
        _session = session
        _output = output
        _started_at = started_at
        _last_changed = last_output_changed_at
        _is_final = is_final
        _exit_code = exit_code
        _render_md = render_markdown

        async def _dispatch() -> str | None:
            return await UiAdapter.send_output_update(
                _self, _session, _output, _started_at, _last_changed, _is_final, _exit_code, _render_md
            )

        self._qos_scheduler.enqueue(session.session_id, _dispatch, is_final=is_final)
        return None  # Delivery is deferred; message_id stored asynchronously.

    async def send_threaded_output(  # type: ignore[override]
        self,
        session: Session,
        text: str,
        multi_message: bool = False,
    ) -> str | None:
        """Route Telegram threaded output through the QoS scheduler.

        Threaded output payloads are coalesced (latest-only) so that only the
        most recent accumulated text is dispatched per scheduler tick.
        """
        from teleclaude.adapters.ui_adapter import UiAdapter
        from teleclaude.utils.markdown import MARKDOWN_V2_INITIAL_STATE

        if self._qos_scheduler._policy.mode == "off":
            return await UiAdapter.send_threaded_output(self, session, text, multi_message)

        _self = self
        _session = session
        _text = text
        _multi = multi_message

        async def _dispatch() -> str | None:
            return await UiAdapter.send_threaded_output(_self, _session, _text, _multi, MARKDOWN_V2_INITIAL_STATE)

        # Threaded output chunks are non-final (the coordinator handles completion separately).
        self._qos_scheduler.enqueue(session.session_id, _dispatch, is_final=False)
        return None  # Delivery is deferred.

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
            callback_prefix: Prefix for callback_data (e.g., "s", "as:claude", "ars:gemini")

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
        from teleclaude.core.agents import get_enabled_agents

        keyboard: list[list[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    text="🚀 Tmux Session",
                    callback_data=f"{CallbackAction.SESSION_SELECT.value}:{bot_username}",
                )
            ],
        ]
        for agent in get_enabled_agents():
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=f"🤖 New {agent.title()}",
                        callback_data=f"{CallbackAction.AGENT_SELECT.value}:{agent}:{bot_username}",
                    ),
                    InlineKeyboardButton(
                        text=f"🔄 Resume {agent.title()}",
                        callback_data=f"{CallbackAction.AGENT_RESUME_SELECT.value}:{agent}:{bot_username}",
                    ),
                ]
            )
        return InlineKeyboardMarkup(keyboard)
