"""Private chat handlers mixin for Telegram adapter.

Handles /start invite binding, private text routing, simple command
dispatching, and the dynamic command-handler factory.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger
from telegram import Update
from telegram.ext import ContextTypes

import teleclaude.core.agents as agents_module
import teleclaude.core.identity as identity_module
import teleclaude.invite as invite_module
from teleclaude.cli.config_handlers import find_person_by_invite_token, get_global_config, save_person_config
from teleclaude.config.schema import TelegramCreds
from teleclaude.core import command_registry
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.db import db
from teleclaude.core.inbound import InboundSessionPolicy, handle_inbound_message, resolve_binding_key
from teleclaude.core.models import Session, SessionLaunchIntent, SessionLaunchKind, TelegramAdapterMetadata
from teleclaude.core.next_machine.session_hold import hold_todo_for_manual_session_close
from teleclaude.core.origins import InputOrigin
from teleclaude.slug import normalize_slug
from teleclaude.types.commands import CloseSessionCommand, CommandType, CreateSessionCommand, ProcessMessageCommand

if TYPE_CHECKING:
    from typing import Protocol

    from teleclaude.core.command_service import CommandService
    from teleclaude.core.models import MessageMetadata

    class _PrivateHandlersHost(Protocol):
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

        person_slug, person_config = result
        display_name = next((p.name for p in get_global_config().people if p.slug == person_slug), person_slug)
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
            save_person_config(person_slug, person_config)
            logger.info("Bound Telegram user %s to person slug %s", user_id, person_slug)

        # Scaffold personal workspace and create session
        workspace_path = invite_module.scaffold_personal_workspace(person_slug, display_name)

        # Create session in personal workspace
        create_cmd = CreateSessionCommand(
            project_path=str(workspace_path),
            origin=InputOrigin.TELEGRAM.value,
            origin_metadata={
                "user_id": int(user_id),
                "telegram_user_id": int(user_id),
                "platform": "telegram",
                "chat_type": "private",
            },
            launch_intent=SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT,
                agent=agents_module.get_default_agent(),
                thinking_mode="slow",
            ),
        )
        result_dict = await get_command_service().create_session(create_cmd)
        session_id = str(result_dict.get("session_id", ""))
        if not session_id:
            logger.error("Private chat session creation returned empty session_id for slug %s", person_slug)
            await update.effective_message.reply_text("Failed to create session. Please contact your admin.")
            return

        session = await db.get_session(session_id)
        if not session:
            logger.error("Session %s not found after creation for slug %s", session_id, person_slug)
            return

        # Send greeting
        await update.effective_message.reply_text(
            f"Hi {display_name}, I'm your personal assistant. What would you like to work on?"
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

        text = update.effective_message.text or ""
        msg_id = str(update.effective_message.message_id)
        person_slug = identity.person_slug or normalize_slug(identity.person_name or "")
        binding_key = resolve_binding_key("telegram", {"user_id": user_id})

        async def _create() -> Session | None:
            result_dict = await self._create_private_session_for_identity(
                user_id,
                person_slug,
                identity.person_name,
                text,
            )
            session_id = str(result_dict.get("session_id", ""))
            if not session_id:
                logger.error("Private chat session creation failed for slug %s", person_slug)
                return None
            return await db.get_session(session_id)

        async def _reconcile(session: Session) -> Session:
            return session

        async def _dispatch(session: Session) -> None:
            host = cast("_PrivateHandlersHost", self)
            metadata = host._metadata()
            cmd = ProcessMessageCommand(
                session_id=session.session_id,
                text=text,
                origin="telegram",
                actor_id=binding_key,
                actor_name=identity.person_name or binding_key,
                request_id=msg_id,
                source_message_id=msg_id,
            )
            await host._dispatch_command(
                session,
                msg_id,
                metadata,
                "process_message",
                cmd.to_payload(),
                lambda: get_command_service().process_message(cmd),
            )

        policy = InboundSessionPolicy(
            find=lambda: self._find_private_session(user_id),
            create=_create,
            reconcile=_reconcile,
            dispatch=_dispatch,
        )

        await handle_inbound_message(policy)

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
        metadata.platform_message_id = str(update.effective_message.message_id)

        # Normalize via mapper
        cmds = get_command_service()
        cmd = CommandMapper.map_telegram_input(
            event=event,
            args=args,
            metadata=metadata,
            session_id=session.session_id,
        )
        cmd.request_id = str(update.effective_message.message_id)
        if cmd.command_type == CommandType.KEYS:
            await host._dispatch_command(
                session,
                str(update.effective_message.message_id),
                metadata,
                cmd.key,  # type: ignore[attr-defined]
                cmd.to_payload(),
                lambda: cmds.keys(cmd),  # type: ignore[arg-type]
            )
            return

        if cmd.command_type == CommandType.CLOSE_SESSION:
            close_cmd = cast("CloseSessionCommand", cmd)

            async def _close_with_manual_hold() -> object:
                try:
                    await hold_todo_for_manual_session_close(db, close_cmd.session_id)
                except Exception:
                    logger.error(
                        "Telegram session close hold interlock failed for %s", close_cmd.session_id, exc_info=True
                    )
                return await cmds.close_session(close_cmd)

            await host._dispatch_command(
                session,
                str(update.effective_message.message_id),
                metadata,
                "close_session",
                cmd.to_payload(),
                _close_with_manual_hold,
            )
            return

        raise ValueError(f"Unsupported simple command type: {cmd.command_type.value}")

    async def _find_private_session(self, user_id: str) -> Session | None:
        """Return the active private-chat session for a Telegram user, if one exists."""
        sessions = await db.list_sessions(last_input_origin="telegram", include_closed=False)
        for session in sessions:
            tg = TelegramAdapterMetadata.from_dict(session.get_origin_section("telegram"))
            if tg.user_id == int(user_id):
                return session
        return None

    async def _create_private_session_for_identity(
        self,
        user_id: str,
        person_slug: str,
        display_name: str | None,
        text: str,
    ) -> dict[str, str]:
        """Create a private-chat session with the initial message bundled into launch_intent."""
        workspace_path = invite_module.scaffold_personal_workspace(person_slug, display_name)
        create_cmd = CreateSessionCommand(
            project_path=str(workspace_path),
            initial_input=text,
            origin=InputOrigin.TELEGRAM.value,
            origin_metadata={
                "user_id": int(user_id),
                "telegram_user_id": int(user_id),
                "platform": "telegram",
                "chat_type": "private",
            },
            launch_intent=SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
                agent=agents_module.get_default_agent(),
                thinking_mode="slow",
                message=text,
            ),
        )
        return await get_command_service().create_session(create_cmd)
