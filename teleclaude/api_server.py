"""API server for HTTP/Unix socket access.

This server provides HTTP endpoints for local clients (telec CLI, etc.)
and routes write requests through AdapterClient.
"""

# pylint: disable=import-outside-toplevel,too-many-instance-attributes,too-many-locals,too-many-statements
# pylint: disable=too-many-arguments,too-many-positional-arguments,broad-exception-caught,protected-access
from __future__ import annotations

import asyncio
import faulthandler
import os
import tempfile
import time
import traceback as _tb
import uuid
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from fastapi import Depends, FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from instrukt_ai_logging import get_logger

from teleclaude.api import (
    agents_routes,
    chiptunes_routes,
    computers_routes,
    history_routes,
    jobs_routes,
    mcp_routes,
    people_routes,
    projects_routes,
    readiness_routes,
    reminders_routes,
    session_inspection_routes,
    sessions_actions_routes,
    sessions_routes,
    settings_routes,
    tui_routes,
)
from teleclaude.api.auth import (
    CallerIdentity,
    caller_for_role_resolution,
    carried_caller,
    carried_caller_session_id,
    principal_for_carried_caller,
)
from teleclaude.api.bugs_routes import router as bugs_router
from teleclaude.api.commit_review_stamp_routes import router as commit_review_stamp_router
from teleclaude.api.config_routes import router as config_router
from teleclaude.api.event_serialization import agent_availability_event_dto
from teleclaude.api.ingress_listener import WebhookIngressListener
from teleclaude.api.operations_routes import router as operations_router
from teleclaude.api.relay_boundary import configure as configure_relay_boundary
from teleclaude.api.relay_boundary import relay_boundary
from teleclaude.api.shutdown_refusal import STATE_CHANGING_METHODS, shutdown_refusal_response
from teleclaude.api.todo_artifact_routes import router as todo_artifact_router
from teleclaude.api.todo_by_id_routes import router as todo_by_id_router
from teleclaude.api.todo_routes import router as todo_router
from teleclaude.api.todo_slug_routes import router as todo_slug_router
from teleclaude.api.todo_stamp_routes import router as todo_stamp_router
from teleclaude.api.work_feedback import DeclaredWorkRefusal, declared_refusal_response
from teleclaude.api.ws_constants import API_WS_PING_INTERVAL_S, API_WS_PING_TIMEOUT_S
from teleclaude.api.ws_mixin import _WebSocketMixin
from teleclaude.api.ws_options import (
    WS_INCLUDE_REMOVED_PARAM,
    WS_STREAM_PARAM,
    WsProjectionOptionError,
    parse_ws_projection_options,
)
from teleclaude.api_models import (
    AgentStopActivityEventDTO,
    SessionLifecycleStatusEventDTO,
    ToolUseActivityEventDTO,
    UserPromptSubmitActivityEventDTO,
)
from teleclaude.api_models_health import HealthDTO, PreparationObservationDTO
from teleclaude.api_models_identity import WhoAmIDTO
from teleclaude.api_models_operations import OperationFailedEventDTO, OperationSucceededEventDTO
from teleclaude.caller_identity import CliCaller, PersonCliCaller, Platform, SessionOf, authorizing_role
from teleclaude.checkout_head import read_checkout_head
from teleclaude.config.machine import config
from teleclaude.config.person_secrets import resolve_person_mcp_secret_values
from teleclaude.constants import API_SOCKET_PATH
from teleclaude.core.db import db
from teleclaude.core.error_feedback import get_user_facing_error_message
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentActivityEvent,
    AgentAvailabilityContext,
    ErrorEventContext,
    OperationFailedContext,
    OperationSucceededContext,
    ProjectRefreshTrigger,
    SessionLifecycleContext,
    SessionStatusContext,
    SessionUpdatedContext,
    TeleClaudeEvents,
)
from teleclaude.core.models import JsonDict, MessageMetadata, SessionSnapshot
from teleclaude.core.operation_caller_identity import reset_caller_session_id, set_caller_session_id
from teleclaude.core.operations._kinds import all_outcome_events
from teleclaude.core.origins import InputOrigin
from teleclaude.core.relayed_request import configure as configure_relayed_request
from teleclaude.core.session_lifecycle import LifecycleTransitionReason
from teleclaude.core.shutdown_drain import CONTINUATION_HEADER, ShutdownRefusal, get_shutdown_drain
from teleclaude.hooks.inbound import INBOUND_PATH_PREFIX
from teleclaude.identity_reach import ReachCache
from teleclaude.mcp.runtime import McpRuntimePool
from teleclaude.memory.api_routes import router as memory_router
from teleclaude.paths import REPO_ROOT
from teleclaude.project_root import resolve_project_root

