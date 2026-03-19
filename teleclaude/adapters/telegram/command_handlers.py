"""Command handlers mixin for Telegram adapter.

Handles slash commands like /new_session, /claude.
"""
# pylint: disable=protected-access

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger
from telegram import Update
from telegram.ext import ContextTypes

from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.command_registry import get_command_service

if TYPE_CHECKING:
    from typing import Protocol

    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import MessageMetadata, Session

    class _CommandHandlersHost(Protocol):  # pylint: disable=too-few-public-methods
        client: AdapterClient
        user_whitelist: set[int]
        _validate_update_for_command: Callable[[Update], bool]
        _metadata: Callable[..., MessageMetadata]
        _handle_simple_command: Callable[[Update, ContextTypes.DEFAULT_TYPE, str], Awaitable[None]]
        _get_session_from_topic: Callable[[Update], Awaitable[Session | None]]
        _require_session_from_topic: Callable[[Update], Awaitable[Session | None]]
        _dispatch_command: Callable[
            [Session, str | None, MessageMetadata, str, Mapping[str, object], Callable[[], Awaitable[object]]],
            Awaitable[object],
        ]


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
    client: AdapterClient
    user_whitelist: set[int]

    # =========================================================================
    # Command Handler Implementation
    # =========================================================================

    async def _handle_new_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /new_session command."""
        host = cast("_CommandHandlersHost", self)
        if not host._validate_update_for_command(update) or not update.effective_chat:
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
        metadata = host._metadata()
        cmd = CommandMapper.map_telegram_input(
            event="new_session",
            args=context.args or [],
            metadata=metadata,
        )
        await get_command_service().create_session(cmd)  # type: ignore[arg-type]

    async def _handle_claude_plan(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /claude_plan command - alias for /shift_tab 3 (navigate to Claude Code plan mode)."""
        context.args = ["3"]
        await cast("_CommandHandlersHost", self)._handle_simple_command(update, context, "shift_tab")

    async def handle_agent_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE, agent_name: str) -> None:
        """Public wrapper for direct agent-command dispatch."""
        await self._handle_agent_command(update, context, agent_name)

    async def handle_simple_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE, event: str) -> None:
        """Public wrapper for the shared simple-command dispatcher."""
        await cast("_CommandHandlersHost", self)._handle_simple_command(update, context, event)

    async def _handle_agent_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE, agent_name: str) -> None:
        """Generic handler for agent start commands."""
        host = cast("_CommandHandlersHost", self)
        session = await host._get_session_from_topic(update)
        if not session:
            return

        # After successful session fetch, effective_user and effective_message are guaranteed non-None
        assert update.effective_user is not None
        assert update.effective_message is not None

        # Normalize command through mapper before dispatching
        metadata = host._metadata()
        metadata.channel_metadata = metadata.channel_metadata or {}
        metadata.channel_metadata["message_id"] = str(update.effective_message.message_id)

        cmd = CommandMapper.map_telegram_input(
            event="agent",
            args=[agent_name] + (context.args or []),
            metadata=metadata,
            session_id=session.session_id,
        )
        await host._dispatch_command(
            session,
            str(update.effective_message.message_id),
            metadata,
            "start_agent",
            cmd.to_payload(),
            lambda: get_command_service().start_agent(cmd),  # type: ignore[arg-type]
        )

    async def _handle_agent_resume_command(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /agent_resume command - resume the last AI agent session.

        Resumes the active agent from the session's UX state. No arguments needed.
        """
        host = cast("_CommandHandlersHost", self)
        session = await host._require_session_from_topic(update)
        if not session:
            return

        assert update.effective_user is not None
        assert update.effective_message is not None

        # Agent name comes from session's active_agent in UX state (handled by daemon)
        # Normalize command through mapper before dispatching
        metadata = host._metadata()
        metadata.channel_metadata = metadata.channel_metadata or {}
        metadata.channel_metadata["message_id"] = str(update.effective_message.message_id)

        cmd = CommandMapper.map_telegram_input(
            event="agent_resume",
            args=[],  # Empty - daemon gets agent from UX state
            metadata=metadata,
            session_id=session.session_id,
        )
        await host._dispatch_command(
            session,
            str(update.effective_message.message_id),
            metadata,
            "resume_agent",
            cmd.to_payload(),
            lambda: get_command_service().resume_agent(cmd),  # type: ignore[arg-type]
        )

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
        host = cast("_CommandHandlersHost", self)
        session = await host._require_session_from_topic(update)
        if not session:
            return

        assert update.effective_user is not None
        assert update.effective_message is not None

        metadata = host._metadata()
        metadata.channel_metadata = metadata.channel_metadata or {}
        metadata.channel_metadata["message_id"] = str(update.effective_message.message_id)

        cmd = CommandMapper.map_telegram_input(
            event="agent_restart",
            args=[],  # Restart uses stored native_session_id; no args expected.
            metadata=metadata,
            session_id=session.session_id,
        )
        await host._dispatch_command(
            session,
            str(update.effective_message.message_id),
            metadata,
            "restart_agent",
            cmd.to_payload(),
            lambda: get_command_service().restart_agent(cmd),  # type: ignore[arg-type]
        )
