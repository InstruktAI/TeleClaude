"""HTTP client for telec TUI."""

import httpx

API_SOCKET = "/tmp/teleclaude-api.sock"
BASE_URL = "http://localhost"


class TelecAPIClient:
    """Async HTTP client for telec."""

    def __init__(self, socket_path: str = API_SOCKET):
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

    async def list_sessions(self, computer: str | None = None) -> list[dict[str, object]]:  # guard: loose-dict
        """List sessions from all computers or specific computer.

        Args:
            computer: Filter by computer name (None = all)

        Returns:
            List of session dicts
        """
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        params: dict[str, str] = {"computer": computer} if computer else {}
        resp = await self._client.get("/sessions", params=params)
        resp.raise_for_status()
        return resp.json()

    async def list_computers(self) -> list[dict[str, object]]:  # guard: loose-dict
        """List online computers only.

        Returns:
            List of computer dicts
        """
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        resp = await self._client.get("/computers")
        resp.raise_for_status()
        return resp.json()

    async def list_projects(self, computer: str | None = None) -> list[dict[str, object]]:  # guard: loose-dict
        """List projects from all or specific computer.

        Args:
            computer: Filter by computer name (None = all)

        Returns:
            List of project dicts
        """
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        params: dict[str, str] = {"computer": computer} if computer else {}
        resp = await self._client.get("/projects", params=params)
        resp.raise_for_status()
        return resp.json()

    async def create_session(self, **kwargs: object) -> dict[str, object]:  # guard: loose-dict
        """Create a new session.

        Args:
            **kwargs: Session parameters (computer, project_dir, agent, thinking_mode, title, message)

        Returns:
            Session creation result
        """
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        resp = await self._client.post("/sessions", json=kwargs)
        resp.raise_for_status()
        return resp.json()

    async def end_session(self, session_id: str, computer: str) -> bool:
        """End a session.

        Args:
            session_id: Session ID to end
            computer: Computer name where session is running

        Returns:
            True if successful
        """
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        resp = await self._client.delete(
            f"/sessions/{session_id}",
            params={"computer": computer},
        )
        return resp.status_code == 200

    async def send_message(self, session_id: str, computer: str, message: str) -> bool:
        """Send message to a session.

        Args:
            session_id: Session ID
            computer: Computer name where session is running
            message: Message to send

        Returns:
            True if successful
        """
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        resp = await self._client.post(
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
        """
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        resp = await self._client.get(
            f"/sessions/{session_id}/transcript",
            params={"computer": computer, "tail_chars": tail_chars},
        )
        resp.raise_for_status()
        result = resp.json()
        return result.get("transcript", "")

    async def get_agent_availability(self) -> dict[str, dict[str, object]]:  # guard: loose-dict
        """Get agent availability status.

        Returns:
            Dict mapping agent name to availability info
        """
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        resp = await self._client.get("/agents/availability")
        resp.raise_for_status()
        return resp.json()

    async def list_todos(self, project_path: str, computer: str) -> list[dict[str, object]]:  # guard: loose-dict
        """List todos from roadmap.md for a project.

        Args:
            project_path: Absolute path to project directory
            computer: Computer name where project is located

        Returns:
            List of todo dicts
        """
        if not self._client:
            raise RuntimeError("Client not connected. Call connect() first.")

        resp = await self._client.get(
            f"/projects/{project_path}/todos",
            params={"computer": computer},
        )
        resp.raise_for_status()
        return resp.json()
