"""API server for HTTP/Unix socket access.

This server provides HTTP endpoints for local clients (telec CLI, etc.)
and routes write requests through AdapterClient.
"""

from __future__ import annotations

import asyncio
import faulthandler
import json
import os
import shlex
import tempfile
import time
from typing import TYPE_CHECKING, Callable, Literal

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from instrukt_ai_logging import get_logger

from teleclaude.api_models import (
    AgentActivityEventDTO,
    AgentAvailabilityDTO,
    ComputerDTO,
    CreateSessionRequest,
    CreateSessionResponseDTO,
    FileUploadRequest,
    KeysRequest,
    MessageDTO,
    PersonDTO,
    ProjectDTO,
    ProjectsInitialDataDTO,
    ProjectsInitialEventDTO,
    RefreshDataDTO,
    RefreshEventDTO,
    SendMessageRequest,
    SessionClosedDataDTO,
    SessionClosedEventDTO,
    SessionMessagesDTO,
    SessionsInitialDataDTO,
    SessionsInitialEventDTO,
    SessionStartedEventDTO,
    SessionSummaryDTO,
    SessionUpdatedEventDTO,
    SettingsDTO,
    TodoDTO,
    TTSSettingsDTO,
    VoiceInputRequest,
)
from teleclaude.config import config
from teleclaude.constants import API_SOCKET_PATH
from teleclaude.core import command_handlers
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.error_feedback import get_user_facing_error_message
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentActivityEvent,
    ErrorEventContext,
    SessionLifecycleContext,
    SessionUpdatedContext,
    TeleClaudeEvents,
)
from teleclaude.core.models import MessageMetadata, SessionLaunchIntent, SessionLaunchKind, SessionSummary, TodoInfo
from teleclaude.core.origins import InputOrigin
from teleclaude.transport.redis_transport import RedisTransport

if TYPE_CHECKING:
    from teleclaude.config.runtime_settings import RuntimeSettings
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)

API_TCP_HOST = "127.0.0.1"
API_TCP_PORT = int(os.getenv("API_TCP_PORT", "8420"))
API_WS_PING_INTERVAL_S = 20.0
API_WS_PING_TIMEOUT_S = 20.0
API_TIMEOUT_KEEP_ALIVE_S = 5
API_STOP_TIMEOUT_S = 5.0
API_WATCH_INTERVAL_S = float(os.getenv("API_WATCH_INTERVAL_S", "5"))
API_WATCH_LAG_THRESHOLD_MS = float(os.getenv("API_WATCH_LAG_THRESHOLD_MS", "250"))
API_WATCH_INFLIGHT_THRESHOLD_S = float(os.getenv("API_WATCH_INFLIGHT_THRESHOLD_S", "1"))
API_WATCH_DUMP_COOLDOWN_S = float(os.getenv("API_WATCH_DUMP_COOLDOWN_S", "30"))

ServerExitHandler = Callable[[BaseException | None, bool | None, bool | None, bool], None]
PatchBodyScalar = str | int | float | bool | None
PatchBodyValue = PatchBodyScalar | list[PatchBodyScalar] | dict[str, PatchBodyScalar]


def _filter_sessions_by_role(request: Request, sessions: list[SessionSummary]) -> list[SessionSummary]:
    """Apply role-based visibility filtering to session list.

    Only filters when identity headers are present (web interface).
    TUI/MCP clients without headers see all sessions (existing behavior).
    """
    email = request.headers.get("x-web-user-email")
    role = request.headers.get("x-web-user-role")

    # No identity headers = TUI/MCP client, return all
    if not email:
        return sessions

    # Admin sees everything
    if role == "admin":
        return sessions

    # Member sees own + shared
    if role == "member":
        return [s for s in sessions if s.human_email == email or s.visibility == "shared"]

    # Contributor/newcomer/unknown: own sessions only
    return [s for s in sessions if s.human_email == email]


