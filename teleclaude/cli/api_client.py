"""HTTP client for telec TUI."""

import asyncio
import importlib
import json
import os
import stat
import subprocess
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from http import HTTPMethod
from pathlib import Path
from typing import NotRequired, Required, TypedDict, Unpack

import httpx
from instrukt_ai_logging import get_logger
from pydantic import TypeAdapter, ValidationError
from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.sync.client import ClientConnection, unix_connect

from teleclaude.api_models import RunSessionRequest
from teleclaude.cli.models import (
    AgentAvailabilityInfo,
    ChiptunesCommandReceiptInfo,
    ChiptunesStatusInfo,
    ComputerInfo,
    CreateSessionResult,
    JobInfo,
    ProjectInfo,
    ProjectWithTodosInfo,
    SessionInfo,
    SettingsInfo,
    SettingsPatchInfo,
    SubscribeData,
    SubscribeRequest,
    TodoInfo,
    UnsubscribeData,
    UnsubscribeRequest,
    WsEvent,
)
from teleclaude.constants import API_SOCKET_PATH

logger = get_logger(__name__)

BASE_URL = "http://localhost"
WS_URI = "ws://localhost/ws"

# Reconnection settings
WS_INITIAL_BACKOFF = 0.5  # Initial reconnect delay in seconds
WS_MAX_BACKOFF = 5.0  # Maximum reconnect delay for local unix-socket reconnects
WS_BACKOFF_MULTIPLIER = 2.0  # Exponential backoff multiplier
API_CONNECT_RETRY_DELAYS_S = (0.1, 0.3, 0.6)

__all__ = ["APIError", "TelecAPIClient"]

type WsPayload = dict[str, dict[str, str | list[str]]]
type JsonBody = dict[str, object]

WS_OPERATION_ERRORS = (OSError, RuntimeError, WebSocketException)
REQUEST_WRAP_ERRORS = (OSError, RuntimeError, TypeError, ValueError)


def read_current_session_email() -> str | None:
    """Resolve terminal auth state without importing session_auth at module load."""
    session_auth = importlib.import_module("teleclaude.cli.session_auth")
    return session_auth.read_current_session_email()


@dataclass(frozen=True)
class RequestOptions:
    """Optional HTTP request inputs."""

    params: dict[str, str] | None = None
    json_body: JsonBody | None = None


@dataclass
class _HTTPState:
    """Mutable HTTP client state."""

    client: httpx.AsyncClient | None = None
    last_connect_error_log: float | None = None
    identity_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class _WebSocketState:
    """Mutable WebSocket client state."""

    ws: ClientConnection | None = None
    thread: threading.Thread | None = None
    running: bool = False
    subscriptions: set[str] = field(default_factory=set)
    callback: Callable[[WsEvent], None] | None = None
    on_connect: Callable[[], None] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class CreateSessionArgs(TypedDict, total=False):
    """Accepted keyword arguments for session creation."""

    computer: Required[str]
    project_path: Required[str]
    agent: Required[str]
    thinking_mode: Required[str]
    subdir: NotRequired[str | None]
    title: NotRequired[str | None]
    message: NotRequired[str | None]
    auto_command: NotRequired[str | None]
    human_email: NotRequired[str | None]
    human_role: NotRequired[str | None]
    skip_listener_registration: NotRequired[bool]
    metadata: NotRequired[dict[str, object] | None]


class RunSessionArgs(TypedDict, total=False):
    """Accepted keyword arguments for slash-command sessions."""

    command: Required[str]
    project_path: Required[str]
    args: NotRequired[str]
    agent: NotRequired[str]
    thinking_mode: NotRequired[str]
    detach: NotRequired[bool]


