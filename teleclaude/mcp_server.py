"""MCP server for TeleClaude multi-computer communication."""

import asyncio
import logging
import re
import time
from typing import Any, AsyncIterator, Optional

from mcp.server import Server
from mcp.types import TextContent, Tool

from teleclaude.config import get_config

logger = logging.getLogger(__name__)


class TeleClaudeMCPServer:
    """MCP server for exposing TeleClaude functionality to Claude Code."""

    def __init__(
        self,
        telegram_adapter: Any,
        terminal_bridge: Any,
        session_manager: Any,
        computer_registry: Any,
        adapter_client: Any = None,  # NEW: Unified client for multi-adapter support
    ):
        config = get_config()

        self.telegram_adapter = telegram_adapter
        self.terminal_bridge = terminal_bridge
        self.session_manager = session_manager
        self.computer_registry = computer_registry  # Kept for backward compatibility
        self.client = adapter_client  # NEW: Unified client (preferred for peer discovery)

        self.computer_name = config["computer"]["name"]
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
                    description="List available project directories on a target computer (from trusted_dirs config)",
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
                        "(project_dir, status, claude_session_id). Use to discover existing sessions before starting new ones."
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
                                    "Absolute path to project directory (e.g., '/home/user/apps/TeleClaude')"
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
                        "Use teleclaude__list_sessions to find session_id or teleclaude__start_session to create new one."
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
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            """Handle tool calls."""
            if name == "teleclaude__list_computers":
                computers = await self.teleclaude__list_computers()
                return [TextContent(type="text", text=str(computers))]
            elif name == "teleclaude__list_projects":
                projects = await self.teleclaude__list_projects(**arguments)
                return [TextContent(type="text", text=str(projects))]
            elif name == "teleclaude__list_sessions":
                sessions = await self.teleclaude__list_sessions(**arguments)
                return [TextContent(type="text", text=str(sessions))]
            elif name == "teleclaude__start_session":
                # Streaming response - collect session_id + output
                result = await self.teleclaude__start_session(**arguments)
                return [TextContent(type="text", text=str(result))]
            elif name == "teleclaude__send_message":
                # Streaming response - collect output
                result = await self.teleclaude__send_message(**arguments)
                return [TextContent(type="text", text=str(result))]
            else:
                raise ValueError(f"Unknown tool: {name}")

    async def start(self) -> None:
        """Start MCP server with configured transport."""
        import os
        from pathlib import Path

        config = get_config()
        transport = config.get("mcp", {}).get("transport", "socket")

        logger.info("Starting MCP server for %s (transport: %s)", self.computer_name, transport)

        if transport == "stdio":
            # Use stdio transport (for subprocess spawning)
            from mcp.server.stdio import stdio_server

            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(read_stream, write_stream, self.server.create_initialization_options())

        elif transport == "socket":
            # Use Unix socket transport (for connecting to running daemon)
            socket_path = os.path.expandvars(config.get("mcp", {}).get("socket_path", "/tmp/teleclaude.sock"))
            socket_path = Path(socket_path)

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
        import anyio
        import mcp.types as types
        from anyio.streams.memory import (
            MemoryObjectReceiveStream,
            MemoryObjectSendStream,
        )
        from mcp.shared.message import SessionMessage

        logger.info("New MCP client connected")
        try:
            # Create memory streams like stdio_server does
            read_stream_writer: MemoryObjectSendStream
            read_stream: MemoryObjectReceiveStream
            write_stream: MemoryObjectSendStream
            write_stream_reader: MemoryObjectReceiveStream

            read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
            write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

            async def socket_reader():
                """Read from socket and parse JSON-RPC messages."""
                try:
                    async with read_stream_writer:
                        while True:
                            line = await reader.readline()
                            if not line:
                                break
                            try:
                                message = types.JSONRPCMessage.model_validate_json(line.decode("utf-8"))
                                await read_stream_writer.send(SessionMessage(message))
                            except Exception as exc:
                                await read_stream_writer.send(exc)
                except anyio.ClosedResourceError:
                    pass

            async def socket_writer():
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

    async def teleclaude__list_computers(self) -> list[dict[str, Any]]:
        """List available computers from all adapters.

        Returns:
            List of online computers with their info.
        """
        return await self.client.discover_peers()

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

        # Create temporary topic for /list_projects command
        topic_name = f"_temp_list_projects_{computer}_{int(time.time())}"
        topic = await self.telegram_adapter.create_topic(topic_name)
        topic_id = topic.message_thread_id

        try:
            # Register listener for response
            queue = await self.telegram_adapter.register_mcp_listener(topic_id)

            # Send /list_projects command
            await self.telegram_adapter.send_message_to_topic(topic_id, "/list_projects", parse_mode=None)

            # Wait for response (JSON list of directories)
            try:
                async with asyncio.timeout(10):
                    while True:
                        msg = await queue.get()
                        if msg.text and msg.text.strip().startswith("["):
                            # Parse JSON response
                            import json

                            projects = json.loads(msg.text.strip())
                            return projects
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for /list_projects response from %s", computer)
                return []

        finally:
            # Cleanup
            await self.telegram_adapter.unregister_mcp_listener(topic_id)
            # Note: Can't easily delete topic via Bot API, leave it (low impact)

    async def teleclaude__start_session(
        self, computer: str, project_dir: str, initial_message: str = "Hello, I am ready to help"
    ) -> dict[str, Any]:
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

        # Create Telegram topic
        topic_name = f"AI:{computer}:{project_dir.split('/')[-1]}"
        topic = await self.telegram_adapter.create_topic(topic_name)
        topic_id = topic.message_thread_id

        # Create session in database
        session = await self.session_manager.create_session(
            computer_name=self.computer_name,
            tmux_session_name=f"{self.computer_name}-ai-{topic_id}",
            adapter_type="telegram",
            title=topic_name,
            adapter_metadata={
                "channel_id": str(topic_id),
                "is_ai_to_ai": True,
                "is_auto_managed": True,
                "project_dir": project_dir,
                "claude_session_id": claude_session_id,
            },
            description=f"Auto-managed AI session for {project_dir}",
        )

        session_id = session.session_id

        # Start Claude Code on remote computer
        claude_cmd = (
            f"cd {shlex.quote(project_dir)} && "
            f"claude --dangerously-skip-permissions --session-id {claude_session_id}"
        )
        await self.telegram_adapter.send_message_to_topic(topic_id, f"/command {claude_cmd}", parse_mode=None)

        # Wait for Claude ready
        try:
            await self._wait_for_claude_ready(session_id, topic_id, timeout=10)
        except TimeoutError:
            return {
                "session_id": session_id,
                "status": "timeout",
                "output": f"[Warning: Claude Code on {computer} did not respond within 10s]",
            }

        # Send initial message and collect output
        chunks = []
        async for chunk in self.teleclaude__send(session_id, initial_message):
            chunks.append(chunk)

        return {"session_id": session_id, "status": "success", "output": "".join(chunks)}

    async def _wait_for_claude_ready(self, session_id: str, topic_id: int, timeout: float = 10.0) -> None:
        """Wait for Claude Code to send ACK (any message) in the topic.

        Uses event-driven queue - no polling.

        Args:
            session_id: Session ID
            topic_id: Telegram topic ID
            timeout: Max seconds to wait

        Raises:
            TimeoutError: If no ACK received within timeout
        """
        # Register listener queue for instant event-driven delivery
        queue = await self.telegram_adapter.register_mcp_listener(topic_id)

        try:
            # Wait for ACK with timeout
            async with asyncio.timeout(timeout):
                while True:
                    msg = await queue.get()

                    # Skip our own /claude_resume message
                    if msg.text and msg.text.strip() == "/claude_resume":
                        continue

                    # Any other message = ACK received
                    logger.info("Received ACK from remote Claude Code in session %s", session_id[:8])
                    return
        except asyncio.TimeoutError:
            raise TimeoutError(f"No ACK from remote Claude Code after {timeout}s")
        finally:
            # Always unregister (cleanup)
            await self.telegram_adapter.unregister_mcp_listener(topic_id)

    async def teleclaude__list_sessions(self, computer: Optional[str] = None) -> list[dict[str, Any]]:
        """List AI-managed Claude Code sessions with rich metadata.

        Args:
            computer: Optional filter by target computer name

        Returns:
            List of session info dicts with metadata
        """
        # Get all sessions with is_ai_to_ai flag
        all_sessions = await self.session_manager.get_all_sessions()

        # Filter for AI-managed sessions
        result = []
        for session in all_sessions:
            metadata = session.adapter_metadata or {}
            is_ai = metadata.get("is_ai_to_ai", False)
            is_auto_managed = metadata.get("is_auto_managed", False)

            # Skip non-AI sessions
            if not (is_ai or is_auto_managed):
                continue

            # Filter by computer if specified
            if computer and session.computer_name != computer:
                continue

            # Extract project_dir from metadata
            project_dir = metadata.get("project_dir")

            # Parse target computer from title (if AI-to-AI format)
            target = None
            if session.title:
                match = re.match(r"^\$\w+ > \$(\w+) - ", session.title)
                if match:
                    target = match.group(1)

            result.append(
                {
                    "session_id": session.session_id,
                    "computer": session.computer_name,
                    "target": target,
                    "project_dir": project_dir,
                    "claude_session_id": metadata.get("claude_session_id"),
                    "is_auto_managed": is_auto_managed,
                    "status": "closed" if session.closed else "active",
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat() if session.updated_at else None,
                }
            )

        return result

    async def teleclaude__send(self, session_id: str, message: str) -> AsyncIterator[str]:
        """Send message to existing AI-to-AI session and stream response.

        Args:
            session_id: Session ID from teleclaude__start_session
            message: Message/command to send to remote Claude Code

        Yields:
            str: Response chunks from remote Claude Code as they arrive
        """
        # Get session from database
        session = await self.session_manager.get_session(session_id)
        if not session:
            yield "[Error: Session not found]"
            return

        # Verify session is active
        if session.closed:
            yield "[Error: Session is closed]"
            return

        # Send message to tmux session
        try:
            await self.terminal_bridge.send_keys(session.tmux_session_name, message)
        except Exception as e:
            logger.error("Failed to send message to session %s: %s", session_id[:8], e)
            yield f"[Error: Failed to send message: {str(e)}]"
            return

        # Stream output (event-driven queue for instant delivery)
        topic_id = int(session.adapter_metadata.get("channel_id"))

        # Register listener for instant event-driven delivery
        queue = await self.telegram_adapter.register_mcp_listener(topic_id)

        try:
            # Stream chunks as they arrive (up to 5 minutes total timeout)
            timeout = 300
            idle_count = 0
            max_idle_polls = 120  # 120 * 0.5s = 60 seconds max idle
            heartbeat_interval = 60  # Send heartbeat every 60s if no output
            last_yield_time = time.time()

            async with asyncio.timeout(timeout):
                while True:
                    try:
                        # Wait for next message (with 0.5s timeout for idle detection)
                        msg = await asyncio.wait_for(queue.get(), timeout=0.5)

                        # Got message - reset idle counter
                        idle_count = 0

                        if not msg.text:
                            continue

                        # Check for completion marker
                        if "[Output Complete]" in msg.text:
                            logger.info("Received completion marker for session %s", session_id[:8])
                            return  # End stream

                        # Extract chunk content (strip markdown and markers)
                        content = self._extract_chunk_content(msg.text)
                        if content:
                            yield content
                            last_yield_time = time.time()

                    except asyncio.TimeoutError:
                        # No message for 0.5 seconds
                        idle_count += 1

                        # Send heartbeat if no output for a while
                        if time.time() - last_yield_time > heartbeat_interval:
                            yield "[⏳ Waiting for response...]\n"
                            last_yield_time = time.time()

                        # Timeout if idle too long
                        if idle_count >= max_idle_polls:
                            yield "\n[Timeout: No response from remote computer for 60 seconds]"
                            return

        except asyncio.TimeoutError:
            # Overall timeout (5 minutes)
            yield "\n[Timeout: Session exceeded 5 minute limit]"
        finally:
            # Always unregister (cleanup)
            await self.telegram_adapter.unregister_mcp_listener(topic_id)

    async def teleclaude__send_message(self, session_id: str, message: str) -> dict[str, Any]:
        """Send message to existing Claude Code session.

        Args:
            session_id: Session ID from teleclaude__start_session or teleclaude__list_sessions
            message: Message or command to send

        Returns:
            dict with output
        """
        # Verify session exists
        session = await self.session_manager.get_session(session_id)
        if not session:
            return {"status": "error", "message": "Session not found"}
        if session.closed:
            return {"status": "error", "message": "Session is closed"}

        # Send message and collect output
        chunks = []
        async for chunk in self.teleclaude__send(session_id, message):
            chunks.append(chunk)

        return {"status": "success", "output": "".join(chunks)}

    def _extract_chunk_content(self, message_text: str) -> str:
        """Extract actual output from chunk message.

        Strips markdown code fences and chunk markers.

        Args:
            message_text: Raw message text from Telegram

        Returns:
            Extracted content without formatting
        """
        if not message_text:
            return ""

        # Remove markdown code fences
        content = message_text.replace("```sh", "").replace("```", "")
        # Remove chunk markers
        content = re.sub(r"\[Chunk \d+/\d+\]", "", content)
        return content.strip()
