#!/usr/bin/env python3
# pylint: skip-file
# mypy: ignore-errors
"""Resilient MCP wrapper that handles backend server restarts.

Uses a last-known-good tools list from the backend when the daemon is down.
"""

import asyncio
import fcntl
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import MutableMapping, TypedDict

from instrukt_ai_logging import configure_logging, get_logger

from teleclaude.constants import MAIN_MODULE
from teleclaude.mcp.protocol import McpMethod

PARAM_CWD = "cwd"
RESULT_KEY = "result"
EMPTY_STRING = ""

configure_logging("teleclaude")

logger = get_logger("teleclaude.mcp_wrapper")

MCP_SOCKET = "/tmp/teleclaude.sock"
# Map parameter names to env var names. Special value None means use os.getcwd()
CONTEXT_TO_INJECT: dict[str, str | None] = {
    PARAM_CWD: None,  # Special: inject os.getcwd() instead of env var
}
RECONNECT_DELAY = 5
CONNECTION_TIMEOUT = 10
REQUEST_TIMEOUT = 30.0
RESPONSE_TIMEOUT = REQUEST_TIMEOUT
INIT_TIMEOUT = 5.0
LONG_RUNNING_TOOL_TIMEOUTS = {
    "teleclaude__run_agent_command": 60.0,
    "teleclaude__start_session": 30.0,
}
STDIN_CONNECT_TIMEOUT = float(os.getenv("MCP_WRAPPER_STDIN_CONNECT_TIMEOUT", "5"))
STARTUP_TIMEOUT = float(os.getenv("MCP_WRAPPER_STARTUP_TIMEOUT", "20"))
RESPONSE_CHECK_INTERVAL = float(os.getenv("MCP_WRAPPER_RESPONSE_CHECK_INTERVAL", "0.5"))
TIMED_OUT_RETENTION = float(os.getenv("MCP_WRAPPER_TIMEOUT_RETENTION", "300"))
GUARD_CHECK_INTERVAL = float(os.getenv("MCP_WRAPPER_GUARD_INTERVAL", "0.5"))
OUTBOUND_QUEUE_MAX = int(os.getenv("MCP_WRAPPER_OUTBOUND_QUEUE_MAX", "200"))
# Limit concurrent backend connect attempts across wrapper processes.
CONNECT_LOCK_PATH = os.getenv("MCP_WRAPPER_CONNECT_LOCK", "/tmp/teleclaude-mcp-wrapper.lock")
CONNECT_LOCK_TIMEOUT = float(os.getenv("MCP_WRAPPER_CONNECT_LOCK_TIMEOUT", "2.0"))
CONNECT_LOCK_RETRY_S = float(os.getenv("MCP_WRAPPER_CONNECT_LOCK_RETRY", "0.05"))
CONNECT_LOCK_SLOTS = int(os.getenv("MCP_WRAPPER_CONNECT_LOCK_SLOTS", "3"))
CONNECT_LOCK_FAILS = int(os.getenv("MCP_WRAPPER_CONNECT_LOCK_FAILS", "3"))
CONNECT_LOCK_WINDOW_S = float(os.getenv("MCP_WRAPPER_CONNECT_LOCK_WINDOW", "10.0"))
TOOL_CACHE_PATH_ENV = "MCP_WRAPPER_TOOL_CACHE_PATH"
# Keep logs human-friendly by default: no repeated spam while waiting for a restart
# or when running in a restricted environment that can't connect to the socket.
LOG_THROTTLE_S = 60.0
_EPERM_BACKOFF_S = 60.0

_ERR_BACKEND_UNAVAILABLE = -32000
_STARTUP_COMPLETE = threading.Event()


class ToolInputSchema(TypedDict):
    type: str
    properties: dict[str, object]  # type: boundary - JSON schema is dynamic


class ToolSpec(TypedDict):
    name: str
    description: str
    inputSchema: ToolInputSchema


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
    if method == McpMethod.TOOLS_CALL.value:
        params = msg.get("params")
        if isinstance(params, dict):
            tool_name = params.get("name") if isinstance(params.get("name"), str) else None
    return msg.get("id"), method, tool_name


