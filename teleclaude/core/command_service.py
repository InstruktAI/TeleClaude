"""Explicit command execution service for TeleClaude.

Commands are typed inputs that map directly to handler functions.
This service wires required dependencies without using a generic dispatcher.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import (
    COMMAND_ROLE_MAP,
    ROLE_INTEGRATOR,
    ROLE_ORCHESTRATOR,
    ROLE_SYSTEM,
    ROLE_TASKER,
    ROLE_WORKER,
    DriverLaunchClass,
    JobRole,
    SlashCommand,
)
from teleclaude.core import voice_focus
from teleclaude.core.command_handlers import (
    EndSessionHandlerResult,
    SessionDataPayload,
    agent_restart,
    close_session,
    deliver_inbound,
    end_session,
    get_session_data,
    handle_file,
    handle_voice,
    handoff_agent,
    keys,
    notify_delivery_exhausted,
    process_message,
    resume_agent,
    run_agent_command,
    start_agent,
)
from teleclaude.core.integration.discord_admin_state import (
    DiscordSharedChildKind,
    DiscordSharedThreadClaim,
    DiscordThreadClaimInventoryItem,
)
from teleclaude.core.integration.discord_admin_state import (
    DiscordThreadClaimLifecycle as PersistedDiscordThreadClaimLifecycle,
)
from teleclaude.core.models import SessionLaunchIntent, ThinkingMode
from teleclaude.core.session_launcher import create_session
from teleclaude.core.session_lifecycle import LifecycleTransition, LifecycleTransitionReason, transition_session
from teleclaude.core.session_status import SessionLifecycleStatus
from teleclaude.types.commands import (
    CloseSessionCommand,
    CreateSessionCommand,
    DiscordThreadClaimCommand,
    GetSessionDataCommand,
    HandleFileCommand,
    HandleVoiceCommand,
    HandoffAgentCommand,
    KeysCommand,
    ProcessMessageCommand,
    RestartAgentCommand,
    RestartAgentResult,
    ResumeAgentCommand,
    RunAgentCommand,
    SetVoiceFocusCommand,
    StartAgentCommand,
    SystemCommand,
    UnsubscribeSessionCommand,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
from datetime import UTC, datetime

from teleclaude.core.adapter_errors import AdapterError
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionEscalatedPayload, VoiceFocusSetContext
from teleclaude.core.inbound_queue import init_inbound_queue_manager
from teleclaude.core.models import ContentFormat, MessageMetadata
from teleclaude.core.protocols import AdminReflectionAdapter
from teleclaude.core.session_listeners import close_link_for_member, unregister_listener
from teleclaude.events.envelope import EventVisibility

logger = get_logger(__name__)


class UnsubscribeSessionPayload(TypedDict):
    """Payload returned when a caller stops following a session."""

    listener_removed: bool
    link_closed: bool
    link_id: str | None


_REVIEWER_JOB_ROLES = frozenset({JobRole.REVIEWER})


def classify_driver_launch(command: SlashCommand | str | None) -> DriverLaunchClass:
    """Classify a session-create launch by its requested command for driver-start dedup.

    The create-door guard keys on what the requested launch IS (`DriverLaunchClass`):
    a lifecycle orchestrator command is an ``ORCHESTRATOR`` driver, ``/next-run-task``
    is the ``TASK_LANE`` driver, a reviewer command (identified by its `JobRole` in
    `COMMAND_ROLE_MAP` rather than a hand-maintained list, so a review command added
    later inherits the class automatically) is ``REVIEWER``, and every other command
    (including non-lifecycle launches) is a ``WORKER_CHILD`` that an orchestrator may
    legitimately spawn against a shared ``working_slug``.
    """
    if isinstance(command, str):
        try:
            command = SlashCommand(command.lstrip("/"))
        except ValueError:
            return DriverLaunchClass.WORKER_CHILD
    if command is None:
        return DriverLaunchClass.WORKER_CHILD
    if command is SlashCommand.NEXT_RUN_TASK:
        return DriverLaunchClass.TASK_LANE
    role_info = COMMAND_ROLE_MAP.get(command)
    if role_info is not None and role_info[0] == ROLE_ORCHESTRATOR:
        return DriverLaunchClass.ORCHESTRATOR
    if role_info is not None and role_info[1] in _REVIEWER_JOB_ROLES:
        return DriverLaunchClass.REVIEWER
    return DriverLaunchClass.WORKER_CHILD


# Which target roles each caller system_role may dispatch via sessions/run.
# Callers without a system_role (terminal, TUI, daemon lifecycle_router)
# are on the human_role axis — endpoint-level clearance governs their access.
DISPATCH_ALLOWED: dict[str, frozenset[str]] = {
    ROLE_ORCHESTRATOR: frozenset({ROLE_WORKER, ROLE_ORCHESTRATOR, ROLE_INTEGRATOR}),
    ROLE_INTEGRATOR: frozenset({ROLE_WORKER}),
    ROLE_SYSTEM: frozenset({ROLE_WORKER, ROLE_ORCHESTRATOR}),
    ROLE_TASKER: frozenset({ROLE_WORKER}),
    ROLE_WORKER: frozenset(),
}


StartPollingFunc = Callable[[str, str], Awaitable[None]]
ExecuteTerminalCommandFunc = Callable[[str, str, str | None, bool], Awaitable[bool]]
QueueBackgroundTaskFunc = Callable[[Awaitable[object], str], None]
BootstrapSessionFunc = Callable[[str, SessionLaunchIntent | None], Awaitable[None]]

_DATA_KEY_CONTENT = "content"
_DATA_KEY_OUTPUT_FORMAT = "output_format"
_PLAIN_RETRY_WARNING = "Sent as plain content after a delivery failure"


def _content_format_from_request(raw_format: object) -> ContentFormat:
    """Resolve a requested output format, falling back to markdown."""
    try:
        return ContentFormat(str(raw_format))
    except ValueError:
        return ContentFormat.MARKDOWN


class CommandService:
    """Explicit command executor with typed command methods."""

    def __init__(
        self,
        *,
        client: AdapterClient,
        start_polling: StartPollingFunc,
        execute_terminal_command: ExecuteTerminalCommandFunc,
        queue_background_task: QueueBackgroundTaskFunc,
        bootstrap_session: BootstrapSessionFunc,
    ) -> None:
        self.client = client
        self._start_polling = start_polling
        self._execute_terminal_command = execute_terminal_command
        self._queue_background_task = queue_background_task
        self._bootstrap_session = bootstrap_session

        # Initialize the inbound queue manager singleton with delivery wired to this service's deps.
        init_inbound_queue_manager(
            functools.partial(deliver_inbound, client=client, start_polling=start_polling),
            delivery_exhausted_callback=functools.partial(notify_delivery_exhausted, client=client),
            force=True,
        )

    async def create_session(self, cmd: CreateSessionCommand) -> dict[str, str]:
        return await create_session(
            cmd,
            self.client,
            self._queue_background_task,
            self._bootstrap_session,  # type: ignore[arg-type]
        )

    async def process_message(self, cmd: ProcessMessageCommand) -> None:
        await process_message(cmd, self.client, self._start_polling)

    async def handle_voice(self, cmd: HandleVoiceCommand) -> None:
        await handle_voice(cmd, self.client, self._start_polling)

    async def handle_file(self, cmd: HandleFileCommand) -> None:
        await handle_file(cmd, self.client)

    async def keys(self, cmd: KeysCommand) -> None:
        await keys(cmd, self.client, self._start_polling)

    async def start_agent(self, cmd: StartAgentCommand) -> None:
        args = list(cmd.args)
        valid_modes = {mode.value for mode in ThinkingMode}
        if cmd.thinking_mode and (not args or args[0] not in valid_modes):
            args.insert(0, cmd.thinking_mode)
        cmd.args = args
        await start_agent(cmd, self.client, self._execute_terminal_command)

    async def resume_agent(self, cmd: ResumeAgentCommand) -> None:
        await resume_agent(cmd, self.client, self._execute_terminal_command)

    async def restart_agent(self, cmd: RestartAgentCommand) -> tuple[bool, str | None] | RestartAgentResult:
        return await agent_restart(cmd, self.client, self._execute_terminal_command)

    async def handoff_agent(self, cmd: HandoffAgentCommand) -> None:
        await handoff_agent(cmd, self.client, self._execute_terminal_command)

    async def run_agent_command(self, cmd: RunAgentCommand) -> None:
        await run_agent_command(cmd, self.client, self._execute_terminal_command)

    async def get_session_data(self, cmd: GetSessionDataCommand) -> SessionDataPayload:
        return await get_session_data(cmd)

    async def unsubscribe(self, cmd: UnsubscribeSessionCommand) -> UnsubscribeSessionPayload:
        listener_removed = await unregister_listener(
            target_session_id=cmd.session_id,
            caller_session_id=cmd.caller_session_id,
        )
        link_id = await close_link_for_member(
            caller_session_id=cmd.caller_session_id,
            target_session_id=cmd.session_id,
        )
        return {
            "listener_removed": listener_removed,
            "link_closed": link_id is not None,
            "link_id": link_id,
        }

    async def close_session(self, cmd: CloseSessionCommand) -> None:
        await close_session(cmd, self.client)

    async def set_voice_focus(self, cmd: SetVoiceFocusCommand) -> dict[str, str | None]:
        """Durably override a person's voice focus, then notify local subscribers.

        The command envelope crosses computers; the emitted event stays local
        (the Discord adapter subscribes to play the newly focused session's
        current reply immediately). Core imports no adapter module.
        """
        record = await voice_focus.set_explicit(cmd.person_slug, cmd.session_id)
        event_bus.emit(
            "voice_focus_set",
            VoiceFocusSetContext(
                focus_id=record.focus_id,
                session_id=cmd.session_id,
                basis=record.basis.value,
                set_at=record.set_at.isoformat(),
            ),
            visibility=EventVisibility.LOCAL,
        )
        return {
            "focus_id": record.focus_id,
            "session_id": record.focused_session_id,
            "basis": record.basis.value,
            "set_at": record.set_at.isoformat(),
        }

    async def discord_thread_claim(
        self, cmd: DiscordThreadClaimCommand, *, source_computer: str
    ) -> dict[str, str | None]:
        """Apply a claim mutation only on the configured fleet master."""
        if not config.computer.is_master:
            raise ValueError("shared Discord child claims must target the fleet master")
        if cmd.action.value == "open_epoch":
            epoch = await db.open_discord_thread_reconciliation_epoch(protocol_generation=cmd.protocol_generation)
            return {"outcome": "opened", "owner_computer": str(epoch), "lifecycle": None}
        if cmd.action.value == "complete_inventory":
            if cmd.inventory_epoch is None:
                raise ValueError("inventory completion requires an epoch")
            items = tuple(
                DiscordThreadClaimInventoryItem(
                    thread_id=int(cast(int | str, item["thread_id"])),
                    parent_id=int(cast(int | str, item["parent_id"])),
                    kind=DiscordSharedChildKind(str(item["kind"])),
                    local_identity=str(item["local_identity"]),
                    lifecycle=PersistedDiscordThreadClaimLifecycle(str(item["lifecycle"])),
                )
                for item in cmd.inventory_items
            )
            completed = await db.replace_discord_thread_claim_inventory(
                source_computer,
                protocol_generation=cmd.protocol_generation,
                epoch=cmd.inventory_epoch,
                items=items,
            )
            return {"outcome": "completed" if completed else "refused", "owner_computer": None, "lifecycle": None}
        claim = DiscordSharedThreadClaim(
            thread_id=cmd.thread_id,
            parent_id=cmd.parent_id,
            kind=DiscordSharedChildKind(cmd.kind.value),
            computer=source_computer,
            local_identity=cmd.local_identity,
            lifecycle=PersistedDiscordThreadClaimLifecycle(cmd.lifecycle.value),
            protocol_generation=cmd.protocol_generation,
        )
        result = await db.observe_discord_shared_thread(
            claim,
            source_computer=source_computer,
            enforce_owner=cmd.action.value == "claim",
        )
        return {
            "outcome": result.outcome.value,
            "owner_computer": result.owner_computer,
            "lifecycle": result.lifecycle.value if result.lifecycle is not None else None,
        }

    async def end_session(self, cmd: CloseSessionCommand) -> EndSessionHandlerResult:
        return await end_session(cmd, self.client)

    async def deliver_result(self, cmd: SystemCommand) -> object:
        """Deliver a formatted result to a session's user via the adapter."""
        return await self._dispatch_system_command(cmd)

    async def deliver_file(self, cmd: SystemCommand) -> object:
        """Deliver a file attachment to a session's user via the adapter."""
        return await self._dispatch_system_command(cmd)

    async def escalate_session(self, cmd: SystemCommand) -> object:
        """Escalate a customer session to admin via Discord."""
        return await self._dispatch_system_command(cmd)

    async def system_command(self, cmd: SystemCommand) -> object:
        """Route a SystemCommand to its handler based on cmd.command field."""
        return await self._dispatch_system_command(cmd)

    async def _dispatch_system_command(self, cmd: SystemCommand) -> object:
        """Internal dispatch for system commands based on cmd.command value."""
        match cmd.command:
            case "deliver_result":
                return await self._handle_deliver_result(cmd)
            case "deliver_file":
                return await self._handle_deliver_file(cmd)
            case "escalate_session":
                return await self._handle_escalate_session(cmd)
            case _:
                raise ValueError(f"Unknown system command: {cmd.command}")

    async def _handle_deliver_result(self, cmd: SystemCommand) -> object:
        """Send a result message to a session's user, declaring only its content format.

        Rendering and platform limits belong to the adapters: core states what the
        content is (markdown or html) and never escapes, converts, or truncates it.
        """
        data = cmd.data or {}
        content = str(data.get(_DATA_KEY_CONTENT, ""))
        content_format = _content_format_from_request(data.get(_DATA_KEY_OUTPUT_FORMAT))

        session = await db.get_session(cmd.session_id)
        if not session:
            raise ValueError(f"Session {cmd.session_id} not found")

        try:
            message_id = await self.client.send_message(
                session=session,
                text=content,
                metadata=MessageMetadata(content_format=content_format),
                ephemeral=False,
            )
            return {"status": "success", "message_id": message_id}
        except (AdapterError, RuntimeError, ValueError, TypeError) as e:
            logger.warning("deliver_result send failed, retrying as plain content: %s", e)
            try:
                message_id = await self.client.send_message(
                    session=session,
                    text=content,
                    metadata=MessageMetadata(),
                    ephemeral=False,
                )
                return {
                    "status": "success",
                    "message_id": message_id,
                    "warning": _PLAIN_RETRY_WARNING,
                }
            except (AdapterError, RuntimeError, ValueError, TypeError) as fallback_error:
                raise ValueError(f"Failed to send result: {fallback_error}") from fallback_error

    async def _handle_deliver_file(self, cmd: SystemCommand) -> object:
        """Send a file attachment to a session's user via the adapter."""
        data = cmd.data or {}
        file_path = str(data.get("file_path", "")).strip()
        filename = str(data.get("filename", "")).strip()
        caption_obj = data.get("caption")
        caption = caption_obj if isinstance(caption_obj, str) else None

        if not file_path:
            raise ValueError("file_path is required")

        session = await db.get_session(cmd.session_id)
        if not session:
            raise ValueError(f"Session {cmd.session_id} not found")

        try:
            message_id = await self.client.send_file(session, file_path, caption=caption)
        except (AdapterError, OSError, RuntimeError, ValueError, TypeError) as e:
            raise ValueError(f"Failed to send file: {e}") from e

        return {
            "status": "success",
            "message_id": message_id,
            "filename": filename or Path(file_path).name,
        }

    async def _handle_escalate_session(self, cmd: SystemCommand) -> object:
        """Escalate a customer session to an admin via Discord."""
        session = await db.get_session(cmd.session_id)
        if not session:
            raise ValueError(f"Session {cmd.session_id} not found")
        if session.human_role != "customer":
            raise ValueError("Escalation is only available in customer sessions")

        admin_adapter: AdminReflectionAdapter | None = None
        for adapter in self.client.adapters.values():
            if isinstance(adapter, AdminReflectionAdapter):
                admin_adapter = adapter
                break
        if not admin_adapter:
            raise ValueError("No admin-reflection adapter registered")

        data = cmd.data or {}
        session_id = cmd.session_id or ""
        thread_id = await admin_adapter.create_escalation_thread(
            customer_name=str(data.get("customer_name", "")),
            reason=str(data.get("reason", "")),
            context_summary=str(data.get("context_summary", "")),
            session_id=session_id,
        )
        await db.update_session(
            session_id,
            relay_status="active",
            relay_channel_id=str(thread_id),
            relay_started_at=datetime.now(UTC).isoformat(),
        )
        await transition_session(
            db,
            session_id,
            LifecycleTransition(SessionLifecycleStatus.ESCALATED, LifecycleTransitionReason.ESCALATED),
        )
        event_bus.emit(
            "session.escalation_started",  # type: ignore[arg-type]
            SessionEscalatedPayload(session_id=session_id),
            visibility=EventVisibility.CLUSTER,
        )

        return {"status": "accepted", "thread_id": thread_id}