class APIServer:
    """HTTP API server on Unix socket."""

    def __init__(
        self,
        client: AdapterClient,
        cache: "DaemonCache | None" = None,
        task_registry: "TaskRegistry | None" = None,
        socket_path: str | None = None,
        runtime_settings: "RuntimeSettings | None" = None,
    ) -> None:
        self.client = client
        self._cache: "DaemonCache | None" = None  # Initialize private variable
        self.task_registry = task_registry
        self.runtime_settings = runtime_settings
        self.app = FastAPI(title="TeleClaude API", version="1.0.0")
        self._setup_routes()

        from teleclaude.memory.api_routes import router as memory_router

        self.app.include_router(memory_router)

        from teleclaude.hooks.api_routes import router as hooks_router

        self.app.include_router(hooks_router)

        from teleclaude.channels.api_routes import router as channels_router

        self.app.include_router(channels_router)

        from teleclaude.api.streaming import router as streaming_router

        self.app.include_router(streaming_router)

        from teleclaude.api.data_routes import router as data_router

        self.app.include_router(data_router)
        self.socket_path = socket_path or API_SOCKET_PATH
        self.server: uvicorn.Server | None = None
        self.server_task: asyncio.Task[object] | None = None
        self._tcp_server: uvicorn.Server | None = None
        self._tcp_server_task: asyncio.Task[object] | None = None
        self._metrics_task: asyncio.Task[object] | None = None
        self._watch_task: asyncio.Task[object] | None = None
        self._inflight_requests: dict[int, tuple[str, float]] = {}
        self._request_seq = 0
        self._last_watch_tick = 0.0
        self._last_dump_at = 0.0
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
        event_bus.subscribe(TeleClaudeEvents.AGENT_ACTIVITY, self._handle_agent_activity_event)
        event_bus.subscribe(TeleClaudeEvents.ERROR, self._handle_error_event)

        # Set cache through property to trigger subscription
        self.cache = cache

    def _metadata(self, **kwargs: object) -> MessageMetadata:
        """Build API boundary metadata."""
        return MessageMetadata(origin=InputOrigin.API.value, **kwargs)

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

    async def _handle_agent_activity_event(
        self,
        _event: str,
        context: AgentActivityEvent,
    ) -> None:
        """Broadcast agent activity events to WS clients (no cache, no DB re-read)."""
        dto = AgentActivityEventDTO(
            session_id=context.session_id,
            type=context.event_type,
            tool_name=context.tool_name,
            tool_preview=context.tool_preview,
            summary=context.summary,
            timestamp=context.timestamp,
        )
        self._broadcast_payload("agent_activity", dto.model_dump(exclude_none=True))

    async def _handle_error_event(
        self,
        _event: str,
        context: ErrorEventContext,
    ) -> None:
        """Broadcast error events to WS clients."""
        user_message = get_user_facing_error_message(context)
        if user_message is None:
            logger.debug(
                "Suppressing non-user-facing websocket error",
                source=context.source,
                code=context.code,
            )
            return

        payload = {
            "event": "error",
            "data": {
                "session_id": context.session_id,
                "message": user_message,
                "source": context.source,
                "details": context.details,
                "severity": context.severity,
                "retryable": context.retryable,
                "code": context.code,
            },
        }
        self._broadcast_payload("error", payload)

    def _setup_routes(self) -> None:
        """Set up all HTTP endpoints."""

        _IDENTITY_HEADERS = {"x-web-user-email", "x-web-user-name", "x-web-user-role"}
        _TRUSTED_HOSTS = {"127.0.0.1", "::1", "localhost"}

        @self.app.middleware("http")
        async def _validate_identity_headers(request, call_next):  # pyright: ignore
            """Reject identity headers from non-trusted sources."""
            has_identity = any(h in _IDENTITY_HEADERS for h in request.headers)
            if has_identity:
                client_host = request.client.host if request.client else None
                # Unix socket connections have no client host (or show as empty)
                is_trusted = client_host is None or client_host in _TRUSTED_HOSTS
                if not is_trusted:
                    logger.warning(
                        "Rejected identity headers from untrusted source: %s",
                        client_host,
                    )
                    return JSONResponse(
                        {"detail": "Identity headers rejected: untrusted source"},
                        status_code=403,
                    )
            return await call_next(request)

        @self.app.middleware("http")
        async def _track_requests(request, call_next):  # pyright: ignore
            """Track in-flight requests to detect stalls."""
            self._request_seq += 1
            req_id = self._request_seq
            self._inflight_requests[req_id] = (request.url.path, time.monotonic())
            try:
                return await call_next(request)
            finally:
                self._inflight_requests.pop(req_id, None)

        @self.app.get("/health")
        async def health() -> dict[str, str]:  # pyright: ignore
            """Health check endpoint."""
            return {"status": "ok"}

        @self.app.get("/sessions")
        async def list_sessions(  # pyright: ignore
            request: "Request",
            computer: str | None = None,
        ) -> list[SessionSummaryDTO]:
            """List sessions from local storage and remote cache.

            Applies role-based filtering when identity headers are present
            (web interface requests). TUI/MCP clients without headers see all.

            Args:
                request: FastAPI request (for identity headers)
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
                    merged = local_sessions
                elif computer:
                    # With cache, merge local + cached sessions
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

                # Role-based visibility filtering (only when identity headers present)
                merged = _filter_sessions_by_role(request, merged)

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

            channel_metadata: dict[str, str] | None = None
            if request.human_email or request.human_role:
                channel_metadata = {}
                if request.human_email:
                    channel_metadata["human_email"] = request.human_email
                if request.human_role:
                    channel_metadata["human_role"] = request.human_role

            metadata = self._metadata(
                title=request.title or "Untitled",
                project_path=request.project_path,
                subdir=request.subdir,
                channel_metadata=channel_metadata,
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

            auto_command_source = "request" if request.auto_command else ("derived" if launch_intent else "none")
            logger.info(
                "create_session request: computer=%s project=%s agent=%s thinking_mode=%s launch_kind=%s "
                "native_session_id=%s auto_command=%s auto_command_source=%s",
                request.computer,
                request.project_path,
                request.agent,
                request.thinking_mode,
                request.launch_kind,
                request.native_session_id,
                auto_command,
                auto_command_source,
            )

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

                if not session_id or not tmux_session_name:
                    logger.error(
                        "create_session missing required fields (session_id=%s, tmux_session_name=%s)",
                        session_id,
                        tmux_session_name,
                    )
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to create session: missing session_id or tmux_session_name",
                    )

                return CreateSessionResponseDTO(
                    status="success",
                    session_id=str(session_id),
                    tmux_session_name=str(tmux_session_name),
                    agent=launch_intent.agent if launch_intent else None,
                )
            except HTTPException as exc:
                raise exc
            except Exception as e:
                logger.error("create_session failed (computer=%s): %s", request.computer, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to create session: {e}") from e

        @self.app.delete("/sessions/{session_id}")
        async def end_session(  # pyright: ignore
            request: "Request",
            session_id: str,
            computer: str = Query(...),  # noqa: ARG001 - For API consistency, only local sessions supported
        ) -> dict[str, object]:  # guard: loose-dict - API boundary
            """End session - local sessions only (remote session management via MCP tools)."""
            from teleclaude.api.session_access import check_session_access

            await check_session_access(request, session_id, require_owner=True)
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
            http_request: "Request",
            session_id: str,
            request: SendMessageRequest,
            computer: str | None = Query(None),  # noqa: ARG001 - Optional param for API consistency
        ) -> dict[str, object]:  # guard: loose-dict - API boundary
            """Send message to session."""
            from teleclaude.api.session_access import check_session_access

            await check_session_access(http_request, session_id)
            try:
                metadata = self._metadata()
                cmd = CommandMapper.map_api_input(
                    "message",
                    {"session_id": session_id, "text": request.message},
                    metadata,
                )
                await get_command_service().process_message(cmd)
                return {"status": "success"}
            except Exception as e:
                logger.error("process_message failed (session=%s): %s", session_id, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to send message: {e}") from e

        @self.app.post("/sessions/{session_id}/keys")
        async def send_keys_endpoint(  # pyright: ignore
            http_request: "Request",
            session_id: str,
            request: KeysRequest,
            computer: str | None = Query(None),  # noqa: ARG001 - Optional param for API consistency
        ) -> dict[str, object]:  # guard: loose-dict - API boundary
            """Send key command to session."""
            from teleclaude.api.session_access import check_session_access

            await check_session_access(http_request, session_id)
            try:
                metadata = self._metadata()
                args: list[str] = []
                if request.count:
                    args = [str(request.count)]
                cmd = CommandMapper.map_api_input(
                    "keys",
                    {"session_id": session_id, "key": request.key, "args": args},
                    metadata,
                )
                await get_command_service().keys(cmd)
                return {"status": "success"}
            except Exception as e:
                logger.error("send_keys failed (session=%s): %s", session_id, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to send keys: {e}") from e

        @self.app.post("/sessions/{session_id}/voice")
        async def send_voice_endpoint(  # pyright: ignore
            http_request: "Request",
            session_id: str,
            request: VoiceInputRequest,
            computer: str | None = Query(None),  # noqa: ARG001 - Optional param for API consistency
        ) -> dict[str, object]:  # guard: loose-dict - API boundary
            """Send voice input to session."""
            from teleclaude.api.session_access import check_session_access

            await check_session_access(http_request, session_id)
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
            http_request: "Request",
            session_id: str,
            request: FileUploadRequest,
            computer: str | None = Query(None),  # noqa: ARG001 - Optional param for API consistency
        ) -> dict[str, object]:  # guard: loose-dict - API boundary
            """Send file input to session."""
            from teleclaude.api.session_access import check_session_access

            await check_session_access(http_request, session_id)
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
                logger.info("API agent_restart requested (session=%s, origin=api)", session_id[:8])

                # Quick validation before dispatching
                session = await db.get_session(session_id)
                if not session:
                    raise HTTPException(status_code=404, detail="Session not found")
                if not session.active_agent:
                    raise HTTPException(status_code=409, detail="No active agent for this session")
                if not session.native_session_id:
                    raise HTTPException(status_code=409, detail="No native session ID - start agent first")

                # Dispatch work asynchronously - don't await
                metadata = self._metadata()
                cmd = CommandMapper.map_api_input(
                    "agent_restart",
                    {"session_id": session_id, "args": []},
                    metadata,
                )
                asyncio.create_task(get_command_service().restart_agent(cmd))
                return {"status": "accepted"}
            except HTTPException:
                raise
            except Exception as e:
                logger.error("agent_restart failed for session %s: %s", session_id, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to restart agent: {e}") from e

        @self.app.post("/sessions/{session_id}/revive")
        async def revive_session(  # pyright: ignore
            session_id: str,
        ) -> CreateSessionResponseDTO:
            """Revive a session by TeleClaude session ID, including previously closed sessions."""
            try:
                session = await db.get_session(session_id)
                if not session:
                    raise HTTPException(status_code=404, detail="Session not found")
                if not session.active_agent:
                    raise HTTPException(status_code=409, detail="No active agent for this session")
                if not session.native_session_id:
                    raise HTTPException(status_code=409, detail="No native session ID - start agent first")

                metadata = self._metadata()
                cmd = CommandMapper.map_api_input(
                    "agent_restart",
                    {"session_id": session_id, "args": []},
                    metadata,
                )
                success, error = await get_command_service().restart_agent(cmd)
                if not success:
                    detail = error or "Failed to revive session"
                    raise HTTPException(status_code=409, detail=detail)

                refreshed = await db.get_session(session_id)
                tmux_session_name = refreshed.tmux_session_name if refreshed and refreshed.tmux_session_name else ""
                return CreateSessionResponseDTO(
                    status="success",
                    session_id=session_id,
                    tmux_session_name=tmux_session_name,
                    agent=session.active_agent if session.active_agent in {"claude", "gemini", "codex"} else None,
                )
            except HTTPException:
                raise
            except Exception as e:
                logger.error("revive_session failed for session %s: %s", session_id, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to revive session: {e}") from e

        @self.app.get("/sessions/{session_id}/messages")
        async def get_session_messages(  # pyright: ignore
            request: "Request",
            session_id: str,
            since: str | None = Query(None, description="ISO 8601 UTC timestamp; only messages after this time"),
            include_tools: bool = Query(False, description="Include tool_use/tool_result entries"),
            include_thinking: bool = Query(False, description="Include thinking/reasoning blocks"),
        ) -> SessionMessagesDTO:
            """Get structured messages from a session's transcript files."""
            from teleclaude.api.session_access import check_session_access

            await check_session_access(request, session_id)
            from teleclaude.core.agents import AgentName
            from teleclaude.utils.transcript import extract_messages_from_chain

            try:
                session = await db.get_session(session_id)
                if not session:
                    raise HTTPException(status_code=404, detail="Session not found")

                # Build file chain: transcript_files (historical) + native_log_file (current)
                chain: list[str] = []
                if session.transcript_files:
                    try:
                        stored = json.loads(session.transcript_files)
                        if isinstance(stored, list):
                            chain = [str(p) for p in stored if p]
                    except (json.JSONDecodeError, TypeError):
                        pass
                if session.native_log_file and session.native_log_file not in chain:
                    chain.append(session.native_log_file)

                if not chain:
                    return SessionMessagesDTO(
                        session_id=session_id,
                        agent=session.active_agent,
                        messages=[],
                    )

                # Determine agent for parser selection
                try:
                    agent_name = AgentName.from_str(session.active_agent or "claude")
                except ValueError:
                    agent_name = AgentName.CLAUDE

                raw_messages = extract_messages_from_chain(
                    chain,
                    agent_name,
                    since=since,
                    include_tools=include_tools,
                    include_thinking=include_thinking,
                )

                messages = [
                    MessageDTO(
                        role=str(m.get("role", "assistant")),
                        type=str(m.get("type", "text")),
                        text=str(m.get("text", "")),
                        timestamp=str(m["timestamp"]) if m.get("timestamp") else None,
                        entry_index=int(m.get("entry_index", 0)),
                        file_index=int(m.get("file_index", 0)),
                    )
                    for m in raw_messages
                ]

                return SessionMessagesDTO(
                    session_id=session_id,
                    agent=session.active_agent,
                    messages=messages,
                )
            except HTTPException:
                raise
            except Exception as e:
                logger.error("get_session_messages failed (session=%s): %s", session_id, e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to get messages: {e}") from e

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
                # Get LOCAL projects from command handler (with todos for cache population)
                raw_projects = await command_handlers.list_projects_with_todos()
                computer_name = config.computer.name
                result: list[ProjectDTO] = []

                if self.cache:
                    self.cache.apply_projects_snapshot(computer_name, raw_projects)
                    # Populate local todo cache so TUI has data immediately
                    todos_by_project: dict[str, list[TodoInfo]] = {}
                    for p in raw_projects:
                        if p.path and p.todos:
                            todos_by_project[p.path] = p.todos
                    if todos_by_project:
                        self.cache.apply_todos_snapshot(computer_name, todos_by_project)

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
                    status_val = info.get("status")
                    status_text = str(status_val) if status_val in {"available", "unavailable", "degraded"} else None
                    result[agent] = AgentAvailabilityDTO(
                        agent=agent,
                        available=bool(info.get("available", True)),
                        status=status_text,
                        unavailable_until=str(unavail_until) if unavail_until and unavail_until is not True else None,
                        reason=str(reason_val) if reason_val and reason_val is not True else None,
                    )
                else:
                    # No record means agent is available (never marked unavailable)
                    result[agent] = AgentAvailabilityDTO(
                        agent=agent,
                        available=True,
                        status="available",
                    )

            return result

        @self.app.get("/api/people")
        async def list_people() -> list[PersonDTO]:  # pyright: ignore
            """List people from global config (safe subset only)."""
            try:
                from teleclaude.cli.config_handlers import get_global_config

                global_cfg = get_global_config()
                return [PersonDTO(name=p.name, email=p.email, role=p.role) for p in global_cfg.people]
            except Exception as e:
                logger.error("list_people failed: %s", e, exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to list people: {e}") from e

        @self.app.get("/settings")
        async def get_settings() -> SettingsDTO:  # pyright: ignore
            """Return current mutable runtime settings."""
            if not self.runtime_settings:
                raise HTTPException(503, "Runtime settings not available")
            state = self.runtime_settings.get_state()
            return SettingsDTO(
                tts=TTSSettingsDTO(enabled=state.tts.enabled),
                pane_theming_mode=state.pane_theming_mode,
            )

        @self.app.patch("/settings")
        async def patch_settings(body: dict[str, PatchBodyValue] = Body(...)) -> SettingsDTO:  # pyright: ignore
            """Apply partial updates to mutable runtime settings."""
            from teleclaude.config.runtime_settings import RuntimeSettings

            if not self.runtime_settings:
                raise HTTPException(503, "Runtime settings not available")
            try:
                typed_patch = RuntimeSettings.parse_patch(body)
                state = self.runtime_settings.patch(typed_patch)
                return SettingsDTO(
                    tts=TTSSettingsDTO(enabled=state.tts.enabled),
                    pane_theming_mode=state.pane_theming_mode,
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc

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
                                dor_score=t.dor_score,
                                deferrals_status=t.deferrals_status,
                                findings_count=t.findings_count,
                                files=t.files,
                            )
                            for t in raw_todos
                        ]
                    return []

                entries = self.cache.get_todo_entries(
                    computer=computer,
                    project_path=project,
                    include_stale=True,
                )
                stale_remote_computers: set[str] = set()
                result: list[TodoDTO] = []
                for entry in entries:
                    if entry.is_stale and entry.computer:
                        stale_remote_computers.add(entry.computer)
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
                                dor_score=todo.dor_score,
                                deferrals_status=todo.deferrals_status,
                                findings_count=todo.findings_count,
                                files=todo.files,
                            )
                        )
                self._refresh_stale_todos(stale_remote_computers)
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

                    # Update cache interest and refresh only on newly added interest
                    if self.cache:
                        newly_added = self._update_cache_interest()
                        for computer, data_type in newly_added:
                            await self._pull_remote_on_interest(computer, data_type)

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

    def _update_cache_interest(self) -> list[tuple[str, str]]:
        """Update cache interest based on active WebSocket subscriptions."""
        if not self.cache:
            return []

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
        newly_added: list[tuple[str, str]] = []
        for data_type, curr_computers in current_interest.items():
            prev_computers = self._previous_interest.get(data_type, set())
            for computer in curr_computers - prev_computers:
                self.cache.set_interest(data_type, computer)
                logger.debug("Added new interest: %s for %s", data_type, computer)
                newly_added.append((computer, data_type))

        # Update tracking
        self._previous_interest = current_interest
        logger.debug("Current cache interest: %s", current_interest)
        return newly_added

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

        if data_type in ("projects", "preparation"):
            adapter.request_refresh(computer, "projects", reason="interest")
        elif data_type == "sessions":
            adapter.request_refresh(computer, "sessions", reason="interest")

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
            adapter.request_refresh(computer, "projects", reason="ttl")

    def _refresh_stale_todos(self, computers: set[str]) -> None:
        """Trigger background refresh for stale todo cache entries."""
        if not self.cache or not computers:
            return
        adapter = self.client.adapters.get("redis")
        if not isinstance(adapter, RedisTransport):
            return
        for computer in sorted(computers):
            if computer == "local":
                continue
            adapter.request_refresh(computer, "projects", reason="ttl")

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
        # Convert to DTO payload if necessary
        payload: dict[str, object]  # guard: loose-dict - WebSocket payload assembly
        if event in ("session_started", "session_updated"):
            # Extract session from cache notification
            session: SessionSummary | None = None
            if isinstance(data, dict):
                session_val = data.get("session")
                if isinstance(session_val, SessionSummary):
                    session = session_val
            elif isinstance(data, SessionSummary):
                session = data

            if session:
                dto = SessionSummaryDTO.from_core(session, computer=session.computer)
                if event == "session_started":
                    payload = SessionStartedEventDTO(
                        event=event,
                        data=dto,
                    ).model_dump(exclude_none=True)
                else:
                    payload = SessionUpdatedEventDTO(
                        event=event,
                        data=dto,
                    ).model_dump(exclude_none=True)
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
            "todo_created",
            "todo_updated",
            "todo_removed",
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

            normalized_event: Literal[
                "computer_updated",
                "project_updated",
                "projects_updated",
                "todos_updated",
                "todo_created",
                "todo_updated",
                "todo_removed",
            ]
            if event == "projects_snapshot":
                normalized_event = "projects_updated"
            elif event == "todos_snapshot":
                normalized_event = "todos_updated"
            else:
                normalized_event = event  # type: ignore[assignment]

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

            async def _send_with_timeout(client: WebSocket = ws) -> None:
                try:
                    await asyncio.wait_for(client.send_json(payload), timeout=2.0)
                except TimeoutError:
                    logger.warning("WebSocket send timeout, removing client")
                    self._ws_clients.discard(client)
                    self._client_subscriptions.pop(client, None)
                    await self._close_ws(client)
                except (OSError, ConnectionError) as exc:
                    logger.info("WebSocket connection lost: %s", exc)
                    self._ws_clients.discard(client)
                    self._client_subscriptions.pop(client, None)
                    await self._close_ws(client)
                except Exception as exc:
                    # UNEXPECTED - likely a bug in payload construction or serialization
                    logger.error(
                        "Unexpected error sending WebSocket event '%s': %s",
                        event,
                        exc,
                        exc_info=True,
                        extra={"event_type": event, "payload_keys": list(payload.keys())},
                    )
                    # Re-raise to make bugs visible in tests/monitoring
                    raise

            if self.task_registry:
                self.task_registry.spawn(_send_with_timeout(), name=f"ws-broadcast-{event}")
            else:
                asyncio.create_task(_send_with_timeout())

    async def _close_ws(self, websocket: WebSocket) -> None:
        """Close a WebSocket connection safely with timeout."""
        try:
            await asyncio.wait_for(websocket.close(), timeout=1.0)
        except (TimeoutError, Exception):
            pass

    async def start(self) -> None:
        """Start the API server on Unix socket."""
        self._running = True
        logger.info("API server starting")
        await self._start_server()
        self._start_metrics_task()
        self._start_watch_task()

    async def stop(self) -> None:
        """Stop the API server."""
        self._running = False
        logger.info("API server stopping")
        await self._stop_metrics_task()
        await self._stop_watch_task()
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

    def _start_watch_task(self) -> None:
        if self._watch_task and not self._watch_task.done():
            return
        self._last_watch_tick = time.monotonic()
        self._watch_task = asyncio.create_task(self._watch_loop())

    async def _stop_watch_task(self) -> None:
        if not self._watch_task:
            return
        self._watch_task.cancel()
        try:
            await self._watch_task
        except asyncio.CancelledError:
            pass

    def _dump_stacks(self, reason: str) -> None:
        now = time.monotonic()
        if (now - self._last_dump_at) < API_WATCH_DUMP_COOLDOWN_S:
            return
        self._last_dump_at = now
        try:
            with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as buf:
                faulthandler.dump_traceback(file=buf, all_threads=True)
                buf.seek(0)
                dump = buf.read()
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("API watch dump failed: %s", exc)
            return
        logger.error("API HANG_DUMP reason=%s\n%s", reason, dump)

    async def _watch_loop(self) -> None:
        """Detect API stalls (loop lag or long in-flight requests)."""
        loop = asyncio.get_running_loop()
        while self._running:
            await asyncio.sleep(API_WATCH_INTERVAL_S)
            now = loop.time()
            lag_ms = max(0.0, (now - self._last_watch_tick - API_WATCH_INTERVAL_S) * 1000.0)
            self._last_watch_tick = now
            if lag_ms >= API_WATCH_LAG_THRESHOLD_MS:
                logger.warning("API watch: loop lag detected (%.1fms)", lag_ms)
                self._dump_stacks(f"loop_lag_{lag_ms:.1f}ms")

            if not self._inflight_requests:
                continue
            inflight = []
            now_mono = time.monotonic()
            for path, started_at in self._inflight_requests.values():
                age = now_mono - started_at
                if age >= API_WATCH_INFLIGHT_THRESHOLD_S:
                    inflight.append((path, age))
            if inflight:

                def _sort_key(item: tuple[str, float]) -> float:
                    return item[1]

                inflight.sort(key=_sort_key, reverse=True)
                top = ", ".join(f"{path}:{age:.2f}s" for path, age in inflight[:5])
                logger.warning("API watch: slow requests detected (%s)", top)
                self._dump_stacks("slow_requests")

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

        # Start TCP server on localhost:8420
        await self._start_tcp_server()

    async def _start_tcp_server(self) -> None:
        """Start TCP server for web interface access."""
        if self._tcp_server_task and not self._tcp_server_task.done():
            logger.warning("TCP server already running; skipping start")
            return

        tcp_config = uvicorn.Config(
            self.app,
            host=API_TCP_HOST,
            port=API_TCP_PORT,
            log_level="warning",
            ws_ping_interval=API_WS_PING_INTERVAL_S,
            ws_ping_timeout=API_WS_PING_TIMEOUT_S,
            timeout_keep_alive=API_TIMEOUT_KEEP_ALIVE_S,
        )
        self._tcp_server = uvicorn.Server(tcp_config)
        tcp_server = self._tcp_server

        serve_coro = tcp_server._serve() if hasattr(tcp_server, "_serve") else tcp_server.serve()
        self._tcp_server_task = asyncio.create_task(serve_coro)
        self._tcp_server_task.add_done_callback(lambda t, s=tcp_server: self._on_tcp_server_task_done(t, s))

        max_retries = 50
        for _ in range(max_retries):
            if tcp_server.started:
                break
            if self._tcp_server_task.done():
                exc = self._tcp_server_task.exception()
                logger.error("TCP server exited during startup: %s", exc)
                return
            await asyncio.sleep(0.1)

        if tcp_server.started:
            logger.info("TCP server listening on %s:%d", API_TCP_HOST, API_TCP_PORT)
        else:
            logger.error("TCP server failed to start within timeout")

    def _on_tcp_server_task_done(
        self,
        task: asyncio.Task[object],
        server: uvicorn.Server | None = None,
    ) -> None:
        """Handle TCP server exit."""
        if not self._running:
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        server_ref = server or self._tcp_server
        should_exit = getattr(server_ref, "should_exit", None) if server_ref else None
        if exc:
            logger.error("TCP server task crashed: %s (should_exit=%s)", exc, should_exit, exc_info=True)
        elif not should_exit:
            logger.error("TCP server task exited unexpectedly (should_exit=%s)", should_exit)

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
        """Stop uvicorn server tasks safely (Unix socket + TCP)."""
        # Stop TCP server first
        await self._stop_tcp_server()

        # Stop Unix socket server
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

    async def _stop_tcp_server(self) -> None:
        """Stop TCP server task safely."""
        tcp_server = self._tcp_server
        if tcp_server:
            if tcp_server.started:
                tcp_server.should_exit = True
            elif self._tcp_server_task:
                self._tcp_server_task.cancel()

        if self._tcp_server_task:
            try:
                await asyncio.wait_for(self._tcp_server_task, timeout=API_STOP_TIMEOUT_S)
            except asyncio.TimeoutError:
                logger.warning("Timed out stopping TCP server; cancelling task")
                self._tcp_server_task.cancel()
                try:
                    await self._tcp_server_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug("Error during TCP server shutdown: %s", e)

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