def _read_session_id_marker() -> str | None:
    """Read TeleClaude session ID from the per-session TMPDIR marker file."""
    tmpdir_value = os.environ.get("TMPDIR") or os.environ.get("TMP") or os.environ.get("TEMP")
    if not tmpdir_value:
        return None
    marker = Path(tmpdir_value) / "teleclaude_session_id"
    try:
        value = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _get_response_timeout(method: str | None, tool_name: str | None) -> float:
    if method == McpMethod.TOOLS_CALL.value and tool_name:
        return LONG_RUNNING_TOOL_TIMEOUTS.get(tool_name, RESPONSE_TIMEOUT)
    return RESPONSE_TIMEOUT


# Mutable cache so long-lived wrapper processes can refresh after code updates.
_TOOL_CACHE_MTIME: float | None = None
TOOL_LIST_CACHE: list[ToolSpec] | None = None


def _resolve_tool_cache_path() -> Path:
    env_path = os.getenv(TOOL_CACHE_PATH_ENV)
    if env_path:
        return Path(env_path).expanduser()
    script_dir = Path(__file__).resolve().parent
    working_dir = Path(os.getenv("WORKING_DIR", script_dir.parent))
    return working_dir / "logs" / "mcp-tools-cache.json"


TOOL_CACHE_PATH = _resolve_tool_cache_path()


def _tool_names_from_cache(tools: list[ToolSpec] | None) -> list[str]:
    if not tools:
        return []
    return [tool.get("name") for tool in tools if isinstance(tool.get("name"), str)]


def _normalize_tools_list(raw: object) -> list[ToolSpec] | None:
    if not isinstance(raw, list):
        return None
    normalized: list[ToolSpec] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        name = item.get("name")
        input_schema = item.get("inputSchema")
        description = item.get("description", "")
        if not isinstance(name, str) or not name:
            return None
        if not isinstance(input_schema, dict):
            return None
        if description is None:
            description = ""
        if not isinstance(description, str):
            return None
        tool = dict(item)
        tool["name"] = name
        tool["description"] = description
        tool["inputSchema"] = input_schema
        normalized.append(tool)  # type: ignore[arg-type]
    if not normalized:
        return None
    return normalized


def _load_tool_cache(path: Path) -> list[ToolSpec] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("Failed reading tool cache at %s: %s", path, exc)
        return None
    tools = _normalize_tools_list(raw)
    if not tools:
        logger.warning("Ignoring invalid tool cache at %s", path)
        return None
    return tools


def _persist_tool_cache(path: Path, tools: list[ToolSpec]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        payload = json.dumps(tools, ensure_ascii=True, sort_keys=True)
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(path)
        return True
    except Exception as exc:
        logger.warning("Failed persisting tool cache to %s: %s", path, exc)
        return False


def refresh_tool_cache_if_needed(force: bool = False) -> None:
    """Refresh cached tools list if the persisted cache changed."""
    global _TOOL_CACHE_MTIME, TOOL_LIST_CACHE  # pylint: disable=global-statement

    try:
        mtime = TOOL_CACHE_PATH.stat().st_mtime
    except FileNotFoundError:
        return
    except Exception:
        mtime = None

    if not force and mtime is not None and _TOOL_CACHE_MTIME is not None and mtime <= _TOOL_CACHE_MTIME:
        return

    tools = _load_tool_cache(TOOL_CACHE_PATH)
    if not tools:
        return
    TOOL_LIST_CACHE = tools
    _TOOL_CACHE_MTIME = mtime
    logger.info("Tool cache loaded from disk (count=%d)", len(TOOL_LIST_CACHE))


def _build_initialize_response(request_id: object) -> bytes:
    tool_names = _tool_names_from_cache(TOOL_LIST_CACHE)
    result = {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "TeleClaude", "version": "1.0.0"},
    }
    if tool_names:
        result["serverInfo"]["tools_available"] = tool_names
    payload = {"jsonrpc": "2.0", "id": request_id, "result": result}
    return (json.dumps(payload) + "\n").encode("utf-8")


