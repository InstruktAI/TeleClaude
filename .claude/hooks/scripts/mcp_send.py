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

        # Send MCP request
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "teleclaude__send_notification",
                "arguments": {
                    "session_id": session_id,
                    "message": message,
                },
            },
        }

        sock.sendall((json.dumps(request) + "\n").encode())
        sock.recv(4096)
        sock.close()

    except:
        pass  # Fail silently

    sys.exit(0)


if __name__ == "__main__":
    main()
