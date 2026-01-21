"""API server for HTTP/Unix socket access.

This server provides HTTP endpoints for local clients (telec CLI, etc.)
and routes write requests through AdapterClient.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
from typing import TYPE_CHECKING, Callable, Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from instrukt_ai_logging import get_logger

from teleclaude.api_models import (
    AgentAvailabilityDTO,
    ComputerDTO,
    CreateSessionRequest,
    CreateSessionResponseDTO,
    FileUploadRequest,
    ProjectDTO,
    ProjectsInitialDataDTO,
    ProjectsInitialEventDTO,
    RefreshDataDTO,
    RefreshEventDTO,
    SendMessageRequest,
    SessionClosedDataDTO,
    SessionClosedEventDTO,
    SessionsInitialDataDTO,
    SessionsInitialEventDTO,
    SessionStartedEventDTO,
    SessionSummaryDTO,
    TodoDTO,
    VoiceInputRequest,
)
from teleclaude.config import config
from teleclaude.constants import API_SOCKET_PATH
from teleclaude.core import command_handlers
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionLifecycleContext, SessionUpdatedContext, TeleClaudeEvents
from teleclaude.core.models import MessageMetadata, SessionLaunchIntent, SessionLaunchKind, SessionSummary
from teleclaude.transport.redis_transport import RedisTransport

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)

API_WS_PING_INTERVAL_S = 20.0
API_WS_PING_TIMEOUT_S = 20.0
API_TIMEOUT_KEEP_ALIVE_S = 5
API_STOP_TIMEOUT_S = 5.0

ServerExitHandler = Callable[[BaseException | None, bool | None, bool | None, bool], None]


class APIServer:
    """HTTP API server on Unix socket."""

    def __init__(
        self,
        client: AdapterClient,
        cache: "DaemonCache | None" = None,
        task_registry: "TaskRegistry | None" = None,
        socket_path: str | None = None,
    ) -> None:
        """Initialize API server.

        Args:
            client: AdapterClient instance for routing events
            cache: Optional DaemonCache for remote data (None = local-only mode)
            task_registry: Optional TaskRegistry for tracking background tasks
            socket_path: Optional override for API Unix socket path
        """
        self.client = client
        self._cache: "DaemonCache | None" = None  # Initialize private variable
        self.task_registry = task_registry
        self.app = FastAPI(title="TeleClaude API", version="1.0.0")
        self._setup_routes()
        self.socket_path = socket_path or API_SOCKET_PATH
        self.server: uvicorn.Server | None = None
        self.server_task: asyncio.Task[object] | None = None
        self._metrics_task: asyncio.Task[object] | None = None
        self._running = False
        self._on_server_exit: ServerExitHandler | None = None
        # WebSocket state
        self._ws_clients: set[WebSocket] = set()
        # Per-computer subscriptions: {websocket: {computer: {data_types}}}
        self._client_subscriptions: dict[WebSocket, dict[str, set[str]]] = {}
        # Track previous interest to remove stale entries
        self._previous_interest: dict[str, set[str]] = {}  # {data_type: {computers}}
        # Debounce refresh-style WS events to avoid burst refresh storms
        self._refresh_debounce_task: asyncio.Task[object] | None = None
        self._refresh_pending_payload: dict[str, object] | None = None  # guard: loose-dict - WS payload

        # Subscribe to local session updates
        event_bus.subscribe(TeleClaudeEvents.SESSION_UPDATED, self._handle_session_updated_event)
        event_bus.subscribe(TeleClaudeEvents.SESSION_STARTED, self._handle_session_started_event)
        event_bus.subscribe(TeleClaudeEvents.SESSION_CLOSED, self._handle_session_closed_event)

        # Set cache through property to trigger subscription
        self.cache = cache

    def _metadata(self, **kwargs: object) -> MessageMetadata:
        """Build API boundary metadata."""
        return MessageMetadata(origin="cli", **kwargs)

    @property
    def cache(self) -> "DaemonCache | None":
        """Get cache reference."""
        return self._cache

    @cache.setter
    def cache(self, value: "DaemonCache | None") -> None:
        """Set cache reference and subscribe to changes."""
        if self._cache:
            self._cache.unsubscribe(self._on_cache_change)
        self._cache = value
        if value:
            value.subscribe(self._on_cache_change)
            logger.info("API server subscribed to cache notifications")

    async def _handle_session_updated_event(
        self,
        _event: str,
        context: SessionUpdatedContext,
    ) -> None:
        """Handle local session update by updating cache."""
        if not self.cache:
            logger.warning("Cache unavailable, cannot update session in cache")
            return
        session = await db.get_session(context.session_id)
        if not session:
            return
        if session.closed_at:
            self.cache.remove_session(context.session_id)
            return
        summary = SessionSummary.from_db_session(session, computer=config.computer.name)
        self.cache.update_session(summary)

    async def _handle_session_started_event(
        self,
        _event: str,
        context: SessionLifecycleContext,
    ) -> None:
        """Handle local session creation by updating cache."""
        if not self.cache:
            logger.warning("Cache unavailable, cannot create session in cache")
            return
        session = await db.get_session(context.session_id)
        if not session:
            return
        summary = SessionSummary.from_db_session(session, computer=config.computer.name)
        self.cache.update_session(summary)

    async def _handle_session_closed_event(
        self,
        _event: str,
        context: SessionLifecycleContext,
    ) -> None:
        """Handle local session removal by updating cache."""
        if not self.cache:
            logger.warning("Cache unavailable, cannot remove session from cache")
            return
        self.cache.remove_session(context.session_id)

    def _setup_routes(self) -> None:
        """Set up all HTTP endpoints."""

        @self.app.get("/health")
        async def health() -> dict[str, str]:  # pyright: ignore
            """Health check endpoint."""
            return {"status": "ok"}

        @self.app.get("/sessions")
        async def list_sessions(  # pyright: ignore
            computer: str | None = None,
        ) -> list[SessionSummaryDTO]:
            """List sessions from local storage and remote cache.

            Args:
                computer: Optional filter by computer name

            Returns:
                List of session summaries (merged local + cached remote)
            """
            try:
                local_sessions = await command_handlers.list_sessions()

                # No cache: serve local sessions only (respect computer filter)
                if not self.cache:
                    if computer and computer not in ("local", config.computer.name):
                        return []
                    return [SessionSummaryDTO.from_core(s, computer=s.computer) for s in local_sessions]

                # With cache, merge local + cached sessions
                if computer:
                    cached_filtered = self.cache.get_sessions(computer)
                    if computer in ("local", config.computer.name):
                        by_id = {s.session_id: s for s in local_sessions}
                        for s in cached_filtered:
                            by_id.setdefault(s.session_id, s)
                        merged = list(by_id.values())
                    else:
                        merged = cached_filtered
                else:
                    cached_sessions = self.cache.get_sessions()
                    by_id = {s.session_id: s for s in local_sessions}
                    for s in cached_sessions:
                        by_id.setdefault(s.session_id, s)
                    merged = list(by_id.values())

                return [SessionSummaryDTO.from_core(s, computer=s.computer) for s in merged]
            except Exception as e:
                logger.error("list_sessions failed: %s", e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to list sessions: {e}") from e

        @self.app.post("/sessions")
        async def create_session(  # pyright: ignore
            request: CreateSessionRequest,
        ) -> CreateSessionResponseDTO:
            """Create new local session.

            Note: Remote session creation via API is not yet implemented;
            all sessions are created on the local machine regardless of
            the computer field in the request.

            Args:
                request: CreateSessionRequest model

            Returns:
                CreateSessionResponseDTO
            """
            # Normalize request into internal command.

            metadata = self._metadata(
                title=request.title or "Untitled",
                project_path=request.project_path,
                subdir=request.subdir,
                # launch_intent and auto_command logic will be simplified or moved
            )

            # Extract title from message if not provided (legacy behavior)
            title = request.title
            if not title and request.message and request.message.startswith("/"):
                title = request.message
            title = title or "Untitled"

            effective_agent = request.agent or "claude"
            effective_thinking_mode = request.thinking_mode or "slow"

            launch_intent = None
            if not request.auto_command:
                launch_kind = SessionLaunchKind(request.launch_kind)
                if launch_kind == SessionLaunchKind.AGENT and request.message:
                    launch_kind = SessionLaunchKind.AGENT_THEN_MESSAGE

                if launch_kind == SessionLaunchKind.EMPTY:
                    launch_intent = SessionLaunchIntent(kind=SessionLaunchKind.EMPTY)
                elif launch_kind == SessionLaunchKind.AGENT_RESUME:
                    if not request.agent:
                        raise HTTPException(status_code=400, detail="agent required for agent_resume")
                    launch_intent = SessionLaunchIntent(
                        kind=SessionLaunchKind.AGENT_RESUME,
                        agent=request.agent,
                        thinking_mode=effective_thinking_mode,
                        native_session_id=request.native_session_id,
                    )
                elif launch_kind == SessionLaunchKind.AGENT_THEN_MESSAGE:
                    if request.message is None:
                        raise HTTPException(status_code=400, detail="message required for agent_then_message")
                    launch_intent = SessionLaunchIntent(
                        kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
                        agent=effective_agent,
                        thinking_mode=effective_thinking_mode,
                        message=request.message,
                    )
                else:
                    launch_intent = SessionLaunchIntent(
                        kind=SessionLaunchKind.AGENT,
                        agent=effective_agent,
                        thinking_mode=effective_thinking_mode,
                    )

            auto_command = request.auto_command
            if not auto_command and launch_intent:
                if launch_intent.kind == SessionLaunchKind.AGENT:
                    auto_command = f"agent {launch_intent.agent} {launch_intent.thinking_mode}"
                elif launch_intent.kind == SessionLaunchKind.AGENT_THEN_MESSAGE:
                    quoted_message = shlex.quote(launch_intent.message or "")
                    auto_command = (
                        f"agent_then_message {launch_intent.agent} {launch_intent.thinking_mode} {quoted_message}"
                    )
                elif launch_intent.kind == SessionLaunchKind.AGENT_RESUME:
                    if launch_intent.native_session_id:
                        auto_command = f"agent_resume {launch_intent.agent} {launch_intent.native_session_id}"
                    else:
                        auto_command = f"agent_resume {launch_intent.agent}"

            # Update metadata with derived fields
            metadata.title = title
            metadata.launch_intent = launch_intent
            metadata.auto_command = auto_command
            cmd = CommandMapper.map_api_input("new_session", {}, metadata)

            try:
                data = await get_command_service().create_session(cmd)

                session_id = data.get("session_id")
                tmux_session_name = data.get("tmux_session_name")

                if session_id and not tmux_session_name:
                    try:
                        session = await db.get_session(str(session_id))
                    except RuntimeError:
                        session = None
                    if session:
                        tmux_session_name = session.tmux_session_name

                return CreateSessionResponseDTO(
                    status="success",
                    session_id=str(session_id) if session_id else None,
                    tmux_session_name=str(tmux_session_name) if tmux_session_name else None,
                )
            except HTTPException as exc:
                raise exc
            except Exception as e:
                logger.error("create_session failed (computer=%s): %s", request.computer, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to create session: {e}") from e

        @self.app.delete("/sessions/{session_id}")
        async def end_session(  # pyright: ignore
            session_id: str,
            computer: str = Query(...),  # noqa: ARG001 - For API consistency, only local sessions supported
        ) -> dict[str, object]:  # guard: loose-dict - API boundary
            """End session - local sessions only (remote session management via MCP tools)."""
            try:
                metadata = self._metadata()
                cmd = CommandMapper.map_api_input(
                    "end_session",
                    {"session_id": session_id},
                    metadata,
                )
                result = await get_command_service().end_session(cmd)
                return {"status": "success", "result": result}
            except Exception as e:
                logger.error("Failed to end session %s: %s", session_id, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to end session: {e}") from e

        @self.app.post("/sessions/{session_id}/message")
        async def send_message_endpoint(  # pyright: ignore
            session_id: str,
            request: SendMessageRequest,
            computer: str | None = Query(None),  # noqa: ARG001 - Optional param for API consistency
        ) -> dict[str, object]:  # guard: loose-dict - API boundary
            """Send message to session."""
            try:
                metadata = self._metadata()
                cmd = CommandMapper.map_api_input(
                    "message",
                    {"session_id": session_id, "text": request.message},
                    metadata,
                )
                await get_command_service().send_message(cmd)
                return {"status": "success"}
            except Exception as e:
                logger.error("send_message failed (session=%s): %s", session_id, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to send message: {e}") from e

        @self.app.post("/sessions/{session_id}/voice")
        async def send_voice_endpoint(  # pyright: ignore
            session_id: str,
            request: VoiceInputRequest,
            computer: str | None = Query(None),  # noqa: ARG001 - Optional param for API consistency
        ) -> dict[str, object]:  # guard: loose-dict - API boundary
            """Send voice input to session."""
            try:
                metadata = self._metadata()
                cmd = CommandMapper.map_api_input(
                    "handle_voice",
                    {
                        "session_id": session_id,
                        "file_path": request.file_path,
                        "duration": request.duration,
                        "message_id": request.message_id,
                        "message_thread_id": request.message_thread_id,
                    },
                    metadata,
                )
                await get_command_service().handle_voice(cmd)
                return {"status": "success"}
            except Exception as e:
                logger.error("send_voice failed (session=%s): %s", session_id, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to send voice: {e}") from e

        @self.app.post("/sessions/{session_id}/file")
        async def send_file_endpoint(  # pyright: ignore
            session_id: str,
            request: FileUploadRequest,
            computer: str | None = Query(None),  # noqa: ARG001 - Optional param for API consistency
        ) -> dict[str, object]:  # guard: loose-dict - API boundary
            """Send file input to session."""
            try:
                metadata = self._metadata()
                cmd = CommandMapper.map_api_input(
                    "handle_file",
                    {
                        "session_id": session_id,
                        "file_path": request.file_path,
                        "filename": request.filename,
                        "caption": request.caption,
                        "file_size": request.file_size,
                    },
                    metadata,
                )
                await get_command_service().handle_file(cmd)
                return {"status": "success"}
            except Exception as e:
                logger.error("send_file failed (session=%s): %s", session_id, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to send file: {e}") from e

        @self.app.post("/sessions/{session_id}/agent-restart")
        async def agent_restart(  # pyright: ignore
            session_id: str,
        ) -> dict[str, str]:
            """Restart agent in session (preserves conversation via --resume)."""
            try:
                # Normalize command through mapper before dispatching
                metadata = self._metadata()
                cmd = CommandMapper.map_api_input(
                    "agent_restart",
                    {"session_id": session_id, "args": []},
                    metadata,
                )
                await get_command_service().restart_agent(cmd)
                return {"status": "ok"}
            except Exception as e:
                logger.error("agent_restart failed for session %s: %s", session_id, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to restart agent: {e}") from e

        @self.app.get("/computers")
        async def list_computers() -> list[ComputerDTO]:  # pyright: ignore
            """List available computers (local + cached remote computers)."""
            try:
                # Local computer
                info = await command_handlers.get_computer_info()
                result: list[ComputerDTO] = [
                    ComputerDTO(
                        name=config.computer.name,
                        status="online",
                        user=info.user,
                        host=info.host,
                        is_local=True,
                        tmux_binary=info.tmux_binary,
                    )
                ]

                # Add cached remote computers (if available)
                if self.cache:
                    cached_computers = self.cache.get_computers()
                    for comp in cached_computers:
                        result.append(
                            ComputerDTO(
                                name=comp.name,
                                status="online",
                                user=comp.user,
                                host=comp.host,
                                is_local=False,
                            )
                        )

                return result
            except Exception as e:
                logger.error("list_computers failed: %s", e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to list computers: {e}") from e

        @self.app.get("/projects")
        async def list_projects(  # pyright: ignore
            computer: str | None = None,
        ) -> list[ProjectDTO]:
            """List projects (local + cached remote projects).

            Pure cache reader - returns cached data without triggering pulls.
            """
            try:
                # Get LOCAL projects from command handler
                raw_projects = await command_handlers.list_projects()
                computer_name = config.computer.name
                result: list[ProjectDTO] = []

                # Add local projects
                for p in raw_projects:
                    result.append(
                        ProjectDTO(
                            computer=computer_name,
                            name=p.name,
                            path=p.path,
                            description=p.description,
                        )
                    )

                stale_computers: set[str] = set()
                # Add cached REMOTE projects from cache (skip local to avoid duplicates)
                if self.cache:
                    cached_projects = self.cache.get_projects(computer, include_stale=True)
                    for proj in cached_projects:
                        comp_name = str(proj.computer or "")
                        if comp_name == computer_name:
                            continue
                        proj_path = str(proj.path or "")
                        if comp_name and proj_path:
                            cache_key = f"{comp_name}:{proj_path}"
                            if self.cache.is_stale(cache_key, 300):
                                stale_computers.add(comp_name)
                        result.append(
                            ProjectDTO(
                                computer=comp_name,
                                name=proj.name,
                                path=proj_path,
                                description=proj.description,
                            )
                        )
                self._refresh_stale_projects(stale_computers)

                return result
            except Exception as e:
                logger.error("list_projects failed: %s", e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to list projects: {e}") from e

        @self.app.get("/agents/availability")
        async def get_agent_availability() -> dict[str, AgentAvailabilityDTO]:  # pyright: ignore
            """Get agent availability."""
            from teleclaude.core.db import db

            agents: list[Literal["claude", "gemini", "codex"]] = ["claude", "gemini", "codex"]
            result: dict[str, AgentAvailabilityDTO] = {}

            for agent in agents:
                try:
                    info = await db.get_agent_availability(agent)
                except Exception as e:
                    logger.error("Failed to get availability for agent %s: %s", agent, e)
                    result[agent] = AgentAvailabilityDTO(
                        agent=agent,
                        available=None,  # Unknown due to DB error
                        error=str(e),
                    )
                    continue

                if info:
                    unavail_until = info.get("unavailable_until")
                    reason_val = info.get("reason")
                    result[agent] = AgentAvailabilityDTO(
                        agent=agent,
                        available=bool(info.get("available", True)),
                        unavailable_until=str(unavail_until) if unavail_until and unavail_until is not True else None,
                        reason=str(reason_val) if reason_val and reason_val is not True else None,
                    )
                else:
                    # No record means agent is available (never marked unavailable)
                    result[agent] = AgentAvailabilityDTO(
                        agent=agent,
                        available=True,
                    )

            return result

        @self.app.get("/todos")
        async def list_todos(  # pyright: ignore
            project: str | None = Query(None, min_length=1),
            computer: str | None = None,
        ) -> list[TodoDTO]:
            """List todos from cache, optionally filtered by computer and project.

            Read-only cache endpoint. Returns cached data immediately.
            """
            try:
                if not self.cache:
                    if project and (computer in (None, "local")):
                        raw_todos = await command_handlers.list_todos(project)
                        return [
                            TodoDTO(
                                slug=t.slug,
                                status=t.status,
                                description=t.description,
                                computer=config.computer.name,
                                project_path=project,
                                has_requirements=t.has_requirements,
                                has_impl_plan=t.has_impl_plan,
                                build_status=t.build_status,
                                review_status=t.review_status,
                            )
                            for t in raw_todos
                        ]
                    return []

                entries = self.cache.get_todo_entries(
                    computer=computer,
                    project_path=project,
                    include_stale=True,
                )
                result: list[TodoDTO] = []
                for entry in entries:
                    if entry.is_stale:
                        self._refresh_stale_todos(entry.computer, entry.project_path)
                    for todo in entry.todos:
                        result.append(
                            TodoDTO(
                                slug=todo.slug,
                                status=todo.status,
                                description=todo.description,
                                computer=entry.computer,
                                project_path=entry.project_path,
                                has_requirements=todo.has_requirements,
                                has_impl_plan=todo.has_impl_plan,
                                build_status=todo.build_status,
                                review_status=todo.review_status,
                            )
                        )
                return result
            except Exception as e:
                logger.error("list_todos: failed to get todos: %s", e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to list todos: {e}") from e

        @self.app.websocket("/ws")
        async def websocket_endpoint(  # pyright: ignore
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
        if not isinstance(adapter, RedisTransport):
            return
        coro = self._refresh_remote_cache_and_notify()
        if self.task_registry:
            self.task_registry.spawn(coro, name="initial-refresh")
        else:
            asyncio.create_task(coro)

    async def _refresh_remote_cache_and_notify(self) -> None:
        """Refresh remote cache snapshot and notify clients to refresh projects."""
        adapter = self.client.adapters.get("redis")
        if not isinstance(adapter, RedisTransport):
            return
        await adapter.refresh_remote_snapshot()
        self._on_cache_change("projects_updated", {"computer": None})

    async def _pull_remote_on_interest(self, computer: str, data_type: str) -> None:
        """Pull remote data immediately after subscription."""
        if computer == "local":
            return
        adapter = self.client.adapters.get("redis")
        if not isinstance(adapter, RedisTransport):
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
        if not isinstance(adapter, RedisTransport):
            return

        for computer in sorted(computers):
            if computer == "local":
                continue
            coro = adapter.pull_remote_projects_with_todos(computer)
            if self.task_registry:
                self.task_registry.spawn(coro, name=f"projects-refresh-{computer}")
            else:
                asyncio.create_task(coro)

    def _refresh_stale_todos(self, computer: str, project_path: str) -> None:
        """Trigger background refresh for stale todo cache entries."""
        if not self.cache or not project_path or computer == "local":
            return
        cache_key = f"{computer}:{project_path}"
        if not self.cache.is_stale(cache_key, 300):
            return
        adapter = self.client.adapters.get("redis")
        if not isinstance(adapter, RedisTransport):
            return
        coro = adapter.pull_remote_todos(computer, project_path)
        if self.task_registry:
            self.task_registry.spawn(coro, name=f"todos-refresh-{computer}")
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
                    cached_sessions = self.cache.get_sessions(computer)
                    sessions = [SessionSummaryDTO.from_core(s, computer=s.computer) for s in cached_sessions]
                    event = SessionsInitialEventDTO(data=SessionsInitialDataDTO(sessions=sessions, computer=computer))
                    await websocket.send_json(event.model_dump(exclude_none=True))
            elif data_type in ("preparation", "projects"):
                # Send current projects from cache for this computer
                if self.cache:
                    cached_projects = self.cache.get_projects(computer if computer != "local" else None)
                    projects: list[ProjectDTO] = []
                    for proj in cached_projects:
                        projects.append(
                            ProjectDTO(
                                computer=proj.computer or "",
                                name=proj.name,
                                path=proj.path,
                                description=proj.description,
                            )
                        )

                    event = ProjectsInitialEventDTO(
                        event="projects_initial" if data_type == "projects" else "preparation_initial",
                        data=ProjectsInitialDataDTO(projects=projects, computer=computer),
                    )
                    await websocket.send_json(event.model_dump(exclude_none=True))
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
        if event == "session_updated":
            return
        # Convert to DTO payload if necessary
        payload: dict[str, object]  # guard: loose-dict - WebSocket payload assembly
        if event == "session_started":
            if isinstance(data, SessionSummary):
                dto = SessionSummaryDTO.from_core(data, computer=data.computer)
                # Proper cast for Mypy Literal
                payload = SessionStartedEventDTO(
                    event=event,
                    data=dto,
                ).model_dump(exclude_none=True)
            elif isinstance(data, dict):
                # Already a dict (e.g. from _handle_session_updated)
                payload = {"event": event, "data": data}
            else:
                payload = {"event": event, "data": data}
        elif event == "session_closed":
            if isinstance(data, dict):
                payload = SessionClosedEventDTO(
                    data=SessionClosedDataDTO(session_id=str(data.get("session_id", "")))
                ).model_dump(exclude_none=True)
            else:
                payload = {"event": event, "data": data}
        elif event in (
            "computer_updated",
            "project_updated",
            "projects_updated",
            "todos_updated",
            "projects_snapshot",
            "todos_snapshot",
        ):
            computer: str | None = None
            project_path: str | None = None
            if isinstance(data, dict):
                computer_val = data.get("computer")
                if isinstance(computer_val, str):
                    computer = computer_val
                project_val = data.get("project_path")
                if isinstance(project_val, str):
                    project_path = project_val
            else:
                if hasattr(data, "computer"):
                    computer_val = getattr(data, "computer")
                    if isinstance(computer_val, str):
                        computer = computer_val
                if hasattr(data, "path"):
                    path_val = getattr(data, "path")
                    if isinstance(path_val, str):
                        project_path = path_val
                if event == "computer_updated" and computer is None and hasattr(data, "name"):
                    name_val = getattr(data, "name")
                    if isinstance(name_val, str):
                        computer = name_val

            normalized_event: Literal["computer_updated", "project_updated", "projects_updated", "todos_updated"]
            if event == "projects_snapshot":
                normalized_event = "projects_updated"
            elif event == "todos_snapshot":
                normalized_event = "todos_updated"
            else:
                normalized_event = event

            payload = RefreshEventDTO(
                event=normalized_event,
                data=RefreshDataDTO(computer=computer, project_path=project_path),
            ).model_dump(exclude_none=True)
            self._schedule_refresh_broadcast(payload)
            return
        else:
            # Fallback for other events
            if hasattr(data, "to_dict"):
                # Use type ignore since we check hasattr
                payload = {"event": event, "data": data.to_dict()}  # pyright: ignore[reportAttributeAccessIssue]
            else:
                payload = {"event": event, "data": data}

        self._broadcast_payload(event, payload)

    def _schedule_refresh_broadcast(self, payload: dict[str, object]) -> None:  # guard: loose-dict - WS payload
        """Coalesce refresh events into a single WS broadcast."""
        self._refresh_pending_payload = payload
        if self._refresh_debounce_task and not self._refresh_debounce_task.done():
            return

        async def _debounced() -> None:
            await asyncio.sleep(0.25)
            pending = self._refresh_pending_payload
            self._refresh_pending_payload = None
            if pending is None:
                return
            self._broadcast_payload("refresh", pending)

        if self.task_registry:
            self._refresh_debounce_task = self.task_registry.spawn(_debounced(), name="ws-broadcast-refresh")
        else:
            self._refresh_debounce_task = asyncio.create_task(_debounced())

    def _broadcast_payload(self, event: str, payload: dict[str, object]) -> None:  # guard: loose-dict - WS payload
        """Send a WS payload to all connected clients."""
        for ws in list(self._ws_clients):
            # Create tracked async task to send message (don't block)
            coro = ws.send_json(payload)
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
        """Start the API server on Unix socket."""
        self._running = True
        logger.info("API server starting")
        await self._start_server()
        self._start_metrics_task()

    async def stop(self) -> None:
        """Stop the API server."""
        self._running = False
        logger.info("API server stopping")
        await self._stop_metrics_task()
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
        self._cleanup_socket("stop")

        logger.info("API server stopped")

    async def _start_server(self) -> None:
        """Start uvicorn server and attach restart handler."""
        if self.server_task and not self.server_task.done():
            logger.warning("API server already running; skipping start")
            return

        self._cleanup_socket("start_server")

        config = uvicorn.Config(
            self.app,
            uds=self.socket_path,
            log_level="warning",
            ws_ping_interval=API_WS_PING_INTERVAL_S,
            ws_ping_timeout=API_WS_PING_TIMEOUT_S,
            timeout_keep_alive=API_TIMEOUT_KEEP_ALIVE_S,
        )
        self.server = uvicorn.Server(config)
        server = self.server
        logger.debug(
            "API server initialized (should_exit=%s, started=%s)",
            getattr(server, "should_exit", None),
            getattr(server, "started", None),
        )

        # Run server in background task. Avoid uvicorn's signal handling to keep daemon in control.
        serve_coro = server._serve() if hasattr(server, "_serve") else server.serve()
        self.server_task = asyncio.create_task(serve_coro)
        self.server_task.add_done_callback(lambda t, s=server: self._on_server_task_done(t, s))

        # Wait for server to be ready (socket file created and bound)
        max_retries = 50  # 5 seconds total
        for _ in range(max_retries):
            if server.started:
                break
            if self.server_task.done():
                exc = self.server_task.exception()
                raise RuntimeError("API server exited during startup") from exc
            await asyncio.sleep(0.1)
        if not server.started:
            raise TimeoutError("API server failed to start within timeout")

        logger.info("API server listening on %s", self.socket_path)

    async def restart_server(self) -> None:
        """Restart uvicorn server without tearing down server state."""
        await self._stop_server()
        if self.server_task and not self.server_task.done():
            logger.error("API server stop incomplete; aborting restart")
            return
        await self._start_server()

    def set_on_server_exit(self, handler: ServerExitHandler | None) -> None:
        """Set callback invoked when the uvicorn server task exits."""
        self._on_server_exit = handler

    async def _stop_server(self) -> None:
        """Stop uvicorn server task safely."""
        # Stop server gracefully if started, cancel if still starting
        server = self.server
        if server:
            logger.debug(
                "API server stopping (should_exit=%s, started=%s)",
                getattr(server, "should_exit", None),
                getattr(server, "started", None),
            )
            if server.started:
                # Server is running, do graceful shutdown
                server.should_exit = True
            else:
                # Server still starting, force cancel
                if self.server_task:
                    self.server_task.cancel()

        if self.server_task:
            try:
                await asyncio.wait_for(self.server_task, timeout=API_STOP_TIMEOUT_S)
            except asyncio.TimeoutError:
                logger.warning("Timed out stopping API server; cancelling task")
                self.server_task.cancel()
                try:
                    await self.server_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass
            except Exception as e:
                # Suppress errors during teardown (socket already gone, etc.)
                logger.debug("Error during server shutdown: %s", e)

    def _start_metrics_task(self) -> None:
        """Start periodic API server metrics logging."""
        if self._metrics_task and not self._metrics_task.done():
            return
        coro = self._metrics_loop()
        if self.task_registry:
            self._metrics_task = self.task_registry.spawn(coro, name="api-metrics")
        else:
            self._metrics_task = asyncio.create_task(coro)

    async def _stop_metrics_task(self) -> None:
        """Stop periodic API server metrics logging."""
        if not self._metrics_task:
            return
        if not self._metrics_task.done():
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass
        self._metrics_task = None

    async def _metrics_loop(self) -> None:
        """Log API server resource metrics periodically."""
        while self._running:
            fd_count = _get_fd_count()
            ws_count = len(self._ws_clients)
            task_count = self.task_registry.task_count() if self.task_registry else 0
            server = self.server
            server_started = getattr(server, "started", None) if server else None
            server_should_exit = getattr(server, "should_exit", None) if server else None
            server_task_done = self.server_task.done() if self.server_task else None
            logger.info(
                "API server metrics: fds=%d ws=%d tasks=%d started=%s should_exit=%s task_done=%s",
                fd_count,
                ws_count,
                task_count,
                server_started,
                server_should_exit,
                server_task_done,
            )
            await asyncio.sleep(60)

    def _cleanup_socket(self, reason: str) -> None:
        """Remove API server socket file if present."""
        if not os.path.exists(self.socket_path):
            return
        try:
            logger.warning(
                "Removing API server socket (reason=%s): %s",
                reason,
                self.socket_path,
            )
            os.unlink(self.socket_path)
        except OSError as e:
            logger.warning("Failed to remove API server socket %s: %s", self.socket_path, e)

    def _on_server_task_done(
        self,
        task: asyncio.Task[object],
        server: uvicorn.Server | None = None,
    ) -> None:
        """Handle server exit and notify lifecycle owner.

        Args:
            task: The completed server task
        """
        if not self._running:
            return

        try:
            exc = task.exception()
        except asyncio.CancelledError:
            logger.debug("API server task cancelled")
            return

        server_ref = server or self.server
        server_started = getattr(server_ref, "started", None) if server_ref else None
        server_should_exit = getattr(server_ref, "should_exit", None) if server_ref else None
        socket_exists = os.path.exists(self.socket_path)

        if exc:
            logger.error(
                "API server task crashed: %s (started=%s should_exit=%s socket=%s)",
                exc,
                server_started,
                server_should_exit,
                socket_exists,
                exc_info=True,
            )
        elif not server_should_exit:
            logger.error(
                "API server task exited unexpectedly (started=%s should_exit=%s socket=%s)",
                server_started,
                server_should_exit,
                socket_exists,
            )
        else:
            logger.debug(
                "API server task exited cleanly (started=%s should_exit=%s socket=%s)",
                server_started,
                server_should_exit,
                socket_exists,
            )

        if self._on_server_exit:
            self._on_server_exit(exc, server_started, server_should_exit, socket_exists)


def _get_fd_count() -> int:
    """Return count of open file descriptors for current process."""
    try:
        return len(os.listdir("/dev/fd"))
    except OSError:
        return -1
