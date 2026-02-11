"""Callback query handlers mixin for Telegram adapter.

Handles button clicks from inline keyboards including session creation,
project selection, and AI tool launching.
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from instrukt_ai_logging import get_logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes, ExtBot

from teleclaude.core.agents import AgentName
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata
from teleclaude.utils import command_retry
from teleclaude.utils.transcript import get_transcript_parser_info, parse_session_transcript

if TYPE_CHECKING:
    from teleclaude.config import TrustedDir
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

CALLBACK_SEPARATOR = ":"


class CallbackAction(str, Enum):
    """Supported Telegram callback actions."""

    DOWNLOAD_FULL = "download_full"
    SESSION_SELECT = "ssel"
    CLAUDE_SELECT = "csel"
    CLAUDE_RESUME_SELECT = "crsel"
    GEMINI_SELECT = "gsel"
    GEMINI_RESUME_SELECT = "grsel"
    CODEX_SELECT = "cxsel"
    CODEX_RESUME_SELECT = "cxrsel"
    CANCEL = "ccancel"
    SESSION_START = "s"
    CLAUDE_START = "c"
    CLAUDE_RESUME_START = "cr"
    GEMINI_START = "g"
    GEMINI_RESUME_START = "gr"
    CODEX_START = "cx"
    CODEX_RESUME_START = "cxr"


AGENT_SELECT_ACTIONS: set[CallbackAction] = {
    CallbackAction.CLAUDE_SELECT,
    CallbackAction.CLAUDE_RESUME_SELECT,
    CallbackAction.GEMINI_SELECT,
    CallbackAction.GEMINI_RESUME_SELECT,
    CallbackAction.CODEX_SELECT,
    CallbackAction.CODEX_RESUME_SELECT,
}

AGENT_START_ACTIONS: set[CallbackAction] = {
    CallbackAction.CLAUDE_START,
    CallbackAction.CLAUDE_RESUME_START,
    CallbackAction.GEMINI_START,
    CallbackAction.GEMINI_RESUME_START,
    CallbackAction.CODEX_START,
    CallbackAction.CODEX_RESUME_START,
}


class CallbackHandlersMixin:
    """Mixin providing callback query handlers for TelegramAdapter.

    Required from host class:
    - client: AdapterClient
    - trusted_dirs: list[TrustedDir]
    - user_whitelist: set[int]
    - computer_name: str
    - bot: ExtBot[None] (property)
    - _build_project_keyboard(callback_prefix: str) -> InlineKeyboardMarkup
    - _build_heartbeat_keyboard(bot_username: str) -> InlineKeyboardMarkup
    - _send_document_with_retry(...) -> Message
    - _metadata(...) -> AdapterMetadata
    """

    # Abstract properties/attributes (declared for type hints)
    client: "AdapterClient"
    trusted_dirs: list["TrustedDir"]
    user_whitelist: set[int]
    computer_name: str

    if TYPE_CHECKING:

        @property
        def bot(self) -> ExtBot[None]:
            """Return the Telegram bot instance."""
            ...

        def _build_project_keyboard(self, callback_prefix: str) -> InlineKeyboardMarkup:
            """Build keyboard with trusted directories."""
            ...

        def _build_heartbeat_keyboard(self, bot_username: str) -> InlineKeyboardMarkup:
            """Build heartbeat keyboard with action buttons."""
            ...

        async def _send_document_with_retry(
            self,
            chat_id: int,
            message_thread_id: int,
            file_path: str,
            filename: str,
            caption: Optional[str] = None,
        ) -> Message:
            """Send document with retry logic."""
            ...

        def _metadata(self, **kwargs: object) -> MessageMetadata:
            """Create adapter metadata."""
            ...

    # =========================================================================
    # Callback Query Handler Implementation
    # =========================================================================

    async def _handle_callback_query(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:  # pylint: disable=too-many-locals
        """Handle button clicks from inline keyboards."""
        query = update.callback_query
        if not query:
            return
        await query.answer()

        # Parse callback data
        data = query.data
        if not data or CALLBACK_SEPARATOR not in data:
            return

        action_raw, *args = data.split(CALLBACK_SEPARATOR, 1)
        try:
            action = CallbackAction(action_raw)
        except ValueError:
            logger.debug("Unknown callback action: %s", action_raw)
            return

        logger.debug("Callback: action=%s args=%s", action.value, args)

        if action is CallbackAction.DOWNLOAD_FULL:
            await self._handle_download_full(query, args)
        elif action is CallbackAction.SESSION_SELECT:
            await self._handle_session_select(query)
        elif action in AGENT_SELECT_ACTIONS:
            await self._handle_agent_select(query, action.value)
        elif action is CallbackAction.CANCEL:
            await self._handle_cancel(query, args)
        elif action is CallbackAction.SESSION_START:
            await self._handle_session_start(query, args)
        elif action in AGENT_START_ACTIONS:
            await self._handle_agent_start(query, action.value, args)

    async def _edit_callback_message(
        self,
        query: object,
        text: str,
        *,
        parse_mode: Optional[str] = None,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> None:
        """Edit callback message with retry and benign-error tolerance."""
        from telegram import CallbackQuery

        if not isinstance(query, CallbackQuery):
            return

        try:
            await self._edit_callback_message_with_retry(query, text, parse_mode=parse_mode, reply_markup=reply_markup)
        except BadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
            raise

    @command_retry(max_retries=3, max_timeout=60.0)
    async def _edit_callback_message_with_retry(
        self,
        query: object,
        text: str,
        *,
        parse_mode: Optional[str] = None,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> None:
        """Internal retry-protected callback message edit."""
        from telegram import CallbackQuery

        if not isinstance(query, CallbackQuery):
            return

        await query.edit_message_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )

    async def _handle_download_full(self, query: object, args: list[str]) -> None:
        """Handle download_full callback to download session transcript."""
        # Type narrow query
        from telegram import CallbackQuery

        if not isinstance(query, CallbackQuery):
            return

        session_id = args[0] if args else None
        if not session_id or not query.message:
            return

        try:
            # Get session for metadata
            session = await db.get_session(session_id)
            if not session:
                return

            # Check if there's a session transcript
            native_log_file = session.native_log_file
            agent_value = session.active_agent
            if not agent_value:
                await self._edit_callback_message(
                    query,
                    "❌ Active agent unknown for this session",
                    parse_mode="Markdown",
                )
                return
            try:
                agent_name = AgentName.from_str(agent_value)
            except ValueError as exc:
                await self._edit_callback_message(query, f"❌ {exc}", parse_mode="Markdown")
                return
            parser_info = get_transcript_parser_info(agent_name)

            # Convert transcript to markdown
            if not native_log_file:
                await self._edit_callback_message(
                    query,
                    f"❌ No {parser_info.display_name} session file found",
                    parse_mode="Markdown",
                )
                return
            markdown_content = parse_session_transcript(
                native_log_file,
                session.title,
                agent_name=agent_name,
                tail_chars=0,
            )
            filename = f"{parser_info.file_prefix}-{session_id:8}.md"
            caption = f"{parser_info.display_name} session transcript"

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

            # Track download message for cleanup when next feedback is sent
            await db.add_pending_deletion(session_id, str(doc_message.message_id), deletion_type="feedback")
        except Exception as e:
            logger.error("Failed to send output file: %s", e)
            await self._edit_callback_message(query, f"❌ Error sending file: {e}", parse_mode="Markdown")

    async def _handle_session_select(self, query: object) -> None:
        """Handle ssel callback to show project selection for Tmux Session."""
        from telegram import CallbackQuery

        if not isinstance(query, CallbackQuery):
            return

        if not query.from_user or not query.message:
            return

        # Check if authorized
        if query.from_user.id not in self.user_whitelist:
            await query.answer("❌ Not authorized", show_alert=True)
            return

        # Build keyboard with trusted directories using helper
        reply_markup = self._build_project_keyboard("s")

        # Add cancel button to return to original view
        bot_info = await self.bot.get_me()
        keyboard = list(reply_markup.inline_keyboard)
        keyboard.append(
            (
                InlineKeyboardButton(
                    text="❌ Cancel",
                    callback_data=f"ccancel:{bot_info.username}",
                ),
            )
        )

        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._edit_callback_message(
            query,
            "**Select project for Tmux Session:**",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

    async def _handle_agent_select(self, query: object, action: str) -> None:
        """Handle agent selection callbacks (csel, crsel, gsel, grsel, cxsel, cxrsel)."""
        from telegram import CallbackQuery

        if not isinstance(query, CallbackQuery):
            return

        if not query.from_user or not query.message:
            return

        # Check if authorized
        if query.from_user.id not in self.user_whitelist:
            await query.answer("❌ Not authorized", show_alert=True)
            return

        # Determine mode and prefix
        mode_map = {
            "csel": ("c", "Claude"),
            "crsel": ("cr", "Claude Resume"),
            "gsel": ("g", "Gemini"),
            "grsel": ("gr", "Gemini Resume"),
            "cxsel": ("cx", "Codex"),
            "cxrsel": ("cxr", "Codex Resume"),
        }

        callback_prefix, mode_label = mode_map[action]

        # Build keyboard with trusted directories using helper
        reply_markup = self._build_project_keyboard(callback_prefix)

        # Add cancel button to return to original view
        bot_info = await self.bot.get_me()
        keyboard = list(reply_markup.inline_keyboard)
        keyboard.append(
            (
                InlineKeyboardButton(
                    text="❌ Cancel",
                    callback_data=f"ccancel:{bot_info.username}",
                ),
            )
        )

        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._edit_callback_message(
            query,
            f"**Select project for {mode_label}:**",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

    async def _restore_heartbeat_menu(self, query: object) -> None:
        """Restore the menu message back to the heartbeat keyboard view."""
        from telegram import CallbackQuery

        if not isinstance(query, CallbackQuery):
            return

        bot_info = await self.bot.get_me()
        bot_username = bot_info.username or "unknown"
        reply_markup = self._build_heartbeat_keyboard(bot_username)
        text = f"[REGISTRY] {self.computer_name} last seen at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        await self._edit_callback_message(query, text, reply_markup=reply_markup)

    async def _handle_cancel(self, query: object, args: list[str]) -> None:
        """Handle ccancel callback to return to heartbeat view."""
        await self._restore_heartbeat_menu(query)

    async def _handle_session_start(self, query: object, args: list[str]) -> None:
        """Handle s callback to create Tmux Session in selected project."""
        from telegram import CallbackQuery

        if not isinstance(query, CallbackQuery):
            return

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

        # Restore menu immediately (optimistic UX)
        await self._restore_heartbeat_menu(query)

        # Create session in background
        logger.info("_handle_session_start: creating session with project_path=%s", project_path)
        metadata = self._metadata(project_path=project_path)
        cmd = CommandMapper.map_telegram_input(
            event="new_session",
            args=[],
            metadata=metadata,
        )
        await get_command_service().create_session(cmd)

    async def _handle_agent_start(self, query: object, action: str, args: list[str]) -> None:
        """Handle agent start callbacks (c, cr, g, gr, cx, cxr)."""
        from telegram import CallbackQuery

        if not isinstance(query, CallbackQuery):
            return

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

        # Determine event type and label
        event_map = {
            "c": ("agent claude", "Claude"),
            "cr": ("agent_resume claude", "Claude Resume"),
            "g": ("agent gemini", "Gemini"),
            "gr": ("agent_resume gemini", "Gemini Resume"),
            "cx": ("agent codex", "Codex"),
            "cxr": ("agent_resume codex", "Codex Resume"),
        }

        # Trust that action is in map (guaranteed by if condition)
        auto_command, _mode_label = event_map[action]

        # Restore menu immediately (optimistic UX)
        await self._restore_heartbeat_menu(query)

        # Create session in background
        logger.info(
            "_handle_agent_start: creating session with project_path=%s, auto_command=%s",
            project_path,
            auto_command,
        )
        metadata = self._metadata(project_path=project_path, auto_command=auto_command)
        cmd = CommandMapper.map_telegram_input(
            event="new_session",
            args=[],
            metadata=metadata,
        )
        await get_command_service().create_session(cmd)
