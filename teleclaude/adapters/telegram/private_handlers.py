"""Private chat handlers mixin for Telegram adapter.

Handles /start invite binding, private text routing, simple command
dispatching, and the dynamic command-handler factory.
"""
# pylint: disable=protected-access

from __future__ import annotations

import shlex
from collections.abc import Callable, Coroutine, Mapping
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger
from telegram import Update
from telegram.ext import ContextTypes

import teleclaude.core.agents as agents_module
import teleclaude.core.identity as identity_module
import teleclaude.invite as invite_module
from teleclaude.adapters.telegram.message_ops import MessageOperationsMixin
from teleclaude.cli.config_handlers import find_person_by_invite_token, save_person_config
from teleclaude.config.schema import TelegramCreds
from teleclaude.core import command_registry
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.db import db
from teleclaude.core.models import Session, SessionMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import CloseSessionCommand, CreateSessionCommand, KeysCommand, ProcessMessageCommand

if TYPE_CHECKING:
    from typing import Protocol

    from teleclaude.core.command_service import CommandService
    from teleclaude.core.models import MessageMetadata

    class _PrivateHandlersHost(Protocol):  # pylint: disable=too-few-public-methods
        SIMPLE_COMMAND_EVENTS: list[str]
        _metadata: Callable[..., MessageMetadata]
        _get_session_from_topic: Callable[[Update], Coroutine[object, object, Session | None]]
        _dispatch_command: Callable[
            [
                Session,
                str | None,
                MessageMetadata,
                str,
                Mapping[str, object],
                Callable[[], Coroutine[object, object, object]],
            ],
            Coroutine[object, object, object],
        ]


logger = get_logger(__name__)


def get_command_service() -> CommandService:
    """Delegate to the global command-service registry at call time.

    Keeping this local wrapper preserves both test seams:
    - patching `teleclaude.core.command_registry.get_command_service`
    - patching `teleclaude.adapters.telegram.private_handlers.get_command_service`
    """
    return command_registry.get_command_service()


class PrivateHandlersMixin:
    """Mixin providing private-chat handlers and simple-command dispatch for TelegramAdapter.

    Required from host class:
    - SIMPLE_COMMAND_EVENTS: list[str]
    - _metadata(**kwargs) -> MessageMetadata
    - _get_session_from_topic(update: Update) -> Session | None
    - _dispatch_command(session, message_id, metadata, event, payload, fn) -> None
    """

    SIMPLE_COMMAND_EVENTS: list[str]

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

    def register_simple_command_handlers(self) -> None:
        """Public wrapper for dynamic simple-command registration."""
        self._register_simple_command_handlers()

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
            person_config.creds.telegram = TelegramCreds(user_id=int(user_id), user_name=user_name)
            save_person_config(person_name, person_config)
            logger.info("Bound Telegram user %s to person %s", user_id, person_name)

        # Scaffold personal workspace and create session
        workspace_path = invite_module.scaffold_personal_workspace(person_name)

        # Create session in personal workspace
        create_cmd = CreateSessionCommand(
            project_path=str(workspace_path),
            title=f"Telegram: {person_name}",
            origin=InputOrigin.TELEGRAM.value,
            channel_metadata={
                "user_id": int(user_id),
                "telegram_user_id": int(user_id),
                "platform": "telegram",
                "chat_type": "private",
            },
            session_metadata=SessionMetadata(human_role="member"),
            auto_command=f"agent {agents_module.get_default_agent()}",
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

    async def _handle_private_text(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle text messages in private chats from bound users."""
        assert update.effective_user is not None
        assert update.effective_message is not None

        user_id = str(update.effective_user.id)

        identity = identity_module.get_identity_resolver().resolve(
            "telegram",
            {"user_id": user_id, "telegram_user_id": user_id},
        )

        if not identity or not identity.person_name:
            # Unknown user
            await update.effective_message.reply_text(
                "I don't recognize your account. Use an invite link to get started."
            )
            return

        session = await self._find_private_session(user_id)

        if not session:
            # Create new session with user's message bundled into auto_command.
            # agent_then_message waits for the agent TUI to stabilize before injecting
            # the message, preventing the race where the message is sent to tmux before
            # the agent is ready to accept input.
            result_dict = await self._create_private_session_for_identity(
                user_id,
                identity.person_name,
                update.effective_message.text or "",
                identity.person_role or "member",
            )
            session_id = str(result_dict.get("session_id", ""))
            if not session_id:
                logger.error("Private chat session creation failed for %s", identity.person_name)
            return

        # Existing session — deliver message through inbound queue
        text = update.effective_message.text or ""

        msg_id = str(update.effective_message.message_id)
        cmd = ProcessMessageCommand(
            session_id=session.session_id,
            text=text,
            origin="telegram",
            actor_id=f"telegram:{user_id}",
            actor_name=identity.person_name or f"telegram:{user_id}",
            request_id=msg_id,
            source_message_id=msg_id,
        )

        # Dispatch — process_message enqueues for durable delivery
        await get_command_service().process_message(cmd)

    async def delete_message(self, session: Session | str, message_id: str) -> bool:
        """Delete a message by session or session_id."""
        if isinstance(session, str):
            session_obj = await db.get_session(session)
            if not session_obj:
                return False
        else:
            session_obj = session
        return await MessageOperationsMixin.delete_message(self, session_obj, message_id)  # type: ignore[arg-type]

    async def _handle_simple_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE, event: str) -> None:
        """Template method for simple session commands.

        Handles commands that map to explicit command objects and dispatch via CommandService.
        """
        session = await cast("_PrivateHandlersHost", self)._get_session_from_topic(update)
        if not session:
            return

        assert update.effective_user is not None
        assert update.effective_message is not None

        args = context.args or []
        host = cast("_PrivateHandlersHost", self)
        metadata = host._metadata()
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
            await host._dispatch_command(
                session,
                str(update.effective_message.message_id),
                metadata,
                cmd.key,
                cmd.to_payload(),
                lambda: cmds.keys(cmd),
            )
            return

        if isinstance(cmd, CloseSessionCommand):
            await host._dispatch_command(
                session,
                str(update.effective_message.message_id),
                metadata,
                "close_session",
                cmd.to_payload(),
                lambda: cmds.close_session(cmd),
            )
            return

        raise ValueError(f"Unsupported simple command type: {type(cmd).__name__}")

    async def _find_private_session(self, user_id: str) -> Session | None:
        """Return the active private-chat session for a Telegram user, if one exists."""
        sessions = await db.list_sessions(last_input_origin="telegram", include_closed=False)
        for session in sessions:
            telegram_meta = session.get_metadata().get_ui().get_telegram()
            if telegram_meta.user_id == int(user_id):
                return session
        return None

    async def _create_private_session_for_identity(
        self,
        user_id: str,
        person_name: str,
        text: str,
        human_role: str,
    ) -> dict[str, str]:
        """Create a private-chat session with the initial message bundled into auto_command."""
        workspace_path = invite_module.scaffold_personal_workspace(person_name)
        quoted_text = shlex.quote(text)
        auto_command = f"agent_then_message {agents_module.get_default_agent()} slow {quoted_text}"
        create_cmd = CreateSessionCommand(
            project_path=str(workspace_path),
            title=f"Telegram: {person_name}",
            origin=InputOrigin.TELEGRAM.value,
            channel_metadata={
                "user_id": int(user_id),
                "telegram_user_id": int(user_id),
                "platform": "telegram",
                "chat_type": "private",
            },
            session_metadata=SessionMetadata(human_role=human_role),
            auto_command=auto_command,
        )
        return await get_command_service().create_session(create_cmd)
