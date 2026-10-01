"""Direct messages as every computer handles them until master routing is activated.

Until the mesh master has adopted the fleet's direct-message conversations
(`teleclaude.core.inbound.adoption`), the conversation seam answers
``BEFORE_CUTOVER`` and each computer keeps its own DM sessions: an invitation
token binds the account and opens the assistant, a bound user's message goes
to their DM session, and an unknown account gets the onboarding reply.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.caller_identity import PersonCliCaller, RoleResolver, SessionOf
from teleclaude.cli.config_handlers import get_global_config
from teleclaude.config.invitations import find_person_by_invite_token
from teleclaude.constants import HUMAN_ROLE_CUSTOMER
from teleclaude.core.command_input import CommandInputMode
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.identity import IdentityContext, get_identity_resolver
from teleclaude.core.inbound import (
    BindOutcome,
    InboundSessionPolicy,
    handle_inbound_message,
    resolve_binding_key,
    resolve_or_create_bound_session,
)
from teleclaude.core.injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from teleclaude.core.models import (
    AgentDispatchMode,
    DiscordAdapterMetadata,
    DiscordMetadataField,
    Session,
    SessionEntryPoint,
    SessionLaunchIntent,
    SessionLaunchKind,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.invite import scaffold_personal_workspace
from teleclaude.slug import normalize_slug
from teleclaude.types.commands import CreateSessionCommand, ProcessMessageCommand

logger = get_logger(__name__)


def sender_role_for_session(identity: IdentityContext | None, session: Session) -> str | None:
    """The role a sender holds for a session's project; an unregistered sender is a customer."""
    if identity is None:
        return None
    if not identity.person_slug:
        return HUMAN_ROLE_CUSTOMER
    caller = PersonCliCaller(
        email=identity.person_email,
        person_slug=identity.person_slug,
        human_role=identity.person_role,
    )
    return RoleResolver().role_for(caller, SessionOf(session.project_path))


