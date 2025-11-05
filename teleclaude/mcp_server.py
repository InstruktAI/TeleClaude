"""MCP server for TeleClaude multi-computer communication."""

import asyncio
import logging
import re
import time
from typing import Any, AsyncIterator, Optional

from mcp.server import Server
from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)


class TeleClaudeMCPServer:
    """MCP server for exposing TeleClaude functionality to Claude Code."""

    def __init__(
        self, config: dict, telegram_adapter: Any, terminal_bridge: Any, session_manager: Any, computer_registry: Any
    ):
        self.config = config
        self.telegram_adapter = telegram_adapter
        self.terminal_bridge = terminal_bridge
        self.session_manager = session_manager
        self.computer_registry = computer_registry

        self.computer_name = config["computer"]["name"]
        self.server = Server("teleclaude")

        # Setup MCP tool handlers
        self._setup_tools()

    def _setup_tools(self):
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
                    name="teleclaude__start_session",
                    description="Start a new AI-to-AI session with a remote computer's Claude Code",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "target": {
                                "type": "string",
                                "description": "Target computer name (e.g., 'workstation', 'server')",
                            },
                            "title": {
                                "type": "string",
                                "description": "Short title for the session (e.g., 'Check logs', 'Debug issue')",
                            },
                            "description": {
                                "type": "string",
                                "description": "Detailed description of why this session was created",
                            },
                        },
                        "required": ["target", "title", "description"],
                    },
                ),
                Tool(
                    name="teleclaude__list_sessions",
                    description="List AI-to-AI sessions initiated by this computer",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "target": {"type": "string", "description": "Optional filter by target computer name"}
                        },
                    },
                ),
                Tool(
                    name="teleclaude__send",
                    description="Send message to an existing AI-to-AI session and get response",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Session ID from teleclaude__start_session",
                            },
                            "message": {
                                "type": "string",
                                "description": "Message or command to send to remote Claude Code",
                            },
                        },
                        "required": ["session_id", "message"],
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            """Handle tool calls."""
            if name == "teleclaude__list_computers":
                result = await self.teleclaude__list_computers()
                return [TextContent(type="text", text=str(result))]
            elif name == "teleclaude__start_session":
                result = await self.teleclaude__start_session(**arguments)
                return [TextContent(type="text", text=str(result))]
            elif name == "teleclaude__list_sessions":
                result = await self.teleclaude__list_sessions(**arguments)
                return [TextContent(type="text", text=str(result))]
            elif name == "teleclaude__send":
                # Streaming response - collect all chunks and return as single TextContent
                chunks = []
                async for chunk in self.teleclaude__send(**arguments):
                    chunks.append(chunk)
                output = "".join(chunks)
                return [TextContent(type="text", text=output)]
            else:
                raise ValueError(f"Unknown tool: {name}")

    async def start(self):
        """Start MCP server with stdio transport."""
        transport = self.config.get("mcp", {}).get("transport", "stdio")

        logger.info("Starting MCP server for %s (transport: %s)", self.computer_name, transport)

        if transport == "stdio":
            # Use stdio transport for Claude Code integration
            from mcp.server.stdio import stdio_server

            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(read_stream, write_stream, self.server.create_initialization_options())
        else:
            raise NotImplementedError(f"Transport '{transport}' not yet implemented")

    async def teleclaude__list_computers(self) -> list[dict]:
        """List available computers from in-memory registry.

        Returns:
            List of online computers with their info.
        """
        return self.computer_registry.get_online_computers()

    async def teleclaude__start_session(self, target: str, title: str, description: str) -> dict:
        """Start new AI-to-AI session with remote computer.

        Args:
            target: Computer name (e.g., "workstation", "server")
            title: Short title for the session
            description: Detailed description of why this session was created

        Returns:
            dict with session_id, topic_name, status, message
        """
        # Validate target is online
        if not self.computer_registry.is_computer_online(target):
            return {
                "status": "error",
                "message": f"Computer '{target}' is offline",
                "available": [c["name"] for c in self.computer_registry.get_online_computers()],
            }

        # Create topic name
        topic_name = f"${self.computer_name} > ${target} - {title}"

        # Create Telegram topic
        topic = await self.telegram_adapter.create_topic(topic_name)
        topic_id = topic.message_thread_id

        # Create session in database with description
        session = await self.session_manager.create_session(
            computer_name=self.computer_name,
            tmux_session_name=f"{self.computer_name}-ai-{topic_id}",
            adapter_type="telegram",
            title=topic_name,
            adapter_metadata={"channel_id": str(topic_id), "is_ai_to_ai": True},
            description=description,
        )

        # Send /claude_resume to wake remote Claude Code
        await self.telegram_adapter.send_message_to_topic(topic_id, "/claude_resume", parse_mode=None)

        # Wait for Claude Code ready (ACK detection)
        try:
            await self._wait_for_claude_ready(session.session_id, topic_id, timeout=10)
        except TimeoutError:
            logger.warning("Timeout waiting for Claude Code ACK on %s", target)
            return {
                "session_id": session.session_id,
                "topic_name": topic_name,
                "status": "timeout",
                "message": f"Session created but {target} did not respond (timeout after 10s)",
            }

        return {
            "session_id": session.session_id,
            "topic_name": topic_name,
            "status": "ready",
            "message": f"Session ready with {target}",
        }

    async def _wait_for_claude_ready(self, session_id: str, topic_id: int, timeout: float = 10.0):
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

    async def teleclaude__list_sessions(self, target: Optional[str] = None) -> list[dict]:
        """List AI-to-AI sessions initiated by this computer.

        Args:
            target: Optional filter by target computer name

        Returns:
            List of session info dicts
        """
        # Query sessions with AI-to-AI pattern from this computer
        pattern = f"${self.computer_name} > $"
        if target:
            pattern = f"${self.computer_name} > ${target} - "

        sessions = await self.session_manager.get_sessions_by_title_pattern(pattern)

        # Parse and return session info
        result = []
        for session in sessions:
            # Parse topic name: $Initiator > $Target - Title
            match = re.match(r"^\$\w+ > \$(\w+) - (.+)$", session.title)
            if match:
                result.append(
                    {
                        "session_id": session.session_id,
                        "target": match.group(1),
                        "title": match.group(2),
                        "description": session.description,
                        "status": "closed" if session.closed else "active",
                        "created_at": session.created_at.isoformat(),
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
