"""Explicit command execution service for TeleClaude.

Commands are typed inputs that map directly to handler functions.
This service wires required dependencies without using a generic dispatcher.
"""

from __future__ import annotations

import functools
import shlex
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from teleclaude.constants import (
    ROLE_INTEGRATOR,
    ROLE_ORCHESTRATOR,
    ROLE_WORKER,
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
from teleclaude.core.models import ThinkingMode
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
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient


# Maps slash commands to (system_role, job_role) pairs.
# Used both by run_slash_command() internally and exported for api_server.py.
COMMAND_ROLE_MAP: dict[SlashCommand, tuple[str, JobRole]] = {
    SlashCommand.NEXT_BUILD: (ROLE_WORKER, JobRole.BUILDER),
    SlashCommand.NEXT_BUGS_FIX: (ROLE_WORKER, JobRole.FIXER),
    SlashCommand.NEXT_REVIEW_BUILD: (ROLE_WORKER, JobRole.REVIEWER),
    SlashCommand.NEXT_REVIEW_PLAN: (ROLE_WORKER, JobRole.REVIEWER),
    SlashCommand.NEXT_REVIEW_REQUIREMENTS: (ROLE_WORKER, JobRole.REVIEWER),
    SlashCommand.NEXT_FIX_REVIEW: (ROLE_WORKER, JobRole.FIXER),
    SlashCommand.NEXT_FINALIZE: (ROLE_WORKER, JobRole.FINALIZER),
    SlashCommand.NEXT_PREPARE_DISCOVERY: (ROLE_WORKER, JobRole.DISCOVERER),
    SlashCommand.NEXT_PREPARE_DRAFT: (ROLE_WORKER, JobRole.DRAFTER),
    SlashCommand.NEXT_PREPARE_GATE: (ROLE_WORKER, JobRole.GATE_CHECKER),
    SlashCommand.NEXT_PREPARE: (ROLE_ORCHESTRATOR, JobRole.PREPARE_ORCHESTRATOR),
    SlashCommand.NEXT_WORK: (ROLE_ORCHESTRATOR, JobRole.WORK_ORCHESTRATOR),
    SlashCommand.NEXT_INTEGRATE: (ROLE_INTEGRATOR, JobRole.INTEGRATOR),
}


StartPollingFunc = Callable[[str, str], Awaitable[None]]
ExecuteTerminalCommandFunc = Callable[[str, str, str | None, bool], Awaitable[bool]]
ExecuteAutoCommandFunc = Callable[[str, str], Awaitable[dict[str, str]]]
QueueBackgroundTaskFunc = Callable[[Awaitable[object], str], None]
BootstrapSessionFunc = Callable[[str, str | None], Awaitable[None]]


class CommandService:
    """Explicit command executor with typed command methods."""

    def __init__(
        self,
        *,
        client: AdapterClient,
        start_polling: StartPollingFunc,
        execute_terminal_command: ExecuteTerminalCommandFunc,
        execute_auto_command: ExecuteAutoCommandFunc,
        queue_background_task: QueueBackgroundTaskFunc,
        bootstrap_session: BootstrapSessionFunc,
    ) -> None:
        self.client = client
        self._start_polling = start_polling
        self._execute_terminal_command = execute_terminal_command
        self._execute_auto_command = execute_auto_command
        self._queue_background_task = queue_background_task
        self._bootstrap_session = bootstrap_session

        # Initialize the inbound queue manager singleton with delivery wired to this service's deps.
        from teleclaude.core.inbound_queue import init_inbound_queue_manager

        init_inbound_queue_manager(
            functools.partial(deliver_inbound, client=client, start_polling=start_polling),
            force=True,
        )

    async def create_session(self, cmd: CreateSessionCommand) -> dict[str, str]:
        return await create_session(
            cmd,
            self.client,
            self._execute_auto_command,
            self._queue_background_task,
            self._bootstrap_session,
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

    async def close_session(self, cmd: CloseSessionCommand) -> None:
        await close_session(cmd, self.client)

    async def end_session(self, cmd: CloseSessionCommand) -> EndSessionHandlerResult:
        return await end_session(cmd, self.client)

    async def run_slash_command(
        self,
        command: SlashCommand,
        project_path: str,
        *,
        detach: bool = True,
        thinking_mode: str = "slow",
        agent: str = "claude",
    ) -> dict[str, str]:
        """Spawn a new agent session for a slash command without a caller session identity.

        Used for daemon-internal spawning (e.g. integration_bridge) where no
        human caller session is available.  The session_metadata is derived from
        COMMAND_ROLE_MAP so auth can identify system_role and job.
        """
        from teleclaude.core.command_mapper import CommandMapper
        from teleclaude.core.models import MessageMetadata, SessionMetadata
        from teleclaude.core.origins import InputOrigin

        role_info = COMMAND_ROLE_MAP.get(command)
        session_meta = (
            SessionMetadata(system_role=role_info[0], job=role_info[1].value) if role_info else None
        )
        full_command = f"/{command.value}"
        auto_command = f"agent_then_message {agent} {thinking_mode} {shlex.quote(full_command)}"
        metadata = MessageMetadata(
            origin=InputOrigin.API.value,
            title=full_command,
            project_path=project_path,
            session_metadata=session_meta,
            auto_command=auto_command,
        )
        cmd = CommandMapper.map_api_input(
            "new_session",
            {"skip_listener_registration": detach},
            metadata,
        )
        return await self.create_session(cmd)
