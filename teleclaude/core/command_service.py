"""Explicit command execution service for TeleClaude.

Commands are typed inputs that map directly to handler functions.
This service wires required dependencies without using a generic dispatcher.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.constants import (
    ROLE_INTEGRATOR,
    ROLE_ORCHESTRATOR,
    ROLE_SYSTEM,
    ROLE_WORKER,
    DriverLaunchClass,
    JobRole,
    SlashCommand,
)
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
    keys,
    process_message,
    resume_agent,
    run_agent_command,
    start_agent,
)
from teleclaude.core.models import SessionLaunchIntent, ThinkingMode
from teleclaude.core.session_launcher import create_session
from teleclaude.types.commands import (
    CloseSessionCommand,
    CreateSessionCommand,
    GetSessionDataCommand,
    HandleFileCommand,
    HandleVoiceCommand,
    KeysCommand,
    ProcessMessageCommand,
    RestartAgentCommand,
    ResumeAgentCommand,
    RunAgentCommand,
    StartAgentCommand,
    SystemCommand,
    UnsubscribeSessionCommand,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
from datetime import UTC, datetime

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.discord_adapter import DiscordAdapter
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionEscalatedPayload
from teleclaude.core.inbound_queue import init_inbound_queue_manager
from teleclaude.core.models import MessageMetadata
from teleclaude.core.session_listeners import close_link_for_member, unregister_listener
from teleclaude.events.envelope import EventVisibility
from teleclaude.utils.markdown import telegramify_markdown

logger = get_logger(__name__)


class UnsubscribeSessionPayload(TypedDict):
    """Payload returned when a caller stops following a session."""

    listener_removed: bool
    link_closed: bool
    link_id: str | None


# Maps slash commands to (system_role, job_role) pairs.
# Used both by run_slash_command() internally and exported for api_server.py.
COMMAND_ROLE_MAP: dict[SlashCommand, tuple[str, JobRole]] = {
    SlashCommand.NEXT_BUILD: (ROLE_WORKER, JobRole.BUILDER),
    SlashCommand.NEXT_BUGS_FIX: (ROLE_WORKER, JobRole.FIXER),
    SlashCommand.NEXT_REVIEW_BUILD: (ROLE_WORKER, JobRole.REVIEWER),
    SlashCommand.NEXT_REVIEW_PLAN: (ROLE_WORKER, JobRole.REVIEWER),
    SlashCommand.NEXT_REVIEW_ARCHITECTURE: (ROLE_WORKER, JobRole.ARCHITECTURE_REVIEWER),
    SlashCommand.NEXT_REVIEW_COMMITS: (ROLE_WORKER, JobRole.REVIEWER),
    SlashCommand.NEXT_CREATE_ART: (ROLE_WORKER, JobRole.ARTIST),
    SlashCommand.NEXT_CREATE_HTML: (ROLE_WORKER, JobRole.FRONTENDER),
    SlashCommand.NEXT_FIX_REVIEW: (ROLE_WORKER, JobRole.FIXER),
    SlashCommand.NEXT_FINALIZE: (ROLE_WORKER, JobRole.FINALIZER),
    SlashCommand.NEXT_PREPARE_INTAKE: (ROLE_WORKER, JobRole.INTAKER),
    SlashCommand.NEXT_PREPARE_ARCHITECTURE: (ROLE_WORKER, JobRole.ARCHITECT),
    SlashCommand.NEXT_PREPARE_DIAGNOSE: (ROLE_WORKER, JobRole.DIAGNOSER),
    SlashCommand.NEXT_PREPARE_PLAN: (ROLE_WORKER, JobRole.PLANNER),
    SlashCommand.NEXT_PREPARE_TASK: (ROLE_WORKER, JobRole.TASK_PREPARER),
    SlashCommand.NEXT_EMULATE_PO: (ROLE_WORKER, JobRole.PO_EMULATOR),
    SlashCommand.NEXT_DRIFT_ANALYZE: (ROLE_WORKER, JobRole.DRIFT_ANALYZER),
    SlashCommand.NEXT_PREPARE: (ROLE_ORCHESTRATOR, JobRole.PREPARE_ORCHESTRATOR),
    SlashCommand.NEXT_WORK: (ROLE_ORCHESTRATOR, JobRole.WORK_ORCHESTRATOR),
    SlashCommand.NEXT_RUN_TASK: (ROLE_WORKER, JobRole.TASK_RUNNER),
    SlashCommand.NEXT_INTEGRATE: (ROLE_INTEGRATOR, JobRole.INTEGRATOR),
}


def classify_driver_launch(command: SlashCommand | str | None) -> DriverLaunchClass:
    """Classify a session-create launch by its requested command for driver-start dedup.

    The create-door guard keys on what the requested launch IS (`DriverLaunchClass`):
    a lifecycle orchestrator command is an ``ORCHESTRATOR`` driver, ``/next-run-task``
    is the ``TASK_LANE`` driver, and every other command (including non-driver
    ``ROLE_WORKER`` workers and non-lifecycle launches) is a ``WORKER_CHILD`` that an
    orchestrator may legitimately spawn against a shared ``working_slug``.
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
    return DriverLaunchClass.WORKER_CHILD


