"""Private chat handlers mixin for Telegram adapter.

Handles /start invite binding, private text routing, simple command
dispatching, and the dynamic command-handler factory.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from telegram import Update
from telegram.ext import ContextTypes

from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata, Session
from teleclaude.types.commands import CloseSessionCommand, KeysCommand

logger = get_logger(__name__)


class PrivateHandlersMixin:
    """Mixin providing private-chat handlers and simple-command dispatch for TelegramAdapter.

    Required from host class:
    - SIMPLE_COMMAND_EVENTS: list[str]
    - _metadata(**kwargs) -> MessageMetadata
    - _get_session_from_topic(update: Update) -> Session | None
    - _dispatch_command(session, message_id, metadata, event, payload, fn) -> None
    """

    if TYPE_CHECKING:
        SIMPLE_COMMAND_EVENTS: list[str]

        def _metadata(self, **kwargs: object) -> MessageMetadata: ...

        async def _get_session_from_topic(self, update: Update) -> Session | None: ...

        async def _dispatch_command(
            self,
            session: Session,
            message_id: str,
            metadata: MessageMetadata,
            event: str,
            payload: object,
            fn: Callable[[], Coroutine[object, object, object]],
        ) -> None: ...

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
        from teleclaude.core.agents import get_default_agent
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
            auto_command=f"agent {get_default_agent()}",
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
            from teleclaude.core.agents import get_default_agent
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
                auto_command=f"agent {get_default_agent()}",
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
        await gcs().process_message(cmd)

    async def delete_message(self, session: Session | str, message_id: str) -> bool:
        """Delete a message by session or session_id."""
        from teleclaude.adapters.telegram.message_ops import MessageOperationsMixin

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
