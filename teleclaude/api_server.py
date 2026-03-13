"""API server for HTTP/Unix socket access.

This server provides HTTP endpoints for local clients (telec CLI, etc.)
and routes write requests through AdapterClient.
"""

from __future__ import annotations

import asyncio
import faulthandler
import os
import socket
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket
from fastapi.responses import JSONResponse
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, verify_caller
from teleclaude.api.ws_constants import API_WS_PING_INTERVAL_S, API_WS_PING_TIMEOUT_S
from teleclaude.api.ws_mixin import _WebSocketMixin
from teleclaude.api_models import AgentActivityEventDTO, SessionLifecycleStatusEventDTO, TodoDTO
from teleclaude.config import config
from teleclaude.constants import API_SOCKET_PATH
from teleclaude.core import command_handlers
from teleclaude.core.db import db
from teleclaude.core.error_feedback import get_user_facing_error_message
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentActivityEvent,
    ErrorEventContext,
    SessionLifecycleContext,
    SessionStatusContext,
    SessionUpdatedContext,
    TeleClaudeEvents,
)
from teleclaude.core.models import MessageMetadata, SessionSnapshot
from teleclaude.core.origins import InputOrigin
from teleclaude.core.status_contract import serialize_status_event

if TYPE_CHECKING:
    from teleclaude.api.ws_constants import _WsClientState
    from teleclaude.config.runtime_settings import RuntimeSettings
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.task_registry import TaskRegistry
    from teleclaude.events.db import EventDB

logger = get_logger(__name__)

API_TCP_HOST = "127.0.0.1"
API_TCP_PORT = int(os.getenv("API_TCP_PORT", "8420"))
API_TIMEOUT_KEEP_ALIVE_S = 5
API_STOP_TIMEOUT_S = 5.0
API_WATCH_INTERVAL_S = float(os.getenv("API_WATCH_INTERVAL_S", "5"))
API_WATCH_LAG_THRESHOLD_MS = float(os.getenv("API_WATCH_LAG_THRESHOLD_MS", "250"))
API_WATCH_INFLIGHT_THRESHOLD_S = float(os.getenv("API_WATCH_INFLIGHT_THRESHOLD_S", "1"))
API_WATCH_DUMP_COOLDOWN_S = float(os.getenv("API_WATCH_DUMP_COOLDOWN_S", "30"))

ServerExitHandler = Callable[[BaseException | None, bool | None, bool | None, bool], None]


