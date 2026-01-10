"""REST adapter for HTTP/Unix socket access.

This adapter provides HTTP endpoints for local clients (telec CLI, etc.)
and routes all requests through AdapterClient like other adapters.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Literal, Protocol, TypedDict

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.rest_models import CreateSessionRequest, SendMessageRequest
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

    async def teleclaude__end_session(self, *, computer: str, session_id: str) -> EndSessionResult:
        """End a session on a computer."""
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
            """List sessions from all computers or specific computer."""
            # list_sessions is a command event that returns sessions directly
            result = await self.client.handle_event(
                event="list_sessions",
                payload={
                    "session_id": "",  # Not used for list_sessions but required by CommandEventContext
                    "args": [computer] if computer else [],
                },
                metadata=self._metadata(),
            )
            # Result is list[SessionListItem] from handler
            if isinstance(result, list):
                return result  # Dynamic from handler
            logger.error("list_sessions returned non-list result: %s", type(result).__name__)
            raise HTTPException(status_code=500, detail="Internal error: unexpected handler result type")

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
            computer: str = Query(...),  # noqa: ARG001 - computer param for API consistency
        ) -> dict[str, object]:  # guard: loose-dict - REST API boundary
            """Send message to session."""
            result = await self.client.handle_event(
                event="message",
                payload={
                    "session_id": session_id,
                    "text": request.message,
                },
                metadata=self._metadata(),
            )
            return {"status": "success", "result": result}

        @self.app.get("/sessions/{session_id}/transcript")  # type: ignore[misc]
        async def get_transcript(  # type: ignore[reportUnusedFunction, unused-ignore]
            session_id: str,
            computer: str = Query(...),  # noqa: ARG001 - computer param for API consistency
            tail_chars: int = Query(5000),
        ) -> dict[str, object]:  # guard: loose-dict - REST API boundary
            """Get session transcript."""
            result = await self.client.handle_event(
                event="get_session_data",
                payload={
                    "session_id": session_id,
                    "args": [str(tail_chars)],
                },
                metadata=self._metadata(),
            )
            return result  # type: ignore[return-value]  # Dynamic from handler

        @self.app.get("/computers")  # type: ignore[misc]
        async def list_computers() -> list[dict[str, object]]:  # type: ignore[reportUnusedFunction, unused-ignore]  # guard: loose-dict - REST API boundary
            """List available computers."""
            result = await self.client.handle_event(
                event="get_computer_info",
                payload={
                    "session_id": "",  # Not used for get_computer_info
                    "args": [],
                },
                metadata=self._metadata(),
            )
            # Result is computer info list
            if isinstance(result, list):
                return result  # Dynamic from handler
            logger.error("list_computers returned non-list result: %s", type(result).__name__)
            raise HTTPException(status_code=500, detail="Internal error: unexpected handler result type")

        @self.app.get("/projects")  # type: ignore[misc]
        async def list_projects(  # type: ignore[reportUnusedFunction, unused-ignore]
            computer: str | None = None,
        ) -> list[dict[str, object]]:  # guard: loose-dict - REST API boundary
            """List projects."""
            result = await self.client.handle_event(
                event="list_projects",
                payload={
                    "session_id": "",  # Not used for list_projects
                    "args": [computer] if computer else [],
                },
                metadata=self._metadata(),
            )
            # Result is project list
            if isinstance(result, list):
                return result  # Dynamic from handler
            logger.error("list_projects returned non-list result: %s", type(result).__name__)
            raise HTTPException(status_code=500, detail="Internal error: unexpected handler result type")

        @self.app.get("/agents/availability")  # type: ignore[misc]
        async def get_agent_availability() -> dict[str, dict[str, object]]:  # type: ignore[reportUnusedFunction, unused-ignore]  # guard: loose-dict - REST API boundary
            """Get agent availability."""
            from teleclaude.core.db import db

            agents = ["claude", "gemini", "codex"]
            result: dict[str, dict[str, object]] = {}  # guard: loose-dict - REST API boundary

            for agent in agents:
                info = await db.get_agent_availability(agent)
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
                    result[agent] = {
                        "agent": agent,
                        "available": True,
                        "unavailable_until": None,
                        "reason": None,
                    }

            return result

        @self.app.get("/projects/{path:path}/todos")  # type: ignore[misc]
        async def list_todos(path: str, computer: str = Query(...)) -> list[dict[str, object]]:  # type: ignore[reportUnusedFunction, unused-ignore]  # noqa: ARG001  # guard: loose-dict - REST API boundary
            """List todos from roadmap.md."""
            import re

            roadmap_path = Path(path) / "todos" / "roadmap.md"
            if not await asyncio.to_thread(roadmap_path.exists):
                return []

            content = await asyncio.to_thread(roadmap_path.read_text)
            todos: list[dict[str, object]] = []  # guard: loose-dict - REST API boundary

            pattern = re.compile(r"^-\s+\[([ .>])\]\s+(\S+)", re.MULTILINE)
            status_map = {" ": "pending", ".": "ready", ">": "in_progress"}

            lines = content.split("\n")
            for i, line in enumerate(lines):
                match = pattern.match(line)
                if match:
                    status_char = match.group(1)
                    slug = match.group(2)

                    description = ""
                    for j in range(i + 1, len(lines)):
                        next_line = lines[j]
                        if next_line.startswith("      "):
                            description += next_line.strip() + " "
                        elif next_line.strip() == "":
                            continue
                        else:
                            break

                    todos_dir = Path(path) / "todos" / slug
                    has_requirements = await asyncio.to_thread((todos_dir / "requirements.md").exists)
                    has_impl_plan = await asyncio.to_thread((todos_dir / "implementation-plan.md").exists)

                    todos.append(
                        {
                            "slug": slug,
                            "status": status_map.get(status_char, "pending"),
                            "description": description.strip() or None,
                            "has_requirements": has_requirements,
                            "has_impl_plan": has_impl_plan,
                        }
                    )

            return todos

    async def start(self) -> None:
        """Start the REST API server on Unix socket."""
        socket_path = "/tmp/teleclaude-api.sock"

        # Remove old socket if exists
        if os.path.exists(socket_path):
            os.unlink(socket_path)

        config = uvicorn.Config(
            self.app,
            uds=socket_path,
            log_level="warning",
        )
        self.server = uvicorn.Server(config)

        # Run server in background task
        self.server_task = asyncio.create_task(self.server.serve())
        logger.info("REST API server listening on %s", socket_path)

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
