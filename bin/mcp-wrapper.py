#!/usr/bin/env python3
"""MCP wrapper that injects TeleClaude context into tool call arguments.

This wrapper runs as a subprocess of Claude Code (inheriting tmux env vars),
injects TeleClaude-specific context into tool call arguments,
then forwards to the actual TeleClaude MCP socket.

The MCP server extracts context from arguments once at the handler dispatch
level, so individual tool implementations don't need to care about it.

Usage in .mcp.json:
{
  "mcpServers": {
    "teleclaude": {
      "command": "python3",
      "args": ["/path/to/mcp-wrapper.py"]
    }
  }
}
"""

import json
import os
import select
import socket
import sys
from typing import Any

MCP_SOCKET = "/tmp/teleclaude.sock"

# Context values to inject into arguments
# Maps: argument_name -> environment_variable_name
CONTEXT_TO_INJECT = {
    "caller_session_id": "TELECLAUDE_SESSION_ID",
}


def inject_context(params: dict[str, Any]) -> dict[str, Any]:
    """Inject TeleClaude context into params.arguments.

    Creates arguments dict if it doesn't exist. Only injects values that are
    set in the environment. The MCP server extracts these centrally before
    dispatching to tool handlers.
    """
    arguments = params.get("arguments", {})
    if arguments is None:
        arguments = {}

    for field_name, env_var in CONTEXT_TO_INJECT.items():
        env_value = os.environ.get(env_var)
        if env_value:
            arguments[field_name] = env_value

    params["arguments"] = arguments
    return params


def process_message(message: dict[str, Any]) -> dict[str, Any]:
    """Process incoming MCP message, injecting context into tool calls."""
    if message.get("method") == "tools/call":
        params = message.get("params", {})
        message["params"] = inject_context(params)
    return message


def main() -> None:
    """Main loop: read from stdin, inject context, forward to socket, relay response."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(MCP_SOCKET)

    # Set socket to non-blocking for multiplexing
    sock.setblocking(False)

    # Buffer for incomplete messages
    socket_buffer = b""

    while True:
        # Wait for input from either stdin or socket
        readable, _, _ = select.select([sys.stdin, sock], [], [])

        for source in readable:
            if source == sys.stdin:
                # Read from stdin (Claude Code -> wrapper)
                line = sys.stdin.readline()
                if not line:
                    # EOF - Claude Code closed connection
                    sock.close()
                    return

                try:
                    message = json.loads(line)
                    processed = process_message(message)
                    # Forward to socket
                    sock.sendall((json.dumps(processed) + "\n").encode())
                except json.JSONDecodeError:
                    # Forward as-is if not valid JSON
                    sock.sendall(line.encode())

            elif source == sock:
                # Read from socket (TeleClaude daemon -> wrapper)
                try:
                    data = sock.recv(65536)
                    if not data:
                        # Socket closed
                        return
                    socket_buffer += data

                    # Process complete lines
                    while b"\n" in socket_buffer:
                        line_bytes, socket_buffer = socket_buffer.split(b"\n", 1)
                        # Forward to stdout (wrapper -> Claude Code)
                        sys.stdout.write(line_bytes.decode() + "\n")
                        sys.stdout.flush()
                except BlockingIOError:
                    # No data available yet
                    pass


if __name__ == "__main__":
    main()
