"""Discord adapter for TeleClaude."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from types import ModuleType
from typing import TYPE_CHECKING, Protocol, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError, ChannelNotProvisionedError
from teleclaude.adapters.discord import (
    ChannelOperationsMixin,
    GatewayHandlersMixin,
    InfrastructureMixin,
    InputHandlersMixin,
    MessageOperationsMixin,
)
from teleclaude.adapters.discord._runtime import recoverable_operation_errors
from teleclaude.adapters.discord.cancel_command import CancelCommandMixin
from teleclaude.adapters.discord.conversation_turns import ConversationTurnsMixin
from teleclaude.adapters.discord.escalation_threads import EscalationThreadsMixin
from teleclaude.adapters.discord.forum_sessions import ForumSessionsMixin
from teleclaude.adapters.discord.help_desk_categories import DeskForums, HelpDeskCategoriesMixin
from teleclaude.adapters.discord.launcher_clicks import LauncherClicksMixin
from teleclaude.adapters.discord.listen_control import ListenHereView
from teleclaude.adapters.discord.voice_room import VoiceRoom
from teleclaude.adapters.editable_ui_adapter import EditableUiAdapter
from teleclaude.adapters.qos.output_scheduler import OutputQoSScheduler
from teleclaude.adapters.qos.policy import discord_policy
from teleclaude.adapters.ui.threaded_output import OverflowContext
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config.declaration_changes import subscribe_declaration_changes, unsubscribe_declaration_changes
from teleclaude.config.machine import config
from teleclaude.constants import SYSTEM_DAEMON_PRINCIPAL, CacheEvent
from teleclaude.core.command_dispatch import dispatch_command
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.delivery import resolve_destination
from teleclaude.core.events import (
    SystemCommand,
    SystemCommandContext,
)
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.models import DiscordAdapterMetadata, DiscordMetadataField, MessageMetadata
from teleclaude.events.schemas.system import RuntimeSessionStatusData
from teleclaude.types.commands import SetVoiceFocusCommand
from teleclaude.utils.markdown import (
    GFM_MARKDOWN_INITIAL_STATE,
    GfmMarkdownState,
    _gfm_closers,
    continuation_prefix_for_gfm_state,
    discordify_markdown,
    scan_gfm_state,
    truncate_gfm_with_consumed,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session
    from teleclaude.core.task_registry import SupervisedTask, TaskRegistry

logger = get_logger(__name__)
_EMPTY_EVENT_NAME = ""

DISCORD_TYPING_INTERVAL_S = 5.0
_DESK_RECONCILE_TASK_NAME = "discord-desk-reconcile"
_GATEWAY_TASK_NAME = "discord-gateway"
_GATEWAY_LIVENESS_TASK_NAME = "discord-gateway-liveness"
_VOICE_FOCUS_RECONCILE_TASK_NAME = "discord-voice-focus-reconcile"
_DESK_PASS_FAILED_EVENT = "discord.help_desk_pass.failed"


class DiscordClientLike(Protocol):
    """Minimal discord.py client surface used by the adapter."""

    user: object | None

    def event(self, coro: Callable[..., Awaitable[None]]) -> object:
        """Register an event handler."""

    async def start(self, token: str) -> None:
        """Start the client with the given token."""

    async def close(self) -> None:
        """Close the client connection."""


class DiscordAdapter(
    ChannelOperationsMixin,
    GatewayHandlersMixin,
    ConversationTurnsMixin,
    EscalationThreadsMixin,
    InfrastructureMixin,
    HelpDeskCategoriesMixin,
    ForumSessionsMixin,
    LauncherClicksMixin,
    CancelCommandMixin,
    InputHandlersMixin,
    MessageOperationsMixin,
    EditableUiAdapter,
):
    """Discord bot adapter using discord.py."""

    ADAPTER_KEY: str = "discord"
    OUTPUT_MESSAGE_ID_FIELD = "id"
    supports_message_deletion = True
    max_message_size = 2000
    _TRUNCATION_SUFFIX = "\n[...truncated...]"

    # -------------------------------------------------------------------------
    # Markdown strategy — GFM
    # -------------------------------------------------------------------------

    def _markdown_initial_state(self) -> GfmMarkdownState:
        return GFM_MARKDOWN_INITIAL_STATE

    def _continuation_prefix_for_state(self, state: GfmMarkdownState) -> str:
        return continuation_prefix_for_gfm_state(state)

    def _truncate_for_overflow(self, body_text: str, max_chars: int) -> tuple[str, int]:
        return truncate_gfm_with_consumed(body_text, max_chars=max_chars, suffix="")

    def _scan_markdown_state(self, consumed: str, state: GfmMarkdownState) -> GfmMarkdownState:
        return scan_gfm_state(consumed, initial_state=state)

    def _balance_intermediate_chunk(self, text: str) -> str:
        state = scan_gfm_state(text, initial_state=GFM_MARKDOWN_INITIAL_STATE)
        return f"{text}{_gfm_closers(text, state)}"

    def _finalize_overflow_split(
        self,
        active_text: str,
        overflow_context: OverflowContext,
        split_idx: int,
        chunk: str,
    ) -> tuple[int, str]:
        _ = (split_idx, chunk)
        source_limit = max(1, overflow_context.available_for_content - len(overflow_context.continuation_prefix))
        source_chunk = next(self._iter_complete_lines(active_text, source_limit))
        consumed = len(source_chunk)
        if active_text[consumed : consumed + 1] in {"\n", " "}:
            consumed += 1
        display_chunk = f"{overflow_context.continuation_prefix}{source_chunk}"
        return consumed, self._balance_intermediate_chunk(display_chunk)

    def _convert_markdown_for_platform(self, text: str) -> str:
        """Convert generic markdown into Discord-friendly markdown/text."""
        return discordify_markdown(text)

    # -------------------------------------------------------------------------

    def __init__(self, client: AdapterClient, *, task_registry: TaskRegistry) -> None:
        super().__init__(client)
        self.client = client
        self.task_registry = task_registry
        self._discord: ModuleType = importlib.import_module("discord")
        self._token = config.discord.token.strip() if config.discord.token else ""
        self._guild_id = config.discord.guild_id
        self._all_sessions_channel_id: int | None = None
        self._announcements_channel_id: int | None = None
        self._general_channel_id: int | None = None
        self._gateway_task: asyncio.Task[object] | None = None
        self._gateway_liveness: SupervisedTask | None = None
        self._ready_event = asyncio.Event()
        self._client: DiscordClientLike | None = None
        self._voice_room: VoiceRoom | None = None
        self._projects_changed_handler: Callable[[str, object], None] | None = None
        self._voice_focus_reconcile_pending = False
        self._voice_focus_reconcile_task: asyncio.Task[object] | None = None
        self._project_reconcile_lock = asyncio.Lock()
        self._project_reconcile_pending = False
        self._project_reconcile_task: asyncio.Task[object] | None = None
        self._desk_reconcile_lock = asyncio.Lock()
        self._desk_reconcile_pending = False
        self._desk_reconcile_task: asyncio.Task[object] | None = None
        self._registered_listen_message_ids: set[int] = set()
        # project_path -> discord_forum_id mapping, built at startup
        self._project_forum_map: dict[str, int] = {}
        # discord_forum_id -> project_path mapping, built at startup
        self._forum_project_map: dict[int, str] = {}
        # The local project category is the Discord hierarchy authority for launcher ownership.
        self._project_category_id: int | None = None
        # Only concrete launcher messages successfully registered with discord.py enter this set.
        self._registered_launcher_message_ids: set[int] = set()
        # forum-channel-id -> webhook cache for actor-based reflection delivery
        self._reflection_webhook_cache: dict[int, object] = {}
        # team channel ID -> slug of the registered person the channel was provisioned for
        self._team_channel_map: dict[int, str] = {}
        # desk entry identifier -> the desk's forums, rebuilt after each desk reconciliation pass
        self._desk_forums: dict[str, DeskForums] = {}
        self._tree: object | None = None

        # Guard against duplicate infrastructure provisioning on Discord reconnect.
        # on_ready fires on initial connect AND on RESUME failure — re-running
        # provisioning with a stale guild cache creates duplicate categories.
        self._infrastructure_provisioned = False

        # Output QoS scheduler: coalesces stale payloads (coalesce_only mode by default).
        qos_policy = discord_policy(config.discord.qos)
        self._qos_scheduler: OutputQoSScheduler = OutputQoSScheduler(qos_policy, task_registry)

        # No threaded output buffering — Discord uses the base class
        # edit-in-place model for threaded output delivery.

    async def start(self) -> None:
        """Initialize Discord client and start gateway task."""
        if not self._token:
            raise ValueError("DISCORD_TOKEN is required to start Discord adapter")

        intents = self._discord.Intents.default()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True
        intents.voice_states = True

        self._client = self._discord.Client(intents=intents)  # pyright: ignore[reportIncompatibleVariableOverride]
        self._voice_room = VoiceRoom(self.client, self._client)
        get_command_service().set_voice_focus_handler(self._handle_voice_focus_changed)
        if self.client.cache is not None:
            self._projects_changed_handler = self._on_cache_changed
            self.client.cache.subscribe(self._projects_changed_handler)
            self._request_project_reconcile()
        subscribe_declaration_changes(self._request_desk_reconcile)
        self._register_cancel_slash_command()
        self._register_gateway_handlers()
        self._ready_event.clear()

        self._gateway_task = self.task_registry.spawn(self._client.start(self._token), name=_GATEWAY_TASK_NAME)

        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=20.0)
        except TimeoutError as exc:
            if self._gateway_task and self._gateway_task.done():
                task_exc = self._gateway_task.exception()
                if task_exc:
                    raise RuntimeError(f"Discord gateway failed to start: {task_exc}") from task_exc
            raise RuntimeError("Discord adapter did not become ready within 20 seconds") from exc

        # A gateway that ends once the adapter is ready cannot be restarted in place; its end escalates.
        self._gateway_liveness = self.task_registry.observe(_GATEWAY_LIVENESS_TASK_NAME, self._gateway_task)

        # Start QoS scheduler (no-op if mode == "off").
        self._qos_scheduler.start()

    async def stop(self) -> None:
        """Stop Discord client and gateway task."""
        await self._qos_scheduler.stop()
        unsubscribe_declaration_changes(self._request_desk_reconcile)
        self._tree = None
        self._registered_launcher_message_ids.clear()
        self._registered_listen_message_ids.clear()
        get_command_service().set_voice_focus_handler(None)
        if self._projects_changed_handler is not None:
            if self.client.cache is not None:
                self.client.cache.unsubscribe(self._projects_changed_handler)
            self._projects_changed_handler = None
        if self._project_reconcile_task is not None and not self._project_reconcile_task.done():
            self._project_reconcile_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._project_reconcile_task
        self._project_reconcile_task = None
        if self._voice_focus_reconcile_task is not None and not self._voice_focus_reconcile_task.done():
            self._voice_focus_reconcile_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._voice_focus_reconcile_task
        self._voice_focus_reconcile_task = None
        if self._voice_room is not None:
            await self._voice_room.close()
            self._voice_room = None
        if self._gateway_liveness is not None:
            await self._gateway_liveness.cancel()
            self._gateway_liveness = None
        if self._client is not None:
            await self._client.close()
        if self._gateway_task and not self._gateway_task.done():
            self._gateway_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._gateway_task

    async def _handle_voice_focus_changed(self, session_id: str) -> None:
        if self._voice_room is not None:
            await self._voice_room.focus_changed(session_id)

    async def _handle_voice_system_command(self, _event: str, context: SystemCommandContext) -> None:
        payload = context.payload
        if (
            self._voice_room is not None
            and context.command == SystemCommand.SESSION_OUTPUT_STOPPED
            and payload is not None
        ):
            await self._voice_room.handle_observed_stop(payload.session_id)

    async def handle_system_command(self, context: SystemCommandContext) -> None:
        """Complete a voice-owned system command delivered by the runtime client."""
        await self._handle_voice_system_command(_EMPTY_EVENT_NAME, context)

    async def handle_runtime_session_status(self, context: RuntimeSessionStatusData) -> None:
        if self._voice_room is not None and context.status == "accepted" and context.reason == "user_prompt_accepted":
            await self._voice_room.input_accepted(context.session_id, context.timestamp)

    async def recover_runtime_voice_focus(self) -> None:
        """Reconcile room focus after live runtime notifications were interrupted."""
        if self._voice_room is not None:
            await self._voice_room.recover_focus()

    def _on_cache_changed(self, event: str, data: object) -> None:
        """Reconcile projects and voice focus through their separate owning capabilities."""
        self._on_projects_snapshot(event, data)
        if event not in (CacheEvent.SESSION_STARTED.value, CacheEvent.SESSION_UPDATED.value):
            return
        self._voice_focus_reconcile_pending = True
        if self._voice_focus_reconcile_task is None or self._voice_focus_reconcile_task.done():
            self._voice_focus_reconcile_task = self.task_registry.spawn(
                self._drain_voice_focus_reconcile(), name=_VOICE_FOCUS_RECONCILE_TASK_NAME
            )

    async def _drain_voice_focus_reconcile(self) -> None:
        while self._voice_focus_reconcile_pending:
            self._voice_focus_reconcile_pending = False
            await self.recover_runtime_voice_focus()

    def _on_projects_snapshot(self, event: str, data: object) -> None:
        """Route local project-cache changes to Discord's adapter-owned reconciler."""
        if (
            event != CacheEvent.PROJECTS_SNAPSHOT.value
            or not isinstance(data, dict)
            or data.get("computer") != config.computer.name
        ):
            return
        self._project_reconcile_pending = True
        self._request_desk_reconcile()
        if self._infrastructure_provisioned and (
            self._project_reconcile_task is None or self._project_reconcile_task.done()
        ):
            self._project_reconcile_task = self.task_registry.spawn(
                self._drain_project_reconcile(), name="discord-project-reconcile"
            )

    def _request_project_reconcile(self) -> None:
        """Queue a local project pass, retaining startup catch-up until Discord is ready."""
        self._project_reconcile_pending = True
        self._request_desk_reconcile()
        if self._infrastructure_provisioned and (
            self._project_reconcile_task is None or self._project_reconcile_task.done()
        ):
            self._project_reconcile_task = self.task_registry.spawn(
                self._drain_project_reconcile(), name="discord-project-reconcile"
            )

    async def _handle_projects_changed(self, _event: str, context: object) -> None:
        """Await the adapter-owned project pass during gateway startup catch-up."""
        self._request_project_reconcile()
        task = self._project_reconcile_task
        if task is not None:
            await task

    async def _drain_project_reconcile(self) -> None:
        """Serialize local project reconciliation and coalesce snapshot changes."""
        async with self._project_reconcile_lock:
            while self._project_reconcile_pending:
                self._project_reconcile_pending = False
                await self._reconcile_project_forums()
                if self._multi_agent:
                    await self._post_project_forum_launchers()

    def _request_desk_reconcile(self) -> None:
        """Ask for a desk-category pass and make sure one task is draining the requests.

        Called from synchronous publishers, so it only records the request and
        schedules; requests that arrive while a pass runs are absorbed by one more
        pass. Before infrastructure is provisioned the request waits for startup.
        """
        self._desk_reconcile_pending = True
        if not self._infrastructure_provisioned or not config.computer.is_master:
            return
        if self._desk_reconcile_task is not None and not self._desk_reconcile_task.done():
            return
        coroutine = self._drain_desk_reconcile_requests()
        if self.task_registry:
            self._desk_reconcile_task = self.task_registry.spawn(coroutine, name=_DESK_RECONCILE_TASK_NAME)
        else:
            self._desk_reconcile_task = asyncio.create_task(coroutine, name=_DESK_RECONCILE_TASK_NAME)

    async def _drain_desk_reconcile_requests(self) -> None:
        """Run a desk pass per request; a pass that fails is logged once and later requests are still served."""
        async with self._desk_reconcile_lock:
            while self._desk_reconcile_pending:
                self._desk_reconcile_pending = False
                try:
                    await self._reconcile_help_desk_categories()
                except Exception:
                    logger.exception(_DESK_PASS_FAILED_EVENT)

    async def send_output_update(
        self,
        session: Session,
        output: str,
        started_at: float,
        last_output_changed_at: float,
        is_final: bool = False,
        exit_code: int | None = None,
        render_markdown: bool = False,
        multi_message: bool = False,
        delivery_ts: object | None = None,
        output_metadata: MessageMetadata | None = None,
    ) -> str | None:
        result = await super().send_output_update(
            session,
            output,
            started_at,
            last_output_changed_at,
            is_final,
            exit_code,
            render_markdown,
            multi_message,
            delivery_ts=cast("datetime | None", delivery_ts),
            output_metadata=output_metadata,
        )
        if is_final and result:
            await self._attach_listen_control(session, result)
        return result

    async def _attach_listen_control(self, session: Session, output_message_id: str) -> None:
        dc = self._dc(session)
        if dc.thread_id is None or self._client is None:
            return
        if not await self._retire_listen_control(session):
            logger.warning("discord.listen.attach_skipped", session_id=session.session_id, reason="prior_delete_failed")
            return
        channel = await self._get_channel(dc.thread_id)
        send = getattr(channel, "send", None)
        if not callable(send):
            return
        control = await self._require_async_callable(send, label="Discord listen control send")(
            view=ListenHereView(session.session_id, self._handle_listen_click)
        )
        control_id = getattr(control, "id", None)
        add_view = getattr(self._client, "add_view", None)
        if isinstance(control_id, int) and callable(add_view):
            add_view(ListenHereView(session.session_id, self._handle_listen_click), message_id=control_id)
            self._registered_listen_message_ids.add(control_id)
            await db.add_pending_deletion(session.session_id, self.ADAPTER_KEY, str(control_id))
            await db.set_system_setting(f"discord_listen:{session.session_id}", str(control_id))
        logger.info(
            "discord.listen.attached",
            session_id=session.session_id,
            output_message_id=output_message_id,
            control_message_id=control_id,
        )

    async def _retire_listen_control(self, session: Session) -> bool:
        """Delete the one current control while preserving retry state on failure."""
        setting_key = f"discord_listen:{session.session_id}"
        control_id = self._parse_optional_int(await db.get_system_setting(setting_key))
        if control_id is None:
            return True
        destination = resolve_destination(session, self.ADAPTER_KEY)
        deleted = await self.delete_message(destination, str(control_id))
        if not deleted:
            return False
        self._registered_listen_message_ids.discard(control_id)
        await db.remove_pending_deletion(session.session_id, self.ADAPTER_KEY, str(control_id))
        await db.set_system_setting(setting_key, "")
        return True

    async def _pre_handle_user_input(self, session: Session) -> None:
        """Run shared ephemeral cleanup and reconcile exact control registration."""
        await self._retire_listen_control(session)
        await super()._pre_handle_user_input(session)

    async def _handle_listen_click(self, interaction: object, session_id: str) -> None:
        message_id = self._parse_optional_int(getattr(getattr(interaction, "message", None), "id", None))
        if message_id is None or message_id not in self._registered_listen_message_ids:
            logger.info("discord.listen.ownership_decided", owned=False, reason="foreign_message")
            return
        user_id = str(getattr(getattr(interaction, "user", None), "id", ""))
        identity = get_identity_resolver().resolve("discord", {"user_id": user_id, "discord_user_id": user_id})
        if not identity.person_slug:
            return
        logger.info("discord.listen.received", session_id=session_id)
        target = config.computer.name if config.computer.is_master else None
        if target is None:
            for peer in await self.client.discover_peers():
                if peer.get("is_master") is True and isinstance(peer.get("name"), str):
                    target = cast(str, peer["name"])
                    break
        if target is None:
            logger.info("discord.listen.unroutable", reason="no_master_advertised")
            return
        command = SetVoiceFocusCommand(person_slug=identity.person_slug, session_id=session_id)
        command.computer = target
        await dispatch_command(self.client, command, principal=SYSTEM_DAEMON_PRINCIPAL)
        logger.info("discord.listen.ownership_decided", owned=True, reason="master_routed")

    async def _restore_listen_controls(self) -> None:
        """Re-register each persisted exact control message after a restart."""
        if self._client is None:
            return
        add_view = getattr(self._client, "add_view", None)
        if not callable(add_view):
            return
        for session in await db.list_sessions(
            computer_name=config.computer.name, include_closed=True, include_headless=True
        ):
            control_id = self._parse_optional_int(await db.get_system_setting(f"discord_listen:{session.session_id}"))
            if control_id is not None:
                add_view(ListenHereView(session.session_id, self._handle_listen_click), message_id=control_id)
                self._registered_listen_message_ids.add(control_id)

    def _get_enabled_agents(self) -> list[str]:
        return [name.value for name, agent_cfg in config.agents.items() if agent_cfg.enabled]

    @property
    def _multi_agent(self) -> bool:
        return len(self._get_enabled_agents()) > 1

    @staticmethod
    def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]:
        if not callable(fn):
            raise AdapterError(f"{label} is not callable")
        return cast(Callable[..., Awaitable[object]], fn)

    # =========================================================================
    # Per-adapter output message tracking
    # =========================================================================
    # Discord stores output tracking in origin_metadata to prevent cross-adapter races.

    @staticmethod
    def _dc(session: Session) -> DiscordAdapterMetadata:
        """Read Discord section from origin_metadata."""
        return DiscordAdapterMetadata.from_dict(session.get_origin_section("discord"))

    def get_action_throttle_interval_s(self, action_kind: str) -> float:
        """Discord typing indicators persist long enough for a coarse pulse cadence."""
        if action_kind == "typing":
            return DISCORD_TYPING_INTERVAL_S
        if action_kind == "title":
            return 600.0
        return super().get_action_throttle_interval_s(action_kind)

    async def send_typing_indicator(self, session: Session) -> None:
        """Send typing indicator to Discord thread."""
        discord_meta = self._dc(session)
        if discord_meta.thread_id is None:
            logger.debug("Typing skipped: no thread_id for session %s", session.session_id)
            return
        thread = await self._get_channel(discord_meta.thread_id)
        if thread is None:
            logger.debug(
                "Typing skipped: channel %s not found for session %s", discord_meta.thread_id, session.session_id
            )
            return
        typing_fn = getattr(thread, "typing", None)
        if typing_fn and callable(typing_fn):
            recoverable_errors = recoverable_operation_errors(self._discord)
            try:
                await typing_fn()  # type: ignore[unused-ignore]
            except recoverable_errors as exc:
                logger.debug("Typing failed for session %s: %s", session.session_id, exc)
                return
            logger.debug("Typing fired: session=%s thread=%s", session.session_id, discord_meta.thread_id)
        else:
            logger.debug(
                "Typing skipped: typing() not available on channel %s for session %s",
                discord_meta.thread_id,
                session.session_id,
            )

    async def recover_lane_error(
        self,
        session: Session,
        error: Exception,
        task_factory: Callable[[UiAdapter, Session], Awaitable[object]],
        display_title: str,
    ) -> object | None:
        """Absorb expected lane outcomes (unprovisioned channel, stale metadata cleanup)."""
        del task_factory, display_title

        if isinstance(error, ChannelNotProvisionedError):
            logger.info(
                "[DISCORD_RECOVER] Lane skipped — no Discord channel yet for session %s",
                session.session_id,
            )
            return None

        if isinstance(error, AdapterError) and "metadata cleared" in str(error):
            logger.info(
                "[DISCORD_RECOVER] Lane skipped after stale Discord metadata was cleared for session %s: %s",
                session.session_id,
                error,
            )
            return None

        raise error

    # send_threaded_output: inherited from EditableUiAdapter.

    async def on_session_updated(self, session: Session, updated_fields: Mapping[str, object]) -> None:
        """Refresh Discord thread topper when topper-relevant fields change.

        Dispatched by ``AdapterClient.dispatch_session_update`` only for the
        session's origin adapter. Discord owns its own topper-field policy.
        """
        if not {"native_session_id", "active_agent", "thinking_mode"} & set(updated_fields):
            return

        dc = self._dc(session)
        if dc.thread_id is None:
            return

        topper_message_id = dc.thread_topper_message_id
        if not topper_message_id:
            topper_message_id = str(dc.thread_id)
            await db.update_origin_metadata(
                session.session_id, "discord", {DiscordMetadataField.THREAD_TOPPER_MESSAGE_ID: topper_message_id}
            )

        topper = self._build_thread_topper(session)
        destination = resolve_destination(session, self.ADAPTER_KEY)
        edited = await self.edit_message(destination, topper_message_id, topper)
        if not edited:
            logger.debug(
                "Discord topper refresh failed for session %s (msg=%s)",
                session.session_id,
                topper_message_id,
            )