class APIError(Exception):
    """API request failed with structured error info."""

    def __init__(self, message: str, status_code: int | None = None, detail: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or message  # Fallback to full message if no detail


class _TelecConnectionClient:
    """Async HTTP client for telec with WebSocket push support."""

    def __init__(self, socket_path: str = API_SOCKET_PATH):
        """Initialize client.

        Args:
            socket_path: Path to Unix socket
        """
        self.socket_path = socket_path
        self._http_state = _HTTPState()
        self._ws_state = _WebSocketState()

    def __getattr__(self, name: str) -> object:
        """Provide backwards-compatible access to internal state for tests."""
        http_attrs = {
            "_client": "client",
            "_identity_headers": "identity_headers",
            "_last_connect_error_log": "last_connect_error_log",
        }
        ws_attrs = {
            "_ws": "ws",
            "_ws_thread": "thread",
            "_ws_running": "running",
            "_ws_subscriptions": "subscriptions",
            "_ws_callback": "callback",
            "_ws_on_connect": "on_connect",
            "_ws_lock": "lock",
        }
        if name in http_attrs:
            return getattr(self._http_state, http_attrs[name])
        if name in ws_attrs:
            return getattr(self._ws_state, ws_attrs[name])
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")

    async def connect(self) -> None:
        """Connect to API socket."""
        transport = httpx.AsyncHTTPTransport(uds=self.socket_path)
        self._http_state.identity_headers = self._build_identity_headers()
        self._http_state.client = httpx.AsyncClient(
            transport=transport,
            base_url=BASE_URL,
            timeout=5.0,
        )

    @property
    def is_connected(self) -> bool:
        """Check if client is connected.

        Returns:
            True if client is connected
        """
        return self._http_state.client is not None

    async def close(self) -> None:
        """Close connection."""
        self.stop_websocket()
        if self._http_state.client:
            await self._http_state.client.aclose()
            self._http_state.client = None

    # --- WebSocket Push Support ---

    def start_websocket(
        self,
        callback: Callable[[WsEvent], None],
        subscriptions: list[str] | None = None,
        on_connect: Callable[[], None] | None = None,
    ) -> None:
        """Start WebSocket connection for push updates.

        Runs in a background thread to avoid blocking the TUI event loop.

        Args:
            callback: Function called with (event_type, data) for each message
            subscriptions: Topics to subscribe to (e.g., ["sessions", "preparation"])
        """
        if self._ws_state.running:
            logger.debug("WebSocket already running")
            return

        self._ws_state.callback = callback
        self._ws_state.on_connect = on_connect
        self._ws_state.subscriptions = set(subscriptions or ["sessions", "preparation"])
        self._ws_state.running = True

        self._ws_state.thread = threading.Thread(target=self._ws_loop, daemon=True, name="ws-client")
        self._ws_state.thread.start()
        logger.info("WebSocket client thread started")

    def stop_websocket(self) -> None:
        """Stop WebSocket connection."""
        self._ws_state.running = False
        with self._ws_state.lock:
            if self._ws_state.ws:
                try:
                    self._ws_state.ws.close()
                except WS_OPERATION_ERRORS:
                    pass
                self._ws_state.ws = None
        if self._ws_state.thread and self._ws_state.thread.is_alive():
            self._ws_state.thread.join(timeout=2.0)
        self._ws_state.thread = None
        logger.info("WebSocket client stopped")

    def subscribe(self, computer: str, types: list[str]) -> None:
        """Subscribe to updates for a specific computer."""
        payload = SubscribeRequest(subscribe=SubscribeData(computer=computer, types=types))
        self._send_ws({"subscribe": {"computer": payload.subscribe.computer, "types": payload.subscribe.types}})

    def unsubscribe(self, computer: str) -> None:
        """Unsubscribe from updates for a specific computer."""
        payload = UnsubscribeRequest(unsubscribe=UnsubscribeData(computer=computer))
        self._send_ws({"unsubscribe": {"computer": payload.unsubscribe.computer}})

    def _send_ws(self, payload: WsPayload) -> None:
        with self._ws_state.lock:
            if not self._ws_state.ws:
                return
            try:
                self._ws_state.ws.send(json.dumps(payload))
            except WS_OPERATION_ERRORS:
                pass

    @property
    def ws_connected(self) -> bool:
        """Check if WebSocket is connected."""
        with self._ws_state.lock:
            return self._ws_state.ws is not None

    def _ws_loop(self) -> None:
        """WebSocket connection loop with reconnection logic."""
        backoff = WS_INITIAL_BACKOFF

        while self._ws_state.running:
            try:
                self._ws_connect_and_run()
                # Reset backoff on successful connection
                backoff = WS_INITIAL_BACKOFF
            except ConnectionClosed:
                logger.info("WebSocket connection closed")
            except WebSocketException as e:
                logger.warning("WebSocket error: %s", e)
            except OSError as e:
                # Socket connection error (daemon not running)
                logger.debug("WebSocket connection failed: %s", e)
            except (RuntimeError, TypeError, ValueError) as e:
                logger.error("Unexpected WebSocket error: %s", e, exc_info=True)

            # Clear connection state
            with self._ws_state.lock:
                self._ws_state.ws = None

            if not self._ws_state.running:
                break

            # Wait before reconnecting (with exponential backoff)
            logger.debug("Reconnecting in %.1fs...", backoff)
            time.sleep(backoff)
            backoff = min(backoff * WS_BACKOFF_MULTIPLIER, WS_MAX_BACKOFF)

    def _ws_connect_and_run(self) -> None:
        """Connect to WebSocket and process messages until disconnection."""
        logger.debug("Connecting to WebSocket at %s", self.socket_path)
        ws = unix_connect(path=self.socket_path, uri=WS_URI)

        with self._ws_state.lock:
            self._ws_state.ws = ws

        logger.info("WebSocket connected, subscribing to: %s", self._ws_state.subscriptions)

        initial_sub = SubscribeRequest(
            subscribe=SubscribeData(computer="local", types=list(self._ws_state.subscriptions))
        )
        initial_payload: WsPayload = {
            "subscribe": {
                "computer": initial_sub.subscribe.computer,
                "types": initial_sub.subscribe.types,
            }
        }
        ws.send(json.dumps(initial_payload))
        if self._ws_state.on_connect:
            self._ws_state.on_connect()

        # Process incoming messages
        for message in ws:
            if not self._ws_state.running:
                break

            try:
                ws_event: WsEvent = TypeAdapter(WsEvent).validate_json(message)
                if self._ws_state.callback:
                    self._ws_state.callback(ws_event)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from WebSocket: %s", message[:100])
            except ValidationError as e:
                logger.warning("Invalid WebSocket event payload: %s", e)

    # --- API Methods ---

    def _normalize_http_method(self, method: HTTPMethod | str) -> HTTPMethod:
        """Convert a request method into an HTTPMethod enum."""
        try:
            return HTTPMethod(method)
        except ValueError as error:
            raise APIError(f"Unsupported HTTP method: {method}") from error

    async def _request_once(
        self,
        method: HTTPMethod,
        url: str,
        timeout: float,
        request_options: RequestOptions,
    ) -> httpx.Response:
        """Dispatch a single HTTP request."""
        if not self._http_state.client:
            raise APIError("Client not connected. Call connect() first.")

        request_kwargs = {
            "params": request_options.params,
            "headers": self._http_state.identity_headers,
            "timeout": timeout,
        }
        if request_options.json_body is not None:
            request_kwargs["json"] = request_options.json_body
        response = await self._http_state.client.request(method.value, url, **request_kwargs)
        response.raise_for_status()
        return response

    def _log_connect_error(self, method: HTTPMethod | str, url: str, timeout: float, error: Exception) -> None:
        """Log connect errors with a debounce to avoid spam."""
        now = self._now_monotonic()
        if (
            self._http_state.last_connect_error_log is not None
            and (now - self._http_state.last_connect_error_log) < 10.0
        ):
            return

        self._http_state.last_connect_error_log = now
        logger.debug(
            "API connect failed",
            method=str(method),
            url=url,
            socket_path=self.socket_path,
            timeout=timeout,
            error=str(error),
        )

    async def _request(
        self,
        method: HTTPMethod | str,
        url: str,
        *,
        timeout: float | None = None,
        request_options: RequestOptions | None = None,
    ) -> httpx.Response:
        """Make HTTP request with error handling.

        Args:
            method: HTTP method (GET, POST, DELETE)
            url: URL path
            timeout: Optional request timeout override
            request_options: Optional request params and JSON body

        Returns:
            Response object

        Raises:
            APIError: If request fails
        """
        request_timeout = timeout if timeout is not None else 5.0
        options = request_options or RequestOptions()
        method_enum = self._normalize_http_method(method)

        try:
            retry_delays = (0.0, *API_CONNECT_RETRY_DELAYS_S)
            for attempt, delay in enumerate(retry_delays, start=1):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    return await self._request_once(method_enum, url, request_timeout, options)
                except httpx.ConnectError as error:
                    self._log_connect_error(method, url, request_timeout, error)
                    await self._wait_for_socket()
                    if attempt >= len(retry_delays):
                        raise APIError("Cannot connect to API server. Socket may be missing.") from error
        except httpx.HTTPStatusError as error:
            # Parse JSON response to extract human-friendly detail
            status_code = error.response.status_code
            detail = None
            try:
                body = error.response.json()
                detail = body.get("detail")
            except (json.JSONDecodeError, ValueError):
                detail = error.response.text
            raise APIError(
                f"API request failed: {status_code} {detail or error.response.text}",
                status_code=status_code,
                detail=detail,
            ) from error
        except httpx.TimeoutException as error:
            raise APIError("API request timed out. Server may be blocked or overloaded.") from error
        except REQUEST_WRAP_ERRORS as error:
            raise APIError(f"Unexpected error: {error}") from error

        raise APIError("Cannot connect to API server. Socket may be missing.")

    def _now_monotonic(self) -> float:
        """Return a monotonic timestamp for debounce logic."""
        return time.monotonic()

    def _build_identity_headers(self) -> dict[str, str]:
        """Build caller identity headers for daemon-side auth checks."""
        headers: dict[str, str] = {}

        # Agent sessions: send daemon-issued token first (takes priority on the server side).
        token = os.environ.get("TELEC_SESSION_TOKEN")
        if token:
            headers["x-session-token"] = token

        session_id = self._read_caller_session_id()
        if session_id:
            headers["x-caller-session-id"] = session_id

        terminal_email = read_current_session_email()
        if terminal_email:
            headers["x-telec-email"] = terminal_email

        tmux_session = self._read_tmux_session_name()
        if tmux_session:
            headers["x-tmux-session"] = tmux_session

        return headers

    def _read_caller_session_id(self) -> str | None:
        """Read caller session_id from TMPDIR/teleclaude_session_id."""
        tmpdir = os.environ.get("TMPDIR", "")
        if not tmpdir:
            return None

        marker = Path(tmpdir) / "teleclaude_session_id"
        try:
            return marker.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def _read_tmux_session_name(self) -> str | None:
        """Read tmux session name from tmux server for dual-factor checks."""
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-p", "#S"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    async def _wait_for_socket(self, *, timeout_s: float = 1.0) -> None:
        """Wait briefly for the API socket to appear and be connectable."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                if os.path.exists(self.socket_path):
                    mode = os.stat(self.socket_path).st_mode
                    if stat.S_ISSOCK(mode):
                        return
            except OSError:
                pass
            await asyncio.sleep(0.05)


class _TelecSessionAPI:
    """Session and daemon operations."""

    _request: Callable[..., Awaitable[httpx.Response]]

    async def list_sessions(self, computer: str | None = None, *, include_closed: bool = False) -> list[SessionInfo]:
        """List sessions from all computers or a specific computer."""
        params: dict[str, str] = {}
        if computer:
            params["computer"] = computer
        if include_closed:
            params["include_closed"] = "true"
        resp = await self._request("GET", "/sessions", request_options=RequestOptions(params=params))
        return TypeAdapter(list[SessionInfo]).validate_json(resp.text)

    async def list_computers(self) -> list[ComputerInfo]:
        """List online computers only."""
        resp = await self._request("GET", "/computers")
        return TypeAdapter(list[ComputerInfo]).validate_json(resp.text)

    async def list_projects(self, computer: str | None = None) -> list[ProjectInfo]:
        """List projects from all or a specific computer."""
        params: dict[str, str] = {"computer": computer} if computer else {}
        resp = await self._request("GET", "/projects", request_options=RequestOptions(params=params))
        return TypeAdapter(list[ProjectInfo]).validate_json(resp.text)

    async def create_session(self, **kwargs: Unpack[CreateSessionArgs]) -> CreateSessionResult:
        """Create a new session."""
        # Session creation spawns tmux + agent, needs longer timeout
        payload: JsonBody = {
            "computer": kwargs["computer"],
            "project_path": kwargs["project_path"],
            "agent": kwargs["agent"],
            "thinking_mode": kwargs["thinking_mode"],
            "title": kwargs.get("title"),
            "message": kwargs.get("message"),
            "auto_command": kwargs.get("auto_command"),
            "human_email": kwargs.get("human_email"),
            "human_role": kwargs.get("human_role", "admin"),
            "metadata": kwargs.get("metadata"),
        }
        subdir = kwargs.get("subdir")
        if subdir is not None:
            payload["subdir"] = subdir
        if kwargs.get("skip_listener_registration", False):
            payload["skip_listener_registration"] = True
        resp = await self._request(
            "POST",
            "/sessions",
            timeout=30.0,
            request_options=RequestOptions(json_body=payload),
        )
        return TypeAdapter(CreateSessionResult).validate_json(resp.text)

    async def run_session(self, **kwargs: Unpack[RunSessionArgs]) -> CreateSessionResult:
        """Run a slash command in a new session (POST /sessions/run)."""
        request = RunSessionRequest(
            command=kwargs["command"],
            args=kwargs.get("args", ""),
            project=kwargs["project_path"],
            agent=kwargs.get("agent", "claude"),  # type: ignore[arg-type]
            thinking_mode=kwargs.get("thinking_mode", "slow"),  # type: ignore[arg-type]
            detach=kwargs.get("detach", False),
        )
        resp = await self._request(
            "POST",
            "/sessions/run",
            timeout=30.0,
            request_options=RequestOptions(json_body=request.model_dump()),
        )
        return TypeAdapter(CreateSessionResult).validate_json(resp.text)

    async def end_session(self, session_id: str, computer: str) -> bool:
        """End a session."""
        resp = await self._request(
            "DELETE",
            f"/sessions/{session_id}",
            request_options=RequestOptions(params={"computer": computer}),
        )
        return resp.status_code in {200, 202}

    async def send_message(self, session_id: str, computer: str, message: str) -> bool:
        """Send a message to a session."""
        resp = await self._request(
            "POST",
            f"/sessions/{session_id}/message",
            request_options=RequestOptions(
                params={"computer": computer},
                json_body={"message": message},
            ),
        )
        return resp.status_code == 200

    async def send_keys(self, session_id: str, computer: str, key: str, count: int | None = None) -> bool:
        """Send a key command to a session."""
        payload: JsonBody = {"key": key}
        if count is not None:
            payload["count"] = count
        resp = await self._request(
            "POST",
            f"/sessions/{session_id}/keys",
            request_options=RequestOptions(
                params={"computer": computer},
                json_body=payload,
            ),
        )
        return resp.status_code == 200

    async def get_auth_whoami(self) -> dict[str, str | None]:
        """Resolve the calling session's principal via the daemon."""
        resp = await self._request("GET", "/auth/whoami")
        return resp.json()

    async def get_agent_availability(self) -> dict[str, AgentAvailabilityInfo]:
        """Get agent availability status."""
        resp = await self._request("GET", "/agents/availability")
        return TypeAdapter(dict[str, AgentAvailabilityInfo]).validate_json(resp.text)

    async def set_agent_status(
        self,
        agent: str,
        status: str,
        reason: str | None = None,
        duration_minutes: int = 60,
    ) -> AgentAvailabilityInfo:
        """Set agent availability status."""
        resp = await self._request(
            "POST",
            f"/agents/{agent}/status",
            request_options=RequestOptions(
                json_body={
                    "status": status,
                    "reason": reason,
                    "duration_minutes": duration_minutes,
                }
            ),
        )
        return TypeAdapter(AgentAvailabilityInfo).validate_json(resp.text)

    async def list_projects_with_todos(self) -> list[ProjectWithTodosInfo]:
        """List all projects with their todos included."""
        projects, todos = await asyncio.gather(
            self.list_projects(),
            self.list_todos(),
        )
        if not projects:
            return []

        todo_map: dict[tuple[str, str], list[TodoInfo]] = {}
        for todo in todos:
            if not todo.computer or not todo.project_path:
                continue
            key = (todo.computer, todo.project_path)
            todo_map.setdefault(key, []).append(todo)

        result: list[ProjectWithTodosInfo] = []
        for project in projects:
            computer = project.computer or ""
            project_path = project.path
            todos_for_project = todo_map.get((computer, project_path), [])
            result.append(
                ProjectWithTodosInfo(
                    computer=project.computer,
                    name=project.name,
                    path=project.path,
                    description=project.description,
                    todos=todos_for_project,
                )
            )
        return result

    async def list_todos(
        self,
        project_path: str | None = None,
        computer: str | None = None,
    ) -> list[TodoInfo]:
        """List todos."""
        params: dict[str, str] = {}
        if project_path:
            params["project"] = project_path
        if computer:
            params["computer"] = computer
        resp = await self._request("GET", "/todos", request_options=RequestOptions(params=params))
        return TypeAdapter(list[TodoInfo]).validate_json(resp.text)

    async def list_jobs(self) -> list[JobInfo]:
        """List scheduled jobs."""
        resp = await self._request("GET", "/jobs")
        return TypeAdapter(list[JobInfo]).validate_json(resp.text)

    async def run_job(self, name: str) -> bool:
        """Run a scheduled job immediately."""
        resp = await self._request("POST", f"/jobs/{name}/run", timeout=30.0)
        data = resp.json()
        return data.get("status") == "success"

    async def agent_restart(self, session_id: str) -> bool:
        """Restart the agent in a session while preserving conversation state."""
        resp = await self._request("POST", f"/sessions/{session_id}/agent-restart")
        return resp.status_code == 200


class _TelecRuntimeAPI:
    """Settings, chiptunes, revive, and memory operations."""

    _request: Callable[..., Awaitable[httpx.Response]]

    async def get_settings(self) -> SettingsInfo:
        """Get current runtime settings."""
        resp = await self._request("GET", "/settings")
        return TypeAdapter(SettingsInfo).validate_json(resp.text)

    async def patch_settings(self, updates: SettingsPatchInfo) -> SettingsInfo:
        """Apply partial updates to runtime settings."""
        resp = await self._request(
            "PATCH",
            "/settings",
            request_options=RequestOptions(json_body=updates.model_dump(exclude_none=True)),
        )
        return TypeAdapter(SettingsInfo).validate_json(resp.text)

    async def chiptunes_next(self) -> ChiptunesCommandReceiptInfo:
        """Queue skip-to-next chiptunes command."""
        resp = await self._request("POST", "/api/chiptunes/next")
        return TypeAdapter(ChiptunesCommandReceiptInfo).validate_json(resp.text)

    async def chiptunes_prev(self) -> ChiptunesCommandReceiptInfo:
        """Queue previous-track chiptunes command."""
        resp = await self._request("POST", "/api/chiptunes/prev")
        return TypeAdapter(ChiptunesCommandReceiptInfo).validate_json(resp.text)

    async def chiptunes_pause(self) -> ChiptunesCommandReceiptInfo:
        """Queue pause command for chiptunes playback."""
        resp = await self._request("POST", "/api/chiptunes/pause")
        return TypeAdapter(ChiptunesCommandReceiptInfo).validate_json(resp.text)

    async def chiptunes_resume(self) -> ChiptunesCommandReceiptInfo:
        """Queue resume command for chiptunes playback."""
        resp = await self._request("POST", "/api/chiptunes/resume")
        return TypeAdapter(ChiptunesCommandReceiptInfo).validate_json(resp.text)

    async def get_chiptunes_status(self) -> ChiptunesStatusInfo:
        """Fetch current chiptunes playback state."""
        resp = await self._request("GET", "/api/chiptunes/status")
        return TypeAdapter(ChiptunesStatusInfo).validate_json(resp.text)

    async def revive_session(
        self, session_id: str, *, agent: str | None = None, project: str | None = None
    ) -> CreateSessionResult:
        """Revive a session by TeleClaude or native session ID.

        Without agent, session_id is a TeleClaude session ID.
        With agent, session_id is a native agent session ID resolved server-side.
        """
        params: dict[str, str] = {}
        if agent:
            params["agent"] = agent
        if project:
            params["project"] = project
        resp = await self._request(
            "POST",
            f"/sessions/{session_id}/revive",
            timeout=30.0,
            request_options=RequestOptions(params=params),
        )
        return TypeAdapter(CreateSessionResult).validate_json(resp.text)

    async def memory_search(
        self,
        query: str,
        limit: int = 20,
        obs_type: str | None = None,
        project: str | None = None,
    ) -> list[dict[str, object]]:  # guard: loose-dict - JSON response from daemon memory API
        """Search memory observations."""
        params: dict[str, str] = {"query": query, "limit": str(limit)}
        if obs_type:
            params["type"] = obs_type
        if project:
            params["project"] = project
        resp = await self._request("GET", "/api/memory/search", request_options=RequestOptions(params=params))
        return resp.json()

    async def memory_save(
        self,
        text: str,
        title: str | None = None,
        obs_type: str | None = None,
        project: str | None = None,
    ) -> dict[str, object]:  # guard: loose-dict - JSON response from daemon memory API
        """Save a memory observation."""
        body: JsonBody = {"text": text}
        if title:
            body["title"] = title
        if obs_type:
            body["type"] = obs_type
        if project:
            body["project"] = project
        resp = await self._request(
            "POST",
            "/api/memory/save",
            request_options=RequestOptions(json_body=body),
        )
        return resp.json()

    async def memory_delete(
        self, observation_id: int
    ) -> dict[str, object]:  # guard: loose-dict - JSON response from daemon memory API
        """Delete a memory observation by ID."""
        resp = await self._request("DELETE", f"/api/memory/{observation_id}")
        return resp.json()

    async def memory_timeline(
        self,
        anchor: int,
        before: int = 3,
        after: int = 3,
        project: str | None = None,
    ) -> list[dict[str, object]]:  # guard: loose-dict - JSON response from daemon memory API
        """Get observations around an anchor ID."""
        params: dict[str, str] = {
            "anchor": str(anchor),
            "depth_before": str(before),
            "depth_after": str(after),
        }
        if project:
            params["project"] = project
        resp = await self._request("GET", "/api/memory/timeline", request_options=RequestOptions(params=params))
        return resp.json()


class TelecAPIClient(_TelecConnectionClient, _TelecSessionAPI, _TelecRuntimeAPI):
    """Public telec API client."""
