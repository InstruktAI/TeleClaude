"""Gateway event handlers mixin for Discord adapter.

Registers Discord gateway events (on_ready, on_message, thread delete/update)
and the /cancel slash command.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.discord._runtime import recoverable_operation_errors
from teleclaude.adapters.discord.help_desk_categories import DeskForums
from teleclaude.adapters.discord.inbound_continuity import InboundContinuity, await_conclusion
from teleclaude.adapters.discord.session_launcher import (
    LauncherComponentGeneration,
    LauncherEvent,
    LauncherInteractionSource,
    LauncherOwnershipOutcome,
    LauncherOwnershipReason,
    parse_launcher_custom_id,
)
from teleclaude.config.machine import config
from teleclaude.constants import HUMAN_ROLE_CUSTOMER
from teleclaude.core.db import db
from teleclaude.core.help_desk_relay import answer_in_thread
from teleclaude.core.inbound import (
    resolve_binding_key,
)
from teleclaude.core.injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from teleclaude.core.models import (
    Session,
)
from teleclaude.core.session_status import is_session_terminal

if TYPE_CHECKING:
    from types import ModuleType

    from teleclaude.adapters.discord.voice_room import VoiceRoom
import asyncio
from datetime import datetime

from teleclaude.caller_identity import PersonCliCaller, RoleResolver, SessionOf
from teleclaude.core.command_input import CommandInputMode
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.dates import ensure_utc
from teleclaude.core.identity import (
    IdentityContext,
    get_identity_resolver,
    session_person_role,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import CloseSessionCommand, ProcessMessageCommand

logger = get_logger(__name__)

_DATA_FIELD = "data"
_CUSTOM_ID_FIELD = "custom_id"
# The attributes of a discord.py message this module reads.
_AUTHOR_ATTR = "author"
_CHANNEL_ATTR = "channel"
_CONTENT_ATTR = "content"
_ID_ATTR = "id"
_MENTIONS_ATTR = "mentions"
_USER_ATTR = "user"
_NO_TEXT = ""
_GATEWAY_READY_EVENT = "READY"


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


class GatewayHandlersMixin:
    """Mixin providing Discord gateway event registration and handlers for DiscordAdapter.

    Required host attributes:
    - _client: DiscordClientLike | None
    - _discord: ModuleType
    - _guild_id: int | None
    - _tree: object | None
    - _infrastructure_provisioned: bool
    - _ready_event: asyncio.Event
    - _forum_routing_ready: asyncio.Event
    - _continuity: InboundContinuity
    - _project_forum_map: dict[str, int]
    - _all_sessions_channel_id: int | None
    - _team_channel_map: dict[int, str]
    - _multi_agent: bool
    - _require_async_callable(fn, *, label) -> Callable
    - _parse_optional_int(value) -> int | None
    - _ensure_discord_infrastructure() (async)
    - _reconcile_team_channels() (async)
    - _holds_shared_provider_authority() (async)
    - _build_session_launcher_view(forum_id) -> object
    - _post_or_update_launcher(forum_id) (async)
    - _handle_launcher_click(interaction, agent_name, launcher_forum_id) (async)
    - _register_session_launcher_view(forum_id, message_id) -> bool
    - _handle_discord_dm(message) (async)
    - _handle_team_channel_message(message, channel_id, person_slug, *, recovered_at) (async)
    - _is_managed_message(message) -> bool
    - _is_bot_message(message) -> bool
    - _is_customer_session(session) -> bool
    - _resolve_or_create_discord_session(message) -> tuple[Session | None, bool] (async)
    - _handle_voice_attachment(message, attachment, *, recovered_at, retain_refusal) -> Task | None (async)
    - _handle_file_attachments(message, attachments, *, recovered_at, retain_refusal) (async)
    - _extract_audio_attachment(message) -> object | None
    - _extract_file_attachments(message) -> list[object]
    - _discord_actor_name(author, user_id) -> str
    - _discord_actor_avatar_url(author) -> str | None
    - _handle_cancel_slash(interaction) (async)
    - _voice_room.handle_voice_state(member, before, after) (async)
    - _handle_socket_event_type(event_type) (async)
    - _restore_listen_controls() (async)
    """

    _guild_id: int | None
    _project_forum_map: dict[str, int]
    _forum_project_map: dict[int, str]
    _project_category_id: int | None
    _registered_launcher_message_ids: set[int]
    _all_sessions_channel_id: int | None
    _desk_forums: dict[str, DeskForums]
    _team_channel_map: dict[int, str]

    if TYPE_CHECKING:
        _discord: ModuleType
        _client: object
        _tree: object | None
        _infrastructure_provisioned: bool
        _ready_event: asyncio.Event
        _forum_routing_ready: asyncio.Event
        _continuity: InboundContinuity
        _voice_room: VoiceRoom | None

        def _parse_optional_int(self, value: object) -> int | None: ...

        @staticmethod
        def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]: ...

        @property
        def _multi_agent(self) -> bool: ...

        def _build_session_launcher_view(self, *, forum_id: int) -> object: ...

        def _register_session_launcher_view(self, *, forum_id: int, message_id: int) -> bool: ...

        async def _restore_listen_controls(self) -> None: ...

        async def _ensure_discord_infrastructure(self) -> None: ...

        async def _reconcile_team_channels(self) -> None: ...

        async def _holds_shared_provider_authority(self) -> bool: ...

        async def _handle_projects_changed(self, _event: str, context: object) -> None: ...

        def _request_desk_reconcile(self) -> None: ...

        async def _post_or_update_launcher(self, forum_id: int) -> None: ...

        async def _remove_obsolete_launchers(self, forum_id: int) -> None: ...

        async def _resolve_launcher_interaction_source(self, interaction: object) -> LauncherInteractionSource: ...

        async def _handle_discord_dm(self, message: object) -> None: ...

        async def _handle_team_channel_message(
            self, message: object, channel_id: int, person_slug: str, *, recovered_at: datetime | None = None
        ) -> None: ...

        def _is_managed_message(self, message: object) -> bool: ...

        def _is_bot_message(self, message: object) -> bool: ...

        @staticmethod
        def _extract_audio_attachment(message: object) -> object | None: ...

        @staticmethod
        def _extract_file_attachments(message: object) -> list[object]: ...

        async def _handle_voice_attachment(
            self,
            message: object,
            attachment: object,
            *,
            recovered_at: datetime | None = None,
            retain_refusal: bool = False,
        ) -> asyncio.Task[object] | None: ...

        async def _handle_file_attachments(
            self,
            message: object,
            attachments: list[object],
            *,
            recovered_at: datetime | None = None,
            retain_refusal: bool = False,
        ) -> None: ...

        async def _resolve_or_create_discord_session(
            self, message: object, *, first_message: str | None = None
        ) -> tuple[Session | None, bool]: ...

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

        async def on_interaction(interaction: object) -> None:
            await self._handle_launcher_interaction_observation(interaction)

        async def on_voice_state_update(member: object, before: object, after: object) -> None:
            await self._handle_voice_state_update(member, before, after)

        async def on_socket_event_type(event_type: str) -> None:
            await self._handle_socket_event_type(event_type)

        self._client.event(on_ready)  # type: ignore[attr-defined]
        self._client.event(on_message)  # type: ignore[attr-defined]
        self._client.event(on_raw_thread_delete)  # type: ignore[attr-defined]
        self._client.event(on_raw_thread_update)  # type: ignore[attr-defined]
        self._client.event(on_interaction)  # type: ignore[attr-defined]
        self._client.event(on_voice_state_update)  # type: ignore[attr-defined]
        self._client.event(on_socket_event_type)  # type: ignore[attr-defined]

    async def _handle_voice_state_update(self, member: object, before: object, after: object) -> None:
        if self._voice_room is not None:
            await self._voice_room.handle_voice_state(member, before, after)

    async def _handle_socket_event_type(self, event_type: str) -> None:
        """Observe selected Gateway events without enabling raw-payload debug dispatch.

        READY opens a new gateway session, which replays nothing posted before it. The event is delivered
        before the messages that follow it, so the continuity holds them until their place is recovered.
        """
        if event_type == _GATEWAY_READY_EVENT:
            self._continuity.begin_gateway_session()
        if event_type in {"VOICE_STATE_UPDATE", "READY", "INTERACTION_CREATE"}:
            logger.info("discord_gateway_event_received", event_type=event_type, guild_id=self._guild_id)

    async def _handle_launcher_interaction_observation(self, interaction: object) -> None:
        """Observe unmatched current launcher receipts without consuming the interaction."""
        data = getattr(interaction, _DATA_FIELD, None)
        if not isinstance(data, Mapping):
            return
        identity = parse_launcher_custom_id(data.get(_CUSTOM_ID_FIELD))
        if identity is None or identity.generation is not LauncherComponentGeneration.CURRENT:
            return

        source = await self._resolve_launcher_interaction_source(interaction)
        project_path = self._forum_project_map.get(source.forum_id) if source.forum_id is not None else None
        if source.message_id is not None and source.message_id in self._registered_launcher_message_ids:
            return
        logger.info(
            LauncherEvent.RECEIVED,
            generation=identity.generation,
            interaction_id=source.interaction_id,
            message_id=source.message_id,
            thread_id=source.thread_id,
            forum_id=source.forum_id,
            category_id=source.category_id,
            receiver_computer=config.computer.name,
            project_path=project_path,
        )

        if source.message_id is None:
            outcome = LauncherOwnershipOutcome.OWNERSHIP_UNRESOLVED
            reason = LauncherOwnershipReason.MESSAGE_ID_UNRESOLVED
        elif source.forum_id is None:
            outcome = LauncherOwnershipOutcome.OWNERSHIP_UNRESOLVED
            reason = LauncherOwnershipReason.SOURCE_FORUM_UNRESOLVED
        elif source.category_id is None or self._project_category_id is None:
            outcome = LauncherOwnershipOutcome.OWNERSHIP_UNRESOLVED
            reason = LauncherOwnershipReason.SOURCE_CATEGORY_UNRESOLVED
        elif source.category_id != self._project_category_id:
            outcome = LauncherOwnershipOutcome.IGNORED_FOREIGN
            reason = LauncherOwnershipReason.FOREIGN_PROJECT_CATEGORY
        elif project_path is None:
            outcome = LauncherOwnershipOutcome.OWNERSHIP_UNRESOLVED
            reason = LauncherOwnershipReason.PROJECT_FORUM_UNMAPPED
        else:
            outcome = LauncherOwnershipOutcome.OWNERSHIP_UNRESOLVED
            reason = LauncherOwnershipReason.MESSAGE_NOT_REGISTERED

        logger.info(
            LauncherEvent.OWNERSHIP_DECIDED,
            outcome=outcome,
            reason=reason,
            interaction_id=source.interaction_id,
            message_id=source.message_id,
            thread_id=source.thread_id,
            forum_id=source.forum_id,
            category_id=source.category_id,
            receiver_computer=config.computer.name,
            project_path=project_path,
        )

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
        # Every gateway session recovers what was posted before it, once its routing attempt has completed.
        self._continuity.request_recovery()

        if self._voice_room is not None:
            await self._voice_room.verify_configured_identities(self._discord)
            await self._voice_room.open_if_configured_person_present()
        await self._restore_listen_controls()

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
        # Forum routing reads the project forum map provisioning just built; a session
        # routed before this point would land in the catch-all forum for good.
        self._forum_routing_ready.set()

        await self._reconcile_team_channels()

        # Handlers are registered on every computer for the resources it owns; the guild's published
        # command definitions are the shared application's, replaced wholesale by each sync, so only
        # the unique master publishes them.
        if self._tree is not None and self._guild_id is not None and await self._holds_shared_provider_authority():
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
            await self._post_project_forum_launchers()
            if self._all_sessions_channel_id is not None:
                try:
                    await self._remove_obsolete_launchers(self._all_sessions_channel_id)
                except Exception as exc:
                    logger.warning(
                        "Failed to remove obsolete launcher for forum %s: %s", self._all_sessions_channel_id, exc
                    )

        self._infrastructure_provisioned = True
        self._request_desk_reconcile()
        if getattr(self, "_project_reconcile_pending", False):
            await self._handle_projects_changed("startup-catchup", None)

    async def _post_project_forum_launchers(self) -> None:
        """Ensure launchers exist in every currently mapped project forum."""
        for forum_id in set(self._project_forum_map.values()):
            try:
                await self._post_or_update_launcher(forum_id)
            except Exception as exc:
                logger.warning("Failed to post launcher for forum %s: %s", forum_id, exc)

    # =========================================================================
    # on_message
    # =========================================================================

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

        parent_id = self._parse_optional_int(getattr(channel, "parent_id", None))
        escalation_forums = {
            forums.escalations for forums in self._desk_forums.values() if forums.escalations is not None
        }
        if parent_id is not None and parent_id in escalation_forums:
            await self._handle_escalation_thread_message(message)
            return

        # Channel gating: only process messages from managed forums. Until the run's routing attempt has
        # completed, the routing is unknown rather than absent, so the message waits for it.
        await self._forum_routing_ready.wait()
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

        await self._continuity.hand_off_live(message)

    async def _handle_managed_message(self, message: object, recovered_at: datetime | None) -> None:
        """Handle a message of a managed place; a live message and a recovered one take this one path.

        ``recovered_at`` is the time a recovered message was originally posted, absent for a live one.

        A place is recovered after a restart, so a draining refusal is not answered to the sender: it propagates to
        the continuity, which leaves the message unprocessed.
        """
        channel = getattr(message, "channel", None)

        # A provisioned Team channel is a designated conversation channel: its messages are conversation turns.
        team_channel_id = self._parse_optional_int(getattr(channel, _ID_ATTR, None))
        team_person = self._team_channel_map.get(team_channel_id) if team_channel_id is not None else None
        if team_channel_id is not None and team_person is not None:
            await self._handle_team_channel_message(message, team_channel_id, team_person, recovered_at=recovered_at)
            return

        # Voice/audio attachment — handle before the text guard
        audio_attachment = self._extract_audio_attachment(message)
        if audio_attachment is not None:
            voice_task = await self._handle_voice_attachment(
                message, audio_attachment, recovered_at=recovered_at, retain_refusal=True
            )
            await await_conclusion([voice_task])
            return

        # Handle image/file attachments (non-audio)
        file_attachments = self._extract_file_attachments(message)
        if file_attachments:
            await self._handle_file_attachments(
                message, file_attachments, recovered_at=recovered_at, retain_refusal=True
            )

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

        # Role-based authorization: Discord is never a customer surface
        if self._is_customer_session(session):
            logger.error(
                "Blocking customer session %s from a Discord channel (human_role=%s)",
                session.session_id,
                session_person_role(session),
            )
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
        sender_identity = get_identity_resolver().resolve("discord", {"user_id": actor_user_id})
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
            recovered_posted_at=recovered_at,
        )
        await self._dispatch_command(  # type: ignore[attr-defined]
            session,
            message_id,
            metadata,
            "process_message",
            cmd.to_payload(),
            lambda: get_command_service().process_message(cmd),
            retain_refusal=True,
        )

    async def _handle_escalation_thread_message(self, message: object) -> None:
        """Pass a text post in a desk escalation thread to the core relay."""
        channel = getattr(message, _CHANNEL_ATTR, None)
        thread_id = self._parse_optional_int(getattr(channel, _ID_ATTR, None))
        author = getattr(message, _AUTHOR_ATTR, None)
        text = getattr(message, _CONTENT_ATTR, None)
        if thread_id is None or author is None or not isinstance(text, str) or not text.strip():
            return
        raw_author_id = getattr(author, _ID_ATTR, None)
        author_id = str(raw_author_id) if raw_author_id is not None else _NO_TEXT
        author_name = self._discord_actor_name(author, author_id)
        bot = getattr(self._client, _USER_ATTR, None)
        bot_id = getattr(bot, _ID_ATTR, None)
        mentions = getattr(message, _MENTIONS_ATTR, None)
        mentions_agent = (
            bot_id is not None
            and isinstance(mentions, list)
            and any(getattr(mentioned, _ID_ATTR, None) == bot_id for mentioned in mentions)
        )
        await answer_in_thread(str(thread_id), author_name, text, mentions_agent)

    # =========================================================================
    # Thread lifecycle events
    # =========================================================================

    async def _emit_close_for_thread(self, thread_id: int, *, trigger: str) -> None:
        """Look up the thread session and invoke the runtime close command.

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
        await get_command_service().close_session(CloseSessionCommand(session_id=session.session_id))

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
        """Check if a message originates from a managed channel."""
        return self._is_managed_channel(getattr(message, "channel", None))

    def _is_managed_channel(self, channel: object) -> bool:
        """Check if a channel is managed.

        Managed channels include: all-sessions, project forums, and team text
        channels. A help desk's forums and team chat are not managed, so a post
        there reaches no session. When no guild is configured, all channels are
        accepted (dev/test mode).
        """
        if self._guild_id is None:
            return True

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
        if self._all_sessions_channel_id is not None:
            ids.add(self._all_sessions_channel_id)
        ids.update(self._project_forum_map.values())
        return ids
