"""REST adapter for HTTP/Unix socket access.

This adapter provides HTTP endpoints for local clients (telec CLI, etc.)
and routes all requests through AdapterClient like other adapters.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, AsyncIterator, Literal, Protocol, TypedDict

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.rest_models import CreateSessionRequest, SendMessageRequest
from teleclaude.constants import REST_SOCKET_PATH
from teleclaude.core.models import ChannelMetadata, MessageMetadata

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import PeerInfo, Session

logger = get_logger(__name__)


class EndSessionResult(TypedDict):
    """Result from MCP end_session operation."""

    status: Literal["success", "error"]
    message: str


class MCPServerProtocol(Protocol):
    """Protocol for MCP server operations used by REST adapter."""

    computer_name: str
    """Local computer name for normalization."""

    async def teleclaude__end_session(self, *, computer: str, session_id: str) -> EndSessionResult:
        """End a session on a computer."""
        ...

    async def teleclaude__list_computers(self) -> list[dict[str, object]]:  # guard: loose-dict - Protocol boundary
        """List available computers (local + peers)."""
        ...

    async def teleclaude__list_projects(
        self, computer: str | None = None
    ) -> list[dict[str, str]]:  # guard: loose-dict - Protocol boundary
        """List available projects (local + remote when computer=None)."""
        ...

    async def teleclaude__list_sessions(
        self, computer: str | None = None
    ) -> list[dict[str, object]]:  # guard: loose-dict - Protocol boundary
        """List sessions (local + remote when computer=None)."""
        ...

    async def teleclaude__list_todos(
        self, computer: str, project_path: str, *, skip_peer_check: bool = False
    ) -> list[dict[str, object]]:  # guard: loose-dict - Protocol boundary
        """List todos from roadmap.md for a project on target computer."""
        ...


class RESTAdapter(BaseAdapter):
    """REST adapter exposing HTTP API on Unix socket."""

    ADAPTER_KEY = "rest"

    def __init__(self, client: AdapterClient) -> None:
        """Initialize REST adapter.

        Args:
            client: AdapterClient instance for routing events
        """
        self.client = client
        self.mcp_server: MCPServerProtocol | None = None  # Set later via set_mcp_server()
        self.app = FastAPI(title="TeleClaude API", version="1.0.0")
        self._setup_routes()
        self.server: uvicorn.Server | None = None
        self.server_task: asyncio.Task[object] | None = None

    def set_mcp_server(self, mcp_server: MCPServerProtocol) -> None:
        """Set MCP server reference after initialization.

        Args:
            mcp_server: TeleClaudeMCPServer instance (satisfies MCPServerProtocol)
        """
        self.mcp_server = mcp_server

    def _setup_routes(self) -> None:
        """Set up all HTTP endpoints."""

        @self.app.get("/health")  # type: ignore[misc]
        async def health() -> dict[str, str]:  # type: ignore[reportUnusedFunction, unused-ignore]
            """Health check endpoint."""
            return {"status": "ok"}

        @self.app.get("/sessions")  # type: ignore[misc]
        async def list_sessions(  # type: ignore[reportUnusedFunction, unused-ignore]
            computer: str | None = None,
        ) -> list[dict[str, object]]:  # guard: loose-dict - REST API boundary
            """List sessions from all computers (None) or specific computer."""
            if not self.mcp_server:
                raise HTTPException(status_code=503, detail="MCP server not available")
            try:
                # Use MCP handler which adds computer field to each session
                result = await self.mcp_server.teleclaude__list_sessions(computer)
                return [dict(s) for s in result]  # Convert TypedDicts to plain dicts
            except Exception as e:
                logger.error("list_sessions failed (computer=%s): %s", computer, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to list sessions: {e}") from e

        @self.app.post("/sessions")  # type: ignore[misc]
        async def create_session(  # type: ignore[reportUnusedFunction, unused-ignore]
            request: CreateSessionRequest,
        ) -> dict[str, object]:  # guard: loose-dict - REST API boundary
            """Create new session (local or remote)."""
            # Derive title from message if not provided
            title = request.title
            if not title and request.message and request.message.startswith("/"):
                title = request.message
            title = title or "Untitled"

            # Build args list: [computer, agent, thinking_mode, message]
            args = [
                request.computer,
                request.agent,
                request.thinking_mode,
            ]
            if request.message:
                args.append(request.message)

            try:
                result = await self.client.handle_event(
                    event="new_session",
                    payload={
                        "session_id": "",  # Will be created
                        "args": args,
                    },
                    metadata=self._metadata(
                        title=title,
                        project_dir=request.project_dir,
                    ),
                )
                return result  # type: ignore[return-value]  # Dynamic from handler
            except Exception as e:
                logger.error("create_session failed (computer=%s): %s", request.computer, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to create session: {e}") from e

        @self.app.delete("/sessions/{session_id}")  # type: ignore[misc]
        async def end_session(  # type: ignore[reportUnusedFunction, unused-ignore]
            session_id: str, computer: str = Query(...)
        ) -> dict[str, object]:  # guard: loose-dict - REST API boundary
            """End session - uses MCP server directly (no event for this operation)."""
            if not self.mcp_server:
                raise HTTPException(status_code=503, detail="MCP server not available")
            # Call MCP method directly (end_session has no event type)
            try:
                result = await self.mcp_server.teleclaude__end_session(computer=computer, session_id=session_id)
                return dict(result)
            except Exception as e:
                logger.error("Failed to end session %s on %s: %s", session_id, computer, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to end session: {e}") from e

        @self.app.post("/sessions/{session_id}/message")  # type: ignore[misc]
        async def send_message_endpoint(  # type: ignore[reportUnusedFunction, unused-ignore]
            session_id: str,
            request: SendMessageRequest,
            computer: str | None = Query(None),  # noqa: ARG001 - Optional param for API consistency
        ) -> dict[str, object]:  # guard: loose-dict - REST API boundary
            """Send message to session.

            Args:
                session_id: Session ID (unique across computers)
                request: Message request
                computer: Optional computer name (for API consistency, not used)
            """
            try:
                result = await self.client.handle_event(
                    event="message",
                    payload={
                        "session_id": session_id,
                        "text": request.message,
                    },
                    metadata=self._metadata(),
                )
                return {"status": "success", "result": result}
            except Exception as e:
                logger.error("send_message failed (session=%s): %s", session_id, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to send message: {e}") from e

        @self.app.get("/sessions/{session_id}/transcript")  # type: ignore[misc]
        async def get_transcript(  # type: ignore[reportUnusedFunction, unused-ignore]
            session_id: str,
            computer: str | None = Query(None),  # noqa: ARG001 - Optional param for API consistency
            tail_chars: int = Query(5000),
        ) -> dict[str, object]:  # guard: loose-dict - REST API boundary
            """Get session transcript.

            Args:
                session_id: Session ID (unique across computers)
                computer: Optional computer name (for API consistency, not used)
                tail_chars: Number of characters from end of transcript
            """
            try:
                result = await self.client.handle_event(
                    event="get_session_data",
                    payload={
                        "session_id": session_id,
                        "args": [str(tail_chars)],
                    },
                    metadata=self._metadata(),
                )
                return result  # type: ignore[return-value]  # Dynamic from handler
            except Exception as e:
                logger.error("get_transcript failed (session=%s): %s", session_id, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to get transcript: {e}") from e

        @self.app.get("/computers")  # type: ignore[misc]
        async def list_computers() -> list[dict[str, object]]:  # type: ignore[reportUnusedFunction, unused-ignore]  # guard: loose-dict - REST API boundary
            """List available computers (local + online peers only)."""
            if not self.mcp_server:
                raise HTTPException(status_code=503, detail="MCP server not available")
            try:
                # Use MCP handler which does full peer discovery
                raw_computers = await self.mcp_server.teleclaude__list_computers()
                # Filter to online/local and normalize status
                result: list[dict[str, object]] = []  # guard: loose-dict - REST API boundary
                for comp in raw_computers:
                    status = comp.get("status")
                    if status in ("online", "local"):
                        result.append(
                            {
                                "name": comp.get("name"),
                                "status": "online",  # Normalize "local" to "online"
                                "user": comp.get("user"),
                                "host": comp.get("host"),
                            }
                        )
                return result
            except Exception as e:
                logger.error("list_computers failed: %s", e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to list computers: {e}") from e

        @self.app.get("/projects")  # type: ignore[misc]
        async def list_projects(  # type: ignore[reportUnusedFunction, unused-ignore]
            computer: str | None = None,
        ) -> list[dict[str, object]]:  # guard: loose-dict - REST API boundary
            """List projects (local + remote when computer=None)."""
            if not self.mcp_server:
                raise HTTPException(status_code=503, detail="MCP server not available")
            try:
                # Use MCP handler which aggregates local + remote projects
                raw_projects = await self.mcp_server.teleclaude__list_projects(computer)
                local_name = self.mcp_server.computer_name
                # Transform to TUI-expected format:
                # - "local" computer → actual computer name
                # - desc → description (TUI field naming)
                # - location → path fallback (for remotes not yet deployed)
                result: list[dict[str, object]] = []  # guard: loose-dict - REST API boundary
                for p in raw_projects:
                    comp = p.get("computer", "local")
                    result.append(
                        {
                            "computer": local_name if comp == "local" else comp,
                            "name": p.get("name", ""),
                            "path": p.get("path") or p.get("location", ""),
                            "description": p.get("desc"),
                        }
                    )
                return result
            except Exception as e:
                logger.error("list_projects failed (computer=%s): %s", computer, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to list projects: {e}") from e

        @self.app.get("/agents/availability")  # type: ignore[misc]
        async def get_agent_availability() -> dict[str, dict[str, object]]:  # type: ignore[reportUnusedFunction, unused-ignore]  # guard: loose-dict - REST API boundary
            """Get agent availability."""
            from teleclaude.core.db import db

            agents = ["claude", "gemini", "codex"]
            result: dict[str, dict[str, object]] = {}  # guard: loose-dict - REST API boundary

            for agent in agents:
                try:
                    info = await db.get_agent_availability(agent)
                except Exception as e:
                    logger.error("Failed to get availability for agent %s: %s", agent, e)
                    result[agent] = {
                        "agent": agent,
                        "available": None,  # Unknown due to DB error
                        "unavailable_until": None,
                        "reason": None,
                        "error": str(e),
                    }
                    continue

                if info:
                    unavail_until = info.get("unavailable_until")
                    reason_val = info.get("reason")
                    result[agent] = {
                        "agent": agent,
                        "available": bool(info.get("available", True)),
                        "unavailable_until": str(unavail_until)
                        if unavail_until and unavail_until is not True
                        else None,
                        "reason": str(reason_val) if reason_val and reason_val is not True else None,
                    }
                else:
                    # No record means agent is available (never marked unavailable)
                    result[agent] = {
                        "agent": agent,
                        "available": True,
                        "unavailable_until": None,
                        "reason": None,
                    }

            return result

        @self.app.get("/projects/{path:path}/todos")  # type: ignore[misc]
        async def list_todos(path: str, computer: str = Query(...)) -> list[dict[str, object]]:  # type: ignore[reportUnusedFunction, unused-ignore]  # guard: loose-dict - REST API boundary
            """List todos from roadmap.md for a project.

            Args:
                path: Project directory path
                computer: Target computer name (required)
            """
            if not self.mcp_server:
                raise HTTPException(status_code=503, detail="MCP server not available")
            # Empty path means remote didn't provide it - can't fetch todos
            if not path:
                return []
            try:
                # Use MCP handler which routes to local or remote computer
                # skip_peer_check=True because TUI already validated computer is online
                todos = await self.mcp_server.teleclaude__list_todos(computer, path, skip_peer_check=True)
                return list(todos)
            except Exception as e:
                logger.error("list_todos failed (computer=%s, path=%s): %s", computer, path, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to list todos: {e}") from e

    async def start(self) -> None:
        """Start the REST API server on Unix socket."""
        # Remove old socket if exists
        if os.path.exists(REST_SOCKET_PATH):
            os.unlink(REST_SOCKET_PATH)

        config = uvicorn.Config(
            self.app,
            uds=REST_SOCKET_PATH,
            log_level="warning",
        )
        self.server = uvicorn.Server(config)

        # Run server in background task
        self.server_task = asyncio.create_task(self.server.serve())
        logger.info("REST API server listening on %s", REST_SOCKET_PATH)

    async def stop(self) -> None:
        """Stop the REST API server."""
        if self.server:
            self.server.should_exit = True
        if self.server_task:
            self.server_task.cancel()
            try:
                await self.server_task
            except asyncio.CancelledError:
                pass
        logger.info("REST API server stopped")

    # ==================== BaseAdapter abstract methods (mostly no-ops) ====================

    async def create_channel(
        self,
        session: Session,
        title: str,
        metadata: ChannelMetadata,
    ) -> str:
        """No-op for REST adapter (no channels)."""
        _ = (session, title, metadata)
        return ""

    async def update_channel_title(self, session: Session, title: str) -> bool:
        """No-op for REST adapter."""
        _ = (session, title)
        return True

    async def close_channel(self, session: Session) -> bool:
        """No-op for REST adapter."""
        _ = session
        return True

    async def reopen_channel(self, session: Session) -> bool:
        """No-op for REST adapter."""
        _ = session
        return True

    async def delete_channel(self, session: Session) -> bool:
        """No-op for REST adapter."""
        _ = session
        return True

    async def send_message(
        self,
        session: Session,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> str:
        """No-op for REST adapter (clients poll for output)."""
        _ = (session, text, metadata)
        return ""

    async def edit_message(
        self,
        session: Session,
        message_id: str,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> bool:
        """No-op for REST adapter."""
        _ = (session, message_id, text, metadata)
        return True

    async def delete_message(self, session: Session, message_id: str) -> bool:
        """No-op for REST adapter."""
        _ = (session, message_id)
        return True

    async def send_file(
        self,
        session: Session,
        file_path: str,
        *,
        caption: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> str:
        """No-op for REST adapter."""
        _ = (session, file_path, caption, metadata)
        return ""

    async def discover_peers(self) -> list[PeerInfo]:
        """REST adapter doesn't discover peers."""
        return []

    async def poll_output_stream(
        self,
        session: Session,
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        """No-op for REST adapter."""
        _ = (session, timeout)

        async def _empty() -> AsyncIterator[str]:
            if False:
                yield ""

        return _empty()
