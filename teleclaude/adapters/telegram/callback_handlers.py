"""Callback query handlers mixin for Telegram adapter.

Handles button clicks from inline keyboards including session creation,
project selection, and AI tool launching.
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from instrukt_ai_logging import get_logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes, ExtBot

from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.events import TeleClaudeEvents
from teleclaude.core.models import MessageMetadata
from teleclaude.utils.transcript import get_transcript_parser_info, parse_session_transcript

if TYPE_CHECKING:
    from teleclaude.config import TrustedDir
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)


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
        if not data or ":" not in data:
            return

        action, *args = data.split(":", 1)

        if action == "download_full":
            await self._handle_download_full(query, args)
        elif action == "ssel":
            await self._handle_session_select(query)
        elif action == "cd":
            await self._handle_cd_callback(query, args)
        elif action in ("csel", "crsel", "gsel", "grsel", "cxsel", "cxrsel"):
            await self._handle_agent_select(query, action)
        elif action == "ccancel":
            await self._handle_cancel(query, args)
        elif action == "s":
            await self._handle_session_start(query, args)
        elif action in ("c", "cr", "g", "gr", "cx", "cxr"):
            await self._handle_agent_start(query, action, args)

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
                await query.edit_message_text(
                    "❌ Active agent unknown for this session",
                    parse_mode="Markdown",
                )
                return
            try:
                agent_name = AgentName.from_str(agent_value)
            except ValueError as exc:
                await query.edit_message_text(f"❌ {exc}", parse_mode="Markdown")
                return
            parser_info = get_transcript_parser_info(agent_name)

            # Convert transcript to markdown
            if not native_log_file:
                await query.edit_message_text(
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
            await query.edit_message_text(f"❌ Error sending file: {e}", parse_mode="Markdown")

    async def _handle_session_select(self, query: object) -> None:
        """Handle ssel callback to show project selection for Terminal Session."""
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
        await query.edit_message_text(
            "**Select project for Terminal Session:**",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

    async def _handle_cd_callback(self, query: object, args: list[str]) -> None:
        """Handle cd callback to change directory in session."""
        from telegram import CallbackQuery

        if not isinstance(query, CallbackQuery):
            return

        msg = query.message
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
        await query.edit_message_text(
            f"**Select project for {mode_label}:**",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

    async def _handle_cancel(self, query: object, args: list[str]) -> None:
        """Handle ccancel callback to return to heartbeat view."""
        from telegram import CallbackQuery

        if not isinstance(query, CallbackQuery):
            return

        bot_username = args[0] if args else None
        if bot_username is None:
            return
        reply_markup = self._build_heartbeat_keyboard(bot_username)
        text = f"[REGISTRY] {self.computer_name} last seen at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        await query.edit_message_text(text, reply_markup=reply_markup)

    async def _handle_session_start(self, query: object, args: list[str]) -> None:
        """Handle s callback to create Terminal Session in selected project."""
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

        # Acknowledge immediately
        await query.answer("Creating session...", show_alert=False)

        # Emit NEW_SESSION event with project_dir in metadata
        logger.info("_handle_session_start: emitting NEW_SESSION with project_dir=%s", project_path)
        await self.client.handle_event(
            event=TeleClaudeEvents.NEW_SESSION,
            payload={
                "args": [],
            },
            metadata=self._metadata(project_dir=project_path),
        )

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
        auto_command, mode_label = event_map[action]

        # Acknowledge immediately
        await query.answer(f"Creating session with {mode_label}...", show_alert=False)

        # Emit NEW_SESSION event with project_dir and auto_command in metadata
        logger.info(
            "_handle_agent_start: emitting NEW_SESSION with project_dir=%s, auto_command=%s",
            project_path,
            auto_command,
        )
        await self.client.handle_event(
            event=TeleClaudeEvents.NEW_SESSION,
            payload={
                "args": [],
            },
            metadata=self._metadata(project_dir=project_path, auto_command=auto_command),
        )