class DirectMessagesBeforeCutoverMixin:
    """Today's direct-message handling, kept until master routing is activated."""

    if TYPE_CHECKING:

        def _parse_optional_int(self, value: object) -> int | None: ...

        @staticmethod
        def _discord_actor_name(author: object, user_id: str) -> str: ...

        @staticmethod
        def _discord_actor_avatar_url(author: object) -> str | None: ...

        def _bind_discord_invite(self, message: object, user_id: str, person_slug: str) -> BindOutcome: ...

        _metadata: Callable[..., object]
        _dispatch_command: Callable[..., Awaitable[object]]

    async def _handle_discord_dm_before_cutover(self, message: object) -> None:
        """Handle a direct message as every computer does until shared routing is activated.

        Until the mesh master has adopted the fleet's conversations, each computer
        keeps its own DM sessions: invite token binding, or a bound user's
        messaging; an unknown account gets the onboarding reply.
        """
        author = getattr(message, "author", None)
        if not author:
            return

        user_id = str(getattr(author, "id", ""))
        text = getattr(message, "content", None)

        if not isinstance(text, str) or not text.strip():
            return

        text = text.strip()

        # Check if message is an invite token
        if text.startswith("inv_"):
            await self._handle_discord_invite_token(message, user_id, text)
            return

        # Resolve identity
        identity = get_identity_resolver().resolve("discord", {"user_id": user_id, "discord_user_id": user_id})

        if not identity or not identity.person_name:
            # Unknown user
            channel = getattr(message, "channel", None)
            if channel:
                await channel.send(
                    "I don't recognize your account. Send me your invite token to get started, or contact your admin."
                )
            return

        person_slug = identity.person_slug or normalize_slug(identity.person_name or "")
        policy = self._build_dm_session_policy(message, user_id, person_slug, identity.person_name, first_message=text)
        await handle_inbound_message(policy)

    async def _handle_discord_invite_token(self, message: object, user_id: str, token: str) -> None:
        """Handle invite token binding in Discord DM."""
        result = find_person_by_invite_token(token)
        if not result:
            channel = getattr(message, "channel", None)
            if channel:
                await channel.send("I don't recognize this invite. Please contact your admin.")
            return

        person_slug, _person_config = result
        display_name = next((p.name for p in get_global_config().people if p.slug == person_slug), person_slug)
        if self._bind_discord_invite(message, user_id, person_slug) is BindOutcome.CONFLICT:
            channel = getattr(message, "channel", None)
            if channel:
                await channel.send("This invite is already associated with another account.")
            return

        # Find or create the DM-bound personal-assistant session — no first message here
        # (the token itself is not agent input), so a plain AGENT launch intent.
        policy = self._build_dm_session_policy(message, user_id, person_slug, display_name, first_message=None)
        session, _is_new = await resolve_or_create_bound_session(policy)
        if not session:
            channel = getattr(message, "channel", None)
            if channel:
                await channel.send("Failed to create session. Please contact your admin.")
            return

        # Send greeting
        channel = getattr(message, "channel", None)
        if channel:
            await channel.send(f"Hi {display_name}, I'm your personal assistant. What would you like to work on?")

    def _build_dm_session_policy(
        self,
        message: object,
        user_id: str,
        person_slug: str,
        person_name: str,
        *,
        first_message: str | None,
    ) -> InboundSessionPolicy:
        """Build the DM-channel-scoped resolve-or-create policy shared by the invite and text flows.

        Scoping the lookup to the DM channel id (rather than any discord session for
        this user) keeps a direct message from being absorbed into an unrelated guild
        session the same user also holds (team channel, project forum, launcher).
        """
        dm_channel_id = self._parse_optional_int(getattr(getattr(message, "channel", None), "id", None))

        async def _find() -> Session | None:
            if dm_channel_id is None:
                return None
            candidates = await db.get_sessions_by_origin_metadata("discord", "channel_id", dm_channel_id)
            for candidate in candidates:
                discord_meta = DiscordAdapterMetadata.from_dict(candidate.get_origin_section("discord"))
                if discord_meta.user_id == user_id and discord_meta.guild_id is None:
                    return candidate
            return None

        async def _create() -> Session | None:
            workspace_path = scaffold_personal_workspace(person_slug)
            create_cmd = CreateSessionCommand(
                project_path=str(workspace_path),
                initial_input=first_message,
                origin=InputOrigin.DISCORD.value,
                origin_metadata={
                    "user_id": user_id,
                    "discord_user_id": user_id,
                    "platform": "discord",
                },
                launch_intent=SessionLaunchIntent(
                    kind=SessionLaunchKind.AGENT_THEN_MESSAGE if first_message else SessionLaunchKind.AGENT,
                    thinking_mode="slow",
                    message=first_message,
                    dispatch_mode=AgentDispatchMode.AUTOMATIC,
                ),
                entry_point=SessionEntryPoint.DISCORD,
                command_input_mode=CommandInputMode.INTERACTIVE_SHORTHAND,
            )
            result = await get_command_service().create_session(create_cmd)
            session_id = str(result.get("session_id", ""))
            if not session_id:
                logger.error("Discord DM session creation failed for %s", person_name)
                return None

            session = await db.get_session(session_id)
            if not session:
                logger.error("Session %s not found after creation for %s", session_id, person_name)
                return None
            return session

        async def _reconcile(session: Session) -> Session:
            if dm_channel_id is None:
                return session
            discord_meta = DiscordAdapterMetadata.from_dict(session.get_origin_section("discord"))
            if discord_meta.channel_id == dm_channel_id:
                return session
            await db.update_origin_metadata(
                session.session_id, "discord", {DiscordMetadataField.CHANNEL_ID: dm_channel_id}
            )
            return await db.get_session(session.session_id) or session

        async def _dispatch(session: Session) -> None:
            author = getattr(message, "author", None)
            actor_id = resolve_binding_key("discord", {"user_id": user_id})
            actor_name = (person_name or "").strip() or self._discord_actor_name(author, user_id)
            actor_avatar_url = self._discord_actor_avatar_url(author)
            sender_identity = get_identity_resolver().resolve("discord", {"user_id": user_id})
            message_id = str(getattr(message, "id", "")).strip()
            channel_id_str = str(dm_channel_id) if dm_channel_id is not None else None
            cmd = ProcessMessageCommand(
                session_id=session.session_id,
                text=first_message or "",
                origin=InputOrigin.DISCORD.value,
                text_kind=TranscriptEntryKind.ORDINARY,
                source_feature=InjectedTextSourceFeature.DISCORD,
                occurrence_key=message_id or None,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_avatar_url=actor_avatar_url,
                source_message_id=message_id or None,
                source_channel_id=channel_id_str,
                command_input_mode=CommandInputMode.INTERACTIVE_SHORTHAND,
                sender_human_role=sender_role_for_session(sender_identity, session),
            )
            metadata = self._metadata(
                platform_message_id=message_id or None,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_avatar_url=actor_avatar_url,
            )
            await self._dispatch_command(
                session,
                message_id or None,
                metadata,
                "process_message",
                cmd.to_payload(),
                lambda: get_command_service().process_message(cmd),
            )

        return InboundSessionPolicy(find=_find, create=_create, reconcile=_reconcile, dispatch=_dispatch)