class APIServer(_WebSocketMixin):
    """HTTP API server on Unix socket."""

    def __init__(
        self,
        client: AdapterClient,
        cache: DaemonCache | None = None,
        task_registry: TaskRegistry | None = None,
        socket_path: str | None = None,
        runtime_settings: RuntimeSettings | None = None,
    ) -> None:
        self.client = client
        self._cache: DaemonCache | None = None  # Initialize private variable
        self.task_registry = task_registry
        self.runtime_settings = runtime_settings
        self.__event_db_inner: EventDB | None = None  # backing store for _event_db property
        self.app = FastAPI(title="TeleClaude API", version="1.0.0")
        self._setup_routes()

        # --- Route modules ---
        from teleclaude.api import (
            agents_routes,
            chiptunes_routes,
            computers_routes,
            jobs_routes,
            notifications_routes,
            people_routes,
            projects_routes,
            sessions_actions_routes,
            sessions_routes,
            settings_routes,
        )

        sessions_routes.configure(client=client, cache=cache)
        sessions_actions_routes.configure(client=client)
        computers_routes.configure(cache=cache)
        projects_routes.configure(cache=cache)
        settings_routes.configure(runtime_settings=runtime_settings)
        chiptunes_routes.configure(runtime_settings=runtime_settings)
        self.app.include_router(sessions_routes.router)
        self.app.include_router(sessions_actions_routes.router)
        self.app.include_router(computers_routes.router)
        self.app.include_router(projects_routes.router)
        self.app.include_router(agents_routes.router)
        self.app.include_router(people_routes.router)
        self.app.include_router(settings_routes.router)
        self.app.include_router(chiptunes_routes.router)
        self.app.include_router(jobs_routes.router)
        self.app.include_router(notifications_routes.router)

        from teleclaude.memory.api_routes import router as memory_router

        self.app.include_router(memory_router)

        from teleclaude.mirrors.api_routes import router as mirrors_router

        self.app.include_router(mirrors_router)

        from teleclaude.hooks.api_routes import router as hooks_router

        self.app.include_router(hooks_router)

        from teleclaude.channels.api_routes import router as channels_router

        self.app.include_router(channels_router)

        from teleclaude.api.streaming import router as streaming_router

        self.app.include_router(streaming_router)

        from teleclaude.api.data_routes import router as data_router

        self.app.include_router(data_router)

        from teleclaude.api.operations_routes import router as operations_router

        self.app.include_router(operations_router)

        from teleclaude.api.todo_routes import router as todo_router

        self.app.include_router(todo_router)

        from teleclaude.api.event_routes import router as event_router

        self.app.include_router(event_router)
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
        # Per-websocket sender state for serialized outbound writes.
        self._ws_client_states: dict[WebSocket, _WsClientState] = {}
        # Track previous interest to remove stale entries
        self._previous_interest: dict[str, set[str]] = {}  # {data_type: {computers}}
        # Debounce refresh-style WS events to avoid burst refresh storms
        self._refresh_debounce_task: asyncio.Task[object] | None = None
        self._refresh_pending_payload: dict[str, object] | None = None  # guard: loose-dict - WS payload

        # Subscribe to local session updates
        event_bus.subscribe(TeleClaudeEvents.SESSION_UPDATED, self._handle_session_updated_event)
        event_bus.subscribe(TeleClaudeEvents.SESSION_STARTED, self._handle_session_started_event)
        event_bus.subscribe(TeleClaudeEvents.SESSION_CLOSED, self._handle_session_closed_event)
        event_bus.subscribe(TeleClaudeEvents.SESSION_STATUS, self._handle_session_status_event)
        event_bus.subscribe(TeleClaudeEvents.AGENT_ACTIVITY, self._handle_agent_activity_event)
        event_bus.subscribe(TeleClaudeEvents.ERROR, self._handle_error_event)

        # Set cache through property to trigger subscription
        self.cache = cache

    @property
    def _event_db(self) -> EventDB | None:
        """Get event DB reference."""
        return self.__event_db_inner

    @_event_db.setter
    def _event_db(self, value: EventDB | None) -> None:
        """Set event DB and propagate to notifications route module."""
        self.__event_db_inner = value
        from teleclaude.api import notifications_routes

        notifications_routes.configure(event_db=value)

    def _metadata(self, **kwargs: object) -> MessageMetadata:
        """Build API boundary metadata."""
        return MessageMetadata(origin=InputOrigin.API.value, **kwargs)

    @property
    def cache(self) -> DaemonCache | None:
        """Get cache reference."""
        return self._cache

    @cache.setter
    def cache(self, value: DaemonCache | None) -> None:
        """Set cache reference, subscribe to changes, and propagate to route modules."""
        if self._cache:
            self._cache.unsubscribe(self._on_cache_change)
        self._cache = value
        if value:
            value.subscribe(self._on_cache_change)
            logger.info("API server subscribed to cache notifications")
        # Propagate to cache-dependent route modules
        from teleclaude.api import computers_routes, projects_routes, sessions_routes

        sessions_routes.configure(cache=value)
        computers_routes.configure(cache=value)
        projects_routes.configure(cache=value)

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
        snapshot = SessionSnapshot.from_db_session(session, computer=config.computer.name)
        self.cache.update_session(snapshot)

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
        snapshot = SessionSnapshot.from_db_session(session, computer=config.computer.name)
        self.cache.update_session(snapshot)

    async def _handle_session_closed_event(
        self,
        _event: str,
        context: SessionLifecycleContext,
    ) -> None:
        """Handle local session removal by updating cache and broadcasting closed status."""
        if not self.cache:
            logger.warning("Cache unavailable, cannot remove session from cache")
            return
        self.cache.remove_session(context.session_id)

        # Broadcast canonical closed status (R2) to WS clients — validated via contract
        timestamp = datetime.now(UTC).isoformat()
        canonical = serialize_status_event(
            session_id=context.session_id,
            status="closed",
            reason="session_closed",
            timestamp=timestamp,
        )
        if canonical is None:
            return
        dto = SessionLifecycleStatusEventDTO(
            session_id=context.session_id,
            status="closed",
            reason="session_closed",
            timestamp=timestamp,
        )
        self._broadcast_payload("session_status", dto.model_dump(exclude_none=True))

    async def _handle_session_status_event(
        self,
        _event: str,
        context: SessionStatusContext,
    ) -> None:
        """Broadcast canonical lifecycle status transition events to WS clients.

        Delivers the contract-defined status vocabulary (R2) directly to connected
        clients without cache or DB re-read. Clients use this to render truthful
        session status without adapter-local heuristics (R1, R3).
        """
        dto = SessionLifecycleStatusEventDTO(
            session_id=context.session_id,
            status=context.status,
            reason=context.reason,
            timestamp=context.timestamp,
            last_activity_at=context.last_activity_at,
            message_intent=context.message_intent,
            delivery_scope=context.delivery_scope,
        )
        self._broadcast_payload("session_status", dto.model_dump(exclude_none=True))

    async def _handle_agent_activity_event(
        self,
        _event: str,
        context: AgentActivityEvent,
    ) -> None:
        """Broadcast agent activity events to WS clients (no cache, no DB re-read).

        The DTO preserves hook event type in 'type' for consumer compatibility and
        also carries canonical contract fields (canonical_type, message_intent,
        delivery_scope) when produced via the canonical contract module.
        """
        dto = AgentActivityEventDTO(
            session_id=context.session_id,
            type=context.event_type,
            tool_name=context.tool_name,
            tool_preview=context.tool_preview,
            summary=context.summary,
            timestamp=context.timestamp,
            canonical_type=context.canonical_type,
            message_intent=context.message_intent,
            delivery_scope=context.delivery_scope,
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
        """Set up core HTTP endpoints (middleware, health, auth, todos, WebSocket)."""

        _IDENTITY_HEADERS = {"x-web-user-email", "x-web-user-name", "x-web-user-role"}
        _TRUSTED_HOSTS = {"127.0.0.1", "::1", "localhost"}

        @self.app.middleware("http")
        async def _validate_identity_headers(request, call_next):  # pyright: ignore
            """Reject identity headers from non-trusted sources."""
            has_identity = any(h in _IDENTITY_HEADERS for h in request.headers)
            if has_identity:
                client_host = request.client.host if request.client else None
                is_trusted = client_host in _TRUSTED_HOSTS or client_host is None or client_host == ""
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

        @self.app.get("/auth/whoami")
        async def auth_whoami(  # pyright: ignore
            identity: CallerIdentity = Depends(verify_caller),
        ) -> dict[str, str | None]:
            """Return the resolved principal for the calling session.

            Agent sessions (X-Session-Token) return their token principal.
            Terminal/TUI sessions return their email-based identity.
            """
            if identity.principal:
                return {"principal": identity.principal, "role": identity.principal_role}
            if identity.human_role:
                return {"principal": None, "role": identity.human_role}
            return {"principal": None, "role": None}

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
                                after=t.after,
                                group=t.group,
                                prepare_phase=t.prepare_phase,
                                integration_phase=t.integration_phase,
                                finalize_status=t.finalize_status,
                            )
                            for t in raw_todos
                        ]
                    return []

                entries = self.cache.get_todo_entries(
                    computer=computer,
                    project_path=project,
                )
                result: list[TodoDTO] = []
                for entry in entries:
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
                                after=todo.after,
                                group=todo.group,
                                prepare_phase=todo.prepare_phase,
                                integration_phase=todo.integration_phase,
                                finalize_status=todo.finalize_status,
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

        # Start TCP listener only when server lifecycle is active.
        # Unit tests call _start_server() directly without setting _running.
        if self._running:
            await self._start_tcp_server()

    async def _start_tcp_server(self) -> None:
        """Start TCP server for web interface access."""
        if self._tcp_server_task and not self._tcp_server_task.done():
            logger.warning("TCP server already running; skipping start")
            return

        # During daemon restarts, the previous listener can briefly keep the
        # port busy. Probe/retry first so TCP startup doesn't destabilize API
        # initialization.
        tcp_port_ready = False
        for _ in range(20):  # ~2s grace window
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    probe.bind((API_TCP_HOST, API_TCP_PORT))
                    tcp_port_ready = True
                    break
                except OSError:
                    await asyncio.sleep(0.1)

        if not tcp_port_ready:
            logger.warning(
                "TCP port unavailable; skipping TCP listener startup",
                host=API_TCP_HOST,
                port=API_TCP_PORT,
            )
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
            except TimeoutError:
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
            except TimeoutError:
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
