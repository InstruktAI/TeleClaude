#!/usr/bin/env python3
# pylint: skip-file
# mypy: ignore-errors
"""Resilient MCP wrapper that handles backend server restarts.

Dynamically extracts tool definitions from mcp_server.py at startup.
"""

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import MutableMapping

# Configure logging to file (NEVER stdout/stderr - breaks MCP stdio transport)
LOG_FILE = Path(__file__).parent.parent / "logs" / "mcp-wrapper.log"
LOG_FILE.parent.mkdir(exist_ok=True)
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

MCP_SOCKET = "/tmp/teleclaude.sock"
CONTEXT_TO_INJECT: dict[str, str] = {"caller_session_id": "TELECLAUDE_SESSION_ID"}
RECONNECT_DELAY = 5
CONNECTION_TIMEOUT = 10

# If true, always proxy to backend (never use cached handshake)
DISABLE_STATIC_HANDSHAKE = os.getenv("MCP_DISABLE_STATIC_HANDSHAKE", "false").lower() == "true"


def extract_tools_from_mcp_server() -> list[str]:
    """Extract tool names from mcp_server.py by grepping for teleclaude__ pattern.

    Excludes internal-only tools that should not be exposed to MCP clients.
    """
    script_dir = Path(__file__).parent
    mcp_server_path = script_dir.parent / "teleclaude" / "mcp_server.py"

    if not mcp_server_path.exists():
        logger.warning("mcp_server.py not found at %s", mcp_server_path)
        return []

    content = mcp_server_path.read_text()
    # Match: name="teleclaude__something"
    pattern = r'name="(teleclaude__[a-z_]+)"'
    matches = re.findall(pattern, content)

    # Exclude internal-only tools (used by hooks, not for client invocation)
    excluded = {"teleclaude__handle_agent_event"}
    tools = [tool for tool in matches if tool not in excluded]

    return list(dict.fromkeys(tools))  # Dedupe while preserving order


def build_response_template(tool_names: list[str]) -> tuple[str, str]:
    """Pre-build response templates with placeholder for request ID.

    Returns:
        Tuple of (response_template, notification) where response_template
        contains __REQUEST_ID__ placeholder for string replacement.
    """
    # Pre-serialize response structure for maximum speed
    # Use string template with unique placeholder to avoid JSON parsing overhead at runtime
    tools_json = json.dumps(tool_names)
    # Build template with __REQUEST_ID__ placeholder for str.replace()
    response_template = (
        '{"jsonrpc":"2.0","id":__REQUEST_ID__,"result":{'
        '"protocolVersion":"2024-11-05",'
        '"capabilities":{"tools":{}},'
        '"serverInfo":{"name":"TeleClaude","version":"1.0.0","tools_available":' + tools_json + "}}}"
    )
    notification = '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'
    return response_template, notification


# Extract tools and pre-build templates at module load time (zero runtime overhead)
TOOL_NAMES = extract_tools_from_mcp_server()
RESPONSE_TEMPLATE, NOTIFICATION = build_response_template(TOOL_NAMES)


def inject_context(params: MutableMapping[str, object]) -> MutableMapping[str, object]:
    """Inject context from environment variables into tool call params."""
    arguments = params.get("arguments", {})
    if not isinstance(arguments, MutableMapping):
        arguments = {}

    for param_name, env_var in CONTEXT_TO_INJECT.items():
        if param_name not in arguments:
            env_value = os.environ.get(env_var)
            if env_value:
                arguments[param_name] = env_value

    params["arguments"] = arguments
    return params


def process_message(
    message: MutableMapping[str, object],
) -> MutableMapping[str, object]:
    """Process outgoing messages, injecting context where needed."""
    if message.get("method") == "tools/call":
        params = message.get("params")
        if isinstance(params, MutableMapping):
            message["params"] = inject_context(params)
    return message


