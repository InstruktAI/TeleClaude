"""HTTP client for telec TUI."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import threading
import time
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field, replace
from http import HTTPMethod
from typing import TYPE_CHECKING, Any, Unpack
from urllib.parse import urlencode

import httpx
from instrukt_ai_logging import get_logger
from pydantic import TypeAdapter, ValidationError
from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.sync.client import ClientConnection, unix_connect

from teleclaude.api.ws_options import WS_FLAG_FALSE, WS_FLAG_TRUE, WS_INCLUDE_REMOVED_PARAM, WS_STREAM_PARAM, WsStream
from teleclaude.api_models import (
    ComputerDTO,
    CreateSessionResponseDTO,
    JobDTO,
    ProjectDTO,
    RunSessionRequest,
    SessionDTO,
    TuiBootstrapDTO,
    TuiBootstrapPillar,
)
from teleclaude.api_models_operations import OperationStatusDTO
from teleclaude.api_session_actions_models import AgentRestartResponseDTO
from teleclaude.caller_identity import CarriedIdentity
from teleclaude.cli.api_client_health import TelecHealthAPI
from teleclaude.cli.api_client_identity import TelecIdentityAPI
from teleclaude.cli.api_client_request import JsonBody, RequestOptions
from teleclaude.cli.api_client_runtime import TelecRuntimeAPI
from teleclaude.cli.api_session_args import CreateSessionArgs, RunSessionArgs
from teleclaude.cli.clearance import ClearanceScope, clearance_scope_refusal, refresh_cli_identity_role
from teleclaude.cli.models import WsEvent
from teleclaude.cli.session_auth import ResolvedCliIdentity
from teleclaude.cli.telec.addressing import addressed_computer, remote_computer
from teleclaude.cli.tool_client import (
    NotAcceptedCause,
    exit_not_accepted,
    is_shutdown_refusal,
    shutdown_refusal_message,
)
from teleclaude.cli.tui_clearance import clear_tui_bootstrap_pillars
from teleclaude.constants import API_SOCKET_PATH, SYSTEM_DAEMON_PRINCIPAL
from teleclaude.core.command_input import CommandInputMode
from teleclaude.core.daemon_lifecycle_identity import daemon_credential_headers
from teleclaude.core.operation_caller_identity import get_caller_session_id
from teleclaude.core.session_identity_facts import read_session_identity_facts
from teleclaude.history.search_payload import HistorySearchPayload
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.types.creation_record import EntryPoint

if TYPE_CHECKING:
    from teleclaude.history.service import HistoryDetailPayload

logger = get_logger(__name__)

BASE_URL = "http://localhost"
WS_URI = "ws://localhost/ws"
_ALL_SESSIONS_PARAM = "all"
_CLOSED_SESSIONS_PARAM, _SESSION_ID_PARAM = "closed", "id"
_QUERY_TRUE = "true"
_HISTORY_SHOW_PATH_TEMPLATE = "/history/show/{session_id}"
_HISTORY_AGENT_PARAM = "agent"
_HISTORY_THINKING_PARAM = "thinking"
_HISTORY_RAW_PARAM = "raw"
_COMPUTER_PARAM = "computer"
_PROJECTS_ROUTE = "/projects"
_PROJECT_PATH_FIELD = "path"
_MESSAGE_FIELD = "message"
_DIRECT_FIELD = "direct"
_CLOSE_LINK_FIELD = "close_link"
_SESSIONS_SEND_COMMAND = "sessions send"
_SESSIONS_LIST_COMMAND = "sessions list"
_TODO_LIST_COMMAND = "todo list"
_WS_QUERY_SEPARATOR = "?"
_WS_CONNECTED_LOG = "WebSocket connected, streams: %s"
_PROJECT_ADOPT_COMMAND = "telec config project adopt"
_IDENTITY_MODES_EXCLUSIVE_MESSAGE = "daemon_credential and system_principal are mutually exclusive"
_PROJECT_ADOPT_CLEARANCE = ClearanceScope.verb(_PROJECT_ADOPT_COMMAND)
_HTTP_POST = HTTPMethod.POST

# Reconnection settings
WS_INITIAL_BACKOFF = 0.5  # Initial reconnect delay in seconds
WS_MAX_BACKOFF = 5.0  # Maximum reconnect delay for local unix-socket reconnects
WS_BACKOFF_MULTIPLIER = 2.0  # Exponential backoff multiplier
API_CONNECT_RETRY_DELAYS_S = (0.1, 0.3, 0.6)

__all__ = ["APIError", "TelecAPIClient"]

WS_OPERATION_ERRORS = (OSError, RuntimeError, WebSocketException)
REQUEST_WRAP_ERRORS = (OSError, RuntimeError, TypeError, ValueError)


def _with_addressed_computer(
    params: dict[str, str] | list[tuple[str, str]] | None,
) -> dict[str, str] | list[tuple[str, str]] | None:
    """The query parameters with the computer this invocation addresses, so the daemon carries the request there."""
    computer = addressed_computer()
    if computer is None:
        return params
    pairs = list(params.items()) if isinstance(params, dict) else list(params or [])
    if all(name != _COMPUTER_PARAM for name, _ in pairs):
        pairs.append((_COMPUTER_PARAM, computer))
    return pairs


def _computer_params(computer: str | None) -> dict[str, str] | None:
    """The query parameter that addresses a request to a computer, when that is another computer."""
    owner = remote_computer(computer)
    return {_COMPUTER_PARAM: owner} if owner is not None else None


def _addressed_options(options: RequestOptions) -> RequestOptions:
    """Use the same effective destination for request clearance and transmission."""
    params = _with_addressed_computer(options.params)
    pairs = list(params.items()) if isinstance(params, dict) else list(params or [])
    computer = next((value for name, value in pairs if name == _COMPUTER_PARAM), None)
    scope = options.clearance_scope
    return replace(
        options,
        params=params,
        clearance_scope=replace(scope, target_computer=computer if computer is not None else scope.target_computer),
    )


@dataclass
class _HTTPState:
    """Mutable HTTP client state."""

    client: httpx.AsyncClient | None = None
    last_connect_error_log: float | None = None
    identity_headers: dict[str, str] = field(default_factory=dict)
    clearance_identity: ResolvedCliIdentity | None = None


@dataclass
class _WebSocketState:
    """Mutable WebSocket client state."""

    ws: ClientConnection | None = None
    thread: threading.Thread | None = None
    running: bool = False
    include_removed: bool = False
    subscriptions: set[WsStream] = field(default_factory=set)
    callback: Callable[[WsEvent], None] | None = None
    on_connect: Callable[[], None] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class APIError(Exception):
    """API request failed with structured error info."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        detail: str | None = None,
        *,
        not_accepted_cause: NotAcceptedCause | None = None,
        work_feedback: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or message  # Fallback to full message if no detail
        self.not_accepted_cause = not_accepted_cause
        self.work_feedback = work_feedback

    def exit_if_not_accepted(self) -> None:
        """Exit with the not-accepted message when this failure was a refusal or an unreachable daemon."""
        if self.not_accepted_cause is not None:
            exit_not_accepted(self.not_accepted_cause)


