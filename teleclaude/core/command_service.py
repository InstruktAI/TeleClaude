"""Explicit command execution service for TeleClaude.

Commands are typed inputs that map directly to handler functions.
This service wires required dependencies without using a generic dispatcher.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable

from teleclaude.core.command_handlers import (
    EndSessionHandlerResult,
    SessionDataPayload,
    agent_restart,
    close_session,
    end_session,
    get_session_data,
    handle_file,
    handle_voice,
    keys,
    resume_agent,
    run_agent_command,
    send_message,
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
    RestartAgentCommand,
    ResumeAgentCommand,
    RunAgentCommand,
    SendMessageCommand,
    StartAgentCommand,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient


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
        client: "AdapterClient",
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

    async def create_session(self, cmd: CreateSessionCommand) -> dict[str, str]:
        return await create_session(
            cmd,
            self.client,
            self._execute_auto_command,
            self._queue_background_task,
            self._bootstrap_session,
        )

    async def send_message(self, cmd: SendMessageCommand) -> None:
        await send_message(cmd, self.client, self._start_polling)

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

    async def restart_agent(self, cmd: RestartAgentCommand) -> None:
        await agent_restart(cmd, self.client, self._execute_terminal_command)

    async def run_agent_command(self, cmd: RunAgentCommand) -> None:
        await run_agent_command(cmd, self.client, self._execute_terminal_command)

    async def get_session_data(self, cmd: GetSessionDataCommand) -> SessionDataPayload:
        return await get_session_data(cmd)

    async def close_session(self, cmd: CloseSessionCommand) -> None:
        await close_session(cmd, self.client)

    async def end_session(self, cmd: CloseSessionCommand) -> EndSessionHandlerResult:
        return await end_session(cmd, self.client)
