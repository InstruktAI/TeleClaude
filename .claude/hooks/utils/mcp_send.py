#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Send notification to TeleClaude via MCP socket (reads JSON from stdin)."""

import json
import socket
import traceback
from datetime import datetime
from pathlib import Path

MCP_SOCKET = "/tmp/teleclaude.sock"
LOG_FILE = Path.cwd() / ".claude" / "hooks" / "logs" / "mcp_send.log"


def log(message: str) -> None:
    """Write log message to file."""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            timestamp = datetime.now().isoformat()
            f.write(f"[{timestamp}] {message}\n")
    except:
        pass


def mcp_send(session_id: str, message: str) -> None:
    """Send notification to TeleClaude via MCP socket.

    Args:
        session_id: Session UUID
        message: Message to send
    """
    try:
        log("=== mcp_send() called ===")
        log(f"Session ID: {session_id}")
        log(f"Message: {message}")

        # Connect to MCP socket
        log(f"Connecting to socket: {MCP_SOCKET}")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(MCP_SOCKET)
        log("Socket connected")

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
        init_response = send_message(sock, init_request)
        log(f"Initialize response: {json.dumps(init_response)}")

        # 2. Send initialized notification
        initialized_notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        log(f"Sending initialized notification: {json.dumps(initialized_notif)}")
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
        tool_response = send_message(sock, tool_request)
        log(f"Tool response: {json.dumps(tool_response)}")

        sock.close()
        log("Socket closed successfully")
        log("=== mcp_send() finished ===\n")

    except Exception as e:
        log(f"ERROR: {str(e)}")
        log(f"Traceback: {traceback.format_exc()}")
        raise


def send_message(sock: socket.socket, message: dict) -> dict:
    """Send a JSON-RPC message and read response."""
    log(f"Sending: {json.dumps(message)}")
    sock.sendall((json.dumps(message) + "\n").encode())
    response = sock.recv(4096).decode("utf-8")
    log(f"Received: {response}")
    return json.loads(response)
