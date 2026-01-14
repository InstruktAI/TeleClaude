"""REST adapter for HTTP/Unix socket access.

This adapter provides HTTP endpoints for local clients (telec CLI, etc.)
and routes all requests through AdapterClient like other adapters.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import time
from typing import TYPE_CHECKING, AsyncIterator

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.redis_adapter import RedisAdapter
from teleclaude.adapters.rest_models import CreateSessionRequest, SendMessageRequest
from teleclaude.config import config
from teleclaude.constants import REST_SOCKET_PATH
from teleclaude.core import command_handlers
from teleclaude.core.db import db
from teleclaude.core.events import SessionLifecycleContext, SessionUpdatedContext, TeleClaudeEvents
from teleclaude.core.models import ChannelMetadata, MessageMetadata, SessionSummary, ThinkingMode

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.models import PeerInfo, Session
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)

REST_RESTART_WINDOW_S = 60.0
REST_RESTART_MAX = 5
REST_RESTART_BACKOFF_S = 1.0
REST_WS_PING_INTERVAL_S = 20.0
REST_WS_PING_TIMEOUT_S = 20.0
REST_TIMEOUT_KEEP_ALIVE_S = 5


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
        self._running = False
        self._restart_lock = asyncio.Lock()
        self._restart_attempts = 0
        self._restart_window_start = 0.0

        # WebSocket state
        self._ws_clients: set[WebSocket] = set()
        # Per-computer subscriptions: {websocket: {computer: {data_types}}}
        self._client_subscriptions: dict[WebSocket, dict[str, set[str]]] = {}
        # Track previous interest to remove stale entries
        self._previous_interest: dict[str, set[str]] = {}  # {data_type: {computers}}

        # Subscribe to cache changes
        if self.cache:
            self.cache.subscribe(self._on_cache_change)

        # Subscribe to local session updates for TUI
        self.client.on(TeleClaudeEvents.SESSION_UPDATED, self._handle_session_updated)  # type: ignore[arg-type]
        self.client.on(TeleClaudeEvents.SESSION_TERMINATED, self._handle_session_terminated)  # type: ignore[arg-type]

    async def _handle_session_updated(self, _event: str, context: SessionUpdatedContext) -> None:
        """Forward local session updates to WebSocket clients."""
        session = await db.get_session(context.session_id)
        if not session:
            return

        summary = SessionSummary(
            session_id=session.session_id,
            origin_adapter=session.origin_adapter,
            title=session.title,
            working_directory=session.working_directory,
            thinking_mode=session.thinking_mode or ThinkingMode.SLOW.value,
            active_agent=session.active_agent,
            status="active",
            created_at=session.created_at.isoformat() if session.created_at else None,
            last_activity=session.last_activity.isoformat() if session.last_activity else None,
            last_input=session.last_message_sent,
            last_output=session.last_feedback_received,
            tmux_session_name=session.tmux_session_name,
            initiator_session_id=session.initiator_session_id,
        ).to_dict()
        summary["computer"] = config.computer.name
        self._on_cache_change("session_updated", summary)

    async def _handle_session_terminated(self, _event: str, context: SessionLifecycleContext) -> None:
        """Forward local session removals to WebSocket clients."""
        self._on_cache_change("session_removed", {"session_id": context.session_id})

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

            args = [title] if title else []

            auto_command = request.auto_command
            if not auto_command:
                if request.message:
                    quoted_message = shlex.quote(request.message)
                    auto_command = f"agent_then_message {request.agent} {request.thinking_mode} {quoted_message}"
                else:
                    auto_command = f"agent {request.agent} {request.thinking_mode}"

            try:
                envelope = await self.client.handle_event(
                    event="new_session",
                    payload={
                        "session_id": "",  # Will be created
                        "args": args,
                    },
                    metadata=self._metadata(
                        title=title,
                        project_dir=request.project_dir,
                        auto_command=auto_command,
                    ),
                )
                if not isinstance(envelope, dict):
                    raise HTTPException(status_code=500, detail="Invalid session creation response")

                status = str(envelope.get("status", "error"))
                if status != "success":
                    error_msg = str(envelope.get("error", "Session creation failed"))
                    raise HTTPException(status_code=500, detail=error_msg)

                data = envelope.get("data")
                if not isinstance(data, dict):
                    raise HTTPException(status_code=500, detail="Invalid session creation payload")

                session_id = data.get("session_id")
                tmux_session_name = data.get("tmux_session_name")

                if session_id and not tmux_session_name:
                    try:
                        session = await db.get_session(str(session_id))
                    except RuntimeError:
                        session = None
                    if session:
                        tmux_session_name = session.tmux_session_name

                return {
                    "status": "success",
                    "session_id": session_id,
                    "tmux_session_name": tmux_session_name,
                }
            except HTTPException as exc:  # type: ignore[misc]
                raise exc
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
                        "is_local": True,
                        "tmux_binary": computer_info.get("tmux_binary"),
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
                                "is_local": False,
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
            """List projects (local + cached remote projects).

            Pure cache reader - returns cached data without triggering pulls.
            """
            try:
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

                stale_computers: set[str] = set()
                # Add cached REMOTE projects from cache (skip local to avoid duplicates)
                if self.cache:
                    cached_projects = self.cache.get_projects(computer, include_stale=True)
                    for proj in cached_projects:
                        comp_name = str(proj.get("computer", ""))
                        if comp_name == computer_name:
                            continue
                        proj_path = str(proj.get("path", ""))
                        if comp_name and proj_path:
                            cache_key = f"{comp_name}:{proj_path}"
                            if self.cache.is_stale(cache_key, 300):
                                stale_computers.add(comp_name)
                        result.append(
                            {
                                "computer": comp_name,
                                "name": proj["name"],
                                "path": proj_path,
                                "description": proj["desc"],
                            }
                        )
                self._refresh_stale_projects(stale_computers)

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

            Pure cache reader - returns cached data without triggering pulls.

            Returns:
                List of projects, each with a 'todos' field containing the project's todos
            """
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

            stale_computers: set[str] = set()
            # Add REMOTE projects with cached todos from cache (skip local to avoid duplicates)
            if self.cache:
                cached_projects = self.cache.get_projects(include_stale=True)
                for proj in cached_projects:
                    comp_name = str(proj.get("computer", ""))
                    if comp_name == computer_name:
                        continue
                    proj_path = str(proj.get("path", ""))
                    if not proj_path:
                        continue
                    cache_key = f"{comp_name}:{proj_path}"
                    if self.cache.is_stale(cache_key, 300):
                        stale_computers.add(comp_name)

                    cached_todos = self.cache.get_todos(comp_name, proj_path) if comp_name else []

                    remote_project: dict[str, object] = {  # guard: loose-dict - REST API boundary
                        "computer": comp_name,
                        "name": proj.get("name", ""),
                        "path": proj_path,
                        "description": proj.get("desc"),
                        "todos": list(cached_todos),
                    }
                    result.append(remote_project)

            self._refresh_stale_projects(stale_computers)
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
        self._client_subscriptions[websocket] = {}
        logger.info("WebSocket client connected")

        # Update interest in cache when first client connects
        if self.cache and len(self._ws_clients) == 1:
            self._update_cache_interest()
            self._trigger_initial_refresh()

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
                    subscribe_data = data["subscribe"]

                    # Support both old format (string) and new format (dict)
                    if isinstance(subscribe_data, str):
                        # Old format: {"subscribe": "sessions"}
                        # Treat as subscription to "local" computer for backward compatibility
                        topic = subscribe_data
                        computer = "local"
                        if computer not in self._client_subscriptions[websocket]:
                            self._client_subscriptions[websocket][computer] = set()
                        self._client_subscriptions[websocket][computer].add(topic)
                        logger.info("WebSocket client subscribed to %s on local computer", topic)

                        # Send initial state
                        await self._send_initial_state(websocket, topic, computer)

                    elif isinstance(subscribe_data, dict):
                        # New format: {"subscribe": {"computer": "raspi", "types": ["sessions", "projects"]}}
                        computer_raw = subscribe_data.get("computer")
                        types_raw = subscribe_data.get("types")

                        if not isinstance(computer_raw, str) or not isinstance(types_raw, list):
                            logger.warning("Invalid subscribe format: computer or types missing/invalid")
                            continue

                        computer = computer_raw
                        if computer not in self._client_subscriptions[websocket]:
                            self._client_subscriptions[websocket][computer] = set()

                        for type_raw in types_raw:
                            if not isinstance(type_raw, str):
                                logger.warning("Subscribe type is not a string: %s", type(type_raw))
                                continue
                            data_type = type_raw
                            self._client_subscriptions[websocket][computer].add(data_type)
                            logger.info("WebSocket client subscribed to %s on computer %s", data_type, computer)

                            # Pull remote data immediately for this data type
                            await self._pull_remote_on_interest(computer, data_type)
                            # Send initial state for this data type
                            await self._send_initial_state(websocket, data_type, computer)
                    else:
                        logger.warning("WebSocket subscribe data is invalid type: %s", type(subscribe_data))
                        continue

                    # Update cache interest
                    if self.cache:
                        self._update_cache_interest()

                # Handle unsubscribe messages
                elif "unsubscribe" in data:
                    unsubscribe_data = data["unsubscribe"]

                    if isinstance(unsubscribe_data, dict):
                        # New format: {"unsubscribe": {"computer": "raspi"}}
                        computer_raw = unsubscribe_data.get("computer")
                        if not isinstance(computer_raw, str):
                            logger.warning("Invalid unsubscribe format: computer missing/invalid")
                            continue

                        computer = computer_raw
                        if computer in self._client_subscriptions[websocket]:
                            del self._client_subscriptions[websocket][computer]
                            logger.info("WebSocket client unsubscribed from computer %s", computer)

                        # Update cache interest
                        if self.cache:
                            self._update_cache_interest()
                    else:
                        logger.warning("WebSocket unsubscribe data is invalid type: %s", type(unsubscribe_data))

                # Handle refresh messages
                elif data.get("refresh"):
                    logger.info("WebSocket client requested refresh")
                    if self.cache:
                        self.cache.invalidate_all()
                        # Re-send initial state for all subscriptions
                        for computer, data_types in self._client_subscriptions[websocket].items():
                            for data_type in data_types:
                                await self._send_initial_state(websocket, data_type, computer)

        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
        except Exception as e:
            logger.error("WebSocket error: %s", e, exc_info=True)
        finally:
            # Clean up
            self._ws_clients.discard(websocket)
            self._client_subscriptions.pop(websocket, None)
            try:
                await websocket.close()
            except Exception:
                pass

            # Update interest in cache when last client disconnects
            if self.cache and len(self._ws_clients) == 0:
                self._update_cache_interest()

    def _update_cache_interest(self) -> None:
        """Update cache interest based on active WebSocket subscriptions."""
        if not self.cache:
            return

        # Collect current subscriptions from all connected clients
        # Structure: {data_type: {computers}}
        current_interest: dict[str, set[str]] = {}

        for computer_subscriptions in self._client_subscriptions.values():
            for computer, data_types in computer_subscriptions.items():
                for data_type in data_types:
                    if data_type not in current_interest:
                        current_interest[data_type] = set()
                    current_interest[data_type].add(computer)

        # Remove stale interest (present in previous but not in current)
        for data_type, prev_computers in self._previous_interest.items():
            current_computers = current_interest.get(data_type, set())
            for computer in prev_computers - current_computers:
                self.cache.remove_interest(data_type, computer)
                logger.debug("Removed stale interest: %s for %s", data_type, computer)

        # Add new interest (present in current but not in previous)
        for data_type, curr_computers in current_interest.items():
            prev_computers = self._previous_interest.get(data_type, set())
            for computer in curr_computers - prev_computers:
                self.cache.set_interest(data_type, computer)
                logger.debug("Added new interest: %s for %s", data_type, computer)

        # Update tracking
        self._previous_interest = current_interest
        logger.debug("Current cache interest: %s", current_interest)

    def _trigger_initial_refresh(self) -> None:
        """Kick off background cache refresh for remote computers on first UI connect."""
        adapter = self.client.adapters.get("redis")
        if not isinstance(adapter, RedisAdapter):
            return
        coro = self._refresh_remote_cache_and_notify()
        if self.task_registry:
            self.task_registry.spawn(coro, name="initial-refresh")
        else:
            asyncio.create_task(coro)

    async def _refresh_remote_cache_and_notify(self) -> None:
        """Refresh remote cache snapshot and notify clients to refresh projects."""
        adapter = self.client.adapters.get("redis")
        if not isinstance(adapter, RedisAdapter):
            return
        await adapter.refresh_remote_snapshot()
        self._on_cache_change("projects_updated", {"computer": None})

    async def _pull_remote_on_interest(self, computer: str, data_type: str) -> None:
        """Pull remote data immediately after subscription."""
        if computer == "local":
            return
        adapter = self.client.adapters.get("redis")
        if not isinstance(adapter, RedisAdapter):
            return

        await adapter.refresh_peers_from_heartbeats()
        if data_type in ("projects", "preparation"):
            await adapter.pull_remote_projects_with_todos(computer)
        elif data_type == "sessions":
            await adapter.pull_interested_sessions()

    def _refresh_stale_projects(self, computers: set[str]) -> None:
        """Trigger background refresh for stale project caches."""
        if not computers:
            return
        adapter = self.client.adapters.get("redis")
        if not isinstance(adapter, RedisAdapter):
            return

        for computer in sorted(computers):
            if computer == "local":
                continue
            coro = adapter.pull_remote_projects_with_todos(computer)
            if self.task_registry:
                self.task_registry.spawn(coro, name=f"projects-refresh-{computer}")
            else:
                asyncio.create_task(coro)

    async def _send_initial_state(self, websocket: WebSocket, data_type: str, computer: str) -> None:
        """Send initial state for a subscription.

        Args:
            websocket: WebSocket connection
            data_type: Data type (e.g., "sessions", "projects", "todos")
            computer: Computer name to filter data by
        """
        try:
            if data_type == "sessions":
                # Send current sessions from cache for this computer
                if self.cache:
                    sessions = self.cache.get_sessions(computer if computer != "local" else None)
                    await websocket.send_json(
                        {"event": "sessions_initial", "data": {"sessions": sessions, "computer": computer}}  # type: ignore[misc]
                    )
            elif data_type in ("preparation", "projects"):
                # Send current projects from cache for this computer
                if self.cache:
                    raw_projects = self.cache.get_projects(computer if computer != "local" else None)
                    projects: list[dict[str, object]] = []  # guard: loose-dict - WebSocket payload assembly
                    for proj in raw_projects:
                        if "description" not in proj and "desc" in proj:
                            projects.append(
                                {
                                    "computer": proj.get("computer"),
                                    "name": proj.get("name", ""),
                                    "path": proj.get("path", ""),
                                    "description": proj.get("desc"),
                                }
                            )
                        else:
                            projects.append(dict(proj))
                    await websocket.send_json(
                        {"event": "projects_initial", "data": {"projects": projects, "computer": computer}}  # type: ignore[misc]
                    )
            elif data_type == "todos":
                # Todos are project-specific, can't send initial state without project context
                logger.debug("Skipping initial state for todos (project-specific)")
        except Exception as e:
            logger.error("Failed to send initial state for %s on %s: %s", data_type, computer, e, exc_info=True)

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
                    if self.task_registry:
                        self.task_registry.spawn(self._close_ws(client), name="ws-close")
                    else:
                        asyncio.create_task(self._close_ws(client))

            task.add_done_callback(on_done)

    async def _close_ws(self, websocket: WebSocket) -> None:
        """Close a WebSocket connection safely."""
        try:
            await websocket.close()
        except Exception:
            pass

    async def start(self) -> None:
        """Start the REST API server on Unix socket."""
        self._running = True
        await self._start_server()

    async def stop(self) -> None:
        """Stop the REST API server."""
        self._running = False
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

        # Interest is cleared when _client_subscriptions is cleared
        # No need to explicitly clear cache interest

        await self._stop_server()
        self._cleanup_socket()

        logger.info("REST API server stopped")

    async def _start_server(self) -> None:
        """Start uvicorn server and attach restart handler."""
        self._cleanup_socket()

        config = uvicorn.Config(
            self.app,
            uds=REST_SOCKET_PATH,
            log_level="warning",
            ws_ping_interval=REST_WS_PING_INTERVAL_S,
            ws_ping_timeout=REST_WS_PING_TIMEOUT_S,
            timeout_keep_alive=REST_TIMEOUT_KEEP_ALIVE_S,
        )
        self.server = uvicorn.Server(config)

        # Run server in background task
        self.server_task = asyncio.create_task(self.server.serve())
        self.server_task.add_done_callback(self._on_server_task_done)

        # Wait for server to be ready (socket file created and bound)
        max_retries = 50  # 5 seconds total
        for _ in range(max_retries):
            if self.server.started:
                break
            await asyncio.sleep(0.1)

        logger.info("REST API server listening on %s", REST_SOCKET_PATH)

    async def _stop_server(self) -> None:
        """Stop uvicorn server task safely."""
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

    def _cleanup_socket(self) -> None:
        """Remove stale REST socket file if present."""
        if not os.path.exists(REST_SOCKET_PATH):
            return
        try:
            os.unlink(REST_SOCKET_PATH)
        except OSError as e:
            logger.warning("Failed to remove REST socket %s: %s", REST_SOCKET_PATH, e)

    def _on_server_task_done(self, task: asyncio.Task[object]) -> None:
        """Handle unexpected server exit and schedule restart."""
        if not self._running:
            return

        exc = task.exception()
        if exc:
            logger.error("REST API server task crashed: %s", exc, exc_info=True)
        else:
            logger.error("REST API server task exited unexpectedly; restarting")

        if self.task_registry:
            self.task_registry.spawn(self._restart_server("server_task_done"), name="rest-restart")
        else:
            asyncio.create_task(self._restart_server("server_task_done"))

    async def _restart_server(self, reason: str) -> bool:
        """Restart REST API server with backoff and attempt limits."""
        async with self._restart_lock:
            now = time.monotonic()
            if self._restart_window_start == 0.0 or (now - self._restart_window_start) > REST_RESTART_WINDOW_S:
                self._restart_window_start = now
                self._restart_attempts = 0

            self._restart_attempts += 1
            if self._restart_attempts > REST_RESTART_MAX:
                logger.error(
                    "REST restart limit exceeded; leaving server down (reason=%s attempts=%d)",
                    reason,
                    self._restart_attempts,
                )
                return False

            logger.warning(
                "Restarting REST API server (reason=%s attempt=%d)",
                reason,
                self._restart_attempts,
            )
            await asyncio.sleep(REST_RESTART_BACKOFF_S)
            await self._stop_server()
            await self._start_server()
            return True

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
