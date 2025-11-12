#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Send notification to TeleClaude via MCP socket (reads JSON from stdin)."""

import json
import socket
import sys

MCP_SOCKET = "/tmp/teleclaude.sock"


def send_message(sock: socket.socket, message: dict) -> dict:
    """Send a JSON-RPC message and read response."""
    sock.sendall((json.dumps(message) + "\n").encode())
    response = sock.recv(4096).decode("utf-8")
    return json.loads(response)


def main() -> None:
    """Read session_id and message from stdin, send to MCP socket."""
    try:
        # Read JSON from stdin
        data = json.load(sys.stdin)
        session_id = data.get("session_id")
        message = data.get("message")

        if not session_id or not message:
            sys.exit(1)

        # Connect to MCP socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(MCP_SOCKET)

        # 1. Send initialize request
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "claude-code-hook", "version": "1.0.0"},
            },
        }
        send_message(sock, init_request)

        # 2. Send initialized notification
        initialized_notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        sock.sendall((json.dumps(initialized_notif) + "\n").encode())

        # 3. Send tool call request
        tool_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "teleclaude__send_notification",
                "arguments": {
                    "session_id": session_id,
                    "message": message,
                },
            },
        }
        send_message(sock, tool_request)

        sock.close()

    except:
        pass  # Fail silently

    sys.exit(0)


if __name__ == "__main__":
    main()