# Which target roles each caller system_role may dispatch via sessions/run.
# Callers without a system_role (terminal, TUI, web, daemon lifecycle_router)
# are on the human_role axis — endpoint-level clearance governs their access.
DISPATCH_ALLOWED: dict[str, frozenset[str]] = {
    ROLE_ORCHESTRATOR: frozenset({ROLE_WORKER, ROLE_ORCHESTRATOR}),
    ROLE_INTEGRATOR: frozenset({ROLE_WORKER}),
    ROLE_SYSTEM: frozenset({ROLE_WORKER, ROLE_ORCHESTRATOR}),
    ROLE_WORKER: frozenset(),
}


StartPollingFunc = Callable[[str, str], Awaitable[None]]
ExecuteTerminalCommandFunc = Callable[[str, str, str | None, bool], Awaitable[bool]]
QueueBackgroundTaskFunc = Callable[[Awaitable[object], str], None]
BootstrapSessionFunc = Callable[[str, SessionLaunchIntent | None], Awaitable[None]]


def _build_widget_summary(data: dict[str, object]) -> str:  # guard: loose-dict - dynamic payload
    """Build the text summary sent for a rich widget payload."""
    title = str(data.get("title", ""))
    sections = data.get("sections", [])
    footer = str(data.get("footer", ""))
    if not isinstance(sections, list):
        raise ValueError("sections must be an array")

    summary_parts: list[str] = [f"**{title}**\n"] if title else []
    for section in sections:
        if not isinstance(section, dict):
            continue
        label = section.get("label")
        if label:
            summary_parts.append(f"_{label}_")

        section_type = str(section.get("type", ""))
        if section_type == "text":
            content = str(section.get("content", ""))
            if content:
                summary_parts.append(content)
            continue
        if section_type == "table":
            headers = section.get("headers", [])
            rows = section.get("rows", [])
            if isinstance(headers, list) and isinstance(rows, list):
                summary_parts.append(f"Table: {len(headers)} columns, {len(rows)} rows")
            continue
        if section_type == "code":
            lang = str(section.get("language", ""))
            content = str(section.get("content", ""))
            lang_label = f" ({lang})" if lang else ""
            preview = content[:100] + "..." if len(content) > 100 else content
            summary_parts.append(f"Code{lang_label}:\n```\n{preview}\n```")
            continue
        if section_type == "divider":
            summary_parts.append("---")

    if footer:
        summary_parts.append(f"\n{footer}")
    return "\n".join(summary_parts)


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

    async def restart_agent(self, cmd: RestartAgentCommand) -> tuple[bool, str | None]:
        return await agent_restart(cmd, self.client, self._execute_terminal_command)

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

    async def end_session(self, cmd: CloseSessionCommand) -> EndSessionHandlerResult:
        return await end_session(cmd, self.client)

    async def deliver_result(self, cmd: SystemCommand) -> object:
        """Deliver a formatted result to a session's user via the adapter."""
        return await self._dispatch_system_command(cmd)

    async def deliver_file(self, cmd: SystemCommand) -> object:
        """Deliver a file attachment to a session's user via the adapter."""
        return await self._dispatch_system_command(cmd)

    async def render_widget(self, cmd: SystemCommand) -> object:
        """Render a widget expression and send summary to the session's user."""
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
            case "render_widget":
                return await self._handle_render_widget(cmd)
            case "escalate_session":
                return await self._handle_escalate_session(cmd)
            case _:
                raise ValueError(f"Unknown system command: {cmd.command}")

    async def _handle_deliver_result(self, cmd: SystemCommand) -> object:
        """Send a formatted result message to a session's user via the adapter."""
        content = str((cmd.data or {}).get("content", ""))

        session = await db.get_session(cmd.session_id)
        if not session:
            raise ValueError(f"Session {cmd.session_id} not found")

        if str((cmd.data or {}).get("output_format", "markdown")) == "html":
            formatted = content
            parse_mode = "HTML"
        else:
            formatted = telegramify_markdown(content)
            parse_mode = "MarkdownV2"

        if len(formatted) > 4096:
            formatted = formatted[:4090] + "\n..."

        try:
            message_id = await self.client.send_message(
                session=session,
                text=formatted,
                metadata=MessageMetadata(parse_mode=parse_mode),
                ephemeral=False,
            )
            return {"status": "success", "message_id": message_id}
        except (AdapterError, RuntimeError, ValueError, TypeError) as e:
            logger.warning("deliver_result formatted send failed, retrying as plain text: %s", e)
            try:
                message_id = await self.client.send_message(
                    session=session,
                    text=content[:4096],
                    metadata=MessageMetadata(),
                    ephemeral=False,
                )
                return {
                    "status": "success",
                    "message_id": message_id,
                    "warning": "Sent as plain text due to formatting error",
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

    async def _handle_render_widget(self, cmd: SystemCommand) -> object:
        """Render a rich widget and send text summary to the session's user."""
        raw_widget = (cmd.data or {}).get("widget_data")
        if not isinstance(raw_widget, dict):
            raise ValueError("widget_data must be a dict")

        session = await db.get_session(cmd.session_id)
        if not session:
            raise ValueError(f"Session {cmd.session_id} not found")

        text_summary = _build_widget_summary(raw_widget)
        try:
            await self.client.send_message(
                session=session,
                text=telegramify_markdown(text_summary),
                metadata=MessageMetadata(parse_mode="MarkdownV2"),
                ephemeral=False,
            )
        except Exception as e:
            logger.error("render_widget send failed: %s", e, exc_info=True)
            raise ValueError(f"Failed to send widget: {e}") from e

        return {"status": "success", "summary": text_summary}

    async def _handle_escalate_session(self, cmd: SystemCommand) -> object:
        """Escalate a customer session to an admin via Discord."""
        session = await db.get_session(cmd.session_id)
        if not session:
            raise ValueError(f"Session {cmd.session_id} not found")
        if session.human_role != "customer":
            raise ValueError("Escalation is only available in customer sessions")

        discord_adapter: DiscordAdapter | None = None
        for adapter in self.client.adapters.values():
            if isinstance(adapter, DiscordAdapter):
                discord_adapter = adapter
                break
        if not discord_adapter:
            raise ValueError("Discord adapter not available")

        data = cmd.data or {}
        session_id = cmd.session_id or ""
        thread_id = await discord_adapter.create_escalation_thread(
            customer_name=str(data.get("customer_name", "")),
            reason=str(data.get("reason", "")),
            context_summary=str(data.get("context_summary", "")),
            session_id=session_id,
        )
        await db.update_session(
            session_id,
            relay_status="active",
            relay_discord_channel_id=str(thread_id),
            relay_started_at=datetime.now(UTC).isoformat(),
            lifecycle_status="escalated",
        )
        event_bus.emit(
            "session.escalation_started",  # type: ignore[arg-type]
            SessionEscalatedPayload(session_id=session_id),
            visibility=EventVisibility.CLUSTER,
        )

        return {"status": "accepted", "thread_id": thread_id}
