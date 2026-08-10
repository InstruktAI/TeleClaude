"""Gateway event handlers mixin for Discord adapter.

Registers Discord gateway events (on_ready, on_message, thread delete/update)
and the /cancel slash command.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.discord._runtime import recoverable_operation_errors
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionLifecycleContext, TeleClaudeEvents
from teleclaude.core.inbound import (
    InboundSessionPolicy,
    handle_inbound_message,
    resolve_binding_key,
    resolve_or_create_bound_session,
)
from teleclaude.core.models import DiscordAdapterMetadata, SessionLaunchIntent, SessionLaunchKind
from teleclaude.core.session_status import is_session_terminal
from teleclaude.events.envelope import EventVisibility

if TYPE_CHECKING:
    from types import ModuleType

    from teleclaude.core.models import Session
import asyncio
from datetime import datetime

from teleclaude.cli.config_handlers import find_person_by_invite_token, get_global_config
from teleclaude.core.agents import get_default_agent
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.dates import ensure_utc
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.origins import InputOrigin
from teleclaude.invite import bind_discord_credentials, scaffold_personal_workspace
from teleclaude.slug import normalize_slug
from teleclaude.types.commands import CreateSessionCommand, ProcessMessageCommand

logger = get_logger(__name__)


class GatewayHandlersMixin:
    """Mixin providing Discord gateway event registration and handlers for DiscordAdapter.

    Required host attributes:
    - _client: DiscordClientLike | None
    - _discord: ModuleType
    - _guild_id: int | None
    - _tree: object | None
    - _infrastructure_provisioned: bool
    - _ready_event: asyncio.Event
    - _project_forum_map: dict[str, int]
    - _help_desk_channel_id: int | None
    - _all_sessions_channel_id: int | None
    - _escalation_channel_id: int | None
    - _team_channel_map: dict[int, str]
    - _multi_agent: bool
    - _launcher_registration_view: object | None
    - _require_async_callable(fn, *, label) -> Callable
    - _parse_optional_int(value) -> int | None
    - _ensure_discord_infrastructure() (async)
    - _build_session_launcher_view(forum_id) -> object
    - _post_or_update_launcher(forum_id) (async)
    - _handle_launcher_click(interaction, agent_name, launcher_forum_id) (async)
    - _register_session_launcher_view(forum_id, message_id) -> None
    - _handle_discord_dm(message) (async)
    - _handle_relay_thread_message(message, text) (async)
    - _is_managed_message(message) -> bool
    - _is_help_desk_thread(message) -> bool
    - _is_bot_message(message) -> bool
    - _is_customer_session(session) -> bool
    - _forward_to_relay_thread(session, text, message) (async)
    - _resolve_or_create_discord_session(message) -> tuple[Session | None, bool] (async)
    - _handle_voice_attachment(message, attachment) (async)
    - _handle_file_attachments(message, attachments) (async)
    - _extract_audio_attachment(message) -> object | None
    - _extract_file_attachments(message) -> list[object]
    - _discord_actor_name(author, user_id) -> str
    - _discord_actor_avatar_url(author) -> str | None
    - _handle_cancel_slash(interaction) (async)
    """

    _guild_id: int | None
    _project_forum_map: dict[str, int]
    _help_desk_channel_id: int | None
    _all_sessions_channel_id: int | None
    _team_channel_map: dict[int, str]

    if TYPE_CHECKING:
        _discord: ModuleType
        _client: object
        _tree: object | None
        _infrastructure_provisioned: bool
        _launcher_registration_view: object | None
        _escalation_channel_id: int | None

        _ready_event: asyncio.Event

        def _parse_optional_int(self, value: object) -> int | None: ...

        @staticmethod
        def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]: ...

        @property
        def _multi_agent(self) -> bool: ...

        def _build_session_launcher_view(self, *, forum_id: int | None = None) -> object: ...

        def _register_session_launcher_view(self, *, forum_id: int | None, message_id: int | None) -> None: ...

        async def _ensure_discord_infrastructure(self) -> None: ...

        async def _post_or_update_launcher(self, forum_id: int) -> None: ...

        async def _handle_discord_dm(self, message: object) -> None: ...

        async def _handle_relay_thread_message(self, message: object, text: str) -> None: ...

        def _is_managed_message(self, message: object) -> bool: ...

        def _is_help_desk_thread(self, message: object) -> bool: ...

        def _is_bot_message(self, message: object) -> bool: ...

        @staticmethod
        def _extract_audio_attachment(message: object) -> object | None: ...

        @staticmethod
        def _extract_file_attachments(message: object) -> list[object]: ...

        async def _handle_voice_attachment(self, message: object, attachment: object) -> None: ...

        async def _handle_file_attachments(self, message: object, attachments: list[object]) -> None: ...

        async def _resolve_or_create_discord_session(
            self, message: object, *, first_message: str | None = None
        ) -> tuple[Session | None, bool]: ...

        async def _forward_to_relay_thread(self, session: object, text: str, message: object) -> None: ...

        async def _handle_cancel_slash(self, interaction: object) -> None: ...

        @staticmethod
        def _is_customer_session(session: Session) -> bool: ...

        @staticmethod
        def _discord_actor_name(author: object, user_id: str) -> str: ...

        @staticmethod
        def _discord_actor_avatar_url(author: object) -> str | None: ...

    # =========================================================================
    # Slash Command Registration
    # =========================================================================

    def _register_cancel_slash_command(self) -> None:
        if self._client is None:
            return
        app_commands = getattr(self._discord, "app_commands", None)
        command_tree_cls = getattr(app_commands, "CommandTree", None) if app_commands else None
        command_cls = getattr(app_commands, "Command", None) if app_commands else None
        object_cls = getattr(self._discord, "Object", None)
        if not callable(command_tree_cls) or not callable(command_cls):
            logger.warning("Discord app_commands unavailable; /cancel slash command not registered")
            return

        self._tree = command_tree_cls(self._client)
        cancel_command = command_cls(
            name="cancel",
            description="Send CTRL+C to interrupt the current agent",
            callback=self._handle_cancel_slash,
        )
        if self._guild_id is None or not callable(object_cls):
            logger.warning("DISCORD_GUILD_ID missing or invalid; skipping guild-scoped /cancel registration")
            return
        add_command = getattr(self._tree, "add_command", None)
        if callable(add_command):
            add_command(cancel_command, guild=object_cls(id=self._guild_id))

    # =========================================================================
    # Gateway Handler Registration
    # =========================================================================

    def _register_gateway_handlers(self) -> None:
        if self._client is None:
            raise AdapterError("Discord client not initialized")

        async def on_ready() -> None:
            await self._handle_on_ready()

        async def on_message(message: object) -> None:
            await self._handle_on_message(message)

        async def on_raw_thread_delete(payload: object) -> None:
            await self._handle_thread_delete(payload)

        async def on_raw_thread_update(payload: object) -> None:
            await self._handle_thread_update(payload)

        self._client.event(on_ready)  # type: ignore[attr-defined]
        self._client.event(on_message)  # type: ignore[attr-defined]
        self._client.event(on_raw_thread_delete)  # type: ignore[attr-defined]
        self._client.event(on_raw_thread_update)  # type: ignore[attr-defined]

    # =========================================================================
    # on_ready
    # =========================================================================

    async def _handle_on_ready(self) -> None:
        if self._client is None:
            return
        user = getattr(self._client, "user", None)
        logger.info("Discord adapter ready as %s", user)
        # Mark gateway readiness immediately; follow-up bootstrap can be slow.
        self._ready_event.set()

        # Guard: on_ready fires on initial connect AND on RESUME failure.
        # Re-running provisioning with a stale guild cache creates duplicates.
        if self._infrastructure_provisioned:
            logger.debug("Discord infrastructure already provisioned, skipping on reconnect")
            return

        # Auto-provision Discord infrastructure (category + forums)
        try:
            await self._ensure_discord_infrastructure()
            logger.info(
                "Discord on_ready: infrastructure provisioned, team_channel_map=%d entries", len(self._team_channel_map)
            )
        except Exception as exc:
            logger.warning("Discord infrastructure provisioning failed: %s", exc, exc_info=True)

        if self._tree is not None and self._guild_id is not None:
            sync_fn = getattr(self._tree, "sync", None)
            object_cls = getattr(self._discord, "Object", None)
            if callable(sync_fn) and callable(object_cls):
                try:
                    await self._require_async_callable(sync_fn, label="Discord command tree sync")(
                        guild=object_cls(id=self._guild_id)
                    )
                except Exception as exc:
                    logger.warning("Failed to sync Discord slash commands: %s", exc)

        if self._multi_agent:
            add_view = getattr(self._client, "add_view", None)
            if callable(add_view):
                self._register_session_launcher_view(forum_id=None, message_id=None)

            all_forum_ids: set[int] = set(self._project_forum_map.values())
            if self._help_desk_channel_id:
                all_forum_ids.add(self._help_desk_channel_id)
            if self._all_sessions_channel_id:
                all_forum_ids.add(self._all_sessions_channel_id)
            for forum_id in all_forum_ids:
                try:
                    await self._post_or_update_launcher(forum_id)
                except Exception as exc:
                    logger.warning("Failed to post launcher for forum %s: %s", forum_id, exc)

        self._infrastructure_provisioned = True

    # =========================================================================
    # on_message
    # =========================================================================

    async def _handle_discord_dm(self, message: object) -> None:
        """Handle Direct Message (no guild) — invite token binding or bound user messaging."""
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

        person_slug, person_config = result
        display_name = next((p.name for p in get_global_config().people if p.slug == person_slug), person_slug)

        # Check if credentials are already bound
        existing_user_id = person_config.creds.discord.user_id if person_config.creds.discord else None

        if existing_user_id:
            if existing_user_id == user_id:
                # Same user - proceed to session (already bound)
                pass
            else:
                # Different user - reject
                channel = getattr(message, "channel", None)
                if channel:
                    await channel.send("This invite is already associated with another account.")
                return
        else:
            # Bind credentials
            bind_discord_credentials(person_slug, user_id)
            logger.info("Bound Discord user %s to person slug %s", user_id, person_slug)

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
            workspace_path = scaffold_personal_workspace(person_slug, person_name)
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
                    agent=get_default_agent(),
                    thinking_mode="slow",
                    message=first_message,
                ),
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
            await db.update_origin_metadata(session.session_id, "discord", {"channel_id": dm_channel_id})
            return await db.get_session(session.session_id) or session

        async def _dispatch(session: Session) -> None:
            author = getattr(message, "author", None)
            actor_id = resolve_binding_key("discord", {"user_id": user_id})
            actor_name = (person_name or "").strip() or self._discord_actor_name(author, user_id)
            actor_avatar_url = self._discord_actor_avatar_url(author)
            message_id = str(getattr(message, "id", "")).strip()
            channel_id_str = str(dm_channel_id) if dm_channel_id is not None else None
            cmd = ProcessMessageCommand(
                session_id=session.session_id,
                text=first_message or "",
                origin=InputOrigin.DISCORD.value,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_avatar_url=actor_avatar_url,
                source_message_id=message_id or None,
                source_channel_id=channel_id_str,
            )
            metadata = self._metadata(  # type: ignore[attr-defined]
                platform_message_id=message_id or None,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_avatar_url=actor_avatar_url,
            )
            await self._dispatch_command(  # type: ignore[attr-defined]
                session,
                message_id or None,
                metadata,
                "process_message",
                cmd.to_payload(),
                lambda: get_command_service().process_message(cmd),
            )

        return InboundSessionPolicy(find=_find, create=_create, reconcile=_reconcile, dispatch=_dispatch)

    async def _handle_on_message(self, message: object) -> None:
        author = getattr(message, "author", None)
        channel = getattr(message, "channel", None)
        logger.debug(
            "[DISCORD MSG] channel_id=%s author_id=%s is_bot=%s",
            self._parse_optional_int(getattr(channel, "id", None)),
            getattr(author, "id", "?"),
            bool(getattr(author, "bot", False)),
        )

        if self._is_bot_message(message):
            return

        # Guild verification: drop messages from other guilds
        if self._guild_id is not None:
            msg_guild_id = self._parse_optional_int(getattr(getattr(message, "guild", None), "id", None))
            if msg_guild_id is not None and msg_guild_id != self._guild_id:
                logger.debug("Ignoring message from guild %s (expected %s)", msg_guild_id, self._guild_id)
                return

        # Handle DMs (no guild)
        if getattr(message, "guild", None) is None:
            await self._handle_discord_dm(message)
            return

        # Check if this message is in a relay thread (escalation forum)
        channel = getattr(message, "channel", None)
        parent_id = self._parse_optional_int(getattr(channel, "parent_id", None))
        if parent_id and parent_id == self._escalation_channel_id:
            text = getattr(message, "content", None)
            if isinstance(text, str) and text.strip():
                await self._handle_relay_thread_message(message, text)
            return

        # Channel gating: only process messages from managed forums
        if not self._is_managed_message(message):
            channel = getattr(message, "channel", None)
            ch_id = self._parse_optional_int(getattr(channel, "id", None))
            ch_name = getattr(channel, "name", None)
            parent_id = self._parse_optional_int(getattr(channel, "parent_id", None))
            logger.info(
                "Ignoring message from non-managed channel: channel_id=%s name=%s parent_id=%s team_map_size=%d",
                ch_id,
                ch_name,
                parent_id,
                len(self._team_channel_map),
            )
            return

        # Voice/audio attachment — handle before the text guard
        audio_attachment = self._extract_audio_attachment(message)
        if audio_attachment is not None:
            await self._handle_voice_attachment(message, audio_attachment)
            return

        # Handle image/file attachments (non-audio)
        file_attachments = self._extract_file_attachments(message)
        if file_attachments:
            await self._handle_file_attachments(message, file_attachments)

        text = getattr(message, "content", None)
        if not isinstance(text, str) or not text.strip():
            return  # No text — if attachments existed, they were already handled above

        recoverable_errors = recoverable_operation_errors(self._discord)
        try:
            session, is_new = await self._resolve_or_create_discord_session(message, first_message=text)
        except recoverable_errors as exc:
            logger.error("Discord session resolution failed: %s", exc, exc_info=True)
            return
        if not session:
            logger.warning(
                "Discord session resolution returned None for channel %s",
                getattr(getattr(message, "channel", None), "id", None),
            )
            return

        # Role-based authorization: customers only accepted from help desk threads
        if self._is_customer_session(session) and not self._is_help_desk_thread(message):
            logger.error(
                "Blocking customer session %s from non-help-desk channel (human_role=%s)",
                session.session_id,
                session.human_role,
            )
            return

        # Relay mode: divert customer messages to the relay thread instead of the AI session
        if session.relay_status == "active" and session.relay_channel_id:
            await self._forward_to_relay_thread(session, text, message)
            return

        # If the session was just created, the first message was bundled into
        # the launch intent (agent_then_message) — skip the separate delivery.
        if is_new:
            return

        author_obj = getattr(message, "author", None)
        message_id = str(getattr(message, "id", ""))
        actor_user_id = str(getattr(author_obj, "id", "")).strip() or "unknown"
        actor_id = resolve_binding_key("discord", {"user_id": actor_user_id})
        actor_name = self._discord_actor_name(author_obj, actor_user_id)
        actor_avatar_url = self._discord_actor_avatar_url(author_obj)
        metadata = self._metadata(  # type: ignore[attr-defined]
            platform_message_id=message_id or None,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_avatar_url=actor_avatar_url,
        )
        channel_id_str = str(getattr(getattr(message, "channel", None), "id", "")) or None
        cmd = ProcessMessageCommand(
            session_id=session.session_id,
            text=text,
            origin=InputOrigin.DISCORD.value,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_avatar_url=actor_avatar_url,
            source_message_id=message_id or None,
            source_channel_id=channel_id_str,
        )
        await self._dispatch_command(  # type: ignore[attr-defined]
            session,
            message_id,
            metadata,
            "process_message",
            cmd.to_payload(),
            lambda: get_command_service().process_message(cmd),
        )

    # =========================================================================
    # Thread lifecycle events
    # =========================================================================

    async def _emit_close_for_thread(self, thread_id: int, *, trigger: str) -> None:
        """Look up session by thread_id and emit SESSION_CLOSE_REQUESTED.

        Shared by both thread-delete and thread-archive handlers.
        """
        # Guild filtering already done by callers.
        sessions = await db.get_sessions_by_origin_metadata("discord", "thread_id", thread_id, include_closed=True)
        if not sessions:
            logger.debug("No session found for Discord thread %s (%s)", thread_id, trigger)
            return

        session = sessions[0]
        if is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
            logger.debug(
                "Thread %s %s for already-closed session %s",
                thread_id,
                trigger,
                session.session_id,
            )
            return

        # Grace period: ignore events for sessions still initialising.
        if session.created_at:
            created_at = ensure_utc(session.created_at)
            age = (datetime.now(UTC) - created_at).total_seconds()
            if age < 10.0:
                logger.warning(
                    "Ignoring thread %s for new session %s (age=%.1fs)",
                    trigger,
                    session.session_id,
                    age,
                )
                return

        logger.info(
            "Discord thread %s %s by user, terminating session %s",
            thread_id,
            trigger,
            session.session_id,
        )
        event_bus.emit(
            TeleClaudeEvents.SESSION_CLOSE_REQUESTED,
            SessionLifecycleContext(session_id=session.session_id),
            visibility=EventVisibility.CLUSTER,
        )

    async def _handle_thread_delete(self, payload: object) -> None:
        """Handle a Discord thread being deleted externally."""
        thread_id = self._parse_optional_int(getattr(payload, "thread_id", None))
        if thread_id is None:
            return

        if self._guild_id is not None:
            payload_guild_id = self._parse_optional_int(getattr(payload, "guild_id", None))
            if payload_guild_id is not None and payload_guild_id != self._guild_id:
                return

        await self._emit_close_for_thread(thread_id, trigger="deleted")

    async def _handle_thread_update(self, payload: object) -> None:
        """Handle a Discord thread being archived (closed) externally."""
        # Check archived status from cached Thread object or raw gateway data.
        thread = getattr(payload, "thread", None)
        if thread is not None:
            archived = getattr(thread, "archived", False)
        else:
            data = getattr(payload, "data", None) or {}
            thread_meta = data.get("thread_metadata", {}) if isinstance(data, dict) else {}
            archived = thread_meta.get("archived", False)

        if not archived:
            return

        thread_id = self._parse_optional_int(getattr(payload, "thread_id", None))
        if thread_id is None:
            return

        if self._guild_id is not None:
            payload_guild_id = self._parse_optional_int(getattr(payload, "guild_id", None))
            if payload_guild_id is not None and payload_guild_id != self._guild_id:
                return

        await self._emit_close_for_thread(thread_id, trigger="archived")

    # =========================================================================
    # Message classification
    # =========================================================================

    def _is_bot_message(self, message: object) -> bool:
        author = getattr(message, "author", None)
        if not author:
            return True
        if bool(getattr(author, "bot", False)):
            return True
        if self._client is not None and getattr(self._client, "user", None) is not None:
            self_user_id = getattr(getattr(self._client, "user", None), "id", None)
            if self_user_id is not None and self_user_id == getattr(author, "id", None):
                return True
        return False

    def _is_managed_message(self, message: object) -> bool:
        """Check if a message originates from a managed channel.

        Managed channels include: help desk, all-sessions, project forums,
        and team text channels. When ``_help_desk_channel_id`` is not configured,
        all messages are accepted (dev/test mode).
        """
        if self._help_desk_channel_id is None:
            return True

        channel = getattr(message, "channel", None)
        channel_id = self._parse_optional_int(getattr(channel, "id", None))

        # Team text channels are managed
        if channel_id is not None and channel_id in self._team_channel_map:
            return True

        managed_ids = self._get_managed_forum_ids()

        if channel_id in managed_ids:
            return True

        parent_id = self._parse_optional_int(getattr(channel, "parent_id", None))
        if parent_id in managed_ids:
            return True

        parent_obj = getattr(channel, "parent", None)
        parent_obj_id = self._parse_optional_int(getattr(parent_obj, "id", None))
        if parent_obj_id in managed_ids:
            return True

        return False

    def _get_managed_forum_ids(self) -> set[int]:
        """Build the set of all managed Discord forum IDs."""
        ids: set[int] = set()
        if self._help_desk_channel_id is not None:
            ids.add(self._help_desk_channel_id)
        if self._all_sessions_channel_id is not None:
            ids.add(self._all_sessions_channel_id)
        ids.update(self._project_forum_map.values())
        return ids

    def _is_help_desk_thread(self, message: object) -> bool:
        """Check if a message originates from the help desk forum or a thread within it."""
        if self._help_desk_channel_id is None:
            return True
        channel = getattr(message, "channel", None)
        channel_id = self._parse_optional_int(getattr(channel, "id", None))
        if channel_id == self._help_desk_channel_id:
            return True
        parent_id = self._parse_optional_int(getattr(channel, "parent_id", None))
        if parent_id == self._help_desk_channel_id:
            return True
        parent_obj = getattr(channel, "parent", None)
        parent_obj_id = self._parse_optional_int(getattr(parent_obj, "id", None))
        return parent_obj_id == self._help_desk_channel_id
