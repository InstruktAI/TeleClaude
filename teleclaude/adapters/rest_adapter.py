"""REST adapter for HTTP/Unix socket access.

This adapter provides HTTP endpoints for local clients (telec CLI, etc.)
and routes all requests through AdapterClient like other adapters.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING, AsyncIterator

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.rest_models import CreateSessionRequest, SendMessageRequest
from teleclaude.config import config
from teleclaude.constants import REST_SOCKET_PATH
from teleclaude.core import command_handlers
from teleclaude.core.models import ChannelMetadata, MessageMetadata

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.models import PeerInfo, Session
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)


class RESTAdapter(BaseAdapter):
    """REST adapter exposing HTTP API on Unix socket."""

    ADAPTER_KEY = "rest"

    def __init__(
        self,
        client: AdapterClient,
        cache: "DaemonCache | None" = None,
        task_registry: "TaskRegistry | None" = None,
    ) -> None:
        """Initialize REST adapter.

        Args:
            client: AdapterClient instance for routing events
            cache: Optional DaemonCache for remote data (None = local-only mode)
            task_registry: Optional TaskRegistry for tracking background tasks
        """
        self.client = client
        self.cache = cache
        self.task_registry = task_registry
        self.app = FastAPI(title="TeleClaude API", version="1.0.0")
        self._setup_routes()
        self.server: uvicorn.Server | None = None
        self.server_task: asyncio.Task[object] | None = None

        # WebSocket state
        self._ws_clients: set[WebSocket] = set()
        self._client_subscriptions: dict[WebSocket, set[str]] = {}

        # Subscribe to cache changes
        if self.cache:
            self.cache.subscribe(self._on_cache_change)

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
            """List sessions from local computer + cached remote sessions."""
            try:
                # Get LOCAL sessions from command handler
                local_sessions = await command_handlers.handle_list_sessions()
                # Add computer field for consistency
                computer_name = config.computer.name
                result = []
                for session in local_sessions:
                    session_dict = dict(session)
                    session_dict["computer"] = computer_name
                    result.append(session_dict)

                # Add REMOTE sessions from cache (if available)
                if self.cache:
                    cached_sessions = self.cache.get_sessions(computer)
                    result.extend([dict(s) for s in cached_sessions])

                return result
            except Exception as e:
                logger.error("list_sessions failed: %s", e, exc_info=True)
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
            session_id: str,
            computer: str = Query(...),  # noqa: ARG001 - For API consistency, only local sessions supported
        ) -> dict[str, object]:  # guard: loose-dict - REST API boundary
            """End session - local sessions only (remote session management via MCP tools)."""
            try:
                # Use command handler directly - only supports LOCAL sessions
                result = await command_handlers.handle_end_session(session_id, self.client)
                return dict(result)
            except Exception as e:
                logger.error("Failed to end session %s: %s", session_id, e, exc_info=True)
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

        @self.app.post("/sessions/{session_id}/agent-restart")  # type: ignore[misc]
        async def agent_restart(  # type: ignore[reportUnusedFunction, unused-ignore]
            session_id: str,
        ) -> dict[str, str]:
            """Restart agent in session (preserves conversation via --resume)."""
            try:
                await self.client.handle_event(
                    event="agent_restart",
                    payload={"args": [], "session_id": session_id},
                    metadata=self._metadata(),
                )
                return {"status": "ok"}
            except Exception as e:
                logger.error("agent_restart failed for session %s: %s", session_id, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to restart agent: {e}") from e

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
            """List available computers (local + cached remote computers)."""
            try:
                # Local computer
                computer_info = await command_handlers.handle_get_computer_info()
                result: list[dict[str, object]] = [  # guard: loose-dict - REST API boundary
                    {
                        "name": config.computer.name,
                        "status": "online",  # Local computer is always online
                        "user": computer_info["user"],
                        "host": computer_info["host"],
                    }
                ]

                # Add cached remote computers (if available)
                if self.cache:
                    cached_computers = self.cache.get_computers()
                    for comp in cached_computers:
                        result.append(
                            {
                                "name": comp["name"],
                                "status": "online",  # Cached computers are online (auto-expired if stale)
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
            """List projects (local + cached remote projects)."""
            try:
                # Trigger background pull for stale remote projects
                if self.cache:
                    from teleclaude.adapters.redis_adapter import RedisAdapter

                    redis_adapter_base = self.client.adapters.get("redis")
                    if redis_adapter_base and isinstance(redis_adapter_base, RedisAdapter):
                        redis_adapter: RedisAdapter = redis_adapter_base

                        # Get all remote computers and check staleness
                        computers = self.cache.get_computers()
                        for comp in computers:
                            comp_name = comp["name"]
                            cache_key = f"{comp_name}:*"  # Check any project from this computer

                            # Check if projects from this computer are stale (TTL=5 min)
                            if self.cache.is_stale(cache_key, 300):
                                # Trigger background pull (don't wait)
                                if self.task_registry:
                                    self.task_registry.spawn(
                                        redis_adapter.pull_remote_projects(comp_name),
                                        name=f"pull-projects-{comp_name}",
                                    )
                                else:
                                    # Fallback: create untracked task
                                    task = asyncio.create_task(redis_adapter.pull_remote_projects(comp_name))
                                    task.add_done_callback(
                                        lambda t: logger.error("Pull projects failed: %s", t.exception())
                                        if t.exception()
                                        else None
                                    )

                # Get LOCAL projects from command handler
                raw_projects = await command_handlers.handle_list_projects()
                computer_name = config.computer.name
                result: list[dict[str, object]] = []  # guard: loose-dict - REST API boundary

                # Add local projects
                for p in raw_projects:
                    result.append(
                        {
                            "computer": computer_name,
                            "name": p.get("name", ""),
                            "path": p.get("path", ""),
                            "description": p.get("desc"),
                        }
                    )

                # Add cached REMOTE projects (if available)
                # Note: Cached projects don't have computer field yet (Phase 1 limitation)
                # They will be added via heartbeat integration in later phases
                if self.cache:
                    cached_projects = self.cache.get_projects(computer)
                    for proj in cached_projects:
                        result.append(
                            {
                                "computer": "",  # TODO: Add computer field to ProjectInfo in cache
                                "name": proj["name"],
                                "path": proj["path"],
                                "description": proj["desc"],
                            }
                        )

                return result
            except Exception as e:
                logger.error("list_projects failed: %s", e, exc_info=True)
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

        @self.app.get("/projects-with-todos")  # type: ignore[misc]
        async def list_projects_with_todos() -> list[dict[str, object]]:  # type: ignore[reportUnusedFunction, unused-ignore]  # guard: loose-dict - REST API boundary
            """List all projects with their todos included (local + cached remote).

            Returns:
                List of projects, each with a 'todos' field containing the project's todos
            """
            # Trigger background pull for stale remote todos
            if self.cache:
                from teleclaude.adapters.redis_adapter import RedisAdapter

                redis_adapter_base = self.client.adapters.get("redis")
                if redis_adapter_base and isinstance(redis_adapter_base, RedisAdapter):
                    redis_adapter: RedisAdapter = redis_adapter_base

                    # Get all remote projects and check todos staleness
                    cached_projects = self.cache.get_projects()
                    for proj in cached_projects:
                        comp_name = str(proj.get("computer", ""))
                        proj_path = str(proj.get("path", ""))
                        if comp_name and proj_path:
                            cache_key = f"{comp_name}:{proj_path}"

                            # Check if todos for this project are stale (TTL=5 min)
                            if self.cache.is_stale(cache_key, 300):
                                # Trigger background pull (don't wait)
                                if self.task_registry:
                                    self.task_registry.spawn(
                                        redis_adapter.pull_remote_todos(comp_name, proj_path),
                                        name=f"pull-todos-{comp_name}-{proj_path[:20]}",
                                    )
                                else:
                                    # Fallback: create untracked task
                                    task = asyncio.create_task(redis_adapter.pull_remote_todos(comp_name, proj_path))
                                    task.add_done_callback(
                                        lambda t: logger.error("Pull todos failed: %s", t.exception())
                                        if t.exception()
                                        else None
                                    )

            try:
                # Get LOCAL projects
                raw_projects = await command_handlers.handle_list_projects()
            except Exception as e:
                logger.error("list_projects_with_todos: failed to get projects: %s", e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to list projects: {e}") from e

            computer_name = config.computer.name
            result: list[dict[str, object]] = []  # guard: loose-dict - REST API boundary

            # Add LOCAL projects with todos
            for p in raw_projects:
                path = p.get("path", "")

                project: dict[str, object] = {  # guard: loose-dict - REST API boundary
                    "computer": computer_name,
                    "name": p.get("name", ""),
                    "path": path,
                    "description": p.get("desc"),
                    "todos": [],
                }

                if path:
                    try:
                        todos = await command_handlers.handle_list_todos(str(path))
                        project["todos"] = list(todos)
                    except Exception as e:
                        logger.warning("list_projects_with_todos: failed todos for %s: %s", path, e)

                result.append(project)

            # Add REMOTE projects with cached todos
            if self.cache:
                cached_projects = self.cache.get_projects()
                for proj in cached_projects:
                    comp_name = str(proj.get("computer", ""))
                    proj_path = str(proj.get("path", ""))
                    if not comp_name or not proj_path:
                        continue

                    # Get cached todos for this project
                    cached_todos = self.cache.get_todos(comp_name, proj_path)

                    remote_project: dict[str, object] = {  # guard: loose-dict - REST API boundary
                        "computer": comp_name,
                        "name": proj.get("name", ""),
                        "path": proj_path,
                        "description": proj.get("desc"),
                        "todos": list(cached_todos),
                    }
                    result.append(remote_project)

            return result

        @self.app.websocket("/ws")  # type: ignore[misc]
        async def websocket_endpoint(  # type: ignore[reportUnusedFunction, unused-ignore]
            websocket: WebSocket,
        ) -> None:
            """WebSocket endpoint for push updates."""
            await self._handle_websocket(websocket)

    async def _handle_websocket(self, websocket: WebSocket) -> None:
        """Handle WebSocket connection for push updates.

        Args:
            websocket: WebSocket connection
        """
        await websocket.accept()
        self._ws_clients.add(websocket)
        self._client_subscriptions[websocket] = set()
        logger.info("WebSocket client connected")

        # Update interest in cache when first client connects
        if self.cache and len(self._ws_clients) == 1:
            self._update_cache_interest()

        try:
            while True:
                # Receive messages from client
                message = await websocket.receive_text()
                data_raw: object = json.loads(message)

                # Type guard: ensure data is a dict
                if not isinstance(data_raw, dict):
                    logger.warning("WebSocket received non-dict message: %s", type(data_raw))
                    continue

                data: dict[str, object] = data_raw  # guard: loose-dict - WebSocket message

                # Handle subscription messages
                if "subscribe" in data:
                    topic_raw = data["subscribe"]
                    if not isinstance(topic_raw, str):
                        logger.warning("WebSocket subscribe topic is not a string: %s", type(topic_raw))
                        continue
                    topic: str = topic_raw
                    self._client_subscriptions[websocket].add(topic)
                    logger.info("WebSocket client subscribed to: %s", topic)

                    # Update cache interest
                    if self.cache:
                        self._update_cache_interest()

                    # Send initial state for this subscription
                    await self._send_initial_state(websocket, topic)

                # Handle refresh messages
                elif data.get("refresh"):
                    logger.info("WebSocket client requested refresh")
                    if self.cache:
                        self.cache.invalidate_all()
                        # Re-send initial state for all subscriptions
                        for topic in self._client_subscriptions[websocket]:
                            await self._send_initial_state(websocket, topic)

        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
        except Exception as e:
            logger.error("WebSocket error: %s", e, exc_info=True)
        finally:
            # Clean up
            self._ws_clients.discard(websocket)
            self._client_subscriptions.pop(websocket, None)

            # Update interest in cache when last client disconnects
            if self.cache and len(self._ws_clients) == 0:
                self._update_cache_interest()

    def _update_cache_interest(self) -> None:
        """Update cache interest based on active WebSocket subscriptions."""
        if not self.cache:
            return

        # Collect all subscriptions from all connected clients
        all_interests: set[str] = set()
        for subscriptions in self._client_subscriptions.values():
            all_interests.update(subscriptions)

        self.cache.set_interest(all_interests)
        logger.debug("Updated cache interest: %s", all_interests)

    async def _send_initial_state(self, websocket: WebSocket, topic: str) -> None:
        """Send initial state for a subscription topic.

        Args:
            websocket: WebSocket connection
            topic: Subscription topic (e.g., "sessions", "preparation")
        """
        try:
            if topic == "sessions":
                # Send current sessions from cache
                if self.cache:
                    sessions = self.cache.get_sessions()
                    await websocket.send_json({"event": "sessions_initial", "data": {"sessions": sessions}})  # type: ignore[misc]
            elif topic == "preparation":
                # Send current projects/todos from cache
                if self.cache:
                    projects = self.cache.get_projects()
                    await websocket.send_json({"event": "preparation_initial", "data": {"projects": projects}})  # type: ignore[misc]
        except Exception as e:
            logger.error("Failed to send initial state for %s: %s", topic, e, exc_info=True)

    def _on_cache_change(self, event: str, data: object) -> None:
        """Handle cache change notifications and push to WebSocket clients.

        Args:
            event: Event type (e.g., "session_updated", "computer_updated")
            data: Event data
        """
        # Push to all connected WebSocket clients
        for ws in list(self._ws_clients):
            # Create tracked async task to send message (don't block)
            coro = ws.send_json({"event": event, "data": data})  # type: ignore[misc]
            if self.task_registry:
                task = self.task_registry.spawn(coro, name=f"ws-broadcast-{event}")
            else:
                task = asyncio.create_task(coro)

            def on_done(t: asyncio.Task[object], client: WebSocket = ws) -> None:
                if t.done() and t.exception():
                    logger.warning("WebSocket send failed, removing client: %s", t.exception())
                    self._ws_clients.discard(client)
                    self._client_subscriptions.pop(client, None)

            task.add_done_callback(on_done)

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

        # Wait for server to be ready (socket file created and bound)
        max_retries = 50  # 5 seconds total
        for _ in range(max_retries):
            if self.server.started:
                break
            await asyncio.sleep(0.1)

        logger.info("REST API server listening on %s", REST_SOCKET_PATH)

    async def stop(self) -> None:
        """Stop the REST API server."""
        # Unsubscribe from cache changes
        if self.cache:
            self.cache.unsubscribe(self._on_cache_change)

        # Close all WebSocket connections
        for ws in list(self._ws_clients):
            try:
                await ws.close()
            except Exception as e:
                logger.warning("Error closing WebSocket: %s", e)
        self._ws_clients.clear()
        self._client_subscriptions.clear()

        # Clear interest from cache
        if self.cache:
            self.cache.set_interest(set())

        # Stop server gracefully if started, cancel if still starting
        if self.server:
            if self.server.started:
                # Server is running, do graceful shutdown
                self.server.should_exit = True
            else:
                # Server still starting, force cancel
                if self.server_task:
                    self.server_task.cancel()

        if self.server_task:
            try:
                await self.server_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                # Suppress errors during teardown (socket already gone, etc.)
                logger.debug("Error during server shutdown: %s", e)

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