class _TelecConnectionClient:
    """Async HTTP client for telec with WebSocket push support."""

    def __init__(
        self,
        socket_path: str = API_SOCKET_PATH,
        *,
        daemon_credential: bool = False,
        system_principal: bool = False,
    ):
        """Initialize client.

        Args:
            socket_path: Path to Unix socket
            daemon_credential: When True, identity headers carry the daemon's
                own process-local credential — the mode the daemon uses for
                the calls it makes into its own request surface. The credential
                resolves only inside the daemon's own interpreter.
            system_principal: When True, identity headers carry the platform's
                system principal with no session or role — the mode a platform
                process outside the daemon uses, because the daemon credential
                does not resolve across interpreters.

        Raises:
            ValueError: If both identity modes are requested.
        """
        if daemon_credential and system_principal:
            raise ValueError(_IDENTITY_MODES_EXCLUSIVE_MESSAGE)
        self.socket_path = socket_path
        self._daemon_credential = daemon_credential
        self._system_principal = system_principal
        self._http_state = _HTTPState()
        self._ws_state = _WebSocketState()

    @property
    def _carries_fixed_identity(self) -> bool:
        """Whether identity is a fixed platform identity rather than a resolved CLI caller."""
        return self._daemon_credential or self._system_principal

    def __getattr__(self, name: str) -> object:
        """Provide backwards-compatible access to internal state for tests."""
        http_attrs = {
            "_client": "client",
            "_identity_headers": "identity_headers",
            "_last_connect_error_log": "last_connect_error_log",
        }
        ws_attrs = {
            "_ws": "ws",
            "_ws_thread": "thread",
            "_ws_running": "running",
            "_ws_subscriptions": "subscriptions",
            "_ws_callback": "callback",
            "_ws_on_connect": "on_connect",
            "_ws_lock": "lock",
        }
        if name in http_attrs:
            return getattr(self._http_state, http_attrs[name])
        if name in ws_attrs:
            return getattr(self._ws_state, ws_attrs[name])
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")

    async def connect(self) -> None:
        """Connect to API socket."""
        transport = httpx.AsyncHTTPTransport(uds=self.socket_path)
        if not self._carries_fixed_identity:
            from teleclaude.cli.session_auth import resolve_cli_identity  # noqa: PLC0415 - capture the client caller.

            self._http_state.clearance_identity = resolve_cli_identity()
        self._http_state.identity_headers = self._build_identity_headers(self._http_state.clearance_identity)
        self._http_state.client = httpx.AsyncClient(
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
        return self._http_state.client is not None

    async def close(self) -> None:
        """Close connection."""
        self.stop_websocket()
        if self._http_state.client:
            await self._http_state.client.aclose()
            self._http_state.client = None

    # --- WebSocket Push Support ---

    def start_websocket(
        self,
        callback: Callable[[WsEvent], None],
        subscriptions: list[WsStream] | None = None,
        on_connect: Callable[[], None] | None = None,
        include_removed: bool = False,
    ) -> list[str]:
        """Start WebSocket connection for push updates.

        Runs in a background thread to avoid blocking the TUI event loop. The
        connection declares the resource streams its caller holds command
        clearance to read; the daemon projects those streams for the caller.

        Args:
            callback: Function called with (event_type, data) for each message
            subscriptions: Streams to receive (e.g., [WsStream.SESSIONS, WsStream.PREPARATION])
            include_removed: Whether to include soft-removed entries
        """
        if self._ws_state.running:
            logger.debug("WebSocket already running")
            return []

        subscription_scopes = {
            WsStream.SESSIONS: ClearanceScope.verb(_SESSIONS_LIST_COMMAND),
            WsStream.PREPARATION: ClearanceScope.verb(_TODO_LIST_COMMAND),
            WsStream.TODOS: ClearanceScope.verb(_TODO_LIST_COMMAND),
        }
        allowed_subscriptions: list[WsStream] = []
        refusals: list[str] = []
        for subscription in subscriptions or [WsStream.SESSIONS, WsStream.PREPARATION]:
            scope = subscription_scopes.get(subscription, ClearanceScope.ungoverned())
            refusal = clearance_scope_refusal(scope, self._http_state.clearance_identity)
            if refusal is None:
                allowed_subscriptions.append(subscription)
            else:
                refusals.append(refusal)
        if not allowed_subscriptions:
            return refusals

        if not self._carries_fixed_identity and self._http_state.clearance_identity is not None:
            self._http_state.identity_headers = self._build_identity_headers(
                refresh_cli_identity_role(self._http_state.clearance_identity)
            )

        self._ws_state.callback = callback
        self._ws_state.on_connect = on_connect
        self._ws_state.subscriptions = set(allowed_subscriptions)
        self._ws_state.include_removed = include_removed
        self._ws_state.running = True

        self._ws_state.thread = threading.Thread(target=self._ws_loop, daemon=True, name="ws-client")
        self._ws_state.thread.start()
        logger.info("WebSocket client thread started")
        return refusals

    def stop_websocket(self) -> None:
        """Stop WebSocket connection."""
        self._ws_state.running = False
        with self._ws_state.lock:
            if self._ws_state.ws:
                try:
                    self._ws_state.ws.close()
                except WS_OPERATION_ERRORS:
                    pass
                self._ws_state.ws = None
        if self._ws_state.thread and self._ws_state.thread.is_alive():
            self._ws_state.thread.join(timeout=2.0)
        self._ws_state.thread = None
        logger.info("WebSocket client stopped")

    @property
    def ws_connected(self) -> bool:
        """Check if WebSocket is connected."""
        with self._ws_state.lock:
            return self._ws_state.ws is not None

    def _ws_loop(self) -> None:
        """WebSocket connection loop with reconnection logic."""
        backoff = WS_INITIAL_BACKOFF

        while self._ws_state.running:
            try:
                self._ws_connect_and_run()
                # Reset backoff on successful connection
                backoff = WS_INITIAL_BACKOFF
            except ConnectionClosed:
                logger.info("WebSocket connection closed")
            except WebSocketException as e:
                logger.warning("WebSocket error: %s", e)
            except OSError as e:
                # Socket connection error (daemon not running)
                logger.debug("WebSocket connection failed: %s", e)
            except (RuntimeError, TypeError, ValueError) as e:
                logger.error("Unexpected WebSocket error: %s", e, exc_info=True)

            # Clear connection state
            with self._ws_state.lock:
                self._ws_state.ws = None

            if not self._ws_state.running:
                break

            # Wait before reconnecting (with exponential backoff)
            logger.debug("Reconnecting in %.1fs...", backoff)
            time.sleep(backoff)
            backoff = min(backoff * WS_BACKOFF_MULTIPLIER, WS_MAX_BACKOFF)

    def _ws_uri(self) -> str:
        """Build the connection URI declaring the selected streams and the include-removed option."""
        flag = WS_FLAG_TRUE if self._ws_state.include_removed else WS_FLAG_FALSE
        query = [(WS_STREAM_PARAM, stream.value) for stream in sorted(self._ws_state.subscriptions)]
        query.append((WS_INCLUDE_REMOVED_PARAM, flag))
        return WS_URI + _WS_QUERY_SEPARATOR + urlencode(query)

    def _ws_connect_and_run(self) -> None:
        """Connect to WebSocket and process messages until disconnection."""
        logger.debug("Connecting to WebSocket at %s", self.socket_path)
        identity_headers = {} if self._carries_fixed_identity else self._http_state.identity_headers
        ws = unix_connect(path=self.socket_path, uri=self._ws_uri(), additional_headers=identity_headers)

        with self._ws_state.lock:
            self._ws_state.ws = ws

        logger.info(_WS_CONNECTED_LOG, sorted(self._ws_state.subscriptions))

        if self._ws_state.on_connect:
            self._ws_state.on_connect()

        # Process incoming messages
        for message in ws:
            if not self._ws_state.running:
                break

            try:
                ws_event: WsEvent = TypeAdapter(WsEvent).validate_json(message)
                if self._ws_state.callback:
                    self._ws_state.callback(ws_event)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from WebSocket: %s", message[:100])
            except ValidationError as e:
                logger.warning("Invalid WebSocket event payload: %s", e)

    def _normalize_http_method(self, method: HTTPMethod | str) -> HTTPMethod:
        """Convert a request method into an HTTPMethod enum."""
        try:
            return HTTPMethod(method)
        except ValueError as error:
            raise APIError(f"Unsupported HTTP method: {method}") from error

    async def _request_once(
        self,
        method: HTTPMethod,
        url: str,
        timeout: float,
        request_options: RequestOptions,
        identity_headers: dict[str, str],
    ) -> httpx.Response:
        """Dispatch a single HTTP request."""
        if not self._http_state.client:
            raise APIError("Client not connected. Call connect() first.")

        request_kwargs: dict[str, Any] = {  # guard: loose-dict - HTTP request kwargs
            "params": request_options.params,
            "headers": identity_headers,
            "timeout": timeout,
        }
        if request_options.json_body is not None:
            request_kwargs["json"] = request_options.json_body
        response = await self._http_state.client.request(method.value, url, **request_kwargs)
        response.raise_for_status()
        return response

    def _log_connect_error(self, method: HTTPMethod | str, url: str, timeout: float, error: Exception) -> None:
        """Log connect errors with a debounce to avoid spam."""
        now = self._now_monotonic()
        if (
            self._http_state.last_connect_error_log is not None
            and (now - self._http_state.last_connect_error_log) < 10.0
        ):
            return

        self._http_state.last_connect_error_log = now
        logger.debug(
            "API connect failed",
            method=str(method),
            url=url,
            socket_path=self.socket_path,
            timeout=timeout,
            error=str(error),
        )

    async def _request(
        self,
        method: HTTPMethod | str,
        url: str,
        *,
        timeout: float | None = None,
        request_options: RequestOptions | None = None,
    ) -> httpx.Response:
        """Make HTTP request with error handling.

        Args:
            method: HTTP method (GET, POST, DELETE)
            url: URL path
            timeout: Optional request timeout override
            request_options: Optional request params and JSON body

        Returns:
            Response object

        Raises:
            APIError: If request fails
        """
        request_timeout = timeout if timeout is not None else 15.0
        options = _addressed_options(request_options or RequestOptions())
        method_enum = self._normalize_http_method(method)
        identity = (
            refresh_cli_identity_role(self._http_state.clearance_identity)
            if not self._carries_fixed_identity and self._http_state.clearance_identity is not None
            else self._http_state.clearance_identity
        )

        refusal = None if self._carries_fixed_identity else clearance_scope_refusal(options.clearance_scope, identity)
        if refusal is not None:
            raise APIError(refusal, work_feedback=refusal)
        identity_headers = (
            self._build_identity_headers(identity, options.clearance_scope.command_path)
            if identity is not None
            else self._http_state.identity_headers
        )

        try:
            retry_delays = (0.0, *API_CONNECT_RETRY_DELAYS_S)
            for attempt, delay in enumerate(retry_delays, start=1):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    return await self._request_once(method_enum, url, request_timeout, options, identity_headers)
                except httpx.ConnectError as error:
                    self._log_connect_error(method, url, request_timeout, error)
                    await self._wait_for_socket()
                    if attempt >= len(retry_delays):
                        raise APIError(
                            "Cannot connect to API server. Socket may be missing.",
                            not_accepted_cause=NotAcceptedCause.UNREACHABLE,
                        ) from error
        except httpx.HTTPStatusError as error:
            # Parse JSON response to extract human-friendly detail
            status_code = error.response.status_code
            detail = None
            work_feedback = None
            try:
                body = error.response.json()
                if isinstance(body, dict):
                    detail = body.get("detail")
                    raw_work_feedback = body.get("work_feedback")
                    work_feedback = raw_work_feedback if isinstance(raw_work_feedback, str) else None
            except (json.JSONDecodeError, ValueError):
                detail = error.response.text
            if is_shutdown_refusal(status_code, detail):
                refusal_message = shutdown_refusal_message()
                raise APIError(
                    refusal_message,
                    status_code=status_code,
                    detail=refusal_message,
                    not_accepted_cause=NotAcceptedCause.DRAINING,
                    work_feedback=refusal_message,
                ) from error
            raise APIError(
                f"API request failed: {status_code} {detail or error.response.text}",
                status_code=status_code,
                detail=detail,
                work_feedback=work_feedback,
            ) from error
        except httpx.TimeoutException as error:
            raise APIError("API request timed out. Server may be blocked or overloaded.") from error
        except httpx.TransportError as error:
            raise APIError("Connection to API server interrupted mid-request. Daemon may be restarting.") from error
        except REQUEST_WRAP_ERRORS as error:
            raise APIError(f"Unexpected error: {error}") from error

        raise APIError(
            "Cannot connect to API server. Socket may be missing.",
            not_accepted_cause=NotAcceptedCause.UNREACHABLE,
        )

    def _now_monotonic(self) -> float:
        """Return a monotonic timestamp for debounce logic."""
        return time.monotonic()

    def _build_identity_headers(
        self, identity: ResolvedCliIdentity | None = None, command_path: str | None = None
    ) -> dict[str, str]:
        """Build the carried caller headers from the invocation's resolved identity and the command it cleared."""
        if self._daemon_credential:
            return daemon_credential_headers()
        if self._system_principal:
            return CarriedIdentity(principal=SYSTEM_DAEMON_PRINCIPAL, entry_point=EntryPoint.AGENT.value).to_headers()

        operation_session_id = get_caller_session_id()
        if operation_session_id is not None:
            facts = read_session_identity_facts(str(MAIN_DB_PATH), operation_session_id)
            if facts is None:
                return CarriedIdentity().to_headers()
            return CarriedIdentity.from_session_facts(facts).to_headers()

        if identity is None:
            from teleclaude.cli.session_auth import (  # noqa: PLC0415 - request construction resolves edge callers.
                resolve_cli_identity,
            )

            identity = resolve_cli_identity()
        return CarriedIdentity.from_cli_identity(identity).with_command(command_path).to_headers()

    async def _wait_for_socket(self, *, timeout_s: float = 1.0) -> None:
        """Wait briefly for the API socket to appear and be connectable."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                if os.path.exists(self.socket_path):
                    mode = os.stat(self.socket_path).st_mode
                    if stat.S_ISSOCK(mode):
                        return
            except OSError:
                pass
            await asyncio.sleep(0.05)


class _TelecSessionAPI:
    """Session and daemon operations."""

    _request: Callable[..., Awaitable[httpx.Response]]
    _http_state: _HTTPState

    async def list_sessions(
        self,
        computer: str | None = None,
        *,
        include_closed: bool = False,
        all_sessions: bool = False,
        session_ids: Collection[str] | None = None,
    ) -> list[SessionDTO]:
        """List sessions from all computers or a specific computer."""
        params: list[tuple[str, str]] = [(_COMPUTER_PARAM, computer)] if computer else []
        if include_closed:
            params.append((_CLOSED_SESSIONS_PARAM, _QUERY_TRUE))
        if all_sessions:
            params.append((_ALL_SESSIONS_PARAM, _QUERY_TRUE))
        if session_ids is not None:
            params.extend((_SESSION_ID_PARAM, session_id) for session_id in session_ids)
        resp = await self._request(
            "GET",
            "/sessions",
            request_options=RequestOptions(
                params=params, clearance_scope=ClearanceScope.verb("sessions list", target_computer=computer)
            ),
        )
        return TypeAdapter(list[SessionDTO]).validate_json(resp.text)

    async def list_computers(self) -> list[ComputerDTO]:
        """List online computers only."""
        resp = await self._request(
            "GET", "/computers", request_options=RequestOptions(clearance_scope=ClearanceScope.verb("computers list"))
        )
        return TypeAdapter(list[ComputerDTO]).validate_json(resp.text)

    async def search_history(
        self,
        *,
        query: str,
        agent: str,
        limit: int,
        computer: str | None,
        include_workers: bool,
        identity: str | None,
        project: str | None,
    ) -> HistorySearchPayload:
        """Search local or peer mirrors through the daemon relay."""
        params = {
            "q": query,
            "agent": agent,
            "limit": str(limit),
            "include_workers": str(include_workers).lower(),
        }
        if computer:
            params["computer"] = computer
        if identity:
            params["identity"] = identity
        if project:
            params["project"] = project
        resp = await self._request(
            "GET",
            "/history/search",
            request_options=RequestOptions(
                params=params, clearance_scope=ClearanceScope.verb("history search", target_computer=computer)
            ),
        )
        return TypeAdapter(HistorySearchPayload).validate_json(resp.text)

    async def show_history(
        self, session_id: str, *, agent: str, thinking: bool, raw: bool, computer: str
    ) -> HistoryDetailPayload:
        """Fetch one local or peer history detail through the daemon."""
        from teleclaude.history.service import (  # noqa: PLC0415 - detail parsing is specific to history show.
            HistoryDetailPayload,
        )

        resp = await self._request(
            HTTPMethod.GET,
            _HISTORY_SHOW_PATH_TEMPLATE.format(session_id=session_id),
            request_options=RequestOptions(
                params={
                    _HISTORY_AGENT_PARAM: agent,
                    _HISTORY_THINKING_PARAM: str(thinking).lower(),
                    _HISTORY_RAW_PARAM: str(raw).lower(),
                    _COMPUTER_PARAM: computer,
                },
                clearance_scope=ClearanceScope.verb("history show", target_computer=computer),
            ),
        )
        return TypeAdapter(HistoryDetailPayload).validate_json(resp.text)

    async def list_projects(self, computer: str | None = None) -> list[ProjectDTO]:
        """List projects from all or a specific computer."""
        params: dict[str, str] = {"computer": computer} if computer else {}
        resp = await self._request(
            "GET",
            "/projects",
            request_options=RequestOptions(params=params, clearance_scope=ClearanceScope.verb("projects list")),
        )
        return TypeAdapter(list[ProjectDTO]).validate_json(resp.text)

    async def add_project(self, path: str) -> ProjectDTO:
        """Adopt a local project folder through the daemon API."""
        options = RequestOptions(json_body={_PROJECT_PATH_FIELD: path}, clearance_scope=_PROJECT_ADOPT_CLEARANCE)
        response = await self._request(_HTTP_POST, _PROJECTS_ROUTE, request_options=options)
        return ProjectDTO.model_validate_json(response.text)

    async def create_session(self, **kwargs: Unpack[CreateSessionArgs]) -> CreateSessionResponseDTO:
        """Create a new session."""
        # Session creation spawns tmux + agent, needs longer timeout
        payload: JsonBody = {
            "computer": kwargs["computer"],
            "project_path": kwargs["project_path"],
            "launch_kind": kwargs.get("launch_kind", "agent"),
            "title": kwargs.get("title"),
            "message": kwargs.get("message"),
            "metadata": kwargs.get("metadata"),
            "command_input_mode": kwargs.get("command_input_mode", CommandInputMode.ORDINARY),
            "command_input_source_text": kwargs.get("command_input_source_text"),
        }
        agent = kwargs.get("agent")
        if agent is not None:
            payload["agent"] = agent
        thinking_mode = kwargs.get("thinking_mode")
        if thinking_mode is not None:
            payload["thinking_mode"] = thinking_mode
        native_session_id = kwargs.get("native_session_id")
        if native_session_id is not None:
            payload["native_session_id"] = native_session_id
        subdir = kwargs.get("subdir")
        if subdir is not None:
            payload["subdir"] = subdir
        if kwargs.get("skip_listener_registration", False):
            payload["skip_listener_registration"] = True
        company = kwargs.get("company")
        if company is not None:
            payload["company"] = company
        clearance_scope = ClearanceScope.project_verb("sessions start", kwargs["project_path"], kwargs["computer"])
        resp = await self._request(
            "POST",
            "/sessions",
            timeout=30.0,
            request_options=RequestOptions(
                json_body=payload,
                params=_computer_params(kwargs["computer"]),
                clearance_scope=clearance_scope,
            ),
        )
        return TypeAdapter(CreateSessionResponseDTO).validate_json(resp.text)

    async def run_session(self, **kwargs: Unpack[RunSessionArgs]) -> CreateSessionResponseDTO:
        """Run a slash command in a new session (POST /sessions/run)."""
        request_data: dict[str, object] = {  # guard: loose-dict - JSON API request
            "computer": kwargs.get("computer", "local"),
            "command": kwargs["command"],
            "args": kwargs.get("args", ""),
            "project": kwargs["project_path"],
            "detach": kwargs.get("detach", False),
            "additional_context": kwargs.get("additional_context", ""),
        }
        if "thinking_mode" in kwargs:
            request_data["thinking_mode"] = kwargs["thinking_mode"]
        company = kwargs.get("company")
        if company is not None:
            request_data["company"] = company
        job = kwargs.get("job")
        if job is not None:
            request_data["job"] = job
        if kwargs.get("manually_started"):
            request_data.update(manually_started=True)
        request = RunSessionRequest.model_validate(request_data)
        if "agent" in kwargs:
            request = request.model_copy(update={"agent": kwargs["agent"]})
        clearance_scope = ClearanceScope.project_verb("sessions run", kwargs["project_path"], kwargs.get("computer"))
        resp = await self._request(
            "POST",
            "/sessions/run",
            timeout=30.0,
            request_options=RequestOptions(
                json_body=request.model_dump(exclude_unset=True),
                params=_computer_params(kwargs.get("computer")),
                clearance_scope=clearance_scope,
            ),
        )
        return TypeAdapter(CreateSessionResponseDTO).validate_json(resp.text)

    async def end_session(self, session_id: str, computer: str) -> bool:
        """End a session."""
        resp = await self._request(
            "DELETE",
            f"/sessions/{session_id}",
            request_options=RequestOptions(
                params={"computer": computer},
                clearance_scope=ClearanceScope.session_verb("sessions end", session_id, computer=computer),
            ),
        )
        return resp.status_code == 200

    async def send_message(
        self,
        session_id: str,
        computer: str,
        message: str,
        *,
        direct: bool = False,
        close_link: bool = False,
    ) -> bool:
        """Send a message to a session."""
        body: JsonBody = {_MESSAGE_FIELD: message}
        if direct:
            body[_DIRECT_FIELD] = True
        if close_link:
            body[_CLOSE_LINK_FIELD] = True
        resp = await self._request(
            "POST",
            f"/sessions/{session_id}/message",
            request_options=RequestOptions(
                params={"computer": computer},
                json_body=body,
                clearance_scope=ClearanceScope.session_verb(
                    _SESSIONS_SEND_COMMAND,
                    session_id,
                    computer=computer,
                    direct_conversation=direct or close_link,
                ),
            ),
        )
        return resp.status_code in {200, 202}

    async def send_keys(self, session_id: str, computer: str, key: str, count: int | None = None) -> bool:
        """Send a key command to a session."""
        payload: JsonBody = {"key": key}
        if count is not None:
            payload["count"] = count
        resp = await self._request(
            "POST",
            f"/sessions/{session_id}/keys",
            request_options=RequestOptions(
                params={"computer": computer},
                json_body=payload,
                clearance_scope=ClearanceScope.ungoverned(),
            ),
        )
        return resp.status_code in {200, 202}

    async def get_tui_bootstrap(
        self,
        pillars: list[TuiBootstrapPillar] | None = None,
        include_removed: bool = False,
    ) -> TuiBootstrapDTO:
        """Fetch aggregate TUI bootstrap data with partial-success semantics."""
        requested = pillars or ["computers", "projects", "sessions", "availability", "jobs", "settings", "chiptunes"]
        clearance = clear_tui_bootstrap_pillars(requested, self._http_state.clearance_identity)
        if not clearance.allowed:
            return TuiBootstrapDTO(requested=requested, errors=clearance.denied)

        params: dict[str, str] = {"pillars": ",".join(clearance.allowed)}
        if include_removed:
            params["include_removed"] = "true"

        resp = await self._request(
            "GET",
            "/tui/bootstrap",
            request_options=RequestOptions(params=params, clearance_scope=clearance.request_scope),
        )
        response = TypeAdapter(TuiBootstrapDTO).validate_json(resp.text)
        return response.model_copy(update={"requested": requested, "errors": [*response.errors, *clearance.denied]})

    async def list_jobs(self) -> list[JobDTO]:
        """List scheduled jobs."""
        resp = await self._request(
            "GET", "/jobs", request_options=RequestOptions(clearance_scope=ClearanceScope.ungoverned())
        )
        return TypeAdapter(list[JobDTO]).validate_json(resp.text)

    async def run_job(self, name: str, project: str | None = None) -> OperationStatusDTO:
        """Ask for one run of a job; the receipt's terminal outcome is the run's outcome."""
        params = {"project": project} if project else None
        resp = await self._request(
            "POST",
            f"/jobs/{name}/run",
            timeout=30.0,
            request_options=RequestOptions(params=params, clearance_scope=ClearanceScope.ungoverned()),
        )
        return TypeAdapter(OperationStatusDTO).validate_json(resp.text)

    async def agent_restart(
        self,
        session_id: str,
        computer: str | None = None,
        *,
        handoff: bool = False,
        agent: str | None = None,
    ) -> AgentRestartResponseDTO:
        """Restart or hand off the agent in a session while preserving its durable identity."""
        params = {"computer": computer} if computer else None
        resp = await self._request(
            "POST",
            f"/sessions/{session_id}/agent-restart",
            request_options=RequestOptions(
                params=params,
                json_body={"handoff": handoff, "agent": agent} if handoff else None,
                clearance_scope=ClearanceScope.session_verb("sessions restart", session_id, computer=computer),
            ),
        )
        return TypeAdapter(AgentRestartResponseDTO).validate_json(resp.text)


class TelecAPIClient(_TelecConnectionClient, _TelecSessionAPI, TelecRuntimeAPI, TelecIdentityAPI, TelecHealthAPI):
    """Public telec API client."""