def _update_tool_cache(tools: list[object], source: str) -> list[ToolSpec] | None:
    global _TOOL_CACHE_MTIME, TOOL_LIST_CACHE  # pylint: disable=global-statement
    normalized = _normalize_tools_list(tools)
    if not normalized:
        logger.warning("Ignoring invalid tools list from %s", source)
        return None
    TOOL_LIST_CACHE = normalized
    if _persist_tool_cache(TOOL_CACHE_PATH, normalized):
        try:
            _TOOL_CACHE_MTIME = TOOL_CACHE_PATH.stat().st_mtime
        except Exception:
            _TOOL_CACHE_MTIME = None
    logger.info("Tool cache updated (%s, count=%d)", source, len(normalized))
    return normalized


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
        existing = arguments.get(param_name)
        has_value = existing is not None and (not isinstance(existing, str) or existing != EMPTY_STRING)
        if has_value:
            continue
        if env_var is None:
            # Special case: cwd uses os.getcwd()
            if param_name == PARAM_CWD:
                arguments[param_name] = os.getcwd()
        else:
            env_value = os.environ.get(env_var)
            if env_value:
                arguments[param_name] = env_value

    caller_existing = arguments.get("caller_session_id")
    has_caller = caller_existing is not None and (
        not isinstance(caller_existing, str) or caller_existing != EMPTY_STRING
    )
    if not has_caller:
        marker_value = _read_session_id_marker()
        if marker_value:
            arguments["caller_session_id"] = marker_value

    params["arguments"] = arguments
    return params


def _jsonrpc_tools_list_response(request_id: object, tools_list: list[ToolSpec]) -> bytes:
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"tools": tools_list},
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


