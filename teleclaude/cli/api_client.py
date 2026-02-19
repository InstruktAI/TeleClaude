"""HTTP client for telec TUI."""

import asyncio
import json
import os
import stat
import threading
import time
from collections.abc import Callable
from http import HTTPMethod
from typing import TypeAlias

import httpx
from instrukt_ai_logging import get_logger
from pydantic import TypeAdapter, ValidationError
from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.sync.client import ClientConnection, unix_connect

from teleclaude.cli.models import (
    AgentAvailabilityInfo,
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
WS_INITIAL_BACKOFF = 1.0  # Initial reconnect delay in seconds
WS_MAX_BACKOFF = 30.0  # Maximum reconnect delay
WS_BACKOFF_MULTIPLIER = 2.0  # Exponential backoff multiplier
API_CONNECT_RETRY_DELAYS_S = (0.1, 0.3, 0.6)

__all__ = ["TelecAPIClient", "APIError"]

WsPayload: TypeAlias = dict[str, dict[str, str | list[str]]]


class APIError(Exception):
    """API request failed with structured error info."""

    def __init__(self, message: str, status_code: int | None = None, detail: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or message  # Fallback to full message if no detail


class TelecAPIClient:
    """Async HTTP client for telec with WebSocket push support."""

    def __init__(self, socket_path: str = API_SOCKET_PATH):
        """Initialize client.

        Args:
            socket_path: Path to Unix socket
        """
        self.socket_path = socket_path
        self._client: httpx.AsyncClient | None = None
        # WebSocket state
        self._ws: ClientConnection | None = None
        self._ws_thread: threading.Thread | None = None
        self._ws_running = False
        self._ws_subscriptions: set[str] = set()
        self._ws_callback: Callable[[WsEvent], None] | None = None
        self._ws_lock = threading.Lock()
        self._last_connect_error_log: float | None = None

    async def connect(self) -> None:
        """Connect to API socket."""
        transport = httpx.AsyncHTTPTransport(uds=self.socket_path)
        self._client = httpx.AsyncClient(
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
        return self._client is not None

    async def close(self) -> None:
        """Close connection."""
        self.stop_websocket()
        if self._client:
            await self._client.aclose()
            self._client = None

    # --- WebSocket Push Support ---

    def start_websocket(
        self,
        callback: Callable[[WsEvent], None],
        subscriptions: list[str] | None = None,
    ) -> None:
        """Start WebSocket connection for push updates.

        Runs in a background thread to avoid blocking the TUI event loop.

        Args:
            callback: Function called with (event_type, data) for each message
            subscriptions: Topics to subscribe to (e.g., ["sessions", "preparation"])
        """
        if self._ws_running:
            logger.debug("WebSocket already running")
            return

        self._ws_callback = callback
        self._ws_subscriptions = set(subscriptions or ["sessions", "preparation"])
        self._ws_running = True

        self._ws_thread = threading.Thread(target=self._ws_loop, daemon=True, name="ws-client")
        self._ws_thread.start()
        logger.info("WebSocket client thread started")

    def stop_websocket(self) -> None:
        """Stop WebSocket connection."""
        self._ws_running = False
        with self._ws_lock:
            if self._ws:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=2.0)
        self._ws_thread = None
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
        with self._ws_lock:
            if not self._ws:
                return
            try:
                self._ws.send(json.dumps(payload))
            except Exception:
                pass

    @property
    def ws_connected(self) -> bool:
        """Check if WebSocket is connected."""
        with self._ws_lock:
            return self._ws is not None

    def _ws_loop(self) -> None:
        """WebSocket connection loop with reconnection logic."""
        backoff = WS_INITIAL_BACKOFF

        while self._ws_running:
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
            except Exception as e:
                logger.error("Unexpected WebSocket error: %s", e, exc_info=True)

            # Clear connection state
            with self._ws_lock:
                self._ws = None

            if not self._ws_running:
                break

            # Wait before reconnecting (with exponential backoff)
            logger.debug("Reconnecting in %.1fs...", backoff)
            time.sleep(backoff)
            backoff = min(backoff * WS_BACKOFF_MULTIPLIER, WS_MAX_BACKOFF)

    def _ws_connect_and_run(self) -> None:
        """Connect to WebSocket and process messages until disconnection."""
        logger.debug("Connecting to WebSocket at %s", self.socket_path)
        ws = unix_connect(path=self.socket_path, uri=WS_URI)

        with self._ws_lock:
            self._ws = ws

        logger.info("WebSocket connected, subscribing to: %s", self._ws_subscriptions)

        initial_sub = SubscribeRequest(subscribe=SubscribeData(computer="local", types=list(self._ws_subscriptions)))
        initial_payload: WsPayload = {
            "subscribe": {
                "computer": initial_sub.subscribe.computer,
                "types": initial_sub.subscribe.types,
            }
        }
        ws.send(json.dumps(initial_payload))

        # Process incoming messages
        for message in ws:
            if not self._ws_running:
                break

            try:
                ws_event: WsEvent = TypeAdapter(WsEvent).validate_json(message)
                if self._ws_callback:
                    self._ws_callback(ws_event)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from WebSocket: %s", message[:100])
            except ValidationError as e:
                logger.warning("Invalid WebSocket event payload: %s", e)

    # --- API Methods ---

    async def _request(
        self,
        method: HTTPMethod | str,
        url: str,
        *,
        timeout: float | None = None,
        params: dict[str, str] | None = None,
        json_body: dict[str, str | None] | None = None,
    ) -> httpx.Response:
        """Make HTTP request with error handling.

        Args:
            method: HTTP method (GET, POST, DELETE)
            url: URL path
            timeout: Optional request timeout override
            **kwargs: Additional request arguments

        Returns:
            Response object

        Raises:
            APIError: If request fails
        """
        if not self._client:
            raise APIError("Client not connected. Call connect() first.")

        request_timeout = timeout if timeout is not None else 5.0
        logged_connect_error = False

        try:
            try:
                method_enum = HTTPMethod(method)
            except ValueError as e:
                raise APIError(f"Unsupported HTTP method: {method}") from e

            for attempt, delay in enumerate((0.0, *API_CONNECT_RETRY_DELAYS_S), start=1):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    if method_enum is HTTPMethod.GET:
                        resp = await self._client.get(url, params=params, timeout=request_timeout)
                    elif method_enum is HTTPMethod.POST:
                        resp = await self._client.post(url, params=params, json=json_body, timeout=request_timeout)
                    elif method_enum is HTTPMethod.PATCH:
                        resp = await self._client.patch(url, params=params, json=json_body, timeout=request_timeout)
                    elif method_enum is HTTPMethod.DELETE:
                        resp = await self._client.delete(url, params=params, timeout=request_timeout)
                    else:
                        raise APIError(f"Unsupported HTTP method: {method}")

                    resp.raise_for_status()
                    return resp
                except httpx.ConnectError as e:
                    if not logged_connect_error:
                        now = self._now_monotonic()
                        if self._last_connect_error_log is None or (now - self._last_connect_error_log) >= 10.0:
                            self._last_connect_error_log = now
                            logger.debug(
                                "API connect failed",
                                method=str(method),
                                url=url,
                                socket_path=self.socket_path,
                                timeout=request_timeout,
                                error=str(e),
                            )
                        logged_connect_error = True
                    await self._wait_for_socket()
                    if attempt >= (1 + len(API_CONNECT_RETRY_DELAYS_S)):
                        raise APIError("Cannot connect to API server. Socket may be missing.") from e
        except httpx.HTTPStatusError as e:
            # Parse JSON response to extract human-friendly detail
            status_code = e.response.status_code
            detail = None
            try:
                body = e.response.json()
                detail = body.get("detail")
            except (json.JSONDecodeError, ValueError):
                detail = e.response.text
            raise APIError(
                f"API request failed: {status_code} {detail or e.response.text}",
                status_code=status_code,
                detail=detail,
            ) from e
        except httpx.TimeoutException as e:
            raise APIError("API request timed out. Server may be blocked or overloaded.") from e
        except APIError:
            raise
        except Exception as e:
            raise APIError(f"Unexpected error: {e}") from e

        raise APIError("Cannot connect to API server. Socket may be missing.")

    def _now_monotonic(self) -> float:
        """Return a monotonic timestamp for debounce logic."""
        return time.monotonic()

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

    async def list_sessions(self, computer: str | None = None) -> list[SessionInfo]:
        """List sessions from all computers or specific computer.

        Args:
            computer: Filter by computer name (None = all)

        Returns:
            List of session dicts

        Raises:
            APIError: If request fails
        """
        params: dict[str, str] = {"computer": computer} if computer else {}
        resp = await self._request("GET", "/sessions", params=params)
        return TypeAdapter(list[SessionInfo]).validate_json(resp.text)

    async def list_computers(self) -> list[ComputerInfo]:
        """List online computers only.

        Returns:
            List of computer dicts

        Raises:
            APIError: If request fails
        """
        resp = await self._request("GET", "/computers")
        return TypeAdapter(list[ComputerInfo]).validate_json(resp.text)

    async def list_projects(self, computer: str | None = None) -> list[ProjectInfo]:
        """List projects from all or specific computer.

        Args:
            computer: Filter by computer name (None = all)

        Returns:
            List of project dicts

        Raises:
            APIError: If request fails
        """
        params: dict[str, str] = {"computer": computer} if computer else {}
        resp = await self._request("GET", "/projects", params=params)
        return TypeAdapter(list[ProjectInfo]).validate_json(resp.text)

    async def create_session(
        self,
        *,
        computer: str,
        project_path: str,
        subdir: str | None = None,
        agent: str,
        thinking_mode: str,
        title: str | None = None,
        message: str | None = None,
        auto_command: str | None = None,
        human_email: str | None = None,
        human_role: str | None = "admin",
        metadata: dict[str, object] | None = None,  # guard: loose-dict
    ) -> CreateSessionResult:
        """Create a new session.

        Args:
            **kwargs: Session parameters (computer, project_path, agent, thinking_mode, title, message)

        Returns:
            Session creation result

        Raises:
            APIError: If request fails
        """
        # Session creation spawns tmux + agent, needs longer timeout
        payload = {
            "computer": computer,
            "project_path": project_path,
            "agent": agent,
            "thinking_mode": thinking_mode,
            "title": title,
            "message": message,
            "auto_command": auto_command,
            "human_email": human_email,
            "human_role": human_role,
            "metadata": metadata,
        }
        if subdir is not None:
            payload["subdir"] = subdir
        resp = await self._request("POST", "/sessions", timeout=30.0, json_body=payload)
        return TypeAdapter(CreateSessionResult).validate_json(resp.text)

    async def end_session(self, session_id: str, computer: str) -> bool:
        """End a session.

        Args:
            session_id: Session ID to end
            computer: Computer name where session is running

        Returns:
            True if successful

        Raises:
            APIError: If request fails
        """
        resp = await self._request("DELETE", f"/sessions/{session_id}", params={"computer": computer})
        return resp.status_code == 200

    async def send_message(self, session_id: str, computer: str, message: str) -> bool:
        """Send message to a session.

        Args:
            session_id: Session ID
            computer: Computer name where session is running
            message: Message to send

        Returns:
            True if successful

        Raises:
            APIError: If request fails
        """
        resp = await self._request(
            "POST",
            f"/sessions/{session_id}/message",
            params={"computer": computer},
            json_body={"message": message},
        )
        return resp.status_code == 200

    async def send_keys(self, session_id: str, computer: str, key: str, count: int | None = None) -> bool:
        """Send a key command to a session.

        Args:
            session_id: Session ID
            computer: Computer name where session is running
            key: Key command name (e.g. enter, escape, key_up)
            count: Optional repeat count for commands that support it

        Returns:
            True if successful

        Raises:
            APIError: If request fails
        """
        payload = {"key": key}
        if count is not None:
            payload["count"] = count
        resp = await self._request(
            "POST",
            f"/sessions/{session_id}/keys",
            params={"computer": computer},
            json_body=payload,
        )
        return resp.status_code == 200

    async def get_agent_availability(self) -> dict[str, AgentAvailabilityInfo]:
        """Get agent availability status.

        Returns:
            Dict mapping agent name to availability info

        Raises:
            APIError: If request fails
        """
        resp = await self._request("GET", "/agents/availability")
        return TypeAdapter(dict[str, AgentAvailabilityInfo]).validate_json(resp.text)

    async def list_projects_with_todos(self) -> list[ProjectWithTodosInfo]:
        """List all projects with their todos included.

        Returns:
            List of projects, each with a 'todos' field

        Raises:
            APIError: If request fails
        """
        projects = await self.list_projects()
        todos = await self.list_todos()
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
        """List todos.

        Args:
            project_path: Optional project path filter
            computer: Optional computer name filter

        Returns:
            List of todo objects

        Raises:
            APIError: If request fails
        """
        params: dict[str, str] = {}
        if project_path:
            params["project"] = project_path
        if computer:
            params["computer"] = computer
        resp = await self._request("GET", "/todos", params=params)
        return TypeAdapter(list[TodoInfo]).validate_json(resp.text)

    async def list_jobs(self) -> list[JobInfo]:
        """List scheduled jobs.

        Returns:
            List of job objects

        Raises:
            APIError: If request fails
        """
        resp = await self._request("GET", "/jobs")
        return TypeAdapter(list[JobInfo]).validate_json(resp.text)

    async def run_job(self, name: str) -> bool:
        """Run a scheduled job immediately.

        Args:
            name: Job name

        Returns:
            True if successful

        Raises:
            APIError: If request fails
        """
        resp = await self._request("POST", f"/jobs/{name}/run", timeout=30.0)
        data = resp.json()
        return data.get("status") == "success"

    async def agent_restart(self, session_id: str) -> bool:
        """Restart agent in a session (preserves conversation via --resume).

        Args:
            session_id: Session ID to restart agent in

        Returns:
            True if successful

        Raises:
            APIError: If request fails
        """
        resp = await self._request("POST", f"/sessions/{session_id}/agent-restart")
        return resp.status_code == 200

    async def get_settings(self) -> SettingsInfo:
        """Get current runtime settings."""
        resp = await self._request("GET", "/settings")
        return TypeAdapter(SettingsInfo).validate_json(resp.text)

    async def patch_settings(self, updates: SettingsPatchInfo) -> SettingsInfo:
        """Apply partial updates to runtime settings."""
        resp = await self._request("PATCH", "/settings", json_body=updates.model_dump(exclude_none=True))
        return TypeAdapter(SettingsInfo).validate_json(resp.text)

    async def revive_session(self, session_id: str) -> CreateSessionResult:
        """Revive a session by TeleClaude session ID.

        This endpoint can revive previously closed sessions as long as the session
        still has an active agent and native session ID.
        """
        resp = await self._request("POST", f"/sessions/{session_id}/revive", timeout=30.0)
        return TypeAdapter(CreateSessionResult).validate_json(resp.text)
