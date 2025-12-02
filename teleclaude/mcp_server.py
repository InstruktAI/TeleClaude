"""MCP server for TeleClaude multi-computer communication."""

import asyncio
import json
import logging
import os
import types
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Optional

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.server import Server
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, TextContent, Tool

from teleclaude.adapters.redis_adapter import RedisAdapter
from teleclaude.config import config
from teleclaude.core import command_handlers
from teleclaude.core.db import db
from teleclaude.core.events import TeleClaudeEvents
from teleclaude.core.models import MessageMetadata

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
                        "Start a new Claude Code session on a remote computer in a specific project. "
                        "**REQUIRED WORKFLOW:** "
                        "1) Call teleclaude__list_projects FIRST to discover available projects "
                        "2) Match and select the correct project from the results "
                        "3) Use the exact project path from list_projects in the project_dir parameter here. "
                        "Returns session_id. Wait 10 seconds then use teleclaude__get_session_data to check progress."
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
                                    "The initial task or prompt to send to Claude Code "
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
                        "Send message to an existing Claude Code session. "
                        "After calling this tool, wait a few seconds then use teleclaude__get_session_data "
                        "to retrieve the session output and see the response. "
                        "Use teleclaude__list_sessions to find session_id or "
                        "teleclaude__start_session to create new one."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "computer": {
                                "type": "string",
                                "description": "Target computer name (same as used in teleclaude__start_session)",
                            },
                            "session_id": {
                                "type": "string",
                                "description": "Session ID from teleclaude__start_session",
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
                    name="teleclaude__get_session_data",
                    title="TeleClaude: Get Session Data",
                    description=(
                        "Retrieve session data from a remote computer's Claude Code session. "
                        "Reads from the claude_session_file which contains complete session history. "
                        "Optionally filter by timestamp to get only recent messages. "
                        "**Use this to check on delegated work** after teleclaude__send_message. "
                        "**Replaces**: teleclaude__get_session_status (use this instead for new code)"
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
                    name="teleclaude__handle_claude_event",
                    title="TeleClaude: Handle Claude Event",
                    description=(
                        "Emit Claude Code events to registered listeners. "
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
                                "description": "Type of Claude event (e.g., 'stop', 'compact')",
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

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict[str, object]) -> list[TextContent]:
            """Handle tool calls."""
            logger.debug("MCP call_tool() invoked: name=%s, arguments=%s", name, arguments)
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
                computer = arguments.get("computer", "local") if arguments else "local"
                sessions = await self.teleclaude__list_sessions(computer)
                return [TextContent(type="text", text=json.dumps(sessions, default=str))]
            elif name == "teleclaude__start_session":
                # All arguments required by MCP schema - no fallbacks needed
                if not arguments:
                    raise ValueError("Arguments required for teleclaude__start_session")
                computer = str(arguments["computer"])
                project_dir = str(arguments["project_dir"])
                title = str(arguments["title"])
                message = str(arguments["message"])
                result = await self.teleclaude__start_session(computer, project_dir, title, message)
                return [TextContent(type="text", text=json.dumps(result, default=str))]
            elif name == "teleclaude__send_message":
                # Extract arguments explicitly
                computer = str(arguments.get("computer", "")) if arguments else ""
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                message = str(arguments.get("message", "")) if arguments else ""
                # Collect all chunks from async generator
                chunks: list[str] = []
                async for chunk in self.teleclaude__send_message(computer, session_id, message):
                    chunks.append(chunk)
                result_text = "".join(chunks)
                return [TextContent(type="text", text=result_text)]
            elif name == "teleclaude__get_session_data":
                computer = str(arguments.get("computer", "")) if arguments else ""
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                since_timestamp_obj = arguments.get("since_timestamp") if arguments else None
                since_timestamp = str(since_timestamp_obj) if since_timestamp_obj else None
                result = await self.teleclaude__get_session_data(computer, session_id, since_timestamp)
                return [TextContent(type="text", text=json.dumps(result, default=str))]
            elif name == "teleclaude__deploy_to_all_computers":
                # No arguments - always deploys to ALL computers
                deploy_result: dict[str, dict[str, object]] = await self.teleclaude__deploy_to_all_computers()
                return [TextContent(type="text", text=json.dumps(deploy_result, default=str))]
            elif name == "teleclaude__send_file":
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                file_path = str(arguments.get("file_path", "")) if arguments else ""
                caption_obj = arguments.get("caption") if arguments else None
                caption = str(caption_obj) if caption_obj else None
                result_text = await self.teleclaude__send_file(session_id, file_path, caption)
                return [TextContent(type="text", text=result_text)]
            elif name == "teleclaude__handle_claude_event":
                session_id = str(arguments.get("session_id", "")) if arguments else ""
                event_type = str(arguments.get("event_type", "")) if arguments else ""
                data_obj = arguments.get("data") if arguments else None
                data = dict(data_obj) if isinstance(data_obj, dict) else {}
                result_text = await self.teleclaude__handle_claude_event(session_id, event_type, data)
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
        logger.debug("teleclaude__list_computers() called")
        result: list[dict[str, object]] = await self.client.discover_peers()  # Adapter returns Any for backward compat
        logger.debug("teleclaude__list_computers() returning %d computers", len(result))
        return result

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

        # Send list_projects command via AdapterClient
        # Transport layer generates request_id from Redis message ID
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
    ) -> dict[str, object]:
        """Create remote session via request/response pattern.

        Client mode creates NO local session - only sends request to remote computer
        which creates session in its own database and returns session_id.

        This follows the unified adapter architecture where only ONE session exists
        (on the remote computer), and the client pulls data on demand.

        Design by contract: Assumes computer is online. Fails explicitly if offline.

        Args:
            computer: Target computer name (from teleclaude__list_computers)
            project_dir: Absolute path to project directory on remote computer
                (from teleclaude__list_projects)
            title: Session title describing the task (use "TEST: {description}" for testing sessions)
            message: Initial task or prompt to send to Claude Code

        Returns:
            dict with remote session_id and status
        """

        # Validate computer is online - fail fast if not
        peers = await self.client.discover_peers()
        target_online = any(p["name"] == computer and p["status"] == "online" for p in peers)

        if not target_online:
            return {"status": "error", "message": f"Computer '{computer}' is offline"}

        # Send new_session command to remote - uses standardized handle_create_session
        # Transport layer generates request_id from Redis message ID
        metadata = MessageMetadata(project_dir=project_dir, title=title)

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
                return {"status": "error", "message": f"Remote session creation failed: {error_msg}"}

            # Extract session_id from success response
            data = envelope.get("data", {})
            remote_session_id = data.get("session_id") if isinstance(data, dict) else None

            if not remote_session_id:
                return {"status": "error", "message": "Remote did not return session_id"}

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

            # Send /claude command with message to start Claude Code
            await self.client.send_request(
                computer_name=computer,
                command=f"/claude '{message}'",
                metadata=MessageMetadata(),
                session_id=str(remote_session_id),
            )
            logger.debug("Sent /claude command with message to remote session %s", remote_session_id[:8])

            return {"session_id": remote_session_id, "status": "success"}

        except TimeoutError:
            return {"status": "error", "message": "Timeout waiting for remote session creation"}
        except Exception as e:
            logger.error("Failed to create remote session: %s", e)
            return {"status": "error", "message": f"Failed to create remote session: {str(e)}"}

    async def teleclaude__list_sessions(self, computer: Optional[str] = "local") -> list[dict[str, object]]:
        """List sessions from local or remote computer(s).

        Args:
            computer: Which computer(s) to query:
                - "local" (default): Query local database only
                - None: Query ALL computers via Redis
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
            - computer: Computer name (only for remote queries)
        """
        if computer == "local":
            # Query local database directly
            sessions_data = await command_handlers.handle_list_sessions()
            return sessions_data

        # Query remote computer(s) via Redis
        redis_adapter = self.client.adapters.get("redis")
        if not redis_adapter:
            logger.warning("Redis adapter not available - cannot query remote sessions")
            return []

        # Start with local sessions when querying all computers
        all_sessions: list[dict[str, object]] = []
        if computer is None:
            # Include local sessions first
            local_sessions = await command_handlers.handle_list_sessions()
            for session in local_sessions:
                session["computer"] = self.computer_name
            all_sessions.extend(local_sessions)
            # Then get all online remote computers
            computers_to_query = await redis_adapter._get_online_computers()
        else:
            # Query specific remote computer only
            computers_to_query = [computer]

        # Aggregate sessions from all target computers
        for computer_name in computers_to_query:
            try:
                # Send list_sessions request via Redis
                message_id = await redis_adapter.send_request(computer_name, "list_sessions", MessageMetadata())

                # Wait for response (short timeout)
                response_data = await self.client.read_response(message_id, timeout=3.0)
                sessions = json.loads(response_data.strip())

                # Add computer_name to each session for aggregation
                for session in sessions:
                    session["computer"] = computer_name
                all_sessions.extend(sessions)

            except (TimeoutError, Exception) as e:
                logger.warning("Failed to get sessions from %s: %s", computer_name, e)
                continue

        return all_sessions

    async def teleclaude__send_message(self, computer: str, session_id: str, message: str) -> AsyncIterator[str]:
        """Send message to remote session via request/response pattern.

        Simplified design - no local session, no streaming. Just sends message to remote
        and returns acknowledgment. Use teleclaude__get_session_data to pull results.

        Args:
            computer: Target computer name
            session_id: Remote session ID (from teleclaude__start_session)
            message: Message/command to send to remote Claude Code

        Yields:
            str: Acknowledgment message
        """
        try:
            await self.client.send_request(
                computer_name=computer,
                command=f"message {message}",
                session_id=session_id,
                metadata=MessageMetadata(),
            )

            yield f"Message sent to session {session_id[:8]}. Use teleclaude__get_session_data to check output."

        except Exception as e:
            logger.error("Failed to send message to session %s: %s", session_id[:8], e)
            yield f"[Error: Failed to send message: {str(e)}]"

    async def teleclaude__get_session_data(
        self,
        computer: str,
        session_id: str,
        since_timestamp: Optional[str] = None,
    ) -> dict[str, object]:
        """Get session data from remote computer.

        Pulls accumulated session data from claude_session_file on remote computer.

        Args:
            computer: Target computer name
            session_id: Session ID on remote computer
            since_timestamp: Optional ISO 8601 UTC timestamp

        Returns:
            Dict with session data, status, and messages
        """
        # Build command with optional timestamp
        command = f"/get_session_data {since_timestamp}" if since_timestamp else "/get_session_data"

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
        computers = [str(peer.name) for peer in all_peers if peer.name != self.computer_name]

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

    async def teleclaude__handle_claude_event(self, session_id: str, event_type: str, data: dict[str, object]) -> str:
        """Emit Claude Code event to registered listeners (called by Claude Code hooks).

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

        # Emit event to registered listeners
        await self.client.handle_event(
            TeleClaudeEvents.CLAUDE_EVENT,
            {"session_id": session_id, "event_type": event_type, "data": data},  # type: ignore[dict-item]
            MessageMetadata(adapter_type="internal"),
        )

        logger.debug("Emitted Claude event: session=%s, type=%s", session_id[:8], event_type)
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

        # Send notification as feedback (UI only, never to terminal)
        # UI adapters: shows message + auto-deletes on next input
        # Transport adapters (Redis): no-op, prevents typing into tmux
        message_id = await self.client.send_feedback(session, message, MessageMetadata())

        # Mark notification message for cleanup on next user input (if UI adapter returned message_id)
        if message_id:
            await db.add_pending_deletion(session_id, message_id)

        # Set notification_sent flag (prevents idle notifications)
        await db.set_notification_flag(session_id, True)

        return f"OK: {message_id}" if message_id else "OK: no-op (transport adapter)"