def process_message(
    message: MutableMapping[str, object],
) -> MutableMapping[str, object]:
    """Process outgoing messages, injecting context where needed."""
    if message.get("method") == McpMethod.TOOLS_CALL.value:
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
        self._resync_lock = asyncio.Lock()
        self._outbound: asyncio.Queue[_QueueItem] = asyncio.Queue(maxsize=OUTBOUND_QUEUE_MAX)
        self._sender_task: asyncio.Task[None] | None = None
        self._log_last_at: dict[str, float] = {}
        self._log_throttle_s: float = LOG_THROTTLE_S
        self._connect_hard_error_seen = False
        self._connect_failures = 0
        self._connect_failure_window_start = 0.0
        self._connect_lock_enabled = False

    async def _acquire_connect_lock(self) -> int | None:
        """Acquire a cross-process connect slot to cap connect storms."""
        start = time.monotonic()
        slot_count = max(1, CONNECT_LOCK_SLOTS)
        lock_paths = [CONNECT_LOCK_PATH] if slot_count == 1 else [f"{CONNECT_LOCK_PATH}.{i}" for i in range(slot_count)]
        while not self.shutdown.is_set():
            for lock_path in lock_paths:
                fd: int | None = None
                try:
                    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return fd
                except BlockingIOError:
                    if fd is not None:
                        os.close(fd)
                    continue
                except Exception:
                    if fd is not None:
                        os.close(fd)
                    return None
            if time.monotonic() - start >= CONNECT_LOCK_TIMEOUT:
                return None
            await asyncio.sleep(CONNECT_LOCK_RETRY_S)
        return None

    @staticmethod
    def _release_connect_lock(fd: int | None) -> None:
        if fd is None:
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            os.close(fd)
        except Exception:
            pass

    def _note_connect_failure(self) -> None:
        now = time.monotonic()
        if (
            self._connect_failure_window_start == 0.0
            or (now - self._connect_failure_window_start) > CONNECT_LOCK_WINDOW_S
        ):
            self._connect_failure_window_start = now
            self._connect_failures = 1
        else:
            self._connect_failures += 1

        if not self._connect_lock_enabled and self._connect_failures >= CONNECT_LOCK_FAILS:
            self._connect_lock_enabled = True
            self._log_throttled(
                "connect:guard:enabled",
                logging.WARNING,
                "Connect guard enabled after %d failures in %.1fs (slots=%d)",
                self._connect_failures,
                CONNECT_LOCK_WINDOW_S,
                max(1, CONNECT_LOCK_SLOTS),
            )

    def _reset_connect_guard(self) -> None:
        if self._connect_failures or self._connect_lock_enabled:
            self._connect_failures = 0
            self._connect_failure_window_start = 0.0
            self._connect_lock_enabled = False
            self._log_throttled(
                "connect:guard:disabled",
                logging.INFO,
                "Connect guard disabled",
            )

    def _should_use_connect_lock(self) -> bool:
        if not self._connect_lock_enabled:
            return False
        now = time.monotonic()
        if (now - self._connect_failure_window_start) > CONNECT_LOCK_WINDOW_S:
            self._reset_connect_guard()
            return False
        return True

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

        # When triggered by "initialize", handle_initialize() handles the handshake directly,
        # so we skip _startup_resync() to avoid duplicate initialize requests.
        skip_resync = reason == McpMethod.INITIALIZE.value

        async def _runner() -> None:
            async with self._reconnect_lock:
                try:
                    await self.reconnect()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.error("Reconnect task failed: %s", exc)
                if not self.shutdown.is_set() and not skip_resync:
                    await self._startup_resync()

        self._reconnect_task = asyncio.create_task(_runner())

    async def connect(self) -> bool:
        """Connect to backend socket with timeout."""
        while not self.shutdown.is_set():
            try:
                self._log_throttled("connect:attempt", logging.INFO, "Connecting to %s...", MCP_SOCKET)
                lock_fd = None
                if self._should_use_connect_lock():
                    lock_fd = await self._acquire_connect_lock()
                    if lock_fd is None:
                        self._log_throttled(
                            "connect:lock",
                            logging.WARNING,
                            "Connect guard busy. Retrying in %ss...",
                            RECONNECT_DELAY,
                        )
                        await asyncio.sleep(RECONNECT_DELAY)
                        continue
                try:
                    self.reader, self.writer = await asyncio.wait_for(
                        asyncio.open_unix_connection(MCP_SOCKET),
                        timeout=CONNECTION_TIMEOUT,
                    )
                finally:
                    self._release_connect_lock(lock_fd)
                self.connected.set()
                self._backend_generation += 1
                logger.info("Connected to backend")
                self._connect_hard_error_seen = False
                self._reset_connect_guard()
                return True
            except FileNotFoundError:
                self._note_connect_failure()
                self._log_throttled(
                    "connect:missing", logging.WARNING, "Socket not found. Retrying in %ss...", RECONNECT_DELAY
                )
            except ConnectionRefusedError:
                self._note_connect_failure()
                self._log_throttled(
                    "connect:refused", logging.WARNING, "Connection refused. Retrying in %ss...", RECONNECT_DELAY
                )
            except asyncio.TimeoutError:
                self._note_connect_failure()
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
                self._note_connect_failure()
                await asyncio.sleep(_EPERM_BACKOFF_S)
                continue
            except Exception as e:
                # EPERM can happen in sandboxed contexts; throttle to avoid log spam.
                self._note_connect_failure()
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
        async with self._resync_lock:
            if not self._needs_backend_resync:
                return True
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

    async def _startup_resync(self) -> None:
        """Ensure backend handshake is replayed even if no messages are sent."""
        if not self._needs_backend_resync:
            return
        try:
            await asyncio.wait_for(self.connected.wait(), timeout=STARTUP_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("Backend not ready for handshake resync within %.1fs", STARTUP_TIMEOUT)
            return

        if not self._needs_backend_resync:
            return

        self._suppress_backend_init_messages = True
        ok = await self._resync_backend_handshake(STARTUP_TIMEOUT)
        if ok:
            self._needs_backend_resync = False
        self._suppress_backend_init_messages = False

    async def _send_error(self, request_id: object, message: str) -> None:
        """Send an error response to the client (never raises)."""
        try:
            sys.stdout.buffer.write(_jsonrpc_error_response(request_id, message))
            sys.stdout.buffer.flush()
        except Exception:
            # Never write to stderr; best-effort only.
            pass

    async def _send_tools_list_cached(self, request_id: object) -> None:
        """Send cached tools/list response without touching the backend."""
        tools_list = TOOL_LIST_CACHE
        if not tools_list:
            await self._send_error(
                request_id,
                "TeleClaude backend unavailable and no cached tools list is available. Please retry.",
            )
            return
        try:
            sys.stdout.buffer.write(_jsonrpc_tools_list_response(request_id, tools_list))
            sys.stdout.buffer.flush()
        except Exception:
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

                if method == McpMethod.TOOLS_LIST.value and request_id is not None:
                    refresh_tool_cache_if_needed()
                    if not self.connected.is_set() or not self.writer:
                        await self._send_tools_list_cached(request_id)
                        continue
                response_timeout = _get_response_timeout(method, tool_name)

                # Process message (inject context)
                try:
                    msg = json.loads(line.decode())
                    if isinstance(msg, MutableMapping):
                        # Capture client handshake messages for replay across backend restarts.
                        if msg.get("method") == McpMethod.INITIALIZE.value:
                            self._client_initialize_request = (json.dumps(msg) + "\n").encode("utf-8")
                            self._client_initialize_id = msg.get("id")
                        elif msg.get("method") == McpMethod.NOTIFICATIONS_INITIALIZED.value:
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
                            "TeleClaude backend unavailable or busy (wrapper queue full). Please retry.",
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
                        "TeleClaude backend unavailable. Please retry; if this persists, check daemon health.",
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
                if method == McpMethod.NOTIFICATIONS_INITIALIZED.value and request_id is None:
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
                                "TeleClaude backend unavailable (queue full). Please retry.",
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
            global TOOL_LIST_CACHE  # pylint: disable=global-statement
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
                            and RESULT_KEY in msg
                        ):
                            self._backend_init_response.set()
                            continue
                    except json.JSONDecodeError:
                        msg = None

                    if isinstance(msg, dict):
                        response_id = msg.get("id")
                        if (
                            RESULT_KEY in msg
                            and isinstance(msg.get(RESULT_KEY), dict)
                            and isinstance(msg[RESULT_KEY].get("tools"), list)
                        ):
                            # Cache tools/list response for startup fallbacks.
                            tools = msg[RESULT_KEY]["tools"]
                            if isinstance(tools, list):
                                updated = _update_tool_cache(tools, "backend")
                                if updated is not None:
                                    msg[RESULT_KEY]["tools"] = updated
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

            if msg.get("method") == McpMethod.INITIALIZE.value:
                # Delay backend connection until we know a real client is present.
                # This prevents orphaned wrappers from consuming backend sockets.
                self._schedule_reconnect(McpMethod.INITIALIZE.value)
                request_id = msg.get("id", 1)
                self._client_initialize_request = line
                self._client_initialize_id = request_id
                timeout = 0.5

                # Wait for backend - if it connects, proxy the real handshake
                try:
                    await asyncio.wait_for(self.connected.wait(), timeout=timeout)
                    # Backend is ready! Forward the initialize request
                    logger.info("Backend ready, proxying initialize request")
                    # Clear resync flag BEFORE writing to prevent race with _startup_resync()
                    self._needs_backend_resync = False
                    self._suppress_backend_init_messages = False
                    if self.writer:
                        self.writer.write(line)
                        await self.writer.drain()
                except asyncio.TimeoutError:
                    # Backend not ready yet, send cached response for zero-downtime
                    refresh_tool_cache_if_needed()
                    logger.info("Backend not ready, using cached handshake (id=%s)", request_id)
                    sys.stdout.buffer.write(_build_initialize_response(request_id))
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
        startup_resync_task = None
        if self._needs_backend_resync:
            startup_resync_task = asyncio.create_task(self._startup_resync())

        try:
            tasks = [stdin_task, stdout_task, self._sender_task, response_task, watchdog_task]
            if startup_resync_task:
                tasks.append(startup_resync_task)
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
            for task in (stdin_task, stdout_task, self._sender_task, response_task, watchdog_task, startup_resync_task):
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
    logger.info(
        "MCP wrapper env",
        teleclaude_session_id=os.environ.get("TELECLAUDE_SESSION_ID"),
        tmux=os.environ.get("TMUX"),
        tmpdir=os.environ.get("TMPDIR"),
        ppid=os.getppid(),
    )
    _start_guard_thread()
    # Exit cleanly on signals (especially SIGHUP when parent dies)
    signal.signal(signal.SIGHUP, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("MCP wrapper starting. Cached tools: %s", _tool_names_from_cache(TOOL_LIST_CACHE))
    proxy = MCPProxy()
    asyncio.run(proxy.run())


if __name__ == MAIN_MODULE:
    main()
