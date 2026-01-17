"""HTTP client for telec TUI."""

import json
import threading
import time
from collections.abc import Callable
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
    ProjectInfo,
    ProjectWithTodosInfo,
    SessionInfo,
    SubscribeData,
    SubscribeRequest,
    TodoInfo,
    UnsubscribeData,
    UnsubscribeRequest,
    WsEvent,
)
from teleclaude.constants import REST_SOCKET_PATH

logger = get_logger(__name__)

BASE_URL = "http://localhost"
WS_URI = "ws://localhost/ws"

# Reconnection settings
WS_INITIAL_BACKOFF = 1.0  # Initial reconnect delay in seconds
WS_MAX_BACKOFF = 30.0  # Maximum reconnect delay
WS_BACKOFF_MULTIPLIER = 2.0  # Exponential backoff multiplier

__all__ = ["TelecAPIClient", "APIError"]

WsPayload: TypeAlias = dict[str, dict[str, str | list[str]]]


class APIError(Exception):
    """API request failed."""


class TelecAPIClient:
    """Async HTTP client for telec with WebSocket push support."""

    def __init__(self, socket_path: str = REST_SOCKET_PATH):
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

    # --- REST API Methods ---

    async def _request(
        self,
        method: str,
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

        try:
            if method == "GET":
                resp = await self._client.get(url, params=params, timeout=request_timeout)
            elif method == "POST":
                resp = await self._client.post(url, params=params, json=json_body, timeout=request_timeout)
            elif method == "DELETE":
                resp = await self._client.delete(url, params=params, timeout=request_timeout)
            else:
                raise APIError(f"Unsupported HTTP method: {method}")

            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            raise APIError(f"API request failed: {e.response.status_code} {e.response.text}") from e
        except httpx.ConnectError as e:
            raise APIError("Cannot connect to REST API server. Socket may be missing.") from e
        except httpx.TimeoutException as e:
            raise APIError("REST API request timed out. Server may be blocked or overloaded.") from e
        except Exception as e:
            raise APIError(f"Unexpected error: {e}") from e

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

    async def get_transcript(self, session_id: str, computer: str, tail_chars: int = 5000) -> str:
        """Get session transcript.

        Args:
            session_id: Session ID
            computer: Computer name where session is running
            tail_chars: Number of characters to retrieve from end

        Returns:
            Transcript text

        Raises:
            APIError: If request fails
        """
        resp = await self._request(
            "GET",
            f"/sessions/{session_id}/transcript",
            params={"computer": computer, "tail_chars": str(tail_chars)},
        )
        result = TypeAdapter(dict[str, str | None]).validate_json(resp.text)
        return result.get("transcript") or ""

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
