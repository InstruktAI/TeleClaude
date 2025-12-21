"""MCP server for TeleClaude multi-computer communication."""

import asyncio
import json
import os
import shlex
import types
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Optional, cast

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from instrukt_ai_logging import get_logger
from mcp.server import Server
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, TextContent, Tool

from teleclaude.adapters.redis_adapter import RedisAdapter
from teleclaude.config import config
from teleclaude.constants import MCP_SOCKET_PATH
from teleclaude.core import command_handlers
from teleclaude.core.db import db
from teleclaude.core.events import AgentHookEvents, CommandEventContext, TeleClaudeEvents
from teleclaude.core.models import MessageMetadata, RunAgentCommandArgs, StartSessionArgs
from teleclaude.core.session_listeners import register_listener, unregister_listener

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)


def _is_client_disconnect_exception(exc: BaseException) -> bool:
    """Return True if the exception indicates the client went away."""
    if isinstance(exc, ExceptionGroup):
        return all(_is_client_disconnect_exception(inner) for inner in exc.exceptions)
    return isinstance(
        exc,
        (
            ConnectionResetError,
            BrokenPipeError,
            anyio.ClosedResourceError,
            anyio.EndOfStream,
        ),
    )


class TeleClaudeMCPServer:
    """MCP server for exposing TeleClaude functionality to AI Agent.

    Uses AdapterClient for all AI-to-AI communication via transport adapters.
    """

    def __init__(
        self,
        adapter_client: "AdapterClient",
        terminal_bridge: types.ModuleType,
    ):
        # config already imported

        self.client = adapter_client
        self.terminal_bridge = terminal_bridge

        self.computer_name = config.computer.name

    def _is_local_computer(self, computer: str) -> bool:
        """Check if the target computer refers to the local machine.

        Args:
            computer: Target computer name (or "local"/self.computer_name)

        Returns:
            True if computer refers to local machine
        """
        return computer in ("local", self.computer_name)

    async def _maybe_register_listener(self, target_session_id: str, caller_session_id: str | None = None) -> None:
        """Register caller as listener for target session's stop event if possible.

        Called on any contact with a session (start, send_message, get_session_data)
        so observers who tap in later also receive stop notifications.

        Args:
            target_session_id: The session to listen to
            caller_session_id: The caller's session ID (required for listener registration)
        """
        if not caller_session_id:
            return

        # Prevent self-subscription (would cause notification loops)
        if target_session_id == caller_session_id:
            return

        try:
            caller_session = await db.get_session(caller_session_id)
            if caller_session:
                register_listener(
                    target_session_id=target_session_id,
                    caller_session_id=caller_session_id,
                    caller_tmux_session=caller_session.tmux_session_name,
                )
        except RuntimeError:
            # Database not initialized (e.g., in tests)
            pass

    def _setup_tools(self, server: Server) -> None:
        """Register MCP tools with the server."""

        @server.list_tools()  # type: ignore
        async def list_tools() -> list[Tool]:  # pyright: ignore[reportUnusedFunction]
            """List available MCP tools."""
            return [
                Tool(
                    name="teleclaude__help",
                    title="TeleClaude: Help",
                    description="Return a short, human-readable description of TeleClaude capabilities and local helper scripts.",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="teleclaude__list_computers",
                    title="TeleClaude: List Computers",
                    description=(
                        "List all available TeleClaude computers in the network with detailed information: "
                        "role, system stats (memory, disk, CPU), and active sessions. "
                        "Optionally filter by specific computer names."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "computer_names": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional: Only return these computers (e.g., ['raspi', 'macbook'])",
                            },
                        },
                    },
                ),
                Tool(
                    name="teleclaude__list_projects",
                    title="TeleClaude: List Projects",
                    description=(
                        "**CRITICAL: Call this FIRST before teleclaude__start_session** "
                        "List available project directories on a target computer (from trusted_dirs config). "
                        "Returns structured data with name, desc, and location for each directory. "
                        "Use the 'location' field in teleclaude__start_session. "
                        "Always use this to discover and match the correct project before starting a session."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "computer": {
                                "type": "string",
                                "description": "Target computer name (e.g., 'workstation', 'server')",
                            }
                        },
                        "required": ["computer"],
                    },
                ),
                Tool(
                    name="teleclaude__list_sessions",
                    title="TeleClaude: List Sessions",
                    description=(
                        "List active sessions from local or remote computer(s). "
                        "Defaults to local sessions only. Set computer=None to query ALL computers, "
                        "or computer='name' to query a specific remote computer."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "computer": {
                                "type": ["string", "null"],
                                "description": (
                                    "Which computer(s) to query: "
                                    "'local' (default) = this computer only, "
                                    "None = all computers, "
                                    "'name' = specific remote computer"
                                ),
                                "default": "local",
                            }
                        },
                    },
                ),
                Tool(
                    name="teleclaude__start_session",
                    title="TeleClaude: Start Session",
                    description=(
                        "Start a new session (Claude, Gemini, or Codex) on a remote computer in a specific project. "
                        "**REQUIRED WORKFLOW:** "
                        "1) Call teleclaude__list_projects FIRST to discover available projects "
                        "2) Match and select the correct project from the results "
                        "3) Use the exact project path from list_projects in the project_dir parameter here. "
                        "Returns session_id. Wait 10 seconds then use teleclaude__get_session_data to check progress. "
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "computer": {
                                "type": "string",
                                "description": "Target computer name (e.g., 'workstation', 'server')",
                            },
                            "agent": {
                                "type": "string",
                                "enum": ["claude", "gemini", "codex"],
                                "default": "claude",
                                "description": "Which AI agent to start in the session. Defaults to 'claude'.",
                            },
                            "thinking_mode": {
                                "type": "string",
                                "description": (
                                    "Model tier: 'fast' (cheapest), 'med' (balanced), 'slow' (most capable). "
                                    "Default: slow"
                                ),
                                "enum": ["fast", "med", "slow"],
                                "default": "slow",
                            },
                            "project_dir": {
                                "type": "string",
                                "description": (
                                    "**MUST come from teleclaude__list_projects output** "
                                    "Absolute path to project directory (e.g., '/home/user/apps/TeleClaude'). "
                                    "Do NOT guess or construct paths - always use teleclaude__list_projects first."
                                ),
                            },
                            "title": {
                                "type": "string",
                                "description": (
                                    "Session title describing the task (e.g., 'Debug auth flow', 'Review PR #123'). "
                                    "Use 'TEST: {description}' prefix for testing sessions."
                                ),
                            },
                            "message": {
                                "type": "string",
                                "description": (
                                    "The initial task or prompt to send to the agent "
                                    "(e.g., 'Read README and summarize', 'Trace message flow from Telegram to session'). "
                                    "Session starts immediately processing this message."
                                ),
                            },
                        },
                        "required": ["computer", "project_dir", "title", "message"],
                    },
                ),
                Tool(
                    name="teleclaude__send_message",
                    title="TeleClaude: Send Message",
                    description=(
                        "Send message to an existing AI Agent session. "
                        "Use teleclaude__list_sessions to find session IDs. "
                        "For slash commands, prefer teleclaude__run_agent_command instead."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "computer": {
                                "type": "string",
                                "description": "Target computer name. Use 'local' for sessions on this computer.",
                            },
                            "session_id": {
                                "type": "string",
                                "description": (
                                    "Target session ID (from teleclaude__list_sessions or teleclaude__start_session)"
                                ),
                            },
                            "message": {
                                "type": "string",
                                "description": "Message or command to send to Claude Code",
                            },
                        },
                        "required": ["computer", "session_id", "message"],
                    },
                ),
                Tool(
                    name="teleclaude__run_agent_command",
                    title="TeleClaude: Run Agent Command",
                    description=(
                        "Run a slash command on an AI agent session. "
                        "Two modes: (1) If session_id provided, sends command to existing session. "
                        "(2) If session_id not provided, starts a new session with the command. "
                        "Supports all agent types (Claude, Gemini, Codex) and worktree subfolders. "
                        "Commands are for AI slash commands (e.g., 'compact', 'next-work'), not shell commands."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "computer": {
                                "type": "string",
                                "description": "Target computer name",
                            },
                            "command": {
                                "type": "string",
                                "description": (
                                    "Command name without leading / (e.g., 'next-work', 'compact', 'help')"
                                ),
                            },
                            "args": {
                                "type": "string",
                                "description": "Optional arguments for the command",
                                "default": "",
                            },
                            "session_id": {
                                "type": "string",
                                "description": (
                                    "Optional: send command to existing session. "
                                    "If omitted, starts a new session with the command."
                                ),
                            },
                            "project": {
                                "type": "string",
                                "description": (
                                    "Project directory path. Required when starting new session (no session_id). "
                                    "Use teleclaude__list_projects to discover available projects."
                                ),
                            },
                            "agent": {
                                "type": "string",
                                "enum": ["claude", "gemini", "codex"],
                                "default": "claude",
                                "description": "Agent type for new sessions. Default: claude",
                            },
                            "thinking_mode": {
                                "type": "string",
                                "description": (
                                    "Model tier: 'fast' (cheapest), 'med' (balanced), 'slow' (most capable). "
                                    "Default: slow"
                                ),
                                "enum": ["fast", "med", "slow"],
                                "default": "slow",
                            },
                            "subfolder": {
                                "type": "string",
                                "description": (
                                    "Optional subfolder within project (e.g., 'worktrees/my-feature'). "
                                    "Working directory becomes project/subfolder."
                                ),
                                "default": "",
                            },
                        },
                        "required": ["computer", "command"],
                    },
                ),
                Tool(
                    name="teleclaude__get_session_data",
                    title="TeleClaude: Get Session Data",
                    description=(
                        "Retrieve session data from a remote computer's Claude Code session. "
                        "Reads from the claude_session_file which contains complete session history. "
                        "By default returns last 5000 chars. Use timestamp filters to scrub through history. "
                        "**Use this to check on delegated work** after teleclaude__send_message. "
                        "**Replaces**: teleclaude__get_session_status (use this instead for new code). "
                        "**Supervising Worker AI Sessions:** When managing/monitoring another AI session, "
                        "use `tail_chars=0` to see the FULL decision trail - not just recent output. "
                        "You need to observe: what choices the AI made and why, whether it followed the proper workflow, "
                        "if it took shortcuts or blamed external factors, the reasoning behind implementation decisions. "
                        "The tail only shows recent activity. Full transcript reveals the decision-making process "
                        "throughout the entire session."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "computer": {
                                "type": "string",
                                "description": "Target computer name where session is running",
                            },
                            "session_id": {
                                "type": "string",
                                "description": "Session ID to retrieve data for",
                            },
                            "since_timestamp": {
                                "type": "string",
                                "description": (
                                    "Optional ISO 8601 UTC timestamp. "
                                    "Returns only messages since this time. "
                                    "Example: '2025-11-28T10:30:00Z'"
                                ),
                            },
                            "until_timestamp": {
                                "type": "string",
                                "description": (
                                    "Optional ISO 8601 UTC timestamp. "
                                    "Returns only messages until this time. "
                                    "Use with since_timestamp to get a time window."
                                ),
                            },
                            "tail_chars": {
                                "type": "integer",
                                "description": (
                                    "Max characters to return from end of transcript. "
                                    "Default: 5000. Set to 0 for unlimited (full transcript)."
                                ),
                            },
                        },
                        "required": ["computer", "session_id"],
                    },
                ),
                Tool(
                    name="teleclaude__deploy",
                    title="TeleClaude: Deploy",
                    description=(
                        "Deploy latest code to remote computers (git pull + restart). "
                        "Provide an optional list of computers; if omitted or empty, "
                        "deploys to all remote computers except self. "
                        "Use this after committing changes to update machines. "
                        "**Workflow**: commit changes → push to GitHub → call this tool. "
                        "Returns deployment status for each computer (success, deploying, error)."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "computers": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional list of target computers. Omit/empty for all remotes.",
                            },
                        },
                    },
                ),
                Tool(
                    name="teleclaude__send_file",
                    title="TeleClaude: Send File",
                    description=(
                        "Send a file to the specified TeleClaude session. "
                        "Use this to send files for download (logs, reports, screenshots, etc.). "
                        "Get session_id from TELECLAUDE_SESSION_ID environment variable."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "TeleClaude session UUID (from TELECLAUDE_SESSION_ID env var)",
                            },
                            "file_path": {
                                "type": "string",
                                "description": "Absolute path to file to send",
                            },
                            "caption": {
                                "type": "string",
                                "description": "Optional caption for the file",
                            },
                        },
                        "required": ["session_id", "file_path"],
                    },
                ),
                Tool(
                    name="teleclaude__stop_notifications",
                    title="TeleClaude: Stop Notifications",
                    description=(
                        "Unsubscribe from a session's stop/notification events without ending it. "
                        "Removes the caller's listener for the target session. "
                        "The target session continues running, but the caller no longer receives events from it. "
                        "Use this when a master AI no longer needs to monitor a specific worker session."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "computer": {
                                "type": "string",
                                "description": "Target computer name. Use 'local' for sessions on this computer.",
                            },
                            "session_id": {
                                "type": "string",
                                "description": "Session ID to stop receiving notifications from",
                            },
                        },
                        "required": ["computer", "session_id"],
                    },
                ),
                Tool(
                    name="teleclaude__end_session",
                    title="TeleClaude: End Session",
                    description=(
                        "Gracefully end a Claude Code session (local or remote). "
                        "Kills the tmux session, marks it closed in database, and cleans up all resources "
                        "(listeners, workspace directories, channels). "
                        "Use this when a master AI wants to terminate a worker session that has completed its work "
                        "or needs to be replaced (e.g., due to context exhaustion)."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "computer": {
                                "type": "string",
                                "description": "Target computer name. Use 'local' for sessions on this computer.",
                            },
                            "session_id": {
                                "type": "string",
                                "description": "Session ID to end",
                            },
                        },
                        "required": ["computer", "session_id"],
                    },
                ),
                Tool(
                    name="teleclaude__handle_agent_event",
                    title="TeleClaude: Handle Agent Event",
                    description=(
                        "Emit Agent events to registered listeners. "
                        "USED BY HOOKS, AND FOR INTERNAL USE ONLY, so do not call yourself."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "TeleClaude session UUID",
                            },
                            "event_type": {
                                "type": "string",
                                "description": "Type of Agent event (e.g., 'stop', 'compact')",
                            },
                            "data": {
                                "type": "object",
                                "description": "Event-specific data",
                            },
                        },
                        "required": ["session_id", "event_type", "data"],
                    },
                ),
            ]

        @server.call_tool()  # type: ignore
        async def call_tool(  # pyright: ignore[reportUnusedFunction]
            name: str, arguments: dict[str, object]
        ) -> list[TextContent]:
            """Handle tool calls.

            Context variables (injected by mcp-wrapper.py from tmux env):
            - caller_session_id: The calling session's ID for notifications/prefixes

            These are extracted once here and passed to handlers that need them,
            keeping context handling centralized.
            """
            # Extract context (injected by wrapper) - handlers don't need to parse this
            caller_session_id = str(arguments.pop("caller_session_id")) if arguments.get("caller_session_id") else None

            if name == "teleclaude__handle_agent_event":
                event_type = str(arguments.get("event_type", "")) if arguments else ""
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                logger.debug(
                    "MCP tool call",
                    tool=name,
                    session=session_id[:8],
                    event=event_type,
                    caller=caller_session_id,
                )
            else:
                logger.trace("MCP tool call", tool=name, caller=caller_session_id)
            if name == "teleclaude__help":
                text = (
                    "TeleClaude MCP Server\n"
                    "\n"
                    "Local helper scripts:\n"
                    "- `bin/notify_agents.py`: out-of-band Telegram alerts with exponential backoff (max 1/hour). "
                    "State is stored in `logs/monitoring/`.\n"
                    "- `bin/send_telegram.py`: Telegram Bot API sender (`sendMessage`). "
                    "Supports `--chat-id` for direct IDs and `--to` for @username/display-name resolution "
                    "if a local Telegram user session is configured.\n"
                )
                return [TextContent(type="text", text=text)]
            if name == "teleclaude__list_computers":
                # Extract optional filter (currently unused by implementation)
                # computer_names_obj = arguments.get("computer_names") if arguments else None
                # computer_names = None
                # if computer_names_obj and isinstance(computer_names_obj, list):
                #     computer_names = [str(c) for c in computer_names_obj]

                computers = await self.teleclaude__list_computers()
                return [TextContent(type="text", text=json.dumps(computers, default=str, indent=2))]
            if name == "teleclaude__list_projects":
                computer = str(arguments.get("computer", "")) if arguments else ""
                projects = await self.teleclaude__list_projects(computer)
                return [TextContent(type="text", text=json.dumps(projects, default=str))]
            elif name == "teleclaude__list_sessions":
                computer_obj = arguments.get("computer", "local") if arguments else "local"
                computer: str | None = None if computer_obj is None else str(computer_obj)
                sessions = await self.teleclaude__list_sessions(computer)
                return [TextContent(type="text", text=json.dumps(sessions, default=str))]
            elif name == "teleclaude__start_session":
                start_args = StartSessionArgs.from_mcp(arguments or {}, caller_session_id)
                result = await self.teleclaude__start_session(**start_args.__dict__)
                return [TextContent(type="text", text=json.dumps(result, default=str))]
            elif name == "teleclaude__send_message":
                # Extract arguments explicitly
                computer = str(arguments.get("computer", "")) if arguments else ""
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                message = str(arguments.get("message", "")) if arguments else ""
                # caller_session_id extracted at top of call_tool for AI-to-AI message prefix
                # Collect all chunks from async generator
                chunks: list[str] = []
                async for chunk in self.teleclaude__send_message(computer, session_id, message, caller_session_id):
                    chunks.append(chunk)
                result_text = "".join(chunks)
                return [TextContent(type="text", text=result_text)]
            elif name == "teleclaude__run_agent_command":
                run_args = RunAgentCommandArgs.from_mcp(arguments or {}, caller_session_id)
                result = await self.teleclaude__run_agent_command(**run_args.__dict__)
                return [TextContent(type="text", text=json.dumps(result, default=str))]
            elif name == "teleclaude__get_session_data":
                computer = str(arguments.get("computer", "")) if arguments else ""
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                since_timestamp_obj = arguments.get("since_timestamp") if arguments else None
                since_timestamp = str(since_timestamp_obj) if since_timestamp_obj else None
                until_timestamp_obj = arguments.get("until_timestamp") if arguments else None
                until_timestamp = str(until_timestamp_obj) if until_timestamp_obj else None
                tail_chars_obj = arguments.get("tail_chars") if arguments else None
                if isinstance(tail_chars_obj, (int, str)):
                    tail_chars = int(tail_chars_obj)
                else:
                    tail_chars = 5000
                # caller_session_id extracted at top of call_tool for stop notifications (observer pattern)
                result = await self.teleclaude__get_session_data(
                    computer,
                    session_id,
                    since_timestamp,
                    until_timestamp,
                    tail_chars,
                    caller_session_id,
                )
                return [TextContent(type="text", text=json.dumps(result, default=str))]
            elif name == "teleclaude__deploy":
                computers_obj = arguments.get("computers") if arguments else None
                target_computers: list[str] | None = None
                if isinstance(computers_obj, list):
                    target_computers = [c for c in computers_obj if isinstance(c, str)]
                deploy_result: dict[str, dict[str, object]] = await self.teleclaude__deploy(target_computers)
                return [TextContent(type="text", text=json.dumps(deploy_result, default=str))]
            elif name == "teleclaude__send_file":
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                file_path = str(arguments.get("file_path", "")) if arguments else ""
                caption_obj = arguments.get("caption") if arguments else None
                caption = str(caption_obj) if caption_obj else None
                result_text = await self.teleclaude__send_file(session_id, file_path, caption)
                return [TextContent(type="text", text=result_text)]
            elif name == "teleclaude__stop_notifications":
                computer = str(arguments.get("computer", "")) if arguments else ""
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                # caller_session_id extracted at top of call_tool for listener unregistration
                result = await self.teleclaude__stop_notifications(computer, session_id, caller_session_id)
                return [TextContent(type="text", text=json.dumps(result, default=str))]
            elif name == "teleclaude__end_session":
                computer = str(arguments.get("computer", "")) if arguments else ""
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                result = await self.teleclaude__end_session(computer, session_id)
                return [TextContent(type="text", text=json.dumps(result, default=str))]
            elif name == "teleclaude__handle_agent_event":
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                event_type = str(arguments.get("event_type", "")) if arguments else ""
                data_obj = arguments.get("data") if arguments else None
                data = dict(data_obj) if isinstance(data_obj, dict) else {}
                result_text = await self.teleclaude__handle_agent_event(session_id, event_type, data)
                return [TextContent(type="text", text=result_text)]
            else:
                raise ValueError(f"Unknown tool: {name}")

    async def start(self) -> None:
        """Start MCP server on Unix socket."""
        socket_path_str = os.path.expandvars(MCP_SOCKET_PATH)
        socket_path = Path(socket_path_str)

        # Remove existing socket file if present
        if socket_path.exists():
            socket_path.unlink()

        logger.info("MCP server listening on socket: %s", socket_path)

        # Create Unix socket server
        server = await asyncio.start_unix_server(
            lambda r, w: asyncio.create_task(self._handle_socket_connection(r, w)),
            path=str(socket_path),
        )

        # Make socket accessible (owner only)
        socket_path.chmod(0o600)

        async with server:
            await server.serve_forever()

    async def _handle_socket_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle a single MCP client connection over Unix socket."""
        logger.debug("New MCP client connected")
        try:
            # Create FRESH server instance for this connection
            # This ensures clean state (no stale initialization)
            server = Server("teleclaude")
            self._setup_tools(server)

            # Create memory streams like stdio_server does
            read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]
            read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
            write_stream: MemoryObjectSendStream[SessionMessage]
            write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

            read_stream_writer, read_stream = cast(
                tuple[
                    MemoryObjectSendStream[SessionMessage | Exception],
                    MemoryObjectReceiveStream[SessionMessage | Exception],
                ],
                anyio.create_memory_object_stream(0),
            )
            write_stream, write_stream_reader = cast(
                tuple[
                    MemoryObjectSendStream[SessionMessage],
                    MemoryObjectReceiveStream[SessionMessage],
                ],
                anyio.create_memory_object_stream(0),
            )

            async def socket_reader() -> None:
                """Read from socket and parse JSON-RPC messages."""
                try:
                    async with read_stream_writer:
                        while True:
                            line = await reader.readline()
                            if not line:
                                break
                            try:
                                message = JSONRPCMessage.model_validate_json(line.decode("utf-8"))
                                dump = message.model_dump()
                                method = dump.get("method")
                                if method != "notifications/initialized":
                                    logger.trace(
                                        "MCP reader received: method=%s id=%s",
                                        method,
                                        dump.get("id"),
                                    )
                                await read_stream_writer.send(SessionMessage(message))
                            except Exception as exc:
                                await read_stream_writer.send(exc)
                except anyio.ClosedResourceError:
                    pass

            async def socket_writer() -> None:
                """Write JSON-RPC messages to socket."""
                try:
                    async with write_stream_reader:
                        async for session_message in write_stream_reader:
                            json_str = session_message.message.model_dump_json(by_alias=True, exclude_none=True)
                            writer.write((json_str + "\n").encode("utf-8"))
                            await writer.drain()
                except anyio.ClosedResourceError:
                    pass

            # Run socket I/O and MCP server concurrently
            async with anyio.create_task_group() as tg:
                tg.start_soon(socket_reader)
                tg.start_soon(socket_writer)
                try:
                    await server.run(
                        read_stream,
                        write_stream,
                        server.create_initialization_options(),
                    )
                except (
                    anyio.ClosedResourceError,
                    anyio.EndOfStream,
                    ConnectionResetError,
                    BrokenPipeError,
                ):
                    logger.debug("MCP client disconnected (stream closed)")
                except Exception as e:
                    if _is_client_disconnect_exception(e):
                        logger.debug("MCP client disconnected (task group closed)")
                    else:
                        logger.warning("MCP server session ended with error: %s", e)

        except Exception:
            logger.exception("Error handling MCP connection")
        finally:
            writer.close()
            await writer.wait_closed()
            logger.debug("MCP client disconnected")

    async def teleclaude__list_computers(self) -> list[dict[str, object]]:
        """List available computers including local and remote.

        Returns:
            List of computers with their info (role, system_stats, etc.)
            Local computer is always first in the list.
        """
        logger.debug("teleclaude__list_computers() called")

        # Get local computer info
        local_info = await command_handlers.handle_get_computer_info()
        local_computer: dict[str, object] = {
            "name": self.computer_name,
            "status": "local",
            "last_seen": datetime.now(),
            "adapter_type": "local",
            "user": local_info.get("user"),
            "host": local_info.get("host"),
            "role": local_info.get("role"),
            "system_stats": local_info.get("system_stats"),
        }

        # Get remote peers
        remote_peers: list[dict[str, object]] = await self.client.discover_peers()

        # Combine: local first, then remotes
        result = [local_computer] + remote_peers
        logger.debug("teleclaude__list_computers() returning %d computers", len(result))
        return result

    async def teleclaude__list_projects(self, computer: str) -> list[dict[str, str]]:
        """List available projects on target computer with metadata.

        For local computer: Reads trusted_dirs from config directly.
        For remote computers: Sends request via Redis transport.

        Args:
            computer: Target computer name (or "local"/self.computer_name)

        Returns:
            List of dicts with keys: name, desc, location
        """
        if self._is_local_computer(computer):
            return await self._list_local_projects()
        return await self._list_remote_projects(computer)

    async def _list_local_projects(self) -> list[dict[str, str]]:
        """List projects from local config directly."""
        return await command_handlers.handle_list_projects()

    async def _list_remote_projects(self, computer: str) -> list[dict[str, str]]:
        """List projects from remote computer via Redis.

        Args:
            computer: Target computer name

        Returns:
            List of dicts with keys: name, desc, location
        """
        # Validate computer is online
        peers = await self.client.discover_peers()
        target_online = any(p["name"] == computer and p["status"] == "online" for p in peers)

        if not target_online:
            logger.warning("Computer %s not online, skipping list_projects", computer)
            return []

        # Send list_projects command via AdapterClient
        message_id = await self.client.send_request(
            computer_name=computer, command="list_projects", metadata=MessageMetadata()
        )
        logger.debug("Request sent with message_id=%s, reading response...", message_id[:15])

        # Read response from AdapterClient (one-shot, not streaming)
        try:
            response_data = await self.client.read_response(message_id, timeout=3.0)
            envelope = json.loads(response_data.strip())

            # Handle error response
            if envelope.get("status") == "error":
                error_msg = envelope.get("error", "Unknown error")
                logger.error("list_projects failed on %s: %s", computer, error_msg)
                return []

            # Extract projects list from success envelope
            data = envelope.get("data", [])
            if not isinstance(data, list):
                logger.warning("Unexpected data format from %s: %s", computer, type(data).__name__)
                return []
            return list(data)  # Type assertion for mypy

        except TimeoutError:
            logger.error("Timeout waiting for list_projects response from %s", computer)
            return []
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON response from %s: %s", computer, e)
            return []

    async def teleclaude__start_session(
        self,
        computer: str,
        project_dir: str,
        title: str,
        message: str,
        caller_session_id: str | None = None,
        agent: str = "claude",
        thinking_mode: str = "slow",
    ) -> dict[str, object]:
        """Create session on local or remote computer.

        For local computer: Creates session directly via handle_event.
        For remote computers: Sends request via Redis transport.

        Args:
            computer: Target computer name (from teleclaude__list_computers, or "local"/self.computer_name)
            project_dir: Absolute path to project directory on target computer
                (from teleclaude__list_projects)
            title: Session title describing the task (use "TEST: {description}" for testing sessions)
            message: Initial task or prompt to send to the agent
            caller_session_id: Optional caller's session ID for completion notifications
            agent: Which AI agent to start ('claude', 'gemini', 'codex'). Defaults to 'claude'.
            thinking_mode: Model tier ('fast', 'med', 'slow'). Defaults to 'slow'.

        Returns:
            dict with session_id and status
        """
        if self._is_local_computer(computer):
            return await self._start_local_session(project_dir, title, message, caller_session_id, agent, thinking_mode)
        return await self._start_remote_session(
            computer, project_dir, title, message, caller_session_id, agent, thinking_mode
        )

    async def _start_local_session(
        self,
        project_dir: str,
        title: str,
        message: str,
        caller_session_id: str | None = None,
        agent: str = "claude",
        thinking_mode: str = "slow",
    ) -> dict[str, object]:
        """Create session on local computer directly via handle_event.

        Args:
            project_dir: Absolute path to project directory
            title: Session title
            message: Initial prompt for agent
            caller_session_id: Optional caller's session ID for completion notifications
            agent: Agent to start ('claude', 'gemini', 'codex')

        Returns:
            dict with session_id and status
        """
        # Emit NEW_SESSION event - daemon's handle_event will call handle_create_session
        # Include channel_metadata with target_computer to identify this as AI-to-AI session
        # (for remote sessions, Redis transport auto-injects "initiator" field)
        result: object = await self.client.handle_event(
            TeleClaudeEvents.NEW_SESSION,
            {"session_id": "", "args": [title]},
            MessageMetadata(
                adapter_type="redis",
                project_dir=project_dir,
                title=title,
                channel_metadata={"target_computer": self.computer_name},
            ),
        )

        # handle_event returns {"status": "success", "data": {"session_id": "..."}}
        if not isinstance(result, dict) or result.get("status") != "success":
            error_msg = result.get("error", "Unknown error") if isinstance(result, dict) else "Session creation failed"
            return {
                "status": "error",
                "message": f"Local session creation failed: {error_msg}",
            }

        data: object = result.get("data", {})
        session_id: str | None = data.get("session_id") if isinstance(data, dict) else None

        if not session_id:
            return {
                "status": "error",
                "message": "Local session did not return session_id",
            }

        logger.info("Local session created: %s", session_id[:8])

        # Preserve caller ID only for listener registration/notifications
        effective_caller_id = caller_session_id or os.environ.get("TELECLAUDE_SESSION_ID", "unknown")

        # Register listener so we get notified when target session stops
        await self._maybe_register_listener(
            session_id,
            effective_caller_id if effective_caller_id != "unknown" else None,
        )

        # Determine which event to fire based on agent (now always AGENT_START)
        # Send command with prefixed message to start the agent
        await self.client.handle_event(
            TeleClaudeEvents.AGENT_START,
            {"session_id": session_id, "args": [agent, thinking_mode, message]},
            MessageMetadata(adapter_type="redis"),
        )
        logger.debug("Sent AGENT_START command with message to local session %s", session_id[:8])

        return {"session_id": session_id, "status": "success"}

    async def _start_remote_session(
        self,
        computer: str,
        project_dir: str,
        title: str,
        message: str,
        caller_session_id: str | None = None,
        agent: str = "claude",
        thinking_mode: str = "slow",
    ) -> dict[str, object]:
        """Create session on remote computer via Redis transport.

        Args:
            computer: Target computer name
            project_dir: Absolute path to project directory on remote computer
            title: Session title
            message: Initial prompt for agent
            caller_session_id: Optional caller's session ID for completion notifications
            agent: Agent to start ('claude', 'gemini', 'codex')

        Returns:
            dict with session_id and status
        """
        # Validate computer is online - fail fast if not
        peers = await self.client.discover_peers()
        target_online = any(p["name"] == computer and p["status"] == "online" for p in peers)

        if not target_online:
            return {"status": "error", "message": f"Computer '{computer}' is offline"}

        # Send new_session command to remote - uses standardized handle_create_session
        # Transport layer generates request_id from Redis message ID
        # Only pass claude_model if agent is claude (as it's stored in session)
        metadata = MessageMetadata(
            project_dir=project_dir,
            title=title,
        )

        message_id = await self.client.send_request(
            computer_name=computer,
            command="/new_session",
            metadata=metadata,
        )

        # Wait for response with remote session_id
        try:
            response_data = await self.client.read_response(message_id, timeout=5.0)
            envelope = json.loads(response_data.strip())

            # Handle error response
            if envelope.get("status") == "error":
                error_msg = envelope.get("error", "Unknown error")
                return {
                    "status": "error",
                    "message": f"Remote session creation failed: {error_msg}",
                }

            # Extract session_id from success response
            data = envelope.get("data", {})
            remote_session_id = data.get("session_id") if isinstance(data, dict) else None

            if not remote_session_id:
                return {
                    "status": "error",
                    "message": "Remote did not return session_id",
                }

            logger.info("Remote session created: %s on %s", remote_session_id[:8], computer)

            # Now send /cd command if project_dir provided
            if project_dir:
                await self.client.send_request(
                    computer_name=computer,
                    command=f"/cd {project_dir}",
                    metadata=MessageMetadata(),
                    session_id=str(remote_session_id),
                )
                logger.debug("Sent /cd command to remote session %s", remote_session_id[:8])

            # Preserve caller ID only for listener registration/notifications
            effective_caller_id = caller_session_id or os.environ.get("TELECLAUDE_SESSION_ID", "unknown")

            # Register listener so we get notified when target session stops
            # Note: For remote sessions, the Stop event comes via Redis transport
            logger.debug(
                "Attempting listener registration: caller=%s, target=%s",
                effective_caller_id[:8] if effective_caller_id != "unknown" else "unknown",
                str(remote_session_id)[:8],
            )
            if effective_caller_id != "unknown":
                try:
                    caller_session = await db.get_session(effective_caller_id)
                    logger.debug(
                        "Database lookup for caller %s: found=%s",
                        effective_caller_id[:8],
                        caller_session is not None,
                    )
                    if caller_session:
                        register_listener(
                            target_session_id=str(remote_session_id),
                            caller_session_id=effective_caller_id,
                            caller_tmux_session=caller_session.tmux_session_name,
                        )
                        logger.info(
                            "Listener registered: caller=%s -> target=%s (tmux=%s)",
                            effective_caller_id[:8],
                            str(remote_session_id)[:8],
                            caller_session.tmux_session_name,
                        )
                    else:
                        logger.warning(
                            "Cannot register listener: caller session %s not found in database",
                            effective_caller_id[:8],
                        )
                except RuntimeError as e:
                    logger.warning("Database not initialized for listener registration: %s", e)
            else:
                logger.debug("Skipping listener registration: no caller_session_id")

            # Send agent start command with prefixed message
            # The remote handle_command expects: /agent {agent_name} {message}
            quoted_message = shlex.quote(message)
            await self.client.send_request(
                computer_name=computer,
                command=f"/{TeleClaudeEvents.AGENT_START} {agent} {thinking_mode} {quoted_message}",
                metadata=MessageMetadata(),
                session_id=str(remote_session_id),
            )
            logger.debug(
                "Sent AGENT_START command with message to remote session %s",
                remote_session_id[:8],
            )

            return {"session_id": remote_session_id, "status": "success"}

        except TimeoutError:
            return {
                "status": "error",
                "message": "Timeout waiting for remote session creation",
            }
        except Exception as e:
            logger.error("Failed to create remote session: %s", e)
            return {
                "status": "error",
                "message": f"Failed to create remote session: {str(e)}",
            }

    async def teleclaude__list_sessions(self, computer: Optional[str] = "local") -> list[dict[str, object]]:
        """List sessions from local or remote computer(s).

        For local computer: Queries local database directly.
        For remote computers: Sends request via Redis transport.
        For None: Aggregates sessions from ALL computers.

        Args:
            computer: Which computer(s) to query:
                - "local" or self.computer_name: Query local database only
                - None: Query ALL computers (local + remotes)
                - "name": Query specific remote computer via Redis

        Returns:
            List of session dicts with fields:
            - session_id: Session identifier
            - origin_adapter: Adapter that initiated session
            - title: Session title
            - working_directory: Current working directory
            - status: Session status (active/closed)
            - created_at: ISO timestamp
            - last_activity: ISO timestamp
            - computer: Computer name (included for all queries)
        """
        # None means query ALL computers
        if computer is None:
            return await self._list_all_sessions()

        # Local computer (handles both "local" and actual computer name)
        if self._is_local_computer(computer):
            return await self._list_local_sessions()

        # Specific remote computer
        return await self._list_remote_sessions(computer)

    async def _list_local_sessions(self) -> list[dict[str, object]]:
        """List sessions from local database directly."""
        sessions = await command_handlers.handle_list_sessions()
        # Add computer name for consistency
        for session in sessions:
            session["computer"] = self.computer_name
        return sessions

    async def _list_remote_sessions(self, computer: str) -> list[dict[str, object]]:
        """List sessions from a specific remote computer via Redis.

        Args:
            computer: Target remote computer name

        Returns:
            List of session dicts with computer field added
        """
        redis_adapter_base = self.client.adapters.get("redis")
        if not redis_adapter_base or not isinstance(redis_adapter_base, RedisAdapter):
            logger.warning("Redis adapter not available - cannot query remote sessions")
            return []
        redis_adapter: RedisAdapter = redis_adapter_base

        try:
            message_id = await redis_adapter.send_request(computer, "list_sessions", MessageMetadata())
            response_data = await self.client.read_response(message_id, timeout=3.0)
            sessions = json.loads(response_data.strip())

            # Add computer name to each session
            for session in sessions:
                session["computer"] = computer
            return sessions

        except (TimeoutError, Exception) as e:
            logger.warning("Failed to get sessions from %s: %s", computer, e)
            return []

    async def _list_all_sessions(self) -> list[dict[str, object]]:
        """List sessions from ALL computers (local + all remotes).

        Returns:
            Aggregated list of sessions from all online computers
        """
        all_sessions: list[dict[str, object]] = []

        # Start with local sessions
        local_sessions = await self._list_local_sessions()
        all_sessions.extend(local_sessions)

        # Get all online remote computers
        redis_adapter_base = self.client.adapters.get("redis")
        if not redis_adapter_base or not isinstance(redis_adapter_base, RedisAdapter):
            logger.warning("Redis adapter not available - returning local sessions only")
            return all_sessions
        redis_adapter: RedisAdapter = redis_adapter_base

        computers_to_query = await redis_adapter._get_online_computers()

        # Query each remote computer
        for computer_name in computers_to_query:
            remote_sessions = await self._list_remote_sessions(computer_name)
            all_sessions.extend(remote_sessions)

        return all_sessions

    async def teleclaude__send_message(
        self,
        computer: str,
        session_id: str,
        message: str,
        caller_session_id: str | None = None,
    ) -> AsyncIterator[str]:
        """Send message to an AI agent session.

        For local computer: Sends message directly via handle_event.
        For remote computers: Sends via Redis transport.

        Args:
            computer: Target computer name (or "local"/self.computer_name)
            session_id: Target session ID (from teleclaude__start_session)
            message: Message/command to send to the agent
            caller_session_id: Optional caller's session ID for listener registration

        Yields:
            str: Acknowledgment message
        """
        try:
            # Get caller's session_id for listener registration
            effective_caller_id = caller_session_id or os.environ.get("TELECLAUDE_SESSION_ID", "unknown")

            # Register as listener so we get notified when target session stops
            await self._maybe_register_listener(
                session_id,
                effective_caller_id if effective_caller_id != "unknown" else None,
            )

            is_local = self._is_local_computer(computer)

            if is_local:
                # Local session - send directly via handle_event
                await self.client.handle_event(
                    TeleClaudeEvents.MESSAGE,
                    {"session_id": session_id, "args": [], "text": message},
                    MessageMetadata(adapter_type="mcp"),
                )
            else:
                # Remote session - send via Redis transport
                await self.client.send_request(
                    computer_name=computer,
                    command=f"message {message}",
                    session_id=session_id,
                    metadata=MessageMetadata(),
                )

            yield (
                f"Message sent to session {session_id[:8]} on {computer}. "
                f"Use teleclaude__get_session_data to check for responses."
            )

        except Exception as e:
            logger.error("Failed to send message to session %s: %s", session_id[:8], e)
            yield f"[Error: Failed to send message: {str(e)}]"

    async def teleclaude__run_agent_command(
        self,
        computer: str,
        command: str,
        args: str = "",
        session_id: str | None = None,
        project: str | None = None,
        agent: str = "claude",
        subfolder: str = "",
        caller_session_id: str | None = None,
        thinking_mode: str = "slow",
    ) -> dict[str, object]:
        """Run a slash command on an AI agent session.

        Two modes of operation:
        1. If session_id is provided: Send command to existing session
        2. If session_id is not provided: Start new session with command

        Args:
            computer: Target computer name
            command: Command name (e.g., 'next-work', 'compact') - leading / stripped if present
            args: Optional arguments for the command
            session_id: Optional existing session ID to send command to
            project: Project directory (required when starting new session)
            agent: Agent type for new sessions ('claude', 'gemini', 'codex')
            thinking_mode: Model tier ('fast', 'med', 'slow') for the agent
            subfolder: Optional subfolder within project (e.g., 'worktrees/feat-x')
            caller_session_id: Caller's session ID for listener registration

        Returns:
            dict with session_id and status
        """
        # Normalize command and args
        normalized_cmd = command.lstrip("/")
        normalized_args = args.strip()

        # Build full command string
        full_command = f"/{normalized_cmd} {normalized_args}" if normalized_args else f"/{normalized_cmd}"

        if session_id:
            # Mode 1: Send command to existing session
            chunks: list[str] = []
            async for chunk in self.teleclaude__send_message(computer, session_id, full_command, caller_session_id):
                chunks.append(chunk)
            return {"status": "sent", "session_id": session_id, "message": "".join(chunks)}

        # Mode 2: Start new session with command
        if not project:
            return {"status": "error", "message": "project required when session_id not provided"}

        # Compute working directory
        working_dir = f"{project}/{subfolder}".rstrip("/") if subfolder.strip() else project

        # Use command as title
        title = full_command

        # Delegate to start_session
        result = await self.teleclaude__start_session(
            computer=computer,
            project_dir=working_dir,
            title=title,
            message=full_command,
            caller_session_id=caller_session_id,
            agent=agent,
            thinking_mode=thinking_mode,
        )
        return result

    async def teleclaude__get_session_data(
        self,
        computer: str,
        session_id: str,
        since_timestamp: Optional[str] = None,
        until_timestamp: Optional[str] = None,
        tail_chars: int = 5000,
        caller_session_id: Optional[str] = None,
    ) -> dict[str, object]:
        """Get session data from local or remote computer.

        For local computer: Reads claude_session_file directly.
        For remote computers: Sends request via Redis transport.

        Args:
            computer: Target computer name (or "local"/self.computer_name)
            session_id: Session ID on target computer
            since_timestamp: Optional ISO 8601 UTC start filter
            until_timestamp: Optional ISO 8601 UTC end filter
            tail_chars: Max chars to return (default 5000, 0 for unlimited)
            caller_session_id: Optional caller's session ID for stop notifications

        Returns:
            Dict with session data, status, and messages
        """
        # Register as listener so caller gets notified when target session stops
        # Enables "master orchestrator" pattern - check multiple sessions, get notified when any stops
        await self._maybe_register_listener(session_id, caller_session_id)

        if self._is_local_computer(computer):
            return await self._get_local_session_data(session_id, since_timestamp, until_timestamp, tail_chars)
        return await self._get_remote_session_data(computer, session_id, since_timestamp, until_timestamp, tail_chars)

    async def _get_local_session_data(
        self,
        session_id: str,
        since_timestamp: Optional[str] = None,
        until_timestamp: Optional[str] = None,
        tail_chars: int = 5000,
    ) -> dict[str, object]:
        """Get session data from local computer directly.

        Args:
            session_id: Session ID
            since_timestamp: Optional ISO 8601 UTC start filter
            until_timestamp: Optional ISO 8601 UTC end filter
            tail_chars: Max chars to return (default 5000, 0 for unlimited)

        Returns:
            Dict with session data, status, and messages
        """
        # Create context for the handler
        context = CommandEventContext(session_id=session_id, args=[])

        # Call handler directly with all params
        return await command_handlers.handle_get_session_data(context, since_timestamp, until_timestamp, tail_chars)

    async def _get_remote_session_data(
        self,
        computer: str,
        session_id: str,
        since_timestamp: Optional[str] = None,
        until_timestamp: Optional[str] = None,
        tail_chars: int = 5000,
    ) -> dict[str, object]:
        """Get session data from remote computer via Redis.

        Args:
            computer: Target computer name
            session_id: Session ID on remote computer
            since_timestamp: Optional ISO 8601 UTC start filter
            until_timestamp: Optional ISO 8601 UTC end filter
            tail_chars: Max chars to return (default 5000, 0 for unlimited)

        Returns:
            Dict with session data, status, and messages
        """
        # Build command with optional params (space-separated for parsing)
        # Format: /get_session_data [since_timestamp] [until_timestamp] [tail_chars]
        params = []
        params.append(since_timestamp or "")
        params.append(until_timestamp or "")
        params.append(str(tail_chars))
        command = f"/get_session_data {' '.join(params)}"

        # Send request to remote computer
        # Transport layer generates request_id from Redis message ID
        message_id = await self.client.send_request(
            computer_name=computer,
            command=command,
            session_id=session_id,
            metadata=MessageMetadata(),
        )

        # Read response (remote reads claude_session_file)
        try:
            response = await self.client.read_response(message_id, timeout=5.0)
            envelope = json.loads(response)

            # Handle error response
            if envelope.get("status") == "error":
                error_msg = envelope.get("error", "Unknown error")
                return {"status": "error", "error": f"Remote error: {error_msg}"}

            # Extract session data from success envelope
            data = envelope.get("data")
            if isinstance(data, dict):
                return data

            # Data is missing or wrong type
            return {"status": "error", "error": "Invalid response data format"}
        except TimeoutError:
            return {
                "status": "error",
                "error": f"Timeout waiting for session data from {computer}",
            }
        except json.JSONDecodeError:
            return {
                "status": "error",
                "error": "Invalid JSON response from remote computer",
            }

    async def teleclaude__deploy(self, computers: list[str] | None = None) -> dict[str, dict[str, object]]:
        """Deploy latest code to remote computers via Redis.

        Args:
            computers: Optional list of target computers. Omit/empty to deploy to all remotes.

        Returns:
            Status for each computer: {computer: {status, timestamp, pid, error}}
        """
        # Get Redis adapter
        redis_adapter_base = self.client.adapters.get("redis")
        if not redis_adapter_base or not isinstance(redis_adapter_base, RedisAdapter):
            return {"_error": {"status": "error", "message": "Redis adapter not available"}}

        redis_adapter: RedisAdapter = redis_adapter_base

        # Discover peers (exclude self)
        all_peers = await redis_adapter.discover_peers()
        available = [str(peer.name) for peer in all_peers if peer.name != self.computer_name]
        available_set = set(available)

        requested = [str(name) for name in (computers or [])]
        targets = list(available) if not requested else [name for name in requested if name in available_set]

        # Preserve requested order and de-duplicate
        if requested:
            seen: set[str] = set()
            ordered_targets: list[str] = []
            for name in targets:
                if name not in seen:
                    seen.add(name)
                    ordered_targets.append(name)
            targets = ordered_targets

        results: dict[str, dict[str, object]] = {}

        # Report unknown computers if explicitly requested
        if requested:
            for name in requested:
                if name == self.computer_name:
                    results[name] = {
                        "status": "skipped",
                        "message": "Skipping self deployment",
                    }
                elif name not in available_set:
                    results[name] = {
                        "status": "error",
                        "message": "Unknown or offline computer",
                    }

        if not targets:
            return {
                "_message": {
                    "status": "success",
                    "message": "No remote computers to deploy to",
                }
            }

        logger.info("Deploying to computers: %s", targets)

        # Send deploy command to all computers
        verify_health = True  # Always verify health
        for computer in targets:
            await redis_adapter.send_system_command(
                computer_name=computer,
                command="deploy",
                args={"verify_health": verify_health},
            )
            logger.info("Sent deploy command to %s", computer)

        # Poll for completion (max 60 seconds per computer)
        for computer in targets:
            for _ in range(60):  # 60 attempts, 1 second apart
                status = await redis_adapter.get_system_command_status(computer_name=computer, command="deploy")

                status_str = str(status.get("status", "unknown"))
                if status_str in ("deployed", "error"):
                    results[computer] = status
                    logger.info("Computer %s deployment status: %s", computer, status_str)
                    break

                await asyncio.sleep(1)
            else:
                # Timeout
                results[computer] = {
                    "status": "timeout",
                    "message": "Deployment timed out after 60 seconds",
                }
                logger.warning("Deployment to %s timed out", computer)

        return results

    async def teleclaude__send_file(self, session_id: str, file_path: str, caption: str | None = None) -> str:
        """Send file via session's origin adapter.

        Args:
            session_id: TeleClaude session UUID
            file_path: Absolute path to file
            caption: Optional caption

        Returns:
            Success message or error
        """
        path = Path(file_path)
        if not path.exists():
            return f"Error: File not found: {file_path}"

        if not path.is_file():
            return f"Error: Not a file: {file_path}"

        # Get session
        session = await db.get_session(session_id)
        if not session:
            return f"Error: Session {session_id} not found"

        try:
            message_id = await self.client.send_file(session=session, file_path=str(path.absolute()), caption=caption)
            return f"File sent successfully: {path.name} (message_id: {message_id})"
        except ValueError as e:
            logger.error("Failed to send file %s: %s", file_path, e)
            return f"Error: {e}"
        except Exception as e:
            logger.error("Failed to send file %s: %s", file_path, e)
            return f"Error sending file: {e}"

    async def teleclaude__stop_notifications(
        self,
        computer: str,
        session_id: str,
        caller_session_id: str | None = None,
    ) -> dict[str, object]:
        """Stop receiving notifications from a session without ending it.

        Unregisters the caller's listener for the target session.
        Target session continues running, but caller no longer receives stop/notification events.

        Args:
            computer: Target computer name (or "local"/self.computer_name)
            session_id: Session to stop monitoring
            caller_session_id: Optional caller's session ID for listener removal

        Returns:
            dict with status and message
        """
        if not caller_session_id:
            return {"status": "error", "message": "caller_session_id required"}

        if self._is_local_computer(computer):
            # Local - unregister listener directly
            success = unregister_listener(target_session_id=session_id, caller_session_id=caller_session_id)
            if success:
                return {
                    "status": "success",
                    "message": f"Stopped notifications from session {session_id[:8]}",
                }
            return {
                "status": "error",
                "message": f"No listener found for session {session_id[:8]}",
            }

        # Remote - send stop_notifications command via Redis
        try:
            message_id = await self.client.send_request(
                computer_name=computer,
                command=f"stop_notifications {session_id} {caller_session_id}",
                metadata=MessageMetadata(),
            )

            # Read response
            response_data = await self.client.read_response(message_id, timeout=3.0)
            envelope = json.loads(response_data.strip())

            if envelope.get("status") == "error":
                error_msg = envelope.get("error", "Unknown error")
                return {"status": "error", "message": f"Remote error: {error_msg}"}

            return envelope.get("data", {"status": "success"})

        except TimeoutError:
            return {"status": "error", "message": "Timeout waiting for response"}
        except Exception as e:
            logger.error("Failed to stop notifications: %s", e)
            return {
                "status": "error",
                "message": f"Failed to stop notifications: {str(e)}",
            }

    async def teleclaude__end_session(
        self,
        computer: str,
        session_id: str,
    ) -> dict[str, object]:
        """End a session gracefully (kill tmux, mark closed, clean up resources).

        Args:
            computer: Target computer name (or "local"/self.computer_name)
            session_id: Session to end

        Returns:
            dict with status and message
        """
        if self._is_local_computer(computer):
            # Local - call handle_end_session directly
            return await command_handlers.handle_end_session(session_id, self.client)

        # Remote - send end_session command via Redis
        try:
            message_id = await self.client.send_request(
                computer_name=computer,
                command=f"end_session {session_id}",
                metadata=MessageMetadata(),
            )

            # Read response
            response_data = await self.client.read_response(message_id, timeout=5.0)
            envelope = json.loads(response_data.strip())

            if envelope.get("status") == "error":
                error_msg = envelope.get("error", "Unknown error")
                return {"status": "error", "message": f"Remote error: {error_msg}"}

            return envelope.get("data", {"status": "success"})

        except TimeoutError:
            return {"status": "error", "message": "Timeout waiting for response"}
        except Exception as e:
            logger.error("Failed to end session: %s", e)
            return {"status": "error", "message": f"Failed to end session: {str(e)}"}

    async def teleclaude__handle_agent_event(self, session_id: str, event_type: str, data: dict[str, object]) -> str:
        """Emit Agent event to registered listeners (called by agent hooks).

        Args:
            session_id: TeleClaude session UUID
            event_type: Type of Claude event (e.g., "stop", "compact", "session_start")
            data: Event-specific data

        Returns:
            Success message
        """
        # Verify session exists
        session = await db.get_session(session_id)
        if not session:
            raise ValueError(f"TeleClaude session {session_id} not found")

        if event_type == AgentHookEvents.AGENT_ERROR:
            await self.client.handle_event(
                TeleClaudeEvents.ERROR,
                {
                    "session_id": session_id,
                    "message": str(data["message"]),
                    "source": str(data["source"]) if "source" in data else None,
                    "details": cast(dict[str, object] | None, data["details"]) if "details" in data else None,
                },
                MessageMetadata(adapter_type="internal"),
            )
            return "OK"

        # Emit event to registered listeners
        response = await self.client.handle_event(
            TeleClaudeEvents.AGENT_EVENT,
            {"session_id": session_id, "event_type": event_type, "data": data},  # type: ignore[dict-item]
            MessageMetadata(adapter_type="internal"),
        )

        logger.trace("Agent event emitted", session=session_id[:8], event=event_type)
        if isinstance(response, dict) and response.get("status") == "error":
            raise ValueError(str(response.get("error")))
        return "OK"
