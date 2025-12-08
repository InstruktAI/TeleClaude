#!/usr/bin/env python3
# pylint: skip-file
# mypy: ignore-errors
"""MCP wrapper that injects TeleClaude context into tool call arguments."""

from __future__ import annotations

import json
import os
import select
import socket
import sys
from typing import MutableMapping

MCP_SOCKET = "/tmp/teleclaude.sock"

# Context values to inject into arguments
# Maps: argument_name -> environment_variable_name
CONTEXT_TO_INJECT: dict[str, str] = {"caller_session_id": "TELECLAUDE_SESSION_ID"}


def inject_context(params: MutableMapping[str, object]) -> MutableMapping[str, object]:
    """Inject TeleClaude context into params.arguments."""
    arguments_obj = params.get("arguments")
    arguments: MutableMapping[str, object] = dict(arguments_obj) if isinstance(arguments_obj, MutableMapping) else {}

    for field_name, env_var in CONTEXT_TO_INJECT.items():
        env_value = os.environ.get(env_var)
        if env_value is not None:
            arguments[field_name] = env_value

    params["arguments"] = arguments
    return params


def process_message(message: MutableMapping[str, object]) -> MutableMapping[str, object]:
    """Process incoming MCP message, injecting context into tool calls."""
    if message.get("method") == "tools/call":
        params_value = message.get("params")
        params: MutableMapping[str, object] = params_value if isinstance(params_value, MutableMapping) else {}
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
            if source is sys.stdin:
                # Read from stdin (Claude Code -> wrapper)
                line = sys.stdin.readline()
                if not line:
                    # EOF - Claude Code closed connection
                    sock.close()
                    return

                try:
                    parsed: object = json.loads(line)
                except json.JSONDecodeError:
                    sock.sendall(line.encode())
                    continue

                if isinstance(parsed, MutableMapping):
                    processed = process_message(parsed)
                    sock.sendall((json.dumps(processed) + "\n").encode())
                else:
                    sock.sendall(line.encode())

            elif source is sock:
                # Read from socket (TeleClaude daemon -> wrapper)
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


if __name__ == "__main__":
    main()
