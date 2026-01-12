"""HTTP client for telec TUI."""

import json
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
from instrukt_ai_logging import get_logger
from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.sync.client import ClientConnection, unix_connect

from teleclaude.constants import REST_SOCKET_PATH

logger = get_logger(__name__)

BASE_URL = "http://localhost"
WS_URI = "ws://localhost/ws"

# Reconnection settings
WS_INITIAL_BACKOFF = 1.0  # Initial reconnect delay in seconds
WS_MAX_BACKOFF = 30.0  # Maximum reconnect delay
WS_BACKOFF_MULTIPLIER = 2.0  # Exponential backoff multiplier

__all__ = ["TelecAPIClient", "APIError"]


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
        self._ws_callback: Callable[[str, dict[str, object]], None] | None = None  # guard: loose-dict
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
        callback: Callable[[str, dict[str, object]], None],  # guard: loose-dict
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

        # Subscribe to topics
        for topic in self._ws_subscriptions:
            ws.send(json.dumps({"subscribe": topic}))

        # Process incoming messages
        for message in ws:
            if not self._ws_running:
                break

            try:
                data_raw = json.loads(message)
                if not isinstance(data_raw, dict):
                    continue

                data: dict[str, object] = data_raw  # guard: loose-dict
                event = str(data.get("event", ""))
                event_data_raw = data.get("data")

                if event and self._ws_callback:
                    # Type guard: ensure event_data is a dict
                    if isinstance(event_data_raw, dict):
                        event_data: dict[str, object] = event_data_raw  # guard: loose-dict
                    else:
                        event_data = {}
                    self._ws_callback(event, event_data)

            except json.JSONDecodeError:
                logger.warning("Invalid JSON from WebSocket: %s", message[:100])

    # --- REST API Methods ---

    async def _request(  # type: ignore[explicit-any]
        self,
        method: str,
        url: str,
        *,
        timeout: float | None = None,
        **kwargs: Any,
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

        if timeout is not None:
            kwargs["timeout"] = timeout

        try:
            if method == "GET":
                resp = await self._client.get(url, **kwargs)
            elif method == "POST":
                resp = await self._client.post(url, **kwargs)
            elif method == "DELETE":
                resp = await self._client.delete(url, **kwargs)
            else:
                raise APIError(f"Unsupported HTTP method: {method}")

            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            raise APIError(f"API request failed: {e.response.status_code} {e.response.text}") from e
        except httpx.ConnectError as e:
            raise APIError("Cannot connect to TeleClaude daemon. Is it running?") from e
        except httpx.TimeoutException as e:
            raise APIError("Request timed out. Daemon may be overloaded.") from e
        except Exception as e:
            raise APIError(f"Unexpected error: {e}") from e

    async def list_sessions(self, computer: str | None = None) -> list[dict[str, object]]:  # guard: loose-dict
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
        return resp.json()

    async def list_computers(self) -> list[dict[str, object]]:  # guard: loose-dict
        """List online computers only.

        Returns:
            List of computer dicts

        Raises:
            APIError: If request fails
        """
        resp = await self._request("GET", "/computers")
        return resp.json()

    async def list_projects(self, computer: str | None = None) -> list[dict[str, object]]:  # guard: loose-dict
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
        return resp.json()

    async def create_session(self, **kwargs: object) -> dict[str, object]:  # guard: loose-dict
        """Create a new session.

        Args:
            **kwargs: Session parameters (computer, project_dir, agent, thinking_mode, title, message)

        Returns:
            Session creation result

        Raises:
            APIError: If request fails
        """
        # Session creation spawns tmux + agent, needs longer timeout
        resp = await self._request("POST", "/sessions", timeout=30.0, json=kwargs)
        return resp.json()

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
            json={"message": message},
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
            params={"computer": computer, "tail_chars": tail_chars},
        )
        result = resp.json()
        return result.get("transcript", "")

    async def get_agent_availability(self) -> dict[str, dict[str, object]]:  # guard: loose-dict
        """Get agent availability status.

        Returns:
            Dict mapping agent name to availability info

        Raises:
            APIError: If request fails
        """
        resp = await self._request("GET", "/agents/availability")
        return resp.json()

    async def list_projects_with_todos(self) -> list[dict[str, object]]:  # guard: loose-dict
        """List all projects with their todos included.

        Returns:
            List of projects, each with a 'todos' field

        Raises:
            APIError: If request fails
        """
        resp = await self._request("GET", "/projects-with-todos")
        return resp.json()

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
