"""MCP server for TeleClaude multi-computer communication."""

import asyncio
import json
import logging
import os
import re
import time
import types
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Optional

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, TextContent, Tool

from teleclaude.config import config
from teleclaude.core.db import db

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.db import Db

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
                    description="List all available TeleClaude computers in the network",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="teleclaude__list_projects",
                    description=(
                        "**CRITICAL: Call this FIRST before teleclaude__start_session** "
                        "List available project directories on a target computer (from trusted_dirs config). "
                        "Returns project paths that can be used in teleclaude__start_session. "
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
                            "initial_message": {
                                "type": "string",
                                "description": "Initial message to Claude Code (default: 'Hello, I am ready to help')",
                            },
                        },
                        "required": ["computer", "project_dir"],
                    },
                ),
                Tool(
                    name="teleclaude__send_message",
                    description=(
                        "Send message to an existing Claude Code session. "
                        "Use teleclaude__list_sessions to find session_id "
                        "or teleclaude__start_session to create new one."
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
                        },
                        "required": ["session_id", "message"],
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict[str, object]) -> list[TextContent]:
            """Handle tool calls."""
            if name == "teleclaude__list_computers":
                computers = await self.teleclaude__list_computers()
                return [TextContent(type="text", text=str(computers))]
            elif name == "teleclaude__list_projects":
                computer = str(arguments.get("computer", "")) if arguments else ""
                projects = await self.teleclaude__list_projects(computer)
                return [TextContent(type="text", text=str(projects))]
            elif name == "teleclaude__list_sessions":
                computer_obj = arguments.get("computer") if arguments else None
                computer = str(computer_obj) if computer_obj else None
                sessions = await self.teleclaude__list_sessions(computer)
                return [TextContent(type="text", text=str(sessions))]
            elif name == "teleclaude__start_session":
                # Extract arguments explicitly
                computer = str(arguments.get("computer", "")) if arguments else ""
                project_dir_obj = arguments.get("project_dir") if arguments else None
                project_dir = str(project_dir_obj) if project_dir_obj else None
                initial_message = str(arguments.get("initial_message", "Hello, I am ready to help")) if arguments else "Hello, I am ready to help"
                result = await self.teleclaude__start_session(computer, project_dir, initial_message)
                return [TextContent(type="text", text=str(result))]
            elif name == "teleclaude__send_message":
                # Extract arguments explicitly
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                message = str(arguments.get("message", "")) if arguments else ""
                # Collect all chunks from async generator
                chunks: list[str] = []
                async for chunk in self.teleclaude__send_message(session_id, message):
                    chunks.append(chunk)
                result_text = "".join(chunks)
                return [TextContent(type="text", text=result_text)]
            else:
                raise ValueError(f"Unknown tool: {name}")

    async def start(self) -> None:
        """Start MCP server with configured transport."""
        # config already imported
        mcp_config = config.mcp.__dict__
        transport = mcp_config.get("transport", "socket")

        logger.info("Starting MCP server for %s (transport: %s)", self.computer_name, transport)

        if transport == "stdio":
            # Use stdio transport (for subprocess spawning)
            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(read_stream, write_stream, self.server.create_initialization_options())

        elif transport == "socket":
            # Use Unix socket transport (for connecting to running daemon)
            socket_path_str = os.path.expandvars(str(mcp_config.get("socket_path", "/tmp/teleclaude.sock")))
            socket_path = Path(socket_path_str)

            # Remove existing socket file if present
            if socket_path.exists():
                socket_path.unlink()

            logger.info("MCP server listening on socket: %s", socket_path)

            # Create Unix socket server using asyncio
            server = await asyncio.start_unix_server(
                lambda r, w: asyncio.create_task(self._handle_socket_connection(r, w)), path=str(socket_path)
            )

            # Make socket accessible
            socket_path.chmod(0o666)

            async with server:
                await server.serve_forever()

        else:
            raise NotImplementedError(f"Transport '{transport}' not yet implemented")

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
        """List available computers from all adapters.

        Returns:
            List of online computers with their info.
        """
        result: list[dict[str, object]] = await self.client.discover_peers()
        return result

    async def teleclaude__list_projects(self, computer: str) -> list[str]:
        """List available project directories on target computer.

        Args:
            computer: Target computer name

        Returns:
            List of trusted project directories
        """
        # Validate computer is online
        peers = await self.client.discover_peers()
        target_online = any(p["name"] == computer and p["status"] == "online" for p in peers)

        if not target_online:
            return []

        # Generate session ID for this query
        session_id = str(uuid.uuid4())

        # Send list_projects command via AdapterClient
        await self.client.send_remote_command(computer_name=computer, session_id=session_id, command="list_projects")

        # Stream response from AdapterClient
        result: list[str] = []
        try:
            async with asyncio.timeout(10):
                async for chunk in self.client.poll_remote_output(session_id, timeout=10.0):
                    # Look for JSON array response
                    if chunk.strip().startswith("["):
                        projects: list[str] = json.loads(chunk.strip())
                        result = projects
                        break
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for list_projects response from %s", computer)
            return []

        return result

    async def teleclaude__start_session(
        self, computer: str, project_dir: str, initial_message: str = "Hello, I am ready to help"
    ) -> dict[str, object]:
        """Start new Claude Code session on remote computer.

        Args:
            computer: Target computer name
            project_dir: Absolute path to project directory
            initial_message: Initial message to send (default greeting)

        Returns:
            dict with session_id and output
        """
        import shlex
        import uuid

        # Validate computer is online
        peers = await self.client.discover_peers()
        target_online = any(p["name"] == computer and p["status"] == "online" for p in peers)

        if not target_online:
            return {"status": "error", "message": f"Computer '{computer}' is offline"}

        # Generate Claude session UUID
        claude_session_id = str(uuid.uuid4())

        # Create session in database to track this AI-to-AI session
        title = f"AI:{computer}:{project_dir.split('/')[-1]}"
        session = await db.create_session(
            computer_name=self.computer_name,
            tmux_session_name=f"{self.computer_name}-ai-{claude_session_id[:8]}",
            origin_adapter="redis",
            title=title,
            adapter_metadata={
                "is_ai_to_ai": True,
                "is_auto_managed": True,
                "project_dir": project_dir,
                "target_computer": computer,
            },
            description=f"Auto-managed AI session for {project_dir} on {computer}",
        )

        session_id = session.session_id

        # Start Claude Code on remote computer via AdapterClient
        claude_cmd = f"cd {shlex.quote(project_dir)} && claude"
        await self.client.send_remote_command(
            computer_name=computer,
            session_id=session_id,
            command=claude_cmd,
            metadata={"title": title, "project_dir": project_dir},
        )

        # Send initial message and collect output
        chunks = []
        try:
            async with asyncio.timeout(30):  # 30s for initial startup
                async for chunk in self.client.poll_remote_output(session_id, timeout=30.0):
                    chunks.append(chunk)
                    # Stop after receiving initial response
                    if len(chunks) > 5:
                        break
        except asyncio.TimeoutError:
            return {
                "session_id": session_id,
                "status": "timeout",
                "output": f"[Warning: Claude Code on {computer} did not respond within 30s]",
            }

        return {"session_id": session_id, "status": "success", "output": "".join(chunks)}

    async def teleclaude__list_sessions(self, computer: Optional[str] = None) -> list[dict[str, object]]:
        """List AI-managed Claude Code sessions with rich metadata.

        Args:
            computer: Optional filter by target computer name

        Returns:
            List of session info dicts with metadata
        """
        # Get AI-managed sessions by searching for "AI:" title pattern
        sessions = await db.get_sessions_by_title_pattern("AI:")

        # Filter by computer if specified
        result = []
        for session in sessions:
            if computer and session.computer_name != computer:
                continue

            metadata = session.adapter_metadata or {}
            result.append(
                {
                    "session_id": session.session_id,
                    "computer": session.computer_name,
                    "target": metadata.get("target_computer"),
                    "project_dir": metadata.get("project_dir"),
                    "is_auto_managed": metadata.get("is_auto_managed", False),
                    "status": "closed" if session.closed else "active",
                    "created_at": session.created_at.isoformat(),
                    "last_activity": session.last_activity.isoformat(),
                }
            )

        return result

    async def teleclaude__send_message(self, session_id: str, message: str) -> AsyncIterator[str]:
        """Send message to existing AI-to-AI session and stream response.

        Args:
            session_id: Session ID from teleclaude__start_session
            message: Message/command to send to remote Claude Code

        Yields:
            str: Response chunks from remote Claude Code as they arrive
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

        # Send command to remote computer via AdapterClient
        try:
            await self.client.send_remote_command(computer_name=target_computer, session_id=session_id, command=message)
        except Exception as e:
            logger.error("Failed to send command to %s: %s", target_computer, e)
            yield f"[Error: Failed to send command: {str(e)}]"
            return

        # Stream output from AdapterClient
        try:
            async for chunk in self.client.poll_remote_output(session_id, timeout=300.0):
                yield chunk
        except asyncio.TimeoutError:
            yield "\n[Timeout: Session exceeded 5 minute limit]"
        except Exception as e:
            logger.error("Error streaming output for session %s: %s", session_id[:8], e)
            yield f"\n[Error: {str(e)}]"
