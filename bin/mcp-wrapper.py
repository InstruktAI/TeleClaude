#!/usr/bin/env python3
# pylint: skip-file
# mypy: ignore-errors
"""MCP wrapper that injects TeleClaude context and handles daemon restarts via transparent reconnection."""

from __future__ import annotations

import json
import os
import select
import socket
import sys
import time
from typing import MutableMapping, Optional

MCP_SOCKET = "/tmp/teleclaude.sock"
RECONNECT_DELAY = 0.5  # Seconds between reconnection attempts

# Context values to inject into arguments
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


class McpProxy:
    """Stateful proxy that maintains MCP connection across daemon restarts."""

    def __init__(self, socket_path: str):
        self.socket_path = socket_path
        self.sock: Optional[socket.socket] = None
        self.cached_initialize_request: Optional[dict] = None
        self.is_connected = False

        # Buffer for data from stdin when socket is down
        self.stdin_buffer: list[bytes] = []
        # Buffer for incomplete socket reads
        self.socket_buffer = b""

    def connect(self) -> bool:
        """Attempt to connect to the daemon socket."""
        try:
            if self.sock:
                self.sock.close()

            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect(self.socket_path)
            self.sock.setblocking(False)
            self.is_connected = True

            # If we are reconnecting (have cached init), perform silent handshake
            if self.cached_initialize_request:
                self._perform_silent_handshake()

            return True
        except (FileNotFoundError, ConnectionRefusedError, OSError):
            self.is_connected = False
            return False

    def _perform_silent_handshake(self):
        """Replay initialize request and swallow the response."""
        if not self.sock or not self.cached_initialize_request:
            return

        # 1. Send cached 'initialize'
        init_json = json.dumps(self.cached_initialize_request) + "\n"
        try:
            self.sock.sendall(init_json.encode())
        except OSError:
            self.is_connected = False
            return

        # 2. Consume responses until we get the result and the initialized notification
        # This is a blocking read with timeout because we MUST clear the pipe before allowing traffic
        self.sock.setblocking(True)
        self.sock.settimeout(2.0)

        try:
            temp_buffer = b""
            handshake_complete = False
            # We expect a response to ID and potentially a notification
            expected_id = self.cached_initialize_request.get("id")

            while not handshake_complete:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                temp_buffer += chunk

                while b"\n" in temp_buffer:
                    line, temp_buffer = temp_buffer.split(b"\n", 1)
                    try:
                        msg = json.loads(line)
                        # Check if this is the response to our init
                        if msg.get("id") == expected_id:
                            # Send 'notifications/initialized' if the protocol requires client to send it after result
                            # (MCP spec: Client sends initialized notification after receiving initialize result)
                            initialized_msg = {"jsonrpc": "2.0", "method": "notifications/initialized"}
                            self.sock.sendall((json.dumps(initialized_msg) + "\n").encode())
                            handshake_complete = True
                    except json.JSONDecodeError:
                        pass

        except (socket.timeout, OSError):
            # If handshake fails, we'll just try again in the main loop
            self.is_connected = False
        finally:
            if self.sock:
                self.sock.setblocking(False)

    def process_stdin_line(self, line: str) -> None:
        """Process a line from stdin (Agent -> Daemon)."""
        try:
            msg = json.loads(line)

            # Cache initialize request if seen
            if msg.get("method") == "initialize":
                self.cached_initialize_request = msg

            # Inject context into tool calls
            if msg.get("method") == "tools/call":
                params = msg.get("params", {})
                if isinstance(params, dict):
                    msg["params"] = inject_context(params)

            payload = (json.dumps(msg) + "\n").encode()

            if self.is_connected and self.sock:
                try:
                    self.sock.sendall(payload)
                except OSError:
                    self.is_connected = False
                    self.stdin_buffer.append(payload)
            else:
                self.stdin_buffer.append(payload)

        except json.JSONDecodeError:
            # Forward raw if not JSON (shouldn't happen in MCP, but safe fallback)
            payload = line.encode()
            if self.is_connected and self.sock:
                try:
                    self.sock.sendall(payload)
                except OSError:
                    self.is_connected = False
                    self.stdin_buffer.append(payload)
            else:
                self.stdin_buffer.append(payload)

    def run(self):
        """Main event loop."""
        # Initial connection with timeout
        start_time = time.time()
        while not self.connect():
            if time.time() - start_time > 5.0:
                # Fail gracefully so agent can continue (albeit without this tool)
                sys.stderr.write("Error: Could not connect to TeleClaude daemon within 5 seconds.\n")
                sys.exit(1)
            time.sleep(RECONNECT_DELAY)

        while True:
            # Prepare select lists
            readers = [sys.stdin]
            if self.is_connected and self.sock:
                readers.append(self.sock)

            try:
                # Wait for data (or timeout to retry connection)
                readable, _, _ = select.select(readers, [], [], RECONNECT_DELAY)
            except (ValueError, OSError):
                # Handle bad file descriptors
                if self.sock:
                    self.sock.close()
                self.is_connected = False
                continue

            # Check if we need to reconnect
            if not self.is_connected:
                if self.connect():
                    # Flush buffer
                    if self.sock:
                        try:
                            for packet in self.stdin_buffer:
                                self.sock.sendall(packet)
                            self.stdin_buffer.clear()
                        except OSError:
                            self.is_connected = False
                else:
                    # Still down, wait a bit
                    continue

            for source in readable:
                if source is sys.stdin:
                    line = sys.stdin.readline()
                    if not line:
                        # EOF from Agent -> Shutdown
                        return
                    self.process_stdin_line(line)

                elif source is self.sock:
                    try:
                        data = self.sock.recv(65536)
                        if not data:
                            # Socket closed by daemon
                            self.is_connected = False
                            if self.sock:
                                self.sock.close()
                            continue

                        self.socket_buffer += data
                        while b"\n" in self.socket_buffer:
                            line_bytes, self.socket_buffer = self.socket_buffer.split(b"\n", 1)
                            sys.stdout.write(line_bytes.decode() + "\n")
                            sys.stdout.flush()
                    except OSError:
                        self.is_connected = False
                        if self.sock:
                            self.sock.close()


if __name__ == "__main__":
    proxy = McpProxy(MCP_SOCKET)
    try:
        proxy.run()
    except KeyboardInterrupt:
        pass
