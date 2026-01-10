"""HTTP client for telec TUI."""

from typing import Any

import httpx

from teleclaude.constants import REST_SOCKET_PATH

BASE_URL = "http://localhost"

__all__ = ["TelecAPIClient", "APIError"]


class APIError(Exception):
    """API request failed."""


class TelecAPIClient:
    """Async HTTP client for telec."""

    def __init__(self, socket_path: str = REST_SOCKET_PATH):
        """Initialize client.

        Args:
            socket_path: Path to Unix socket
        """
        self.socket_path = socket_path
        self._client: httpx.AsyncClient | None = None

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
        if self._client:
            await self._client.aclose()
            self._client = None

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

    async def list_todos(self, project_path: str, computer: str) -> list[dict[str, object]]:  # guard: loose-dict
        """List todos from roadmap.md for a project.

        Args:
            project_path: Absolute path to project directory
            computer: Computer name where project is located

        Returns:
            List of todo dicts

        Raises:
            APIError: If request fails
        """
        resp = await self._request("GET", f"/projects/{project_path}/todos", params={"computer": computer})
        return resp.json()
