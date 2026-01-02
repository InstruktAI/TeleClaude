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
import signal
import sys
import threading
import time
from pathlib import Path
from typing import MutableMapping, TypedDict

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

MCP_SOCKET = "/tmp/teleclaude.sock"
# Map parameter names to env var names. Special value None means use os.getcwd()
CONTEXT_TO_INJECT: dict[str, str | None] = {
    "caller_session_id": "TELECLAUDE_SESSION_ID",
    "cwd": None,  # Special: inject os.getcwd() instead of env var
}
RECONNECT_DELAY = 5
CONNECTION_TIMEOUT = 10
REQUEST_TIMEOUT = 15.0
RESPONSE_TIMEOUT = REQUEST_TIMEOUT
INIT_TIMEOUT = 5.0
LONG_RUNNING_TOOL_TIMEOUTS = {
    "teleclaude__run_agent_command": 30.0,
    "teleclaude__start_session": 30.0,
}
STDIN_CONNECT_TIMEOUT = float(os.getenv("MCP_WRAPPER_STDIN_CONNECT_TIMEOUT", "5"))
STARTUP_TIMEOUT = float(os.getenv("MCP_WRAPPER_STARTUP_TIMEOUT", "20"))
RESPONSE_CHECK_INTERVAL = float(os.getenv("MCP_WRAPPER_RESPONSE_CHECK_INTERVAL", "0.5"))
TIMED_OUT_RETENTION = float(os.getenv("MCP_WRAPPER_TIMEOUT_RETENTION", "300"))
GUARD_CHECK_INTERVAL = float(os.getenv("MCP_WRAPPER_GUARD_INTERVAL", "0.5"))
OUTBOUND_QUEUE_MAX = int(os.getenv("MCP_WRAPPER_OUTBOUND_QUEUE_MAX", "200"))
# Keep logs human-friendly by default: no repeated spam while waiting for a restart
# or when running in a restricted environment that can't connect to the socket.
LOG_THROTTLE_S = 60.0
_EPERM_BACKOFF_S = 60.0

_ERR_BACKEND_UNAVAILABLE = -32000
_STARTUP_COMPLETE = threading.Event()


class _QueueItem(TypedDict):
    raw: bytes
    request_id: object | None
    method: str | None
    enqueued_at: float
    attempts: int


def _jsonrpc_error_response(request_id: object, message: str) -> bytes:
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": _ERR_BACKEND_UNAVAILABLE,
            "message": message,
        },
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


def _extract_request_meta(raw_line: bytes) -> tuple[object | None, str | None, str | None]:
    """Best-effort parse of JSON-RPC request metadata (never raises)."""
    try:
        msg = json.loads(raw_line.decode("utf-8"))
    except Exception:
        return None, None, None
    if not isinstance(msg, dict):
        return None, None, None
    method = msg.get("method")
    tool_name: str | None = None
    if method == "tools/call":
        params = msg.get("params")
        if isinstance(params, dict):
            tool_name = params.get("name") if isinstance(params.get("name"), str) else None
    return msg.get("id"), method, tool_name


def _get_response_timeout(method: str | None, tool_name: str | None) -> float:
    if method == "tools/call" and tool_name:
        return LONG_RUNNING_TOOL_TIMEOUTS.get(tool_name, RESPONSE_TIMEOUT)
    return RESPONSE_TIMEOUT


def extract_tools_from_mcp_server() -> list[str]:
    """Extract tool names from mcp_server.py by grepping for teleclaude__ pattern.

    Excludes internal-only tools that should not be exposed to MCP clients.
    """
    mcp_server_path = _get_mcp_server_path()

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


def build_response_template(tool_names: list[str]) -> str:
    """Pre-build response template with placeholder for request ID."""
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
    return response_template


def _get_mcp_server_path() -> Path:
    script_dir = Path(__file__).parent
    return script_dir.parent / "teleclaude" / "mcp_server.py"


# Mutable cache so long-lived wrapper processes can refresh after code updates.
_TOOL_CACHE_MTIME: float | None = None
TOOL_NAMES: list[str] = []
RESPONSE_TEMPLATE: str = ""


