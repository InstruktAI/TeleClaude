"""Private chat handlers mixin for Telegram adapter.

Handles /start invite binding and private text routing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger
from telegram import Update
from telegram.ext import ContextTypes

import teleclaude.core.identity as identity_module
import teleclaude.invite as invite_module
from teleclaude.cli.config_handlers import get_global_config, save_person_config
from teleclaude.config.invitations import find_person_by_invite_token
from teleclaude.config.schema import TelegramCreds
from teleclaude.core import command_registry
from teleclaude.core.db import db
from teleclaude.core.inbound import InboundSessionPolicy, handle_inbound_message, resolve_binding_key
from teleclaude.core.injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from teleclaude.core.models import (
    AgentDispatchMode,
    Session,
    SessionEntryPoint,
    SessionLaunchIntent,
    SessionLaunchKind,
    TelegramAdapterMetadata,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.slug import normalize_slug
from teleclaude.types.commands import CreateSessionCommand, ProcessMessageCommand

from .input_handlers import ConversationInputDecision, ConversationInputReason, ConversationModality

if TYPE_CHECKING:
    from typing import Protocol

    from teleclaude.core.command_service import CommandService
    from teleclaude.core.models import MessageMetadata

    class _PrivateHandlersHost(Protocol):
        _metadata: Callable[..., MessageMetadata]
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

PRIVATE_SESSION_CREATION_EMPTY_EVENT = "telegram_private_session_creation_empty"
PRIVATE_SESSION_CREATION_FAILED_EVENT = "telegram_private_session_creation_failed"
PRIVATE_SESSION_MISSING_EVENT = "telegram_private_session_missing"


def get_command_service() -> CommandService:
    """Delegate to the global command-service registry at call time.

    Keeping this local wrapper preserves both test seams:
    - patching `teleclaude.core.command_registry.get_command_service`
    - patching `teleclaude.adapters.telegram.private_handlers.get_command_service`
    """
    return command_registry.get_command_service()


class PrivateHandlersMixin:
    """Mixin providing private-chat handlers for TelegramAdapter.

    Required from host class:
    - _metadata(**kwargs) -> MessageMetadata
    - _dispatch_command(session, message_id, metadata, event, payload, fn) -> None
    """

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
                thinking_mode="slow",
                dispatch_mode=AgentDispatchMode.AUTOMATIC,
            ),
            entry_point=SessionEntryPoint.TELEGRAM,
        )
        result_dict = await get_command_service().create_session(create_cmd)
        session_id = str(result_dict.get("session_id", ""))
        if not session_id:
            logger.error(PRIVATE_SESSION_CREATION_EMPTY_EVENT)
            await update.effective_message.reply_text("Failed to create session. Please contact your admin.")
            return

        session = await db.get_session(session_id)
        if not session:
            logger.error(PRIVATE_SESSION_MISSING_EVENT)
            return

        # Send greeting
        await update.effective_message.reply_text(
            f"Hi {display_name}, I'm your personal assistant. What would you like to work on?"
        )

    async def _handle_private_text(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle text messages in private chats from bound users."""
        assert update.effective_user is not None
        assert update.effective_message is not None
        decision = ConversationInputDecision(
            ConversationModality.TEXT,
            str(update.effective_message.message_id),
        )
        try:
            await self._route_private_text(update, decision)
        except asyncio.CancelledError as error:
            decision.reject_for_error(error)
            raise
        except Exception as error:
            decision.reject_for_error(error)
            raise
        decision.reject_if_unreported()

    async def _route_private_text(self, update: Update, decision: ConversationInputDecision) -> None:
        """Route one supported text message after its decision record is armed."""
        assert update.effective_user is not None
        assert update.effective_message is not None

        user_id = str(update.effective_user.id)

        identity = identity_module.get_identity_resolver().resolve(
            "telegram",
            {"user_id": user_id, "telegram_user_id": user_id},
        )

        if not identity or not identity.person_name:
            decision.reject(ConversationInputReason.UNBOUND_IDENTITY)
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
                logger.error(PRIVATE_SESSION_CREATION_FAILED_EVENT)
                decision.reject(ConversationInputReason.SESSION_CREATION_FAILED)
                return None
            session = await db.get_session(session_id)
            if session is None:
                logger.error(PRIVATE_SESSION_MISSING_EVENT)
                decision.reject(ConversationInputReason.SESSION_CREATION_FAILED)
                return None
            decision.bind_session(session)
            decision.accept()
            return session

        async def _reconcile(session: Session) -> Session:
            return session

        async def _dispatch(session: Session) -> None:
            decision.bind_session(session)
            host = cast("_PrivateHandlersHost", self)
            metadata = host._metadata()
            cmd = ProcessMessageCommand(
                session_id=session.session_id,
                text=text,
                origin="telegram",
                text_kind=TranscriptEntryKind.ORDINARY,
                source_feature=InjectedTextSourceFeature.TELEGRAM,
                occurrence_key=msg_id,
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
            decision.accept()

        policy = InboundSessionPolicy(
            find=lambda: self._find_private_session(user_id),
            create=_create,
            reconcile=_reconcile,
            dispatch=_dispatch,
        )

        await handle_inbound_message(policy)

    async def _find_private_session(self, user_id: str) -> Session | None:
        """Return the active private-chat session for a Telegram user, if one exists."""
        sessions = await db.list_sessions(last_input_origin="telegram", include_closed=False)
        for session in sessions:
            tg = TelegramAdapterMetadata.from_dict(session.get_origin_section("telegram"))
            if tg.user_id == int(user_id):
                return session
        return None

    async def _get_private_session_for_update(self, update: Update) -> Session | None:
        """Resolve a bound session for a private Telegram update."""
        user = update.effective_user
        chat = update.effective_chat
        if user is None or chat is None or chat.type != "private":
            return None

        identity = identity_module.get_identity_resolver().resolve(
            "telegram",
            {"user_id": str(user.id), "telegram_user_id": str(user.id)},
        )
        if identity.person_name is None:
            return None

        return await self._find_private_session(str(user.id))

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
                thinking_mode="slow",
                message=text,
                dispatch_mode=AgentDispatchMode.AUTOMATIC,
            ),
            entry_point=SessionEntryPoint.TELEGRAM,
        )
        return await get_command_service().create_session(create_cmd)
