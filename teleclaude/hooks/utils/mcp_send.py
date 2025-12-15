#!/usr/bin/env python3
"""Send notification to TeleClaude via MCP socket.

Gracefully handles missing TeleClaude installation - returns silently if socket doesn't exist.
"""

import json
import socket
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from utils.file_log import append_line

MCP_SOCKET = "/tmp/teleclaude.sock"
LOG_DIR = Path.home() / ".teleclaude" / "logs"
LOG_FILE = LOG_DIR / "mcp_send.log"


def log(message: str) -> None:
    """Write log message to file."""
    try:
        append_line(LOG_FILE, f"[{datetime.now().isoformat()}] {message}")
    except Exception:
        pass


def mcp_send(tool: str, payload: Dict[str, Any]) -> None:
    """Invoke tool call in TeleClaude via MCP socket.

    Gracefully handles missing TeleClaude - returns silently if socket doesn't exist.

    Args:
        tool: TeleClaude tool name to invoke
        payload: Arguments for the tool call, MUST contain 'session_id' key
    """
    try:
        log("=== mcp_send() called ===")
        log(f"MCP tool: {tool}")
        log(f"TeleClaude session ID: {payload.get('session_id')}")

        # Check if TeleClaude is available (socket exists)
        if not Path(MCP_SOCKET).exists():
            log("TeleClaude not running (socket not found), skipping")
            return  # Silent no-op

        log(f"Payload: {payload}")

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
                "clientInfo": {"name": "teleclaude-hook", "version": "1.0.0"},
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

        # 3. Send notification to TeleClaude session
        tool_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool,
                "arguments": payload,
            },
        }
        tool_response = send_message(sock, tool_request)
        log(f"Tool response: {json.dumps(tool_response)}")

        sock.close()
        log("Socket closed successfully")
        log("=== mcp_send() finished ===\n")

    except (FileNotFoundError, ConnectionRefusedError, OSError) as e:
        # TeleClaude not available - silent no-op for global config compatibility
        log(f"TeleClaude not available: {e}")
    except Exception as e:
        log(f"ERROR: {str(e)}")
        log(f"Traceback: {traceback.format_exc()}")
        # Don't re-raise - graceful degradation for global config


def send_message(sock: socket.socket, message: Dict[str, Any]) -> Dict[str, Any]:
    """Send a JSON-RPC message and read response."""
    log(f"Sending: {json.dumps(message)}")
    sock.sendall((json.dumps(message) + "\n").encode())
    response = sock.recv(4096).decode("utf-8")
    log(f"Received: {response}")
    return json.loads(response)
