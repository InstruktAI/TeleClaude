"""Command handlers mixin for Telegram adapter.

Handles slash commands like /new_session, /claude, /rename, /cd.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from teleclaude.core.db import db
from teleclaude.core.events import EventType, TeleClaudeEvents
from teleclaude.core.models import CleanupTrigger, MessageMetadata

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)


class CommandHandlersMixin:
    """Mixin providing slash command handlers for TelegramAdapter.

    Required from host class:
    - client: AdapterClient
    - user_whitelist: set[int]
    - _validate_update_for_command(update: Update) -> bool
    - _event_to_command(event_name: str) -> str
    - _metadata(**kwargs: object) -> AdapterMetadata
    - _build_project_keyboard(callback_prefix: str) -> InlineKeyboardMarkup
    - _get_session_from_topic(update: Update) -> Optional[Session]
    - _require_session_from_topic(update: Update) -> Optional[Session]
    - _pre_handle_user_input(session: Session) -> None
    """

    # Abstract properties/attributes (declared for type hints)
    client: "AdapterClient"
    user_whitelist: set[int]

    if TYPE_CHECKING:

        def _validate_update_for_command(self, update: Update) -> bool:
            """Validate update has required fields for command handling."""
            ...

        def _event_to_command(self, event_name: str) -> str:
            """Convert event name to command string."""
            ...

        def _metadata(self, **kwargs: object) -> MessageMetadata:
            """Create adapter metadata."""
            ...

        def _build_project_keyboard(self, callback_prefix: str) -> InlineKeyboardMarkup:
            """Build keyboard with trusted directories."""
            ...

        async def _get_session_from_topic(self, update: Update) -> "Session | None":
            """Get session from update's topic."""
            ...

        async def _require_session_from_topic(self, update: Update) -> "Session | None":
            """Require session from update's topic, showing error if not found."""
            ...

        async def _pre_handle_user_input(self, session: "Session") -> None:
            """Pre-handle user input (delete old messages)."""
            ...

    # =========================================================================
    # Command Handler Implementation
    # =========================================================================

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

        # Normalize command through mapper before dispatching
        from teleclaude.core.command_mapper import CommandMapper

        metadata = self._metadata()
        cmd = CommandMapper.map_telegram_input(
            event="new_session",
            args=context.args or [],
            metadata=metadata,
        )
        await self.client.handle_internal_command(cmd, metadata=metadata)

    async def _handle_claude_plan(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /claude_plan command - alias for /shift_tab 3 (navigate to Claude Code plan mode)."""
        context.args = ["3"]
        await self._handle_simple_command(update, context, TeleClaudeEvents.SHIFT_TAB)

    if TYPE_CHECKING:

        async def _handle_simple_command(
            self, update: Update, context: ContextTypes.DEFAULT_TYPE, event: EventType
        ) -> None:
            """Handle simple command - stub for type checking."""
            ...

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
            await self.client.send_message(
                session,
                "Usage: /rename <new name>",
                metadata=self._metadata(),
                cleanup_trigger=CleanupTrigger.NEXT_NOTICE,
            )
            return

        metadata = self._metadata()
        metadata.channel_metadata = metadata.channel_metadata or {}
        metadata.channel_metadata["message_id"] = str(update.effective_message.message_id)
        from teleclaude.core.command_mapper import CommandMapper

        cmd = CommandMapper.map_telegram_input(
            event="rename",
            args=context.args or [],
            metadata=metadata,
            session_id=session.session_id,
        )
        await self.client.handle_internal_command(cmd, metadata=metadata)

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
            metadata = self._metadata()
            metadata.channel_metadata = metadata.channel_metadata or {}
            metadata.channel_metadata["message_id"] = str(update.effective_message.message_id)
            from teleclaude.core.command_mapper import CommandMapper

            cmd = CommandMapper.map_telegram_input(
                event="cd",
                args=context.args or [],
                metadata=metadata,
                session_id=session.session_id,
            )
            await self.client.handle_internal_command(cmd, metadata=metadata)
            return

        # No args - show trusted directories as buttons (track command message for deletion)
        await self._pre_handle_user_input(session)
        await db.add_pending_deletion(session.session_id, str(update.effective_message.message_id))
        reply_markup = self._build_project_keyboard("cd")
        await self.client.send_message(
            session,
            "**Select a directory:**",
            metadata=MessageMetadata(reply_markup=reply_markup, parse_mode="Markdown"),
            cleanup_trigger=CleanupTrigger.NEXT_NOTICE,
        )

    async def _handle_agent_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE, agent_name: str) -> None:
        """Generic handler for agent start commands."""
        session = await self._get_session_from_topic(update)
        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        # Normalize command through mapper before dispatching
        from teleclaude.core.command_mapper import CommandMapper

        metadata = self._metadata()
        metadata.channel_metadata = metadata.channel_metadata or {}
        metadata.channel_metadata["message_id"] = str(update.effective_message.message_id)

        cmd = CommandMapper.map_telegram_input(
            event="agent",
            args=[agent_name] + (context.args or []),
            metadata=metadata,
            session_id=session.session_id,
        )
        await self.client.handle_internal_command(cmd, metadata=metadata)

    async def _handle_agent_resume_command(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /agent_resume command - resume the last AI agent session.

        Resumes the active agent from the session's UX state. No arguments needed.
        """
        session = await self._require_session_from_topic(update)
        if not session:
            return

        assert update.effective_user is not None
        assert update.effective_message is not None

        # Agent name comes from session's active_agent in UX state (handled by daemon)
        # Normalize command through mapper before dispatching
        from teleclaude.core.command_mapper import CommandMapper

        metadata = self._metadata()
        metadata.channel_metadata = metadata.channel_metadata or {}
        metadata.channel_metadata["message_id"] = str(update.effective_message.message_id)

        cmd = CommandMapper.map_telegram_input(
            event="agent_resume",
            args=[],  # Empty - daemon gets agent from UX state
            metadata=metadata,
            session_id=session.session_id,
        )
        await self.client.handle_internal_command(cmd, metadata=metadata)

    async def _handle_claude(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /claude command - start Claude agent."""
        await self._handle_agent_command(update, context, "claude")

    async def _handle_gemini(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /gemini command - start Gemini agent."""
        await self._handle_agent_command(update, context, "gemini")

    async def _handle_codex(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /codex command - start Codex agent."""
        await self._handle_agent_command(update, context, "codex")

    async def _handle_agent_restart(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /agent_restart command - restart Agent in this session."""
        session = await self._require_session_from_topic(update)
        if not session:
            return

        assert update.effective_user is not None
        assert update.effective_message is not None

        metadata = self._metadata()
        metadata.channel_metadata = metadata.channel_metadata or {}
        metadata.channel_metadata["message_id"] = str(update.effective_message.message_id)
        from teleclaude.core.command_mapper import CommandMapper

        cmd = CommandMapper.map_telegram_input(
            event="agent_restart",
            args=[],  # Restart uses stored native_session_id; no args expected.
            metadata=metadata,
            session_id=session.session_id,
        )
        await self.client.handle_internal_command(cmd, metadata=metadata)
