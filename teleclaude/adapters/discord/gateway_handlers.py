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
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionLifecycleContext, TeleClaudeEvents

if TYPE_CHECKING:
    from types import ModuleType

    from teleclaude.core.models import Session

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
    - _build_session_launcher_view() -> object
    - _post_or_update_launcher(forum_id) (async)
    - _handle_launcher_click(interaction, agent_name) (async)
    - _handle_discord_dm(message) (async)
    - _handle_relay_thread_message(message, text) (async)
    - _is_managed_message(message) -> bool
    - _is_help_desk_thread(message) -> bool
    - _is_bot_message(message) -> bool
    - _is_customer_session(session) -> bool
    - _forward_to_relay_thread(session, text, message) (async)
    - _resolve_or_create_session(message) -> Session | None (async)
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

        import asyncio

        _ready_event: asyncio.Event

        def _parse_optional_int(self, value: object) -> int | None: ...

        @staticmethod
        def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]: ...

        @property
        def _multi_agent(self) -> bool: ...

        def _build_session_launcher_view(self) -> object: ...

        async def _ensure_discord_infrastructure(self) -> None: ...

        async def _post_or_update_launcher(self, forum_id: int) -> None: ...

        async def _handle_discord_dm(self, message: object) -> None: ...

        async def _handle_relay_thread_message(self, message: object, text: str) -> None: ...

        def _is_managed_message(self, message: object) -> bool: ...

        def _is_help_desk_thread(self, message: object) -> bool: ...

        def _is_bot_message(self, message: object) -> bool: ...

        def _extract_audio_attachment(self, message: object) -> object | None: ...

        def _extract_file_attachments(self, message: object) -> list[object]: ...

        async def _handle_voice_attachment(self, message: object, attachment: object) -> None: ...

        async def _handle_file_attachments(self, message: object, attachments: list[object]) -> None: ...

        async def _resolve_or_create_session(self, message: object) -> Session | None: ...

        async def _forward_to_relay_thread(self, session: object, text: str, message: object) -> None: ...

        async def _handle_cancel_slash(self, interaction: object) -> None: ...

        @staticmethod
        def _is_customer_session(session: object) -> bool: ...

        @staticmethod
        def _discord_actor_name(author: object, user_id: str) -> str: ...

        @staticmethod
        def _discord_actor_avatar_url(author: object) -> str | None: ...

    # =========================================================================
    # Slash Command Registration
    # =========================================================================

    def _register_cancel_slash_command(self) -> None:
        if self._client is None:  # type: ignore[attr-defined]
            return
        app_commands = getattr(self._discord, "app_commands", None)  # type: ignore[attr-defined]
        command_tree_cls = getattr(app_commands, "CommandTree", None) if app_commands else None
        command_cls = getattr(app_commands, "Command", None) if app_commands else None
        object_cls = getattr(self._discord, "Object", None)  # type: ignore[attr-defined]
        if not callable(command_tree_cls) or not callable(command_cls):
            logger.warning("Discord app_commands unavailable; /cancel slash command not registered")
            return

        self._tree = command_tree_cls(self._client)  # type: ignore[attr-defined]
        cancel_command = command_cls(
            name="cancel",
            description="Send CTRL+C to interrupt the current agent",
            callback=self._handle_cancel_slash,  # type: ignore[attr-defined]
        )
        if self._guild_id is None or not callable(object_cls):
            logger.warning("DISCORD_GUILD_ID missing or invalid; skipping guild-scoped /cancel registration")
            return
        add_command = getattr(self._tree, "add_command", None)  # type: ignore[attr-defined]
        if callable(add_command):
            add_command(cancel_command, guild=object_cls(id=self._guild_id))

    # =========================================================================
    # Gateway Handler Registration
    # =========================================================================

    def _register_gateway_handlers(self) -> None:
        if self._client is None:  # type: ignore[attr-defined]
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
        if self._client is None:  # type: ignore[attr-defined]
            return
        user = getattr(self._client, "user", None)  # type: ignore[attr-defined]
        logger.info("Discord adapter ready as %s", user)
        # Mark gateway readiness immediately; follow-up bootstrap can be slow.
        self._ready_event.set()  # type: ignore[attr-defined]

        # Guard: on_ready fires on initial connect AND on RESUME failure.
        # Re-running provisioning with a stale guild cache creates duplicates.
        if self._infrastructure_provisioned:
            logger.debug("Discord infrastructure already provisioned, skipping on reconnect")
            return

        # Auto-provision Discord infrastructure (category + forums)
        try:
            await self._ensure_discord_infrastructure()  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("Discord infrastructure provisioning failed: %s", exc)

        if self._tree is not None and self._guild_id is not None:  # type: ignore[attr-defined]
            sync_fn = getattr(self._tree, "sync", None)  # type: ignore[attr-defined]
            object_cls = getattr(self._discord, "Object", None)  # type: ignore[attr-defined]
            if callable(sync_fn) and callable(object_cls):
                try:
                    await self._require_async_callable(sync_fn, label="Discord command tree sync")(  # type: ignore[attr-defined]
                        guild=object_cls(id=self._guild_id)
                    )
                except Exception as exc:
                    logger.warning("Failed to sync Discord slash commands: %s", exc)

        if self._multi_agent:  # type: ignore[attr-defined]
            add_view = getattr(self._client, "add_view", None)  # type: ignore[attr-defined]
            if callable(add_view):
                try:
                    self._launcher_registration_view = self._build_session_launcher_view()  # type: ignore[attr-defined]
                    add_view(self._launcher_registration_view)
                except Exception as exc:
                    logger.warning("Failed to register persistent Discord launcher view: %s", exc)

            all_forum_ids: set[int] = set(self._project_forum_map.values())
            if self._help_desk_channel_id:
                all_forum_ids.add(self._help_desk_channel_id)
            if self._all_sessions_channel_id:
                all_forum_ids.add(self._all_sessions_channel_id)
            for forum_id in all_forum_ids:
                try:
                    await self._post_or_update_launcher(forum_id)  # type: ignore[attr-defined]
                except Exception as exc:
                    logger.warning("Failed to post launcher for forum %s: %s", forum_id, exc)

        self._infrastructure_provisioned = True

    # =========================================================================
    # on_message
    # =========================================================================

    async def _handle_discord_dm(self, message: object) -> None:
        """Handle Direct Message (no guild) — invite token binding or bound user messaging."""
        from teleclaude.core.agents import get_default_agent
        from teleclaude.core.command_registry import get_command_service
        from teleclaude.core.origins import InputOrigin
        from teleclaude.types.commands import CreateSessionCommand, ProcessMessageCommand

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
        from teleclaude.core.identity import get_identity_resolver

        identity = get_identity_resolver().resolve("discord", {"user_id": user_id, "discord_user_id": user_id})

        if not identity or not identity.person_name:
            # Unknown user
            channel = getattr(message, "channel", None)
            if channel:
                await channel.send(
                    "I don't recognize your account. Send me your invite token to get started, or contact your admin."
                )
            return

        # Find or create session for this user
        sessions = await db.list_sessions(last_input_origin="discord", include_closed=False)
        session = None
        for s in sessions:
            discord_meta = s.get_metadata().get_ui().get_discord()
            if discord_meta.user_id == user_id:
                session = s
                break

        if not session:
            # Create new session in personal workspace
            from teleclaude.invite import scaffold_personal_workspace

            workspace_path = scaffold_personal_workspace(identity.person_name)

            create_cmd = CreateSessionCommand(
                project_path=str(workspace_path),
                title=f"Discord: {identity.person_name}",
                origin=InputOrigin.DISCORD.value,
                channel_metadata={
                    "user_id": user_id,
                    "discord_user_id": user_id,
                    "human_role": identity.person_role or "member",
                    "platform": "discord",
                },
                auto_command=f"agent {get_default_agent()}",
            )
            result = await get_command_service().create_session(create_cmd)
            session_id = str(result.get("session_id", ""))
            if not session_id:
                logger.error("Discord DM session creation failed for %s", identity.person_name)
                return

            session = await db.get_session(session_id)
            if not session:
                logger.error("Session %s not found after creation for %s", session_id, identity.person_name)
                return

        # Process message
        actor_name = (identity.person_name or "").strip() or self._discord_actor_name(author, user_id)  # type: ignore[attr-defined]
        actor_avatar_url = self._discord_actor_avatar_url(author)  # type: ignore[attr-defined]
        cmd = ProcessMessageCommand(
            session_id=session.session_id,
            text=text,
            origin=InputOrigin.DISCORD.value,
            actor_id=f"discord:{user_id}",
            actor_name=actor_name,
            actor_avatar_url=actor_avatar_url,
        )
        await get_command_service().process_message(cmd)

    async def _handle_discord_invite_token(self, message: object, user_id: str, token: str) -> None:
        """Handle invite token binding in Discord DM."""
        from teleclaude.cli.config_handlers import find_person_by_invite_token
        from teleclaude.core.agents import get_default_agent
        from teleclaude.core.command_registry import get_command_service
        from teleclaude.core.origins import InputOrigin
        from teleclaude.types.commands import CreateSessionCommand

        result = find_person_by_invite_token(token)
        if not result:
            channel = getattr(message, "channel", None)
            if channel:
                await channel.send("I don't recognize this invite. Please contact your admin.")
            return

        person_name, person_config = result

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
            from teleclaude.invite import bind_discord_credentials

            bind_discord_credentials(person_name, user_id)
            logger.info("Bound Discord user %s to person %s", user_id, person_name)

        # Scaffold personal workspace and create session
        from teleclaude.invite import scaffold_personal_workspace

        workspace_path = scaffold_personal_workspace(person_name)

        # Create session
        create_cmd = CreateSessionCommand(
            project_path=str(workspace_path),
            title=f"Discord: {person_name}",
            origin=InputOrigin.DISCORD.value,
            channel_metadata={
                "user_id": user_id,
                "discord_user_id": user_id,
                "human_role": "member",
                "platform": "discord",
            },
            auto_command=f"agent {get_default_agent()}",
        )
        result = await get_command_service().create_session(create_cmd)
        session_id = str(result.get("session_id", ""))
        if not session_id:
            logger.error("Discord DM session creation failed for %s", person_name)
            channel = getattr(message, "channel", None)
            if channel:
                await channel.send("Failed to create session. Please contact your admin.")
            return

        # Send greeting
        channel = getattr(message, "channel", None)
        if channel:
            await channel.send(f"Hi {person_name}, I'm your personal assistant. What would you like to work on?")

    async def _handle_on_message(self, message: object) -> None:
        from teleclaude.core.command_registry import get_command_service
        from teleclaude.core.origins import InputOrigin
        from teleclaude.types.commands import ProcessMessageCommand

        author = getattr(message, "author", None)
        channel = getattr(message, "channel", None)
        logger.debug(
            "[DISCORD MSG] channel_id=%s author_id=%s is_bot=%s",
            self._parse_optional_int(getattr(channel, "id", None)),  # type: ignore[attr-defined]
            getattr(author, "id", "?"),
            bool(getattr(author, "bot", False)),
        )

        if self._is_bot_message(message):  # type: ignore[attr-defined]
            return

        # Guild verification: drop messages from other guilds
        if self._guild_id is not None:
            msg_guild_id = self._parse_optional_int(getattr(getattr(message, "guild", None), "id", None))  # type: ignore[attr-defined]
            if msg_guild_id is not None and msg_guild_id != self._guild_id:
                logger.debug("Ignoring message from guild %s (expected %s)", msg_guild_id, self._guild_id)
                return

        # Handle DMs (no guild)
        if getattr(message, "guild", None) is None:
            await self._handle_discord_dm(message)
            return

        # Check if this message is in a relay thread (escalation forum)
        channel = getattr(message, "channel", None)
        parent_id = self._parse_optional_int(getattr(channel, "parent_id", None))  # type: ignore[attr-defined]
        if parent_id and parent_id == self._escalation_channel_id:  # type: ignore[attr-defined]
            text = getattr(message, "content", None)
            if isinstance(text, str) and text.strip():
                await self._handle_relay_thread_message(message, text)  # type: ignore[attr-defined]
            return

        # Channel gating: only process messages from managed forums
        if not self._is_managed_message(message):  # type: ignore[attr-defined]
            logger.debug("Ignoring message from non-managed channel")
            return

        # Voice/audio attachment — handle before the text guard
        audio_attachment = self._extract_audio_attachment(message)  # type: ignore[attr-defined]
        if audio_attachment is not None:
            await self._handle_voice_attachment(message, audio_attachment)  # type: ignore[attr-defined]
            return

        # Handle image/file attachments (non-audio)
        file_attachments = self._extract_file_attachments(message)  # type: ignore[attr-defined]
        if file_attachments:
            await self._handle_file_attachments(message, file_attachments)  # type: ignore[attr-defined]

        text = getattr(message, "content", None)
        if not isinstance(text, str) or not text.strip():
            return  # No text — if attachments existed, they were already handled above

        try:
            session = await self._resolve_or_create_session(message, first_message=text)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.error("Discord session resolution failed: %s", exc, exc_info=True)
            return
        if not session:
            return

        # Role-based authorization: customers only accepted from help desk threads
        if self._is_customer_session(session) and not self._is_help_desk_thread(message):  # type: ignore[attr-defined]
            logger.debug("Ignoring customer message from non-help-desk channel")
            return

        # Relay mode: divert customer messages to the relay thread instead of the AI session
        if session.relay_status == "active" and session.relay_discord_channel_id:
            await self._forward_to_relay_thread(session, text, message)  # type: ignore[attr-defined]
            return

        # If the session was just created, the first message was bundled into
        # the auto_command (agent_then_message) — skip the separate delivery.
        if session.lifecycle_status == "initializing":
            return

        message_id = str(getattr(message, "id", ""))
        channel_metadata = {
            "message_id": message_id,
            "user_id": str(getattr(getattr(message, "author", None), "id", "")),
            "discord_user_id": str(getattr(getattr(message, "author", None), "id", "")),
        }
        author_obj = getattr(message, "author", None)
        if author_obj is not None:
            channel_metadata["user_name"] = self._discord_actor_name(  # type: ignore[attr-defined]
                author_obj,
                str(getattr(author_obj, "id", "")),
            )
        metadata = self._metadata(channel_metadata=channel_metadata)  # type: ignore[attr-defined]
        actor_user_id = str(getattr(getattr(message, "author", None), "id", "")).strip() or "unknown"
        actor_name = self._discord_actor_name(getattr(message, "author", None), actor_user_id)  # type: ignore[attr-defined]
        actor_avatar_url = self._discord_actor_avatar_url(getattr(message, "author", None))  # type: ignore[attr-defined]
        channel_id_str = str(getattr(getattr(message, "channel", None), "id", "")) or None
        cmd = ProcessMessageCommand(
            session_id=session.session_id,
            text=text,
            origin=InputOrigin.DISCORD.value,
            actor_id=f"discord:{actor_user_id}",
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
        sessions = await db.get_sessions_by_adapter_metadata("discord", "thread_id", thread_id, include_closed=True)
        if not sessions:
            logger.debug("No session found for Discord thread %s (%s)", thread_id, trigger)
            return

        session = sessions[0]
        if session.closed_at or session.lifecycle_status in {"closed", "closing"}:
            logger.debug(
                "Thread %s %s for already-closed session %s",
                thread_id,
                trigger,
                session.session_id,
            )
            return

        # Grace period: ignore events for sessions still initialising.
        if session.created_at:
            from datetime import datetime

            from teleclaude.core.dates import ensure_utc

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
        )

    async def _handle_thread_delete(self, payload: object) -> None:
        """Handle a Discord thread being deleted externally."""
        thread_id = self._parse_optional_int(getattr(payload, "thread_id", None))  # type: ignore[attr-defined]
        if thread_id is None:
            return

        if self._guild_id is not None:
            payload_guild_id = self._parse_optional_int(getattr(payload, "guild_id", None))  # type: ignore[attr-defined]
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

        thread_id = self._parse_optional_int(getattr(payload, "thread_id", None))  # type: ignore[attr-defined]
        if thread_id is None:
            return

        if self._guild_id is not None:
            payload_guild_id = self._parse_optional_int(getattr(payload, "guild_id", None))  # type: ignore[attr-defined]
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
        if self._client is not None and getattr(self._client, "user", None) is not None:  # type: ignore[attr-defined]
            self_user_id = getattr(getattr(self._client, "user", None), "id", None)  # type: ignore[attr-defined]
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
        channel_id = self._parse_optional_int(getattr(channel, "id", None))  # type: ignore[attr-defined]

        # Team text channels are managed
        if channel_id is not None and channel_id in self._team_channel_map:
            return True

        managed_ids = self._get_managed_forum_ids()

        if channel_id in managed_ids:
            return True

        parent_id = self._parse_optional_int(getattr(channel, "parent_id", None))  # type: ignore[attr-defined]
        if parent_id in managed_ids:
            return True

        parent_obj = getattr(channel, "parent", None)
        parent_obj_id = self._parse_optional_int(getattr(parent_obj, "id", None))  # type: ignore[attr-defined]
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
        channel_id = self._parse_optional_int(getattr(channel, "id", None))  # type: ignore[attr-defined]
        if channel_id == self._help_desk_channel_id:
            return True
        parent_id = self._parse_optional_int(getattr(channel, "parent_id", None))  # type: ignore[attr-defined]
        if parent_id == self._help_desk_channel_id:
            return True
        parent_obj = getattr(channel, "parent", None)
        parent_obj_id = self._parse_optional_int(getattr(parent_obj, "id", None))  # type: ignore[attr-defined]
        return parent_obj_id == self._help_desk_channel_id