def refresh_tool_cache_if_needed(force: bool = False) -> None:
    """Refresh cached tool names/templates if teleclaude/mcp_server.py changed.

    This matters for long-lived MCP clients: if the wrapper serves a cached
    handshake while the backend is restarting, the tool list must match the
    current server code (not whatever was present when the wrapper first started).
    """
    global _TOOL_CACHE_MTIME, TOOL_NAMES, RESPONSE_TEMPLATE  # pylint: disable=global-statement

    try:
        mcp_server_path = _get_mcp_server_path()
        mtime = mcp_server_path.stat().st_mtime
    except Exception:
        mtime = None

    if not force and mtime is not None and _TOOL_CACHE_MTIME is not None and mtime <= _TOOL_CACHE_MTIME:
        return

    TOOL_NAMES = extract_tools_from_mcp_server()
    RESPONSE_TEMPLATE = build_response_template(TOOL_NAMES)
    _TOOL_CACHE_MTIME = mtime
    logger.info("Tool cache refreshed (count=%d)", len(TOOL_NAMES))


# Initialize cache at import time
refresh_tool_cache_if_needed(force=True)


def inject_context(params: MutableMapping[str, object]) -> MutableMapping[str, object]:
    """Inject context from environment variables into tool call params.

    Special handling for 'cwd': uses os.getcwd() instead of an env var.
    """
    arguments = params.get("arguments", {})
    if not isinstance(arguments, MutableMapping):
        arguments = {}

    for param_name, env_var in CONTEXT_TO_INJECT.items():
        if param_name not in arguments:
            if env_var is None:
                # Special case: cwd uses os.getcwd()
                if param_name == "cwd":
                    arguments[param_name] = os.getcwd()
            else:
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
        # Backend is a separate MCP server process. If it restarts, it requires a
        # fresh initialize + notifications/initialized sequence even if the client
        # remains connected to this wrapper process.
        self._needs_backend_resync = False
        self._suppress_backend_init_messages = False
        self._backend_init_response = asyncio.Event()
        self._backend_generation = 0
        self._pending_requests: dict[object, float] = {}
        self._timed_out_requests: dict[object, float] = {}
        self._pending_started: dict[object, float] = {}

        self._client_initialize_request: bytes | None = None
        self._client_initialize_id: object | None = None
        self._client_initialized_notification: bytes | None = None

        self.shutdown = asyncio.Event()
        self._reconnect_task: asyncio.Task[None] | None = None
        self._reconnect_lock = asyncio.Lock()
        self._outbound: asyncio.Queue[_QueueItem] = asyncio.Queue(maxsize=OUTBOUND_QUEUE_MAX)
        self._sender_task: asyncio.Task[None] | None = None
        self._log_last_at: dict[str, float] = {}
        self._log_throttle_s: float = LOG_THROTTLE_S
        self._connect_hard_error_seen = False

    def _log_throttled(self, key: str, level: int, message: str, *args: object) -> None:
        """Log a message at most once per throttle window for a given key."""
        now = asyncio.get_running_loop().time()
        last_at = self._log_last_at.get(key)
        if last_at is not None and (now - last_at) < self._log_throttle_s:
            logger.debug("%s (throttled)", message % args if args else message)
            return
        self._log_last_at[key] = now
        logger.log(level, message, *args)

    def _schedule_reconnect(self, reason: str) -> None:
        """Schedule a reconnect exactly once.

        Without this guard, a backend EOF can cause a tight loop that spawns
        unbounded reconnect tasks/logs, leading to runaway memory/disk usage.
        """
        if self.shutdown.is_set():
            return

        # Stop read/write loops from continuing while we reconnect.
        if self.connected.is_set():
            self.connected.clear()
        self._backend_init_response.clear()
        # The next backend connection will need a fresh MCP handshake even though
        # the client doesn't re-initialize.
        self._needs_backend_resync = True
        self._suppress_backend_init_messages = True

        existing = self._reconnect_task
        if existing and not existing.done():
            return

        try:
            self._log_throttled(f"reconnect:{reason}", logging.INFO, "Scheduling reconnect (%s)", reason)
        except RuntimeError:
            # No running loop yet; fall back to direct logging.
            logger.info("Scheduling reconnect (%s)", reason)

        async def _runner() -> None:
            async with self._reconnect_lock:
                try:
                    await self.reconnect()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.error("Reconnect task failed: %s", exc)

        self._reconnect_task = asyncio.create_task(_runner())

    async def connect(self) -> bool:
        """Connect to backend socket with timeout."""
        while not self.shutdown.is_set():
            try:
                self._log_throttled("connect:attempt", logging.INFO, "Connecting to %s...", MCP_SOCKET)
                self.reader, self.writer = await asyncio.wait_for(
                    asyncio.open_unix_connection(MCP_SOCKET),
                    timeout=CONNECTION_TIMEOUT,
                )
                self.connected.set()
                self._backend_generation += 1
                logger.info("Connected to backend")
                self._connect_hard_error_seen = False
                return True
            except FileNotFoundError:
                self._log_throttled(
                    "connect:missing", logging.WARNING, "Socket not found. Retrying in %ss...", RECONNECT_DELAY
                )
            except ConnectionRefusedError:
                self._log_throttled(
                    "connect:refused", logging.WARNING, "Connection refused. Retrying in %ss...", RECONNECT_DELAY
                )
            except asyncio.TimeoutError:
                self._log_throttled(
                    "connect:timeout", logging.WARNING, "Connection timeout. Retrying in %ss...", RECONNECT_DELAY
                )
            except PermissionError as e:
                # In some environments, unix socket connects can be blocked (EPERM).
                # Don't spam logs; back off longer and log at most once per throttle window.
                if not self._connect_hard_error_seen:
                    logger.error(
                        "Permission denied connecting to %s (%s). Backing off for %ss.",
                        MCP_SOCKET,
                        e,
                        int(_EPERM_BACKOFF_S),
                    )
                    self._connect_hard_error_seen = True
                else:
                    self._log_throttled(
                        "connect:perm",
                        logging.ERROR,
                        "Permission denied connecting to %s (%s). Backing off for %ss.",
                        MCP_SOCKET,
                        e,
                        int(_EPERM_BACKOFF_S),
                    )
                await asyncio.sleep(_EPERM_BACKOFF_S)
                continue
            except Exception as e:
                # EPERM can happen in sandboxed contexts; throttle to avoid log spam.
                self._log_throttled(
                    "connect:error", logging.ERROR, "Connection error: %s. Retrying in %ss...", e, RECONNECT_DELAY
                )

            await asyncio.sleep(RECONNECT_DELAY)
        return False

    async def reconnect(self):
        """Handle reconnection after disconnect."""
        self.connected.clear()
        self._backend_init_response.clear()
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass
        self.reader = None
        self.writer = None
        await self.connect()

    async def _resync_backend_handshake(self, timeout_s: float) -> bool:
        """Replay MCP handshake to backend after backend restart.

        The MCP client does NOT re-send initialize after daemon restart; without
        replaying the handshake, backend tool calls can hang or fail.
        """
        if timeout_s <= 0:
            return False
        if not self._client_initialize_request or self._client_initialize_id is None:
            logger.warning("Cannot resync backend: missing stored initialize request")
            return False

        if not self.writer:
            return False

        self._backend_init_response.clear()

        try:
            self.writer.write(self._client_initialize_request)
            await self.writer.drain()
        except Exception as exc:
            logger.warning("Failed writing initialize to backend: %s", exc)
            return False

        try:
            await asyncio.wait_for(self._backend_init_response.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            logger.warning("Backend did not respond to initialize within %.1fs", timeout_s)
            return False

        # Per MCP sequence, send client's notifications/initialized after init response.
        if self._client_initialized_notification:
            try:
                self.writer.write(self._client_initialized_notification)
                await self.writer.drain()
            except Exception as exc:
                logger.warning("Failed writing notifications/initialized to backend: %s", exc)
                return False

        logger.info("Backend handshake resynced successfully")
        return True

    async def _send_error(self, request_id: object, message: str) -> None:
        """Send an error response to the client (never raises)."""
        try:
            sys.stdout.buffer.write(_jsonrpc_error_response(request_id, message))
            sys.stdout.buffer.flush()
        except Exception:
            # Never write to stderr; best-effort only.
            pass

    async def _fail_request(self, request_id: object, message: str) -> None:
        """Mark a request failed and send an error response."""
        now = asyncio.get_running_loop().time()
        self._pending_requests.pop(request_id, None)
        self._timed_out_requests[request_id] = now
        started_at = self._pending_started.pop(request_id, None)
        if started_at is not None:
            logger.debug(
                "Wrapper request failed",
                request_id=request_id,
                elapsed=round(now - started_at, 3),
                reason=message,
                queue_size=self._outbound.qsize(),
                pending=len(self._pending_requests),
            )
        await self._send_error(request_id, message)

    async def _response_timeout_watcher(self) -> None:
        """Send timeout errors for requests that never receive a backend response."""
        loop = asyncio.get_running_loop()
        while not self.shutdown.is_set():
            now = loop.time()
            expired = [request_id for request_id, deadline in self._pending_requests.items() if deadline <= now]
            for request_id in expired:
                await self._fail_request(
                    request_id,
                    "TeleClaude backend did not respond in time. Please retry.",
                )

            if self._timed_out_requests:
                cutoff = now - TIMED_OUT_RETENTION
                self._timed_out_requests = {
                    request_id: ts for request_id, ts in self._timed_out_requests.items() if ts >= cutoff
                }

            await asyncio.sleep(RESPONSE_CHECK_INTERVAL)

    async def stdin_to_socket(self, stdin_reader: asyncio.StreamReader):
        """Forward stdin to backend socket.

        IMPORTANT: Never block the stdin reader waiting for backend connection.
        If we block here, the OS pipe backpressures the client and tool calls "hang".
        Instead, enqueue requests in a bounded queue and let the sender task handle
        connection/retry/timeout behavior.
        """
        try:
            while not self.shutdown.is_set():
                line = await stdin_reader.readline()
                if not line:
                    self.shutdown.set()
                    break

                request_id, method, tool_name = _extract_request_meta(line)
                response_timeout = _get_response_timeout(method, tool_name)

                # Process message (inject context)
                try:
                    msg = json.loads(line.decode())
                    if isinstance(msg, MutableMapping):
                        # Capture client handshake messages for replay across backend restarts.
                        if msg.get("method") == "initialize":
                            self._client_initialize_request = (json.dumps(msg) + "\n").encode("utf-8")
                            self._client_initialize_id = msg.get("id")
                        elif msg.get("method") == "notifications/initialized":
                            self._client_initialized_notification = (json.dumps(msg) + "\n").encode("utf-8")

                        msg = process_message(msg)
                        line = (json.dumps(msg) + "\n").encode()
                except json.JSONDecodeError:
                    pass

                item: _QueueItem = {
                    "raw": line,
                    "request_id": request_id,
                    "method": method,
                    "enqueued_at": asyncio.get_running_loop().time(),
                    "attempts": 0,
                }
                if request_id is not None:
                    self._pending_requests[request_id] = asyncio.get_running_loop().time() + response_timeout
                    self._pending_started[request_id] = asyncio.get_running_loop().time()
                    logger.debug(
                        "Wrapper request queued",
                        request_id=request_id,
                        method=method,
                        tool_name=tool_name,
                        response_timeout=response_timeout,
                        queue_size=self._outbound.qsize(),
                        pending=len(self._pending_requests),
                    )

                try:
                    self._outbound.put_nowait(item)
                except asyncio.QueueFull:
                    # Bounded memory: if we can't queue, fail fast for requests.
                    if request_id is not None:
                        await self._fail_request(
                            request_id,
                            "TeleClaude backend is restarting or busy (wrapper queue full). Please retry.",
                        )
                    else:
                        self._log_throttled(
                            "outbound:queue_full:notify",
                            logging.WARNING,
                            "Dropping notification due to full outbound queue",
                        )
        except Exception as e:
            logger.error("stdin_to_socket error: %s", e)

    async def _socket_sender(self) -> None:
        """Drain outbound queue and write to backend when available.

        Provides bounded buffering + timeout-based failure instead of hanging clients.
        """
        while True:
            if self.shutdown.is_set() and self._outbound.empty():
                break
            try:
                item = await asyncio.wait_for(self._outbound.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if self.shutdown.is_set():
                break

            request_id = item.get("request_id")
            method = item.get("method")
            deadline = item["enqueued_at"] + REQUEST_TIMEOUT

            try:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                await asyncio.wait_for(self.connected.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                if request_id is not None:
                    await self._fail_request(
                        request_id,
                        "TeleClaude backend unavailable (restarting). Please retry.",
                    )
                continue

            if not self.writer or self.shutdown.is_set():
                if request_id is not None:
                    await self._fail_request(
                        request_id,
                        "TeleClaude backend unavailable. Please retry.",
                    )
                continue

            # If backend restarted, it needs a fresh MCP handshake even though the
            # client won't re-send initialize. Perform resync before forwarding
            # ANY queued messages (including notifications/initialized).
            if self._needs_backend_resync:
                self._suppress_backend_init_messages = True
                remaining = deadline - asyncio.get_running_loop().time()
                ok = await self._resync_backend_handshake(remaining)
                self._needs_backend_resync = False
                if not ok:
                    if request_id is not None:
                        await self._fail_request(
                            request_id,
                            "TeleClaude backend restarted but handshake replay failed. Please retry.",
                        )
                    continue
                self._suppress_backend_init_messages = False
                # Avoid sending a duplicate notifications/initialized during
                # startup when the client itself sends it right after initialize.
                if method == "notifications/initialized" and request_id is None:
                    continue

            try:
                self.writer.write(item["raw"])
                await self.writer.drain()
                if request_id is not None:
                    logger.debug(
                        "Wrapper request sent",
                        request_id=request_id,
                        method=method,
                        queue_size=self._outbound.qsize(),
                        pending=len(self._pending_requests),
                    )
            except (ConnectionResetError, BrokenPipeError):
                self._log_throttled(
                    "backend:disconnect:send",
                    logging.WARNING,
                    "Backend disconnected while sending (method=%s)",
                    method,
                )
                self._schedule_reconnect("send failure")
                # Retry once by re-queueing; if it fails again, error out.
                attempts = int(item.get("attempts", 0)) + 1
                if attempts >= 2:
                    if request_id is not None:
                        await self._fail_request(
                            request_id,
                            "TeleClaude backend disconnected during request. Please retry.",
                        )
                else:
                    item["attempts"] = attempts
                    try:
                        self._outbound.put_nowait(item)
                    except asyncio.QueueFull:
                        if request_id is not None:
                            await self._fail_request(
                                request_id,
                                "TeleClaude backend restarting (queue full). Please retry.",
                            )
            except Exception as e:
                self._log_throttled("backend:send:error", logging.WARNING, "Failed sending request to backend: %s", e)
                if request_id is not None:
                    await self._fail_request(
                        request_id,
                        "TeleClaude backend error. Please retry.",
                    )

    async def socket_to_stdout(self):
        """Forward backend socket to stdout, filtering internal tools from responses."""
        try:
            while not self.shutdown.is_set():
                try:
                    await asyncio.wait_for(self.connected.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if not self.reader or self.shutdown.is_set():
                    continue

                try:
                    line = await self.reader.readline()
                    if not line:
                        self._log_throttled("backend:eof", logging.INFO, "Backend closed connection (EOF)")
                        self._schedule_reconnect("backend EOF")
                        # Wait before next iteration to prevent tight loop when
                        # backend keeps accepting then closing connections
                        await asyncio.sleep(RECONNECT_DELAY)
                        continue

                    # Swallow backend initialize response during resync so the client
                    # doesn't see a second initialize response after daemon restart.
                    try:
                        msg = json.loads(line.decode("utf-8"))
                        if (
                            self._suppress_backend_init_messages
                            and isinstance(msg, dict)
                            and msg.get("id") == self._client_initialize_id
                            and "result" in msg
                        ):
                            self._backend_init_response.set()
                            continue
                    except json.JSONDecodeError:
                        msg = None

                    if isinstance(msg, dict):
                        response_id = msg.get("id")
                        if response_id in self._pending_requests:
                            self._pending_requests.pop(response_id, None)
                            started_at = self._pending_started.pop(response_id, None)
                            if started_at is not None:
                                logger.debug(
                                    "Wrapper response received",
                                    request_id=response_id,
                                    elapsed=round(asyncio.get_running_loop().time() - started_at, 3),
                                )
                        elif response_id in self._timed_out_requests:
                            # Late response after we already errored out; drop it.
                            self._timed_out_requests.pop(response_id, None)
                            started_at = self._pending_started.pop(response_id, None)
                            if started_at is not None:
                                logger.debug(
                                    "Wrapper response dropped (late)",
                                    request_id=response_id,
                                    elapsed=round(asyncio.get_running_loop().time() - started_at, 3),
                                )
                            continue

                    # Filter internal tools from tools/list responses
                    try:
                        if msg is None:
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
                    self._log_throttled("backend:disconnect:read", logging.WARNING, "Backend disconnected")
                    self._schedule_reconnect("backend disconnect")
                    await asyncio.sleep(RECONNECT_DELAY)
        except Exception as e:
            logger.error("socket_to_stdout error: %s", e)

    async def handle_initialize(self, stdin_reader: asyncio.StreamReader) -> bool:
        """Handle MCP initialize request.

        Returns True if initialization succeeded, False otherwise.
        """
        try:
            if INIT_TIMEOUT > 0:
                line = await asyncio.wait_for(stdin_reader.readline(), timeout=INIT_TIMEOUT)
            else:
                line = await stdin_reader.readline()
        except asyncio.TimeoutError:
            logger.warning("Initialize timed out after %.1fs, exiting wrapper", INIT_TIMEOUT)
            return False
        if not line:
            return False

        try:
            line_str = line.decode()
            msg = json.loads(line_str)

            if msg.get("method") == "initialize":
                # Delay backend connection until we know a real client is present.
                # This prevents orphaned wrappers from consuming backend sockets.
                self._schedule_reconnect("initialize")
                request_id = msg.get("id", 1)
                self._client_initialize_request = line
                self._client_initialize_id = request_id
                timeout = 0.5

                # Wait for backend - if it connects, proxy the real handshake
                try:
                    await asyncio.wait_for(self.connected.wait(), timeout=timeout)
                    # Backend is ready! Forward the initialize request
                    logger.info("Backend ready, proxying initialize request")
                    if self.writer:
                        self.writer.write(line)
                        await self.writer.drain()
                    # Don't send cached response - let backend handle it
                    self._needs_backend_resync = False
                    self._suppress_backend_init_messages = False
                except asyncio.TimeoutError:
                    # Backend not ready yet, send cached response for zero-downtime
                    refresh_tool_cache_if_needed()
                    logger.info("Backend not ready, using cached handshake (id=%s)", request_id)
                    response = RESPONSE_TEMPLATE.replace("__REQUEST_ID__", str(request_id))
                    sys.stdout.buffer.write((response + "\n").encode())
                    sys.stdout.buffer.flush()
                    # We still must initialize the backend once it comes back up.
                    self._needs_backend_resync = True
                    self._suppress_backend_init_messages = True
                return True

        except json.JSONDecodeError as e:
            logger.error("Handshake error: %s", e)
            return False

        return True

    async def _parent_watchdog(self) -> None:
        """Exit if parent process dies (orphan detection)."""
        while not self.shutdown.is_set():
            if not _check_parent_alive():
                logger.info("Parent process died (PPID changed), forcing exit")
                # Force immediate exit - other tasks may be blocked on I/O
                os._exit(0)
            await asyncio.sleep(5.0)

    async def _connect_stdin(self, stdin_reader: asyncio.StreamReader) -> bool:
        """Connect stdin reader with a bounded timeout to avoid startup hangs."""
        protocol = asyncio.StreamReaderProtocol(stdin_reader)
        loop = asyncio.get_running_loop()
        try:
            if STDIN_CONNECT_TIMEOUT > 0:
                await asyncio.wait_for(
                    loop.connect_read_pipe(lambda: protocol, sys.stdin),
                    timeout=STDIN_CONNECT_TIMEOUT,
                )
            else:
                await loop.connect_read_pipe(lambda: protocol, sys.stdin)
            return True
        except asyncio.TimeoutError:
            logger.warning("STDIN connect timed out after %.1fs, exiting wrapper", STDIN_CONNECT_TIMEOUT)
        except Exception as exc:
            logger.warning("STDIN connect failed, exiting wrapper: %s", exc)
        return False

    async def run(self):
        """Main proxy loop."""
        # Setup stdin reader
        stdin_reader = asyncio.StreamReader()
        if not await self._connect_stdin(stdin_reader):
            self.shutdown.set()
            return

        # Start parent watchdog early so orphaned wrappers exit even before initialize.
        watchdog_task = asyncio.create_task(self._parent_watchdog())

        # Handle MCP initialize request
        init_ok = await self.handle_initialize(stdin_reader)
        _STARTUP_COMPLETE.set()
        if not init_ok:
            logger.error("Initialize failed, shutting down")
            self.shutdown.set()
            watchdog_task.cancel()
            return

        # Start message pumps (connect task already running)
        stdin_task = asyncio.create_task(self.stdin_to_socket(stdin_reader))
        stdout_task = asyncio.create_task(self.socket_to_stdout())
        self._sender_task = asyncio.create_task(self._socket_sender())
        response_task = asyncio.create_task(self._response_timeout_watcher())

        try:
            tasks = [stdin_task, stdout_task, self._sender_task, response_task, watchdog_task]
            if self._reconnect_task:
                tasks.append(self._reconnect_task)
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            self.shutdown.set()
            _STARTUP_COMPLETE.set()
            if self.writer:
                self.writer.close()
            for task in (stdin_task, stdout_task, self._sender_task, response_task, watchdog_task):
                if task and not task.done():
                    task.cancel()
            if self._reconnect_task and not self._reconnect_task.done():
                self._reconnect_task.cancel()


_PARENT_PID = os.getppid()


def _start_guard_thread() -> None:
    """Start a watchdog thread to catch early startup hangs and orphaned wrappers."""
    if STARTUP_TIMEOUT <= 0 and GUARD_CHECK_INTERVAL <= 0:
        return

    interval = GUARD_CHECK_INTERVAL if GUARD_CHECK_INTERVAL > 0 else 0.5

    def _guard() -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT if STARTUP_TIMEOUT > 0 else None
        while True:
            if not _check_parent_alive():
                logger.info("Parent process died (PPID changed), forcing exit")
                os._exit(0)
            if deadline and not _STARTUP_COMPLETE.is_set() and time.monotonic() > deadline:
                logger.warning("Wrapper startup exceeded %.1fs, exiting", STARTUP_TIMEOUT)
                os._exit(1)
            time.sleep(interval)

    thread = threading.Thread(target=_guard, name="mcp-wrapper-guard", daemon=True)
    thread.start()


def _handle_signal(signum: int, _frame: object) -> None:
    """Handle termination signals by exiting immediately."""
    sig_name = signal.Signals(signum).name
    logger.info("Received %s, exiting", sig_name)
    sys.exit(0)


def _check_parent_alive() -> bool:
    """Check if our parent process is still alive.

    Returns False if parent died (PPID changed to 1 on Unix).
    """
    current_ppid = os.getppid()
    if current_ppid == 1:
        return False
    return current_ppid == _PARENT_PID


def main():
    """Entry point."""
    if os.getppid() == 1:
        logger.info("Orphan wrapper detected at startup (PPID=1), exiting")
        return
    _start_guard_thread()
    # Exit cleanly on signals (especially SIGHUP when parent dies)
    signal.signal(signal.SIGHUP, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("MCP wrapper starting. Extracted tools: %s", TOOL_NAMES)
    proxy = MCPProxy()
    asyncio.run(proxy.run())


if __name__ == "__main__":
    main()
