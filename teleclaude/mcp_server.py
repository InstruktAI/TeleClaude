"""MCP server for TeleClaude multi-computer communication."""

import asyncio
import json
import logging
import os
import re
import shlex
import time
import types
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Optional

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.server import Server
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, TextContent, Tool

from teleclaude.adapters.redis_adapter import RedisAdapter
from teleclaude.config import config
from teleclaude.core.command_handlers import get_short_project_name
from teleclaude.core.db import db
from teleclaude.core.session_utils import ensure_unique_title

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = logging.getLogger(__name__)


class TeleClaudeMCPServer:
    """MCP server for exposing TeleClaude functionality to Claude Code.

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
        self.server = Server("teleclaude")

        # Setup MCP tool handlers
        self._setup_tools()

    def _setup_tools(self) -> None:
        """Register MCP tools with the server."""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available MCP tools."""
            return [
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
                        "List active AI-managed Claude Code sessions across all computers with rich metadata "
                        "(project_dir, status, claude_session_id). "
                        "Use to discover existing sessions before starting new ones."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "computer": {
                                "type": "string",
                                "description": "Optional filter by target computer name",
                            }
                        },
                    },
                ),
                Tool(
                    name="teleclaude__start_session",
                    title="TeleClaude: Start Session",
                    description=(
                        "Start a new Claude Code session on a remote computer in a specific project. "
                        "**REQUIRED WORKFLOW:** "
                        "1) Call teleclaude__list_projects FIRST to discover available projects "
                        "2) Match and select the correct project from the results "
                        "3) Use the exact project path from list_projects in the project_dir parameter here. "
                        "Returns session_id and streams initial response."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "computer": {
                                "type": "string",
                                "description": "Target computer name (e.g., 'workstation', 'server')",
                            },
                            "project_dir": {
                                "type": "string",
                                "description": (
                                    "**MUST come from teleclaude__list_projects output** "
                                    "Absolute path to project directory (e.g., '/home/user/apps/TeleClaude'). "
                                    "Do NOT guess or construct paths - always use teleclaude__list_projects first."
                                ),
                            },
                        },
                        "required": ["computer", "project_dir"],
                    },
                ),
                Tool(
                    name="teleclaude__send_message",
                    title="TeleClaude: Send Message",
                    description=(
                        "Send message to an existing Claude Code session and stream initial output. "
                        "**Interest Window Pattern**: Streams output for 15 seconds (configurable), then detaches. "
                        "This allows you to peek at initial execution to verify the task started correctly. "
                        "**IMPORTANT**: After this tool returns, you MUST call teleclaude__get_session_status "
                        "repeatedly to monitor progress until task completes or you determine it's safe to let run. "
                        "Use teleclaude__list_sessions to find session_id or "
                        "teleclaude__start_session to create new one."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Session ID from teleclaude__start_session or teleclaude__list_sessions",
                            },
                            "message": {
                                "type": "string",
                                "description": "Message or command to send to Claude Code",
                            },
                            "interest_window_seconds": {
                                "type": "number",
                                "description": "Seconds to monitor output before detaching (default: 15)",
                            },
                        },
                        "required": ["session_id", "message"],
                    },
                ),
                Tool(
                    name="teleclaude__get_session_status",
                    title="TeleClaude: Get Session Status",
                    description=(
                        "Check session status and get accumulated output since last checkpoint. "
                        "**Purpose**: Monitor delegated tasks running on remote computers. "
                        "**When to use**: Call repeatedly after teleclaude__send_message until: "
                        "(1) You see output indicating task completed successfully, "
                        "(2) You see errors and need to intervene, or "
                        "(3) You determine task is progressing well (polling_active=true) "
                        "and safe to let run. "
                        "**State field**: Shows 'polling_active' when command is running, "
                        "'idle' when waiting for input. "
                        "**Checkpoint System**: Only returns NEW output since last check (no replay). "
                        "This models human delegation: peek → assess → intervene OR let run → check back later."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Session ID to check status for",
                            },
                        },
                        "required": ["session_id"],
                    },
                ),
                Tool(
                    name="teleclaude__observe_session",
                    title="TeleClaude: Observe Session",
                    description=(
                        "Watch real-time output from ANY session on any computer "
                        "(local or AI-to-AI). "
                        "**Use Cases**: Monitor another AI's work, observe human sessions, "
                        "debug sessions, multi-device access. "
                        "**How it works**: Signals observation interest via Redis "
                        "→ target computer streams output → observer receives. "
                        "**Interest Window Pattern**: Observes for specified duration, then detaches automatically. "
                        "Works for both local Telegram sessions and AI-to-AI sessions."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "computer": {
                                "type": "string",
                                "description": "Target computer name (e.g., 'MozBook', 'RasPi')",
                            },
                            "session_id": {
                                "type": "string",
                                "description": "Session ID to observe",
                            },
                            "duration_seconds": {
                                "type": "number",
                                "description": "How long to watch (default: 30 seconds)",
                            },
                        },
                        "required": ["computer", "session_id"],
                    },
                ),
                Tool(
                    name="teleclaude__deploy_to_all_computers",
                    title="TeleClaude: Deploy to All Computers",
                    description=(
                        "Deploy latest code to ALL remote computers (git pull + restart). "
                        "Automatically discovers and deploys to all computers except self. "
                        "Use this after committing changes to update all machines. "
                        "**Workflow**: commit changes → push to GitHub → call this tool. "
                        "Returns deployment status for each computer (success, deploying, error)."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="teleclaude__send_file",
                    title="TeleClaude: Send File",
                    description=(
                        "Send a file to Telegram via the current session. "
                        "Use this to send files for download (logs, session files, etc.). "
                        "File will be sent to the Telegram topic associated with the current session."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Absolute path to file to send",
                            },
                            "caption": {
                                "type": "string",
                                "description": "Optional caption for the file",
                            },
                        },
                        "required": ["file_path"],
                    },
                ),
                Tool(
                    name="teleclaude__send_notification",
                    title="TeleClaude: Send Notification",
                    description=("Send notification to a TeleClaude session when asked."),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "TeleClaude session UUID (not Claude Code session!)",
                            },
                            "message": {
                                "type": "string",
                                "description": "Notification message to send",
                            },
                        },
                        "required": ["session_id", "message"],
                    },
                ),
                Tool(
                    name="teleclaude__init_from_claude",
                    title="TeleClaude: Initialize from Claude",
                    description=(
                        "Initializes TeleClaude session with Claude session data. "
                        "USED BY HOOKS, AND FOR INTERNAL USE ONLY, so do not call yourself."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "TeleClaude session UUID (not Claude Code session!)",
                            },
                            "claude_session_id": {
                                "type": "string",
                                "description": "ID of Claude session",
                            },
                            "claude_session_file": {
                                "type": "string",
                                "description": "Path to Claude session file",
                            },
                        },
                        "required": ["session_id", "claude_session_id", "claude_session_file"],
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict[str, object]) -> list[TextContent]:
            """Handle tool calls."""
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
                computer_obj = arguments.get("computer") if arguments else None
                computer = str(computer_obj) if computer_obj else None
                sessions = await self.teleclaude__list_sessions(computer)
                return [TextContent(type="text", text=json.dumps(sessions, default=str))]
            elif name == "teleclaude__start_session":
                # Extract arguments explicitly
                computer = str(arguments.get("computer", "")) if arguments else ""
                project_dir_obj = arguments.get("project_dir") if arguments else None
                project_dir = str(project_dir_obj) if project_dir_obj else None
                result = await self.teleclaude__start_session(computer, project_dir)
                return [TextContent(type="text", text=json.dumps(result, default=str))]
            elif name == "teleclaude__send_message":
                # Extract arguments explicitly
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                message = str(arguments.get("message", "")) if arguments else ""
                interest_window_obj = arguments.get("interest_window_seconds", 15) if arguments else 15
                interest_window = (
                    float(interest_window_obj) if isinstance(interest_window_obj, (int, float, str)) else 15.0
                )
                # Collect all chunks from async generator
                chunks: list[str] = []
                async for chunk in self.teleclaude__send_message(session_id, message, interest_window):
                    chunks.append(chunk)
                result_text = "".join(chunks)
                return [TextContent(type="text", text=result_text)]
            elif name == "teleclaude__get_session_status":
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                result = await self.teleclaude__get_session_status(session_id)
                return [TextContent(type="text", text=json.dumps(result, default=str))]
            elif name == "teleclaude__observe_session":
                computer = str(arguments.get("computer", "")) if arguments else ""
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                duration_seconds = 30
                if arguments and "duration_seconds" in arguments:
                    duration_obj = arguments["duration_seconds"]
                    if isinstance(duration_obj, (int, float)):
                        duration_seconds = int(duration_obj)
                result = await self.teleclaude__observe_session(computer, session_id, duration_seconds)
                return [TextContent(type="text", text=json.dumps(result, default=str))]
            elif name == "teleclaude__deploy_to_all_computers":
                # No arguments - always deploys to ALL computers
                deploy_result: dict[str, dict[str, object]] = await self.teleclaude__deploy_to_all_computers()
                return [TextContent(type="text", text=json.dumps(deploy_result, default=str))]
            elif name == "teleclaude__send_file":
                file_path = str(arguments.get("file_path", "")) if arguments else ""
                caption_obj = arguments.get("caption") if arguments else None
                caption = str(caption_obj) if caption_obj else None
                result_text = await self.teleclaude__send_file(file_path, caption)
                return [TextContent(type="text", text=result_text)]
            elif name == "teleclaude__init_from_claude":
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                claude_session_id_obj = arguments.get("claude_session_id") if arguments else None
                claude_session_id = str(claude_session_id_obj) if claude_session_id_obj else None
                claude_session_file_obj = arguments.get("claude_session_file") if arguments else None
                claude_session_file = str(claude_session_file_obj) if claude_session_file_obj else None
                result_text = await self.teleclaude__init_from_claude(
                    session_id, claude_session_id, claude_session_file
                )
                return [TextContent(type="text", text=result_text)]
            elif name == "teleclaude__send_notification":
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                message = str(arguments.get("message", "")) if arguments else ""
                result_text = await self.teleclaude__send_notification(session_id, message)
                return [TextContent(type="text", text=result_text)]
            else:
                raise ValueError(f"Unknown tool: {name}")

    async def start(self) -> None:
        """Start MCP server on Unix socket."""
        socket_path_str = os.path.expandvars(config.mcp.socket_path)
        socket_path = Path(socket_path_str)

        # Remove existing socket file if present
        if socket_path.exists():
            socket_path.unlink()

        logger.info("MCP server listening on socket: %s", socket_path)

        # Create Unix socket server
        server = await asyncio.start_unix_server(
            lambda r, w: asyncio.create_task(self._handle_socket_connection(r, w)), path=str(socket_path)
        )

        # Make socket accessible (owner only)
        socket_path.chmod(0o600)

        async with server:
            await server.serve_forever()

    async def _handle_socket_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle a single MCP client connection over Unix socket."""
        logger.info("New MCP client connected")
        try:
            # Create memory streams like stdio_server does
            read_stream_writer: MemoryObjectSendStream
            read_stream: MemoryObjectReceiveStream
            write_stream: MemoryObjectSendStream
            write_stream_reader: MemoryObjectReceiveStream

            read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
            write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

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
                await self.server.run(read_stream, write_stream, self.server.create_initialization_options())

        except Exception:
            logger.exception("Error handling MCP connection")
        finally:
            writer.close()
            await writer.wait_closed()
            logger.info("MCP client disconnected")

    async def teleclaude__list_computers(self) -> list[dict[str, object]]:
        """List available computers.

        Returns:
            List of online computers with their info (role, system_stats, sessions, etc.)
        """
        return await self.client.discover_peers()

    async def teleclaude__list_projects(self, computer: str) -> list[dict[str, str]]:
        """List available projects on target computer with metadata.

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

        # Generate session ID for this query
        session_id = str(uuid.uuid4())
        logger.debug("Sending list_projects request to %s with request_id=%s", computer, session_id[:8])

        # Send list_projects command via AdapterClient
        await self.client.send_request(computer_name=computer, request_id=session_id, command="list_projects")
        logger.debug("Request sent, starting to poll response...")

        # Stream response from AdapterClient
        result: list[dict[str, str]] = []
        try:
            async with asyncio.timeout(10):
                async for chunk in self.client.poll_response(session_id, timeout=10.0):
                    # Look for JSON array response
                    if chunk.strip().startswith("["):
                        projects: list[dict[str, str]] = json.loads(chunk.strip())
                        result = projects
                        break
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for list_projects response from %s", computer)
            return []

        return result

    async def teleclaude__start_session(
        self,
        computer: str,
        project_dir: str,
        continue_last_session: bool = False,
    ) -> dict[str, object]:
        """Start new Claude Code session on remote computer in a specific project.

        Args:
            computer: Target computer name
            project_dir: Absolute path to project directory
            continue_last_session: Whether to continue the last opened session.
                Be careful as this might hijack the session of another user.
                ONLY provide this flag on explicit request!

        Returns:
            dict with session_id and output
        """

        # Validate computer is online
        peers = await self.client.discover_peers()
        target_online = any(p["name"] == computer and p["status"] == "online" for p in peers)

        if not target_online:
            return {"status": "error", "message": f"Computer '{computer}' is offline"}

        # Generate Claude session UUID
        claude_session_id = str(uuid.uuid4())

        # Create session in database to track this AI-to-AI session
        short_project = get_short_project_name(project_dir)
        base_title = f"${self.computer_name} > ${computer}[{short_project}] - AI Session"
        title = await ensure_unique_title(base_title)
        session = await db.create_session(
            computer_name=self.computer_name,
            tmux_session_name=f"{self.computer_name}-ai-{claude_session_id[:8]}",
            origin_adapter="redis",
            title=title,
            adapter_metadata={
                "is_auto_managed": True,
                "project_dir": project_dir,
                "target_computer": computer,
            },
            description=f"Auto-managed AI session for {project_dir} on {computer}",
        )

        session_id = session.session_id

        # Create channels in ALL adapters (Telegram, Redis, etc.)
        # This enables observer broadcasting to Telegram
        await self.client.create_channel(
            session_id=session_id,
            title=title,
            origin_adapter="redis",
        )

        # cd to dir on remote computer via AdapterClient
        cd_cmd = f"/cd {shlex.quote(project_dir)}"
        await self.client.send_request(
            computer_name=computer,
            request_id=session_id,
            command=cd_cmd,
            metadata={"title": title, "project_dir": project_dir},
        )

        # Start Claude Code
        claude_cmd = "/claude" + (" --continue" if continue_last_session else "")
        await self.client.send_request(
            computer_name=computer,
            request_id=session_id,
            command=claude_cmd,
            metadata={"title": title, "project_dir": project_dir},
        )

        # Return immediately - polling happens automatically on remote side
        return {"session_id": session_id, "status": "success"}

    async def teleclaude__list_sessions(self, computer: Optional[str] = None) -> list[dict[str, object]]:
        """List sessions from LOCAL database only.

        This tool queries the local database on THIS computer and returns sessions
        (both Human-to-AI via Telegram and AI-to-AI via MCP). It does NOT query
        remote computers - each computer maintains its own session database.

        Args:
            computer: Optional filter by target computer name for AI-to-AI sessions.
                      If None, returns all active sessions from local database.
                      If specified, filters to AI-to-AI sessions where target_computer matches.
                      Human-to-AI sessions (no target) are included when computer=None.

        Returns:
            List of session dicts with fields:
            - session_id: Unique session identifier
            - origin_adapter: Adapter that initiated session (telegram/redis)
            - target: Target computer name (only for AI-to-AI sessions, None for Human-to-AI)
            - title: Session title
            - working_directory: Current working directory of the session
            - status: Session status (active/closed)
            - created_at: ISO timestamp
            - last_activity: ISO timestamp
            - metadata: Full adapter_metadata dict (project_dir, is_auto_managed, etc.)
        """
        # Get all active sessions (closed=False)
        sessions = await db.get_all_sessions(closed=False)

        # Filter by target computer if specified
        result = []
        for session in sessions:
            metadata = session.adapter_metadata or {}
            target_computer = metadata.get("target_computer")

            # If computer filter specified, only include sessions targeting that computer
            if computer and target_computer != computer:
                continue

            result.append(
                {
                    "session_id": session.session_id,
                    "origin_adapter": session.origin_adapter,
                    "target": target_computer,
                    "title": session.title,
                    "working_directory": session.working_directory,
                    "status": "closed" if session.closed else "active",
                    "created_at": session.created_at.isoformat(),
                    "last_activity": session.last_activity.isoformat(),
                    "metadata": metadata,
                }
            )

        return result

    async def teleclaude__send_message(
        self, session_id: str, message: str, interest_window_seconds: float = 15
    ) -> AsyncIterator[str]:
        """Send message to claude in an existing AI-to-AI session and stream response during interest window.

        Args:
            session_id: Session ID from teleclaude__start_session
            message: Message/command to send to remote Claude Code
            interest_window_seconds: Seconds to monitor output before detaching (default: 15)

        Yields:
            str: Response chunks from remote Claude Code during interest window
        """
        # Get session from database
        session = await db.get_session(session_id)
        if not session:
            yield "[Error: Session not found]"
            return

        # Verify session is active
        if session.closed:
            yield "[Error: Session is closed]"
            return

        # Get target computer from session metadata
        metadata = session.adapter_metadata or {}
        target_computer_obj = metadata.get("target_computer")
        if not target_computer_obj:
            yield "[Error: Session metadata missing target_computer]"
            return

        target_computer = str(target_computer_obj)

        # Wrap non-command messages with /message prefix for proper event routing
        # Commands start with /, plain text needs to be wrapped
        command = message if message.startswith("/") else f"/message {message}"

        # Send command to remote computer via AdapterClient
        try:
            await self.client.send_request(computer_name=target_computer, request_id=session_id, command=command)
        except Exception as e:
            logger.error("Failed to send command to %s: %s", target_computer, e)
            yield f"[Error: Failed to send command: {str(e)}]"
            return

        # Stream output from AdapterClient during interest window
        start_time = time.time()
        # TODO: Track last_checkpoint_stream_id from chunks to save checkpoint (currently unused)

        try:
            # Stream output with interest window timeout
            async for chunk in self.client.poll_response(session_id, timeout=interest_window_seconds):
                # Strip exit markers from output (internal infrastructure, not user-visible)
                clean_chunk = re.sub(r"__EXIT__\d+__", "", chunk)
                if clean_chunk:  # Only yield if there's content after stripping
                    yield clean_chunk

                # Check if interest window expired
                elapsed = time.time() - start_time
                if elapsed >= interest_window_seconds:
                    yield (
                        "\n\n[Interest window closed - task continues remotely. "
                        "Use teleclaude__get_session_status to check progress]"
                    )
                    # TODO: Track last_stream_id from chunks to save checkpoint
                    break

        except asyncio.TimeoutError:
            yield "\n[Interest window timed out - no output received]"
        except Exception as e:
            logger.error("Error streaming output for session %s: %s", session_id[:8], e)
            yield f"\n[Error: {str(e)}]"

        # Save checkpoint (for now, just update timestamp - stream ID tracking needs adapter support)
        metadata["last_checkpoint_time"] = datetime.now(UTC).isoformat()
        await db.update_session(session_id=session_id, adapter_metadata=metadata, last_activity=datetime.now(UTC))

    async def teleclaude__get_session_status(self, session_id: str) -> dict[str, object]:
        """Get session status and accumulated output since last checkpoint.

        Args:
            session_id: Session ID to check status for

        Returns:
            dict with status, new_output, polling_active, runtime_seconds
        """
        # Get session from database
        session = await db.get_session(session_id)
        if not session:
            return {"status": "error", "message": "Session not found"}

        # Check if session was explicitly closed
        if session.closed:
            return {"status": "closed", "message": "Session has been closed"}

        # Get target computer from session metadata
        metadata = session.adapter_metadata or {}
        target_computer_obj = metadata.get("target_computer")
        if not target_computer_obj:
            return {"status": "error", "message": "Session metadata missing target_computer"}

        target_computer = str(target_computer_obj)

        # Poll for new output with short timeout (2s - just check what's available)
        new_output_chunks: list[str] = []
        try:
            async for chunk in self.client.poll_response(session_id, timeout=2.0):
                new_output_chunks.append(chunk)
        except asyncio.TimeoutError:
            # No new output - that's fine
            pass
        except Exception as e:
            logger.error("Error polling output for session %s: %s", session_id[:8], e)
            return {"status": "error", "message": f"Failed to poll output: {str(e)}"}

        new_output = "".join(new_output_chunks)

        # Strip ALL exit markers from output (these are internal infrastructure)
        # Pattern: __EXIT__<number>__ (e.g., __EXIT__0__)
        new_output = re.sub(r"__EXIT__\d+__", "", new_output)

        # Determine session state
        # - For AI-to-AI sessions, Claude Code runs continuously
        # - Session is "running" until explicitly closed
        # - Check if there's recent activity via polling_active flag
        ux_state = await db.get_ux_state(session_id)
        polling_active = ux_state.polling_active if ux_state else False

        status = "running"  # Session is alive unless marked closed
        state_description = "polling_active" if polling_active else "idle"

        # Calculate runtime (ensure both datetimes are timezone-aware)
        now = datetime.now(UTC)
        created_at = session.created_at.replace(tzinfo=UTC) if session.created_at.tzinfo is None else session.created_at
        runtime_seconds = (now - created_at).total_seconds()

        # Update checkpoint timestamp
        metadata["last_checkpoint_time"] = datetime.now(UTC).isoformat()
        await db.update_session(session_id=session_id, adapter_metadata=metadata, last_activity=datetime.now(UTC))

        return {
            "status": status,
            "state": state_description,
            "new_output": new_output,
            "has_new_output": len(new_output.strip()) > 0,
            "polling_active": polling_active,
            "runtime_seconds": runtime_seconds,
            "target_computer": target_computer,
            "project_dir": metadata.get("project_dir"),
        }

    async def teleclaude__observe_session(
        self,
        computer: str,
        session_id: str,
        duration_seconds: int = 30,
    ) -> dict[str, object]:
        """Observe real-time output from any session on any computer.

        Signals observation interest to target computer, then streams output
        for the specified duration. Target computer will broadcast session
        output to Redis only during the observation window.

        Args:
            computer: Target computer name
            session_id: Session ID to observe
            duration_seconds: How long to watch (default: 30s)

        Returns:
            Dict with status and streamed output
        """
        # Get Redis adapter
        redis_adapter_base = self.client.adapters.get("redis")
        if not redis_adapter_base or not isinstance(redis_adapter_base, RedisAdapter):
            return {"status": "error", "message": "Redis adapter not available"}

        redis_adapter: RedisAdapter = redis_adapter_base

        # Signal observation interest to target computer
        try:
            await redis_adapter.signal_observation(computer, session_id, duration_seconds)
        except Exception as e:
            logger.error("Failed to signal observation: %s", e)
            return {"status": "error", "message": f"Failed to signal observation: {str(e)}"}

        # Stream output for duration
        output_chunks: list[str] = []
        start_time = time.time()

        try:
            async for chunk in self.client.poll_response(session_id, timeout=float(duration_seconds)):
                output_chunks.append(chunk)

                # Stop if duration exceeded
                if time.time() - start_time > duration_seconds:
                    break
        except asyncio.TimeoutError:
            # No output during window - that's okay
            pass
        except Exception as e:
            logger.error("Error polling output for observation: %s", e)
            return {"status": "error", "message": f"Failed to poll output: {str(e)}"}

        output = "".join(output_chunks)

        # Strip exit markers
        output = re.sub(r"__EXIT__\d+__", "", output)

        return {
            "status": "success",
            "computer": computer,
            "session_id": session_id,
            "duration_seconds": duration_seconds,
            "output": output if output.strip() else "[No output during observation window]",
            "output_length": len(output),
        }

    async def teleclaude__deploy_to_all_computers(self) -> dict[str, dict[str, object]]:
        """Deploy latest code to ALL remote computers via Redis.

        Automatically discovers all computers and deploys to them (excluding self).
        No arguments - always deploys to ALL computers.

        Returns:
            Status for each computer: {computer: {status, timestamp, pid, error}}
        """
        # Get Redis adapter
        redis_adapter_base = self.client.adapters.get("redis")
        if not redis_adapter_base or not isinstance(redis_adapter_base, RedisAdapter):
            return {"_error": {"status": "error", "message": "Redis adapter not available"}}

        redis_adapter: RedisAdapter = redis_adapter_base

        # Discover ALL computers (excluding self)
        all_peers = await redis_adapter.discover_peers()
        computers = [str(peer["name"]) for peer in all_peers if peer.get("name") != self.computer_name]

        if not computers:
            return {"_message": {"status": "success", "message": "No remote computers to deploy to"}}

        logger.info("Deploying to ALL computers: %s", computers)

        # Send deploy command to all computers
        verify_health = True  # Always verify health
        for computer in computers:
            await redis_adapter.send_system_command(
                computer_name=computer, command="deploy", args={"verify_health": verify_health}
            )
            logger.info("Sent deploy command to %s", computer)

        # Poll for completion (max 60 seconds per computer)
        results: dict[str, dict[str, object]] = {}
        for computer in computers:
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
                results[computer] = {"status": "timeout", "message": "Deployment timed out after 60 seconds"}
                logger.warning("Deployment to %s timed out", computer)

        return results

    async def teleclaude__send_file(self, file_path: str, caption: Optional[str] = None) -> str:
        """Send file via current session's origin adapter.

        Args:
            file_path: Absolute path to file
            caption: Optional caption

        Returns:
            Success message or error
        """
        # Validate file exists
        path = Path(file_path)
        if not path.exists():
            return f"Error: File not found: {file_path}"

        if not path.is_file():
            return f"Error: Not a file: {file_path}"

        # Get current session from environment variable (set by Claude Code)
        session_id = os.environ.get("TELECLAUDE_SESSION_ID")
        if not session_id:
            return "Error: No active TeleClaude session (TELECLAUDE_SESSION_ID not set)"

        # Get session from database
        session = await db.get_session(session_id)
        if not session:
            return f"Error: Session {session_id} not found"

        # Get origin adapter
        origin_adapter_name = session.origin_adapter
        origin_adapter = self.client.adapters.get(origin_adapter_name)
        if not origin_adapter:
            return f"Error: Origin adapter '{origin_adapter_name}' not available"

        # Send file via adapter
        try:
            message_id = await origin_adapter.send_file(
                session_id=session_id, file_path=str(path.absolute()), caption=caption
            )
            return f"File sent successfully: {path.name} (message_id: {message_id})"
        except Exception as e:
            logger.error("Failed to send file %s: %s", file_path, e)
            return f"Error sending file: {e}"

    async def teleclaude__init_from_claude(
        self, session_id: str, claude_session_id: Optional[str] = None, claude_session_file: Optional[str] = None
    ) -> str:
        """Keep Claude Code status information for TeleClaude session (called by Claude Code hooks).

        Args:
            session_id: TeleClaude session UUID (not Claude Code session!)
            claude_session_id: Claude Code session ID
            claude_session_file: Path to Claude session file

        Returns:
            Success message
        """
        # Verify session exists
        session = await db.get_session(session_id)
        if not session:
            raise ValueError(f"TeleClaude session {session_id} not found")

        # Store claude_session_file
        if claude_session_file:
            await db.update_ux_state(
                session_id, claude_session_id=claude_session_id, claude_session_file=claude_session_file
            )

        return "OK"

    async def teleclaude__send_notification(self, session_id: str, message: str) -> str:
        """Send notification to a session.

        Args:
            session_id: TeleClaude session UUID (not Claude Code session!)
            message: Notification message to send

        Returns:
            Success message with message_id
        """
        # Verify session exists
        session = await db.get_session(session_id)
        if not session:
            raise ValueError(f"TeleClaude session {session_id} not found")

        # Send notification via AdapterClient
        message_id = await self.client.send_message(session_id, message)

        # Mark notification message for cleanup on next user input
        await db.add_pending_deletion(session_id, message_id)

        # Set notification_sent flag (prevents idle notifications)
        await db.set_notification_flag(session_id, True)

        return f"OK: {message_id}"
