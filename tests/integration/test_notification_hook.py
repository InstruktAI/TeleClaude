"""Integration test for notification hook via MCP socket.

This test demonstrates that the MCP socket communication works correctly
for the notification hook. It requires the real daemon to be running.
"""

import json
import socket

import pytest


@pytest.mark.integration
def test_mcp_socket_notification_protocol():
    """Test that MCP send script can connect and send notification via socket protocol.

    This is a simplified test that verifies the MCP protocol handshake works.
    It requires the real TeleClaude daemon to be running with MCP socket at /tmp/teleclaude.sock.
    """
    socket_path = "/tmp/teleclaude.sock"

    try:
        # Connect to MCP socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(socket_path)

        # 1. Send initialize request
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        }
        sock.sendall((json.dumps(init_request) + "\n").encode())
        response = sock.recv(4096).decode("utf-8")
        init_response = json.loads(response)

        # Verify initialization succeeded
        assert "result" in init_response, f"Init failed: {init_response}"
        assert init_response["result"]["protocolVersion"] == "2024-11-05"

        # 2. Send initialized notification
        initialized_notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        sock.sendall((json.dumps(initialized_notif) + "\n").encode())

        # 3. Send tool call (with fake session_id)
        tool_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "teleclaude__send_notification",
                "arguments": {
                    "session_id": "nonexistent-session-id",
                    "message": "Test notification from pytest",
                },
            },
        }
        sock.sendall((json.dumps(tool_request) + "\n").encode())
        response = sock.recv(4096).decode("utf-8")
        tool_response = json.loads(response)

        # Verify we got a response (even if session doesn't exist, protocol worked)
        assert "id" in tool_response
        assert tool_response["id"] == 2

        # If error, it should be about session not found (expected)
        if "error" in tool_response:
            assert "not found" in tool_response["error"]["message"].lower()
        else:
            # Success case (if session existed)
            assert "result" in tool_response

        sock.close()

    except FileNotFoundError:
        pytest.skip("Daemon not running - /tmp/teleclaude.sock not found")
    except ConnectionRefusedError:
        pytest.skip("Daemon not running - connection refused")
    except Exception as e:
        pytest.fail(f"MCP protocol test failed: {e}")