if TYPE_CHECKING:
    from teleclaude.api.ws_constants import _WsClientState
    from teleclaude.config.runtime_settings import RuntimeSettings
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.reminders import ReminderService
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)

API_TIMEOUT_KEEP_ALIVE_S = 5
API_STOP_TIMEOUT_S = 5.0
API_WATCH_INTERVAL_S = config.api.watch_interval_s
API_WATCH_LAG_THRESHOLD_MS = config.api.watch_lag_threshold_ms
API_WATCH_INFLIGHT_THRESHOLD_S = config.api.watch_inflight_threshold_s
API_WATCH_DUMP_COOLDOWN_S = config.api.watch_dump_cooldown_s
API_MCP_REAPER_INTERVAL_S = config.api.mcp_reaper_interval_s
WS_POLICY_VIOLATION_CODE = 1008
_WS_OPTIONS_REFUSED_LOG = "WebSocket connection options refused: %s"
_HOOK_RECEIVER_ERROR_SOURCE = "hook_receiver"

ServerExitHandler = Callable[[BaseException | None, bool | None, bool | None, bool], None]


class APIServer(_WebSocketMixin):  # pyright: ignore[reportIncompatibleVariableOverride]
    """HTTP API server on Unix socket with an optional webhook ingress listener."""

    def __init__(
        self,
        client: AdapterClient,
        cache: DaemonCache | None = None,
        task_registry: TaskRegistry | None = None,
        socket_path: str | None = None,
        runtime_settings: RuntimeSettings | None = None,
        reminder_service: ReminderService | None = None,
        refresh_local_projects: Callable[[ProjectRefreshTrigger], Awaitable[None]] | None = None,
    ) -> None:
        self.client = client
        self._start_commit = read_checkout_head(REPO_ROOT)
        self._cache: DaemonCache | None = None  # Initialize private variable
        self.task_registry = task_registry
        self.runtime_settings = runtime_settings
        self.mcp_runtimes = McpRuntimePool(
            repo_root=resolve_project_root(Path.cwd()),
            person_secret_resolver=resolve_person_mcp_secret_values,
        )
        self.app = FastAPI(title="TeleClaude API", version="1.0.0")
        self._webhook_ingress_listener: WebhookIngressListener | None = None
        if config.computer.is_ingress_node:
            self._webhook_ingress_listener = WebhookIngressListener(
                self.app,
                port=config.api.tcp_port,
                keep_alive_timeout_s=API_TIMEOUT_KEEP_ALIVE_S,
                stop_timeout_s=API_STOP_TIMEOUT_S,
            )
        self._setup_routes()
        configure_relay_boundary(client=client)
        configure_relayed_request(self.app)

        # --- Route modules ---
        sessions_routes.configure(client=client, cache=cache, reminder_service=reminder_service)
        session_inspection_routes.configure(client=client, cache=cache)
        reminders_routes.configure(reminder_service)
        sessions_actions_routes.configure(client=client)
        readiness_routes.configure(client=client)
        computers_routes.configure(cache=cache)
        projects_routes.configure(cache=cache, refresh_local_projects=refresh_local_projects)
        tui_routes.configure(cache=cache)
        settings_routes.configure(runtime_settings=runtime_settings)
        mcp_routes.configure(runtime=self.mcp_runtimes)
        # chiptunes_routes are wired by the daemon after lifecycle start
        self.app.include_router(sessions_routes.router)
        self.app.include_router(session_inspection_routes.router)
        self.app.include_router(sessions_actions_routes.router)
        self.app.include_router(computers_routes.router)
        self.app.include_router(projects_routes.router)
        self.app.include_router(readiness_routes.router)
        self.app.include_router(reminders_routes.router)
        self.app.include_router(agents_routes.router)
        self.app.include_router(people_routes.router)
        self.app.include_router(settings_routes.router)
        self.app.include_router(tui_routes.router)
        self.app.include_router(chiptunes_routes.router)
        self.app.include_router(jobs_routes.router)
        self.app.include_router(mcp_routes.router)
        self.app.include_router(memory_router)

        self.app.include_router(history_routes.router)

        self.app.include_router(operations_router)

        self.app.include_router(todo_router)
        self.app.include_router(todo_slug_router)
        self.app.include_router(bugs_router)
        self.app.include_router(config_router)
        self.app.include_router(todo_by_id_router)
        self.app.include_router(todo_artifact_router)
        self.app.include_router(todo_stamp_router)
        self.app.include_router(commit_review_stamp_router)

        self.socket_path = socket_path or API_SOCKET_PATH
        self.server: uvicorn.Server | None = None
        self.server_task: asyncio.Task[object] | None = None
        self._metrics_task: asyncio.Task[object] | None = None
        self._watch_task: asyncio.Task[object] | None = None
        self._mcp_reaper_task: asyncio.Task[object] | None = None
        self._inflight_requests: dict[int, tuple[str, float]] = {}
        self._request_seq = 0
        self._last_watch_tick = 0.0
        self._last_dump_at = 0.0
        self._running = False
        self._on_server_exit: ServerExitHandler | None = None
        # WebSocket state
        self._ws_clients: set[WebSocket] = set()
        self._ws_viewers: dict[WebSocket, CliCaller] = {}
        self._ws_caller_session_ids: dict[WebSocket, str | None] = {}
        self._ws_reach_caches: dict[WebSocket, ReachCache] = {}
        self._ws_sent_session_ids: dict[WebSocket, set[str]] = {}
        # Per-websocket sender state for serialized outbound writes.
        self._ws_client_states: dict[WebSocket, _WsClientState] = {}
        # Debounce refresh-style WS events to avoid burst refresh storms
        self._refresh_debounce_task: asyncio.Task[object] | None = None
        self._refresh_pending_payloads: dict[WebSocket, JsonDict] = {}

        # Subscribe to local session updates
        event_bus.subscribe(TeleClaudeEvents.SESSION_UPDATED, self._handle_session_updated_event)
        event_bus.subscribe(TeleClaudeEvents.SESSION_STARTED, self._handle_session_started_event)
        event_bus.subscribe(TeleClaudeEvents.SESSION_CLOSED, self._handle_session_closed_event)
        event_bus.subscribe(TeleClaudeEvents.SESSION_STATUS, self._handle_session_status_event)
        event_bus.subscribe(TeleClaudeEvents.AGENT_AVAILABILITY, self._handle_agent_availability_event)
        event_bus.subscribe(TeleClaudeEvents.AGENT_ACTIVITY, self._handle_agent_activity_event)
        event_bus.subscribe(TeleClaudeEvents.ERROR, self._handle_error_event)

        # Bridge operation outcome events to WebSocket clients
        for _op_event in all_outcome_events():
            event_bus.subscribe(_op_event, self._handle_operation_completed_event)

        # Set cache through property to trigger subscription
        self.cache = cache

    def _metadata(self, **kwargs: object) -> MessageMetadata:
        """Build API boundary metadata."""
        return MessageMetadata(origin=InputOrigin.TERMINAL.value, **kwargs)

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
        sessions_routes.configure(cache=value)
        session_inspection_routes.configure(cache=value)
        computers_routes.configure(cache=value)
        projects_routes.configure(cache=value)
        tui_routes.configure(cache=value)

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

    async def _handle_session_status_event(
        self,
        _event: str,
        context: SessionStatusContext,
    ) -> None:
        """Broadcast canonical lifecycle status transition events to WS clients.

        Delivers the contract-defined status vocabulary (R2) directly to connected
        clients whose current role reaches the session. Clients use this to render truthful
        session status without adapter-local heuristics (R1, R3).
        """
        session = await db.get_session(context.session_id)
        if session is None:
            return
        snapshot = SessionSnapshot.from_db_session(session, computer=config.computer.name)
        close_failed = context.reason == LifecycleTransitionReason.CLOSE_FAILED
        if close_failed and self.cache:
            # The failed close restored the record; the snapshot below must carry that state.
            self.cache.update_session(snapshot)
        targets = self._session_event_targets(snapshot)
        if not targets:
            return
        dto = SessionLifecycleStatusEventDTO(
            session_id=context.session_id,
            status=context.status,
            reason=context.reason,
            timestamp=context.timestamp,
            last_activity_at=context.last_activity_at,
            message_intent=context.message_intent,
            delivery_scope=context.delivery_scope,
        )
        self._broadcast_payload("session_status", dto.model_dump(exclude_none=True), targets=targets)
        if close_failed:
            await self._send_session_snapshots(targets)

    async def _session_event_targets_for_id(self, session_id: str | None) -> list[WebSocket]:
        """Resolve a session's current reach before delivering its event."""
        if session_id is None:
            return []
        session = await db.get_session(session_id)
        if session is None:
            return []
        snapshot = SessionSnapshot.from_db_session(session, computer=config.computer.name)
        return self._session_event_targets(snapshot)

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
        common = {
            "session_id": context.session_id,
            "timestamp": context.timestamp,
            "canonical_type": context.canonical_type,
            "message_intent": context.message_intent,
            "delivery_scope": context.delivery_scope,
        }
        if context.event_type == "user_prompt_submit":
            dto = UserPromptSubmitActivityEventDTO(**common)
        elif context.event_type == "pre_tool_use":
            dto = ToolUseActivityEventDTO(
                tool_name=getattr(context, "tool_name", None),
                tool_preview=getattr(context, "tool_preview", None),
                **common,
            )
        elif context.event_type == "agent_stop":
            dto = AgentStopActivityEventDTO(summary=getattr(context, "summary", None), **common)
        else:
            return
        targets = await self._session_event_targets_for_id(context.session_id)
        if not targets:
            return
        self._broadcast_payload("agent_activity", dto.model_dump(exclude_none=True), targets=targets)

    async def _handle_agent_availability_event(
        self,
        _event: str,
        context: AgentAvailabilityContext,
    ) -> None:
        """Broadcast live agent availability changes to WS clients."""
        dto = agent_availability_event_dto(context)
        self._broadcast_payload("agent_availability", dto.model_dump(exclude_none=True))

    async def _handle_error_event(
        self,
        _event: str,
        context: ErrorEventContext,
    ) -> None:
        """Broadcast error events to WS clients."""
        if context.source == _HOOK_RECEIVER_ERROR_SOURCE:
            logger.debug(
                "Suppressing technical hook feedback from TUI websocket delivery",
                source=context.source,
                code=context.code,
            )
            return
        user_message = get_user_facing_error_message(context)
        if user_message is None:
            logger.debug(
                "Suppressing non-user-facing websocket error",
                source=context.source,
                code=context.code,
            )
            return

        targets = await self._session_event_targets_for_id(context.session_id)
        if not targets:
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
        self._broadcast_payload("error", payload, targets=targets)

    async def _handle_operation_completed_event(
        self,
        event: str,
        context: OperationSucceededContext | OperationFailedContext,
    ) -> None:
        """Broadcast an operation outcome (success or failure) to WebSocket clients."""
        operation = await db.get_operation(context.operation_id)
        if operation is None:
            return
        targets = self._subject_event_targets(
            operation.subject,
            operation.subject_owner,
            caller_session_id=operation.caller_session_id,
        )
        if not targets:
            return
        dto: OperationSucceededEventDTO | OperationFailedEventDTO
        if isinstance(context, OperationFailedContext):
            dto = OperationFailedEventDTO(
                event=event,
                operation_id=context.operation_id,
                error=context.error,
                work_feedback=operation.work_feedback,
            )
        else:
            dto = OperationSucceededEventDTO(
                event=event,
                operation_id=context.operation_id,
                work_feedback=operation.work_feedback,
            )
        self._broadcast_payload(event, dto.model_dump(exclude_none=True), targets=targets)

    def _setup_routes(self) -> None:
        """Set up core HTTP endpoints (middleware, health, auth, todos, WebSocket)."""

        # Registered before request tracking so the boundary runs inside it: a draining
        # computer refuses a state-changing request before it is carried anywhere.
        self.app.middleware("http")(relay_boundary)

        @self.app.exception_handler(Exception)
        async def _unhandled_exception(request, exc):  # type: ignore[no-untyped-def]
            """Last-resort handler: log full traceback, return generic 500 to client."""
            tb_lines = _tb.format_exception(type(exc), exc, exc.__traceback__)
            logger.error(
                "Unhandled API exception: %s %s\n%s",
                request.method,
                request.url.path,
                "".join(tb_lines),
            )
            return JSONResponse({"detail": "Internal server error"}, status_code=500)

        @self.app.exception_handler(ShutdownRefusal)
        async def _shutdown_refusal(request, exc):  # type: ignore[no-untyped-def]
            """Service-level refusal of new work while draining: explicit and retryable."""
            return shutdown_refusal_response(exc)

        @self.app.exception_handler(DeclaredWorkRefusal)
        async def _declared_work_refusal(request, exc):  # type: ignore[no-untyped-def]
            """Preserve the HTTP refusal contract while carrying its explicit work message."""
            return declared_refusal_response(
                status_code=exc.status_code,
                detail=exc.detail,
                work_feedback=exc.work_feedback,
                headers=exc.headers,
            )

        @self.app.middleware("http")
        async def _track_requests(request, call_next):  # type: ignore[no-untyped-def]
            """Admit requests while the daemon accepts work, and track in-flight requests to detect stalls."""
            drain = get_shutdown_drain()
            capability = request.headers.get(CONTINUATION_HEADER)
            continuation = drain.resolve_continuation(capability) if capability else None
            if not drain.is_open and request.method in STATE_CHANGING_METHODS and continuation is None:
                refusal = ShutdownRefusal(f"{request.method} {request.url.path}", drain.phase)
                return shutdown_refusal_response(refusal)
            self._request_seq += 1
            req_id = self._request_seq
            self._inflight_requests[req_id] = (request.url.path, time.monotonic())
            if request.url.path == "/reminders" or request.url.path.startswith("/reminders/"):
                reminder_request_id = str(uuid.uuid4())
                request.state.reminder_request_id = reminder_request_id
                operation = {"POST": "set", "GET": "list", "DELETE": "cancel"}.get(
                    request.method,
                    "unknown",
                )
                logger.info(
                    "reminder_api_ingress",
                    request_id=reminder_request_id,
                    method=request.method,
                    path=request.url.path,
                    operation=operation,
                )
            # Inbound external requests authenticate by signature alone and carry no caller identity.
            carries_caller = not request.url.path.startswith(INBOUND_PATH_PREFIX)
            caller_token = set_caller_session_id(carried_caller_session_id(request) if carries_caller else None)
            try:
                with continuation.bound() if continuation is not None else nullcontext():
                    return await call_next(request)
            finally:
                self._inflight_requests.pop(req_id, None)
                reset_caller_session_id(caller_token)

        @self.app.get("/health", response_model_exclude_none=True)
        async def health(request: Request) -> HealthDTO:  # pyright: ignore
            """Health check endpoint, carrying the commit the daemon's code stood on at its start.

            The preparation observation rides only on the local API socket: the TCP webhook
            listener shares this app and has a bound port in its server address.
            """
            server = request.scope.get("server")
            over_tcp = server is not None and server[1] is not None
            preparation = (
                None if over_tcp else PreparationObservationDTO.from_observation(get_shutdown_drain().observation())
            )
            return HealthDTO(start_commit=self._start_commit, preparation=preparation)

        @self.app.get("/auth/whoami")
        async def auth_whoami(  # pyright: ignore
            identity: CallerIdentity = Depends(carried_caller),
        ) -> WhoAmIDTO:
            """Return caller identity and its session's recorded configuration subject."""
            caller = caller_for_role_resolution(identity)
            target = Platform()
            session = None
            if identity.session_id:
                session = await db.get_session(identity.session_id)
                if session is not None and session.project_path:
                    target = SessionOf(Path(session.project_path))
            role = authorizing_role(caller, identity.system_role, target)
            email = caller.email if isinstance(caller, PersonCliCaller) else None
            return WhoAmIDTO(
                principal=principal_for_carried_caller(identity),
                role=role,
                email=email,
                session_id=identity.session_id or None,
                config_subject=session.config_subject if session is not None else None,
            )

        @self.app.websocket("/ws")
        async def websocket_endpoint(  # pyright: ignore
            websocket: WebSocket,
        ) -> None:
            """WebSocket endpoint for push updates."""
            identity = carried_caller(websocket, websocket.headers.get("x-teleclaude-daemon-token"))
            try:
                options = parse_ws_projection_options(
                    websocket.query_params.getlist(WS_STREAM_PARAM),
                    websocket.query_params.get(WS_INCLUDE_REMOVED_PARAM),
                )
            except WsProjectionOptionError as exc:
                logger.warning(_WS_OPTIONS_REFUSED_LOG, exc)
                await websocket.accept()
                await websocket.close(code=WS_POLICY_VIOLATION_CODE, reason=str(exc))
                return
            await self._handle_websocket(
                websocket,
                caller_for_role_resolution(identity),
                caller_session_id=identity.session_id or None,
                options=options,
            )

    async def start(self) -> None:
        """Start the Unix API server and configured webhook ingress listener."""
        self._running = True
        logger.info("API server starting")
        await self._start_server()
        self._start_metrics_task()
        self._start_watch_task()
        self._start_mcp_reaper_task()

    async def stop(self) -> None:
        """Stop the API server."""
        self._running = False
        logger.info("API server stopping")
        await self._stop_metrics_task()
        await self._stop_watch_task()
        await self._stop_mcp_reaper_task()
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
        self._ws_viewers.clear()
        self._ws_caller_session_ids.clear()
        for reach_cache in self._ws_reach_caches.values():
            reach_cache.close()
        self._ws_reach_caches.clear()
        self._ws_sent_session_ids.clear()
        self._refresh_pending_payloads.clear()

        await self.mcp_runtimes.close()
        await self._stop_server()
        self._cleanup_socket("stop")

        logger.info("API server stopped")

    def _start_mcp_reaper_task(self) -> None:
        if self._mcp_reaper_task and not self._mcp_reaper_task.done():
            return
        coro = self._mcp_reaper_loop()
        if self.task_registry:
            self._mcp_reaper_task = self.task_registry.spawn(coro, name="api-mcp-reaper")
        else:
            self._mcp_reaper_task = asyncio.create_task(coro, name="api-mcp-reaper")

    async def _stop_mcp_reaper_task(self) -> None:
        if not self._mcp_reaper_task:
            return
        if not self._mcp_reaper_task.done():
            self._mcp_reaper_task.cancel()
            try:
                await self._mcp_reaper_task
            except asyncio.CancelledError:
                pass
        self._mcp_reaper_task = None

    async def _mcp_reaper_loop(self) -> None:
        while self._running:
            await asyncio.sleep(API_MCP_REAPER_INTERVAL_S)
            try:
                await self.mcp_runtimes.reap_idle()
            except Exception as exc:
                logger.warning("MCP idle reaper failed", error_type=type(exc).__name__)

    def _start_watch_task(self) -> None:
        if self._watch_task and not self._watch_task.done():
            return
        # Must use the event loop clock because _watch_loop measures elapsed time
        # with loop.time(). Mixing clock sources produces bogus startup lag values.
        self._last_watch_tick = asyncio.get_running_loop().time()
        self._watch_task = asyncio.create_task(self._watch_loop(), name="api-watch-loop")

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
        """Start the Unix API server and optional webhook ingress listener."""
        if self.server_task and not self.server_task.done():
            logger.warning("API server already running; skipping start")
            return

        self._cleanup_socket("start_server")

        config = uvicorn.Config(  # pylint: disable=redefined-outer-name
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
        self.server_task = asyncio.create_task(serve_coro, name="api-server-serve")
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
        if self._running and self._webhook_ingress_listener is not None:
            await self._webhook_ingress_listener.start()

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
        """Stop the webhook ingress listener before the Unix API server."""
        if self._webhook_ingress_listener is not None:
            await self._webhook_ingress_listener.stop()

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

    def _start_metrics_task(self) -> None:
        """Start periodic API server metrics logging."""
        if self._metrics_task and not self._metrics_task.done():
            return
        coro = self._metrics_loop()
        if self.task_registry:
            self._metrics_task = self.task_registry.spawn(coro, name="api-metrics")
        else:
            self._metrics_task = asyncio.create_task(coro, name="api-metrics")

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