class MCPProxy:
    """Async proxy between MCP client (stdio) and TeleClaude server (unix socket)."""

    def __init__(self):
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.connected = asyncio.Event()
        self.shutdown = asyncio.Event()

    async def connect(self) -> bool:
        """Connect to backend socket with timeout."""
        while not self.shutdown.is_set():
            try:
                logger.info("Connecting to %s...", MCP_SOCKET)
                self.reader, self.writer = await asyncio.wait_for(
                    asyncio.open_unix_connection(MCP_SOCKET),
                    timeout=CONNECTION_TIMEOUT,
                )
                self.connected.set()
                logger.info("Connected to backend")
                return True
            except FileNotFoundError:
                logger.warning("Socket not found. Retrying in %ss...", RECONNECT_DELAY)
            except ConnectionRefusedError:
                logger.warning("Connection refused. Retrying in %ss...", RECONNECT_DELAY)
            except asyncio.TimeoutError:
                logger.warning("Connection timeout. Retrying in %ss...", RECONNECT_DELAY)
            except Exception as e:
                logger.error("Connection error: %s. Retrying in %ss...", e, RECONNECT_DELAY)

            await asyncio.sleep(RECONNECT_DELAY)
        return False

    async def reconnect(self):
        """Handle reconnection after disconnect."""
        self.connected.clear()
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass
        self.reader = None
        self.writer = None
        await self.connect()

    async def stdin_to_socket(self, stdin_reader: asyncio.StreamReader):
        """Forward stdin to backend socket."""
        try:
            while not self.shutdown.is_set():
                line = await stdin_reader.readline()
                if not line:
                    self.shutdown.set()
                    break

                # Process message (inject context)
                try:
                    msg = json.loads(line.decode())
                    if isinstance(msg, MutableMapping):
                        msg = process_message(msg)
                        line = (json.dumps(msg) + "\n").encode()
                except json.JSONDecodeError:
                    pass

                # Wait for connection and send
                await self.connected.wait()
                if self.writer and not self.shutdown.is_set():
                    try:
                        self.writer.write(line)
                        await self.writer.drain()
                    except (ConnectionResetError, BrokenPipeError):
                        logger.warning("Backend disconnected, reconnecting...")
                        asyncio.create_task(self.reconnect())
        except Exception as e:
            logger.error("stdin_to_socket error: %s", e)

    async def socket_to_stdout(self):
        """Forward backend socket to stdout, filtering internal tools from responses."""
        try:
            while not self.shutdown.is_set():
                await self.connected.wait()
                if not self.reader or self.shutdown.is_set():
                    continue

                try:
                    line = await self.reader.readline()
                    if not line:
                        logger.info("Backend closed connection")
                        asyncio.create_task(self.reconnect())
                        continue

                    # Filter internal tools from tools/list responses
                    try:
                        msg = json.loads(line.decode())
                        if (
                            isinstance(msg, dict)
                            and "result" in msg
                            and isinstance(msg.get("result"), dict)
                            and "tools" in msg["result"]
                        ):
                            # This is a tools/list response - filter internal tools
                            tools = msg["result"]["tools"]
                            if isinstance(tools, list):
                                msg["result"]["tools"] = [
                                    tool
                                    for tool in tools
                                    if not (
                                        isinstance(tool, dict) and tool.get("name") == "teleclaude__handle_agent_event"
                                    )
                                ]
                                line = (json.dumps(msg) + "\n").encode()
                                logger.debug("Filtered internal tools from tools/list response")
                    except (json.JSONDecodeError, KeyError):
                        # Not a JSON message or not a tools response - pass through unchanged
                        pass

                    sys.stdout.buffer.write(line)
                    sys.stdout.buffer.flush()
                except (ConnectionResetError, BrokenPipeError):
                    logger.warning("Backend disconnected")
                    asyncio.create_task(self.reconnect())
        except Exception as e:
            logger.error("socket_to_stdout error: %s", e)

    async def handle_initialize(self, stdin_reader: asyncio.StreamReader) -> bool:
        """Handle MCP initialize request.

        Returns True if initialization succeeded, False otherwise.
        """
        line = await stdin_reader.readline()
        if not line:
            return False

        try:
            line_str = line.decode()
            msg = json.loads(line_str)

            if msg.get("method") == "initialize":
                request_id = msg.get("id", 1)

                # Determine timeout based on static handshake setting
                timeout = None if DISABLE_STATIC_HANDSHAKE else 0.5

                # Wait for backend - if it connects, proxy the real handshake
                try:
                    await asyncio.wait_for(self.connected.wait(), timeout=timeout)
                    # Backend is ready! Forward the initialize request
                    logger.info("Backend ready, proxying initialize request")
                    if self.writer:
                        self.writer.write(line)
                        await self.writer.drain()
                    # Don't send cached response - let backend handle it
                except asyncio.TimeoutError:
                    # Backend not ready yet, send cached response for zero-downtime
                    logger.info("Backend not ready, using cached handshake (id=%s)", request_id)
                    response = RESPONSE_TEMPLATE.replace("__REQUEST_ID__", str(request_id))
                    combined = f"{response}\n{NOTIFICATION}\n"
                    sys.stdout.buffer.write(combined.encode())
                    sys.stdout.buffer.flush()
                return True

        except json.JSONDecodeError as e:
            logger.error("Handshake error: %s", e)
            return False

        return True

    async def run(self):
        """Main proxy loop."""
        # Setup stdin reader
        stdin_reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(stdin_reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        # Try to connect to backend immediately (with short timeout for fast clients like Codex)
        quick_connect = asyncio.create_task(self.connect())

        # Handle MCP initialize request
        init_ok = await self.handle_initialize(stdin_reader)
        if not init_ok:
            logger.error("Initialize failed, shutting down")
            return

        # Start message pumps (connect task already running)
        stdin_task = asyncio.create_task(self.stdin_to_socket(stdin_reader))
        stdout_task = asyncio.create_task(self.socket_to_stdout())

        try:
            await asyncio.gather(quick_connect, stdin_task, stdout_task)
        except asyncio.CancelledError:
            pass
        finally:
            self.shutdown.set()
            if self.writer:
                self.writer.close()


def main():
    """Entry point."""
    logger.info("MCP wrapper starting. Extracted tools: %s", TOOL_NAMES)
    proxy = MCPProxy()
    asyncio.run(proxy.run())


if __name__ == "__main__":
    main()
