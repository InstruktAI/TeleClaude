"""MCP server for TeleClaude multi-computer communication."""

import asyncio
import json
import os
import types
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, TypedDict, cast

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from instrukt_ai_logging import get_logger
from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, TextContent, Tool

from teleclaude.config import config
from teleclaude.constants import MCP_SOCKET_PATH, ResultStatus
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata, RunAgentCommandArgs, StartSessionArgs
from teleclaude.core.session_listeners import register_listener
from teleclaude.mcp.handlers import MCPHandlersMixin
from teleclaude.mcp.protocol import McpMethod
from teleclaude.mcp.tool_definitions import get_tool_definitions
from teleclaude.mcp.types import MCPHealthSnapshot, RemoteRequestError

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

MCP_SOCKET_BACKLOG = int(os.getenv("MCP_SOCKET_BACKLOG", "256"))
MCP_SESSION_DATA_MAX_CHARS = int(os.getenv("MCP_SESSION_DATA_MAX_CHARS", "48000"))
MCP_HANDSHAKE_TIMEOUT_S = float(os.getenv("MCP_HANDSHAKE_TIMEOUT_S", "0.0"))
MCP_CONNECTION_SHUTDOWN_TIMEOUT_S = float(os.getenv("MCP_CONNECTION_SHUTDOWN_TIMEOUT_S", "2.0"))
MCP_TOOLS_CHANGED_WINDOW_S = float(os.getenv("MCP_TOOLS_CHANGED_WINDOW_S", "30.0"))


class ToolName(str, Enum):
    HELP = "teleclaude__help"
    GET_CONTEXT = "teleclaude__get_context"
    LIST_COMPUTERS = "teleclaude__list_computers"
    LIST_PROJECTS = "teleclaude__list_projects"
    LIST_SESSIONS = "teleclaude__list_sessions"
    START_SESSION = "teleclaude__start_session"
    SEND_MESSAGE = "teleclaude__send_message"
    RUN_AGENT_COMMAND = "teleclaude__run_agent_command"
    GET_SESSION_DATA = "teleclaude__get_session_data"
    DEPLOY = "teleclaude__deploy"
    SEND_FILE = "teleclaude__send_file"
    SEND_RESULT = "teleclaude__send_result"
    STOP_NOTIFICATIONS = "teleclaude__stop_notifications"
    END_SESSION = "teleclaude__end_session"
    NEXT_PREPARE = "teleclaude__next_prepare"
    NEXT_WORK = "teleclaude__next_work"
    NEXT_MAINTAIN = "teleclaude__next_maintain"
    MARK_PHASE = "teleclaude__mark_phase"
    SET_DEPENDENCIES = "teleclaude__set_dependencies"
    MARK_AGENT_STATUS = "teleclaude__mark_agent_status"
    MARK_AGENT_UNAVAILABLE = "teleclaude__mark_agent_unavailable"


# State file for tracking MCP tool signatures across restarts
_STATE_FILE_PATH = Path(__file__).parent.parent / ".state.json"
_MCP_TOOLS_KEY = "mcp-tools"


class ToolSignature(TypedDict):
    """Schema for tool signature used in change detection."""

    name: str
    inputSchema: dict[str, object]  # guard: loose-dict - JSON Schema is inherently unstructured


def _load_state_file() -> dict[str, object]:  # guard: loose-dict - Extensible state file for future use
    """Load state from .state.json file."""
    try:
        if _STATE_FILE_PATH.exists():
            return json.loads(_STATE_FILE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load state file: %s", e)
    return {}


def _save_state_file(state: dict[str, object]) -> None:  # guard: loose-dict - Extensible state file for future use
    """Save state to .state.json file."""
    try:
        _STATE_FILE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to save state file: %s", e)


def _extract_tool_signatures(tools: list[Tool]) -> list[ToolSignature]:
    """Extract tool signatures (name + inputSchema) for comparison.

    Only these fields affect API compatibility - description changes are ignored.
    """
    signatures: list[ToolSignature] = []
    for tool in sorted(tools, key=lambda t: t.name):
        signatures.append(ToolSignature(name=tool.name, inputSchema=tool.inputSchema))
    return signatures


def _tools_changed(previous: list[ToolSignature], current: list[ToolSignature]) -> bool:
    """Check if tool signatures have changed."""
    return json.dumps(previous, sort_keys=True) != json.dumps(current, sort_keys=True)


def _is_client_disconnect_exception(exc: BaseException) -> bool:
    """Return True if the exception indicates the client went away."""
    if isinstance(exc, ExceptionGroup):
        return all(_is_client_disconnect_exception(inner) for inner in exc.exceptions)
    return isinstance(
        exc,
        (
            ConnectionResetError,
            BrokenPipeError,
            anyio.ClosedResourceError,
            anyio.EndOfStream,
        ),
    )


class TeleClaudeMCPServer(MCPHandlersMixin):
    """MCP server for exposing TeleClaude functionality to AI Agent.

    Uses AdapterClient for all AI-to-AI communication via transport adapters.
    Inherits all teleclaude__* handlers from MCPHandlersMixin.
    """

    def __init__(
        self,
        adapter_client: "AdapterClient",
        tmux_bridge: types.ModuleType,
    ):
        # config already imported

        self.client = adapter_client
        self.tmux_bridge = tmux_bridge

        self.computer_name = config.computer.name
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._server: asyncio.AbstractServer | None = None
        self._connection_tasks: set[asyncio.Task[None]] = set()
        self._active_connections = 0
        self._last_accept_at: float | None = None

        # MCP tool change detection for list_changed notifications
        self._mcp_tools_changed = False
        self._mcp_tools_changed_until: float = 0.0
        self._init_tool_change_detection()

    def _track_background_task(self, task: asyncio.Task[None], label: str) -> None:
        """Keep background tasks alive and log failures."""
        self._background_tasks.add(task)

        def _on_done(done: asyncio.Task[None]) -> None:
            self._background_tasks.discard(done)
            try:
                exc = done.exception()
            except asyncio.CancelledError:
                return
            if exc:
                logger.error("Background task failed (%s): %s", label, exc, exc_info=exc)

        task.add_done_callback(_on_done)

    def _track_connection_task(self, task: asyncio.Task[None]) -> None:
        """Track active MCP client connection tasks."""
        self._connection_tasks.add(task)
        self._active_connections += 1
        self._last_accept_at = asyncio.get_running_loop().time()

        def _on_done(done: asyncio.Task[None]) -> None:
            self._connection_tasks.discard(done)
            self._active_connections = max(0, self._active_connections - 1)

        task.add_done_callback(_on_done)

    def _is_local_computer(self, computer: str) -> bool:
        """Check if the target computer refers to the local machine.

        Args:
            computer: Target computer name (or "local"/self.computer_name)

        Returns:
            True if computer refers to local machine
        """
        return computer in ("local", self.computer_name)

    async def _send_remote_request(
        self,
        computer: str,
        command: str,
        timeout: float = 3.0,
        session_id: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> dict[str, object]:  # guard: loose-dict - MCP envelope structure varies by response type
        """Send request to remote computer and return parsed response envelope.

        Args:
            computer: Target computer name
            command: Command to send
            timeout: Response timeout in seconds
            session_id: Optional session ID for the request
            metadata: Optional message metadata

        Returns:
            Parsed response envelope dict with status and data

        Raises:
            RemoteRequestError: On timeout, JSON error, or remote error response
        """
        message_id = await self.client.send_request(
            computer_name=computer,
            command=command,
            session_id=session_id,
            metadata=metadata or MessageMetadata(),
        )

        try:
            response_data = await self.client.read_response(message_id, timeout=timeout, target_computer=computer)
            envelope = json.loads(response_data.strip())

            if envelope.get("status") == ResultStatus.ERROR.value:
                error_msg = envelope.get("error", "Unknown error")
                raise RemoteRequestError(f"Remote error: {error_msg}")

            return cast(dict[str, object], envelope)  # guard: loose-dict - MCP envelope structure

        except TimeoutError as e:
            raise RemoteRequestError(f"Timeout waiting for response from {computer}") from e
        except json.JSONDecodeError as e:
            raise RemoteRequestError(f"Invalid JSON response from {computer}") from e

    async def _register_listener_if_present(self, target_session_id: str, caller_session_id: str | None = None) -> None:
        """Register caller as listener for target session's stop event when available.

        Called on any contact with a session (start, send_message, get_session_data)
        so observers who tap in later also receive stop notifications.

        Args:
            target_session_id: The session to listen to
            caller_session_id: The caller's session ID (required for listener registration)
        """
        if not caller_session_id:
            logger.debug(
                "Listener register skipped: missing caller_session_id (target=%s)",
                target_session_id[:8],
            )
            return

        # Prevent self-subscription (would cause notification loops)
        if target_session_id == caller_session_id:
            logger.debug(
                "Listener register skipped: caller equals target (session=%s)",
                target_session_id[:8],
            )
            return

        try:
            caller_session = await db.get_session(caller_session_id)
            if caller_session:
                logger.info(
                    "Listener register attempt: caller=%s target=%s tmux=%s",
                    caller_session_id[:8],
                    target_session_id[:8],
                    caller_session.tmux_session_name,
                )
                register_listener(
                    target_session_id=target_session_id,
                    caller_session_id=caller_session_id,
                    caller_tmux_session=caller_session.tmux_session_name,
                )
            else:
                logger.warning(
                    "Listener register skipped: caller session not found (caller=%s target=%s)",
                    caller_session_id[:8],
                    target_session_id[:8],
                )
        except RuntimeError:
            # Database not initialized (e.g., in tests)
            pass

    def _init_tool_change_detection(self) -> None:
        """Initialize tool change detection by comparing current tools with previous state.

        Sets _mcp_tools_changed flag if tools have changed since last daemon run.
        The flag expires after MCP_TOOLS_CHANGED_WINDOW_S seconds.
        """
        import time

        # Get current tool signatures
        current_tools = self._get_tool_definitions()
        current_signatures = _extract_tool_signatures(current_tools)

        # Load previous state
        state = _load_state_file()
        previous_signatures: list[ToolSignature] = []
        mcp_tools_state = state.get(_MCP_TOOLS_KEY)
        if isinstance(mcp_tools_state, list):
            previous_signatures = cast(list[ToolSignature], mcp_tools_state)

        # Compare and set flag
        if previous_signatures and _tools_changed(previous_signatures, current_signatures):
            self._mcp_tools_changed = True
            self._mcp_tools_changed_until = time.time() + MCP_TOOLS_CHANGED_WINDOW_S
            logger.info("MCP tools changed since last run, will notify reconnecting clients")
        else:
            self._mcp_tools_changed = False
            self._mcp_tools_changed_until = 0.0

        # Save current state
        state[_MCP_TOOLS_KEY] = current_signatures
        _save_state_file(state)

    def _should_emit_tools_changed(self) -> bool:
        """Check if tools/list_changed notification should be emitted."""
        import time

        if not self._mcp_tools_changed:
            return False
        if time.time() > self._mcp_tools_changed_until:
            self._mcp_tools_changed = False
            return False
        return True

    @staticmethod
    def _str_arg(
        args: dict[str, object] | None,  # guard: loose-dict - MCP arguments
        key: str,
        default: str = "",
    ) -> str:
        """Extract string argument from MCP tool arguments."""
        if not args:
            return default
        value = args.get(key, default)
        return str(value) if value is not None else default

    @staticmethod
    def _json_response(data: object) -> list[TextContent]:
        """Create JSON TextContent response for MCP tool."""
        return [TextContent(type="text", text=json.dumps(data, default=str))]

    def _get_tool_definitions(self) -> list[Tool]:
        """Get the list of MCP tool definitions.

        Returns the same tools that are registered via _setup_tools.
        Delegates to teleclaude.mcp.tool_definitions module.
        """
        return get_tool_definitions()

    def _setup_tools(self, server: Server) -> None:
        """Register MCP tools with the server."""
        tools = self._get_tool_definitions()

        @server.list_tools()  # type: ignore[untyped-decorator]  # MCP decorators use Callable[...] - see issue #1822
        async def list_tools() -> list[Tool]:  # pyright: ignore[reportUnusedFunction]
            """List available MCP tools."""
            return tools

        @server.call_tool()  # type: ignore[untyped-decorator]  # MCP decorators use Callable[...] - see issue #1822
        async def call_tool(  # pyright: ignore[reportUnusedFunction]
            name: str,
            arguments: dict[str, object],  # guard: loose-dict - MCP protocol boundary, typed per-tool in Group 5
        ) -> list[TextContent]:
            """Handle tool calls.

            Context variables (injected by mcp-wrapper.py):
            - caller_session_id: Required calling session ID for notifications/prefixes

            These are extracted once here and passed to handlers that need them,
            keeping context handling centralized.
            """
            # Extract context (injected by wrapper) - handlers don't need to parse this
            caller_session_id = str(arguments.pop("caller_session_id")) if arguments.get("caller_session_id") else None

            logger.debug("MCP tool call", tool=name, caller=caller_session_id)

            async def _handle_help() -> list[TextContent]:
                text = (
                    "TeleClaude MCP Server\n"
                    "\n"
                    "Local helper scripts:\n"
                    "- `bin/send_telegram.py`: ops-only Telegram sender (uses `TELEGRAM_ALERT_USERNAME`).\n"
                )
                return [TextContent(type="text", text=text)]

            async def _handle_get_context() -> list[TextContent]:
                areas_obj = arguments.get("areas") if arguments else None
                areas: list[str] | None = None
                if isinstance(areas_obj, list):
                    areas = [a for a in areas_obj if isinstance(a, str)]

                snippet_ids_obj = arguments.get("snippet_ids") if arguments else None
                snippet_ids: list[str] | None = None
                if isinstance(snippet_ids_obj, list):
                    snippet_ids = [s for s in snippet_ids_obj if isinstance(s, str)]

                domains_obj = arguments.get("domains") if arguments else None
                domains: list[str] | None = None
                if isinstance(domains_obj, list):
                    domains = [d for d in domains_obj if isinstance(d, str)]

                baseline_only = bool(arguments.get("baseline_only")) if arguments else False
                include_third_party = bool(arguments.get("include_third_party")) if arguments else False
                project_root = self._str_arg(arguments, "project_root") or None
                cwd = self._str_arg(arguments, "cwd") or None
                text = await self.teleclaude__get_context(
                    areas=areas,
                    snippet_ids=snippet_ids,
                    baseline_only=baseline_only,
                    include_third_party=include_third_party,
                    domains=domains,
                    project_root=project_root,
                    cwd=cwd,
                    caller_session_id=caller_session_id,
                )
                return [TextContent(type="text", text=text)]

            async def _handle_list_computers() -> list[TextContent]:
                return self._json_response(await self.teleclaude__list_computers())

            async def _handle_list_projects() -> list[TextContent]:
                return self._json_response(await self.teleclaude__list_projects(self._str_arg(arguments, "computer")))

            async def _handle_list_sessions() -> list[TextContent]:
                computer_obj = arguments.get("computer", "local") if arguments else "local"
                computer: str | None = None if computer_obj is None else str(computer_obj)
                return self._json_response(await self.teleclaude__list_sessions(computer, caller_session_id))

            async def _handle_start_session() -> list[TextContent]:
                args = StartSessionArgs.from_mcp(arguments or {}, caller_session_id)
                return self._json_response(await self.teleclaude__start_session(**args.__dict__))

            async def _handle_send_message() -> list[TextContent]:
                chunks = [
                    chunk
                    async for chunk in self.teleclaude__send_message(
                        self._str_arg(arguments, "computer"),
                        self._str_arg(arguments, "session_id"),
                        self._str_arg(arguments, "message"),
                        caller_session_id,
                    )
                ]
                return [TextContent(type="text", text="".join(chunks))]

            async def _handle_run_agent_command() -> list[TextContent]:
                args = RunAgentCommandArgs.from_mcp(arguments or {}, caller_session_id)
                return self._json_response(await self.teleclaude__run_agent_command(**args.__dict__))

            async def _handle_get_session_data() -> list[TextContent]:
                since = self._str_arg(arguments, "since_timestamp") or None
                until = self._str_arg(arguments, "until_timestamp") or None
                tail_obj = arguments.get("tail_chars") if arguments else None
                tail = int(tail_obj) if isinstance(tail_obj, (int, str)) else 2000
                return self._json_response(
                    await self.teleclaude__get_session_data(
                        self._str_arg(arguments, "computer"),
                        self._str_arg(arguments, "session_id"),
                        since,
                        until,
                        tail,
                        caller_session_id,
                    )
                )

            async def _handle_deploy() -> list[TextContent]:
                computers_obj = arguments.get("computers") if arguments else None
                targets = [c for c in computers_obj if isinstance(c, str)] if isinstance(computers_obj, list) else None
                return self._json_response(await self.teleclaude__deploy(targets))

            async def _handle_send_file() -> list[TextContent]:
                caption = self._str_arg(arguments, "caption") or None
                return [
                    TextContent(
                        type="text",
                        text=await self.teleclaude__send_file(
                            self._str_arg(arguments, "session_id"), self._str_arg(arguments, "file_path"), caption
                        ),
                    )
                ]

            async def _handle_send_result() -> list[TextContent]:
                return self._json_response(
                    await self.teleclaude__send_result(
                        self._str_arg(arguments, "session_id"),
                        self._str_arg(arguments, "content"),
                        self._str_arg(arguments, "output_format", "markdown"),
                    )
                )

            async def _handle_stop_notifications() -> list[TextContent]:
                return self._json_response(
                    await self.teleclaude__stop_notifications(
                        self._str_arg(arguments, "computer"),
                        self._str_arg(arguments, "session_id"),
                        caller_session_id,
                    )
                )

            async def _handle_end_session() -> list[TextContent]:
                return self._json_response(
                    await self.teleclaude__end_session(
                        self._str_arg(arguments, "computer"), self._str_arg(arguments, "session_id")
                    )
                )

            async def _handle_next_prepare() -> list[TextContent]:
                slug = self._str_arg(arguments, "slug") or None
                cwd = self._str_arg(arguments, "cwd") or None
                hitl = cast(bool, arguments.get("hitl", True)) if arguments else True
                return [TextContent(type="text", text=await self.teleclaude__next_prepare(slug, cwd, hitl))]

            async def _handle_next_work() -> list[TextContent]:
                slug = self._str_arg(arguments, "slug") or None
                cwd = self._str_arg(arguments, "cwd") or None
                logger.debug("next_work request", slug=slug, cwd=cwd)
                return [TextContent(type="text", text=await self.teleclaude__next_work(slug, cwd))]

            async def _handle_next_maintain() -> list[TextContent]:
                cwd = self._str_arg(arguments, "cwd") or None
                return [TextContent(type="text", text=await self.teleclaude__next_maintain(cwd))]

            async def _handle_mark_phase() -> list[TextContent]:
                cwd = self._str_arg(arguments, "cwd") or None
                return [
                    TextContent(
                        type="text",
                        text=await self.teleclaude__mark_phase(
                            self._str_arg(arguments, "slug"),
                            self._str_arg(arguments, "phase"),
                            self._str_arg(arguments, "status"),
                            cwd,
                        ),
                    )
                ]

            async def _handle_set_dependencies() -> list[TextContent]:
                after_raw = arguments.get("after", []) if arguments else []
                after = [str(a) for a in after_raw] if isinstance(after_raw, list) else []
                cwd = self._str_arg(arguments, "cwd") or None
                return [
                    TextContent(
                        type="text",
                        text=await self.teleclaude__set_dependencies(self._str_arg(arguments, "slug"), after, cwd),
                    )
                ]

            async def _handle_mark_agent_status() -> list[TextContent]:
                until = self._str_arg(arguments, "unavailable_until") or None
                clear = bool(arguments.get("clear")) if arguments else False
                status = self._str_arg(arguments, "status") or None
                return [
                    TextContent(
                        type="text",
                        text=await self.teleclaude__mark_agent_status(
                            self._str_arg(arguments, "agent"),
                            self._str_arg(arguments, "reason") or None,
                            until,
                            clear,
                            status,
                        ),
                    )
                ]

            tool_handlers: dict[ToolName, Callable[[], Awaitable[list[TextContent]]]] = {
                ToolName.HELP: _handle_help,
                ToolName.GET_CONTEXT: _handle_get_context,
                ToolName.LIST_COMPUTERS: _handle_list_computers,
                ToolName.LIST_PROJECTS: _handle_list_projects,
                ToolName.LIST_SESSIONS: _handle_list_sessions,
                ToolName.START_SESSION: _handle_start_session,
                ToolName.SEND_MESSAGE: _handle_send_message,
                ToolName.RUN_AGENT_COMMAND: _handle_run_agent_command,
                ToolName.GET_SESSION_DATA: _handle_get_session_data,
                ToolName.DEPLOY: _handle_deploy,
                ToolName.SEND_FILE: _handle_send_file,
                ToolName.SEND_RESULT: _handle_send_result,
                ToolName.STOP_NOTIFICATIONS: _handle_stop_notifications,
                ToolName.END_SESSION: _handle_end_session,
                ToolName.NEXT_PREPARE: _handle_next_prepare,
                ToolName.NEXT_WORK: _handle_next_work,
                ToolName.NEXT_MAINTAIN: _handle_next_maintain,
                ToolName.MARK_PHASE: _handle_mark_phase,
                ToolName.SET_DEPENDENCIES: _handle_set_dependencies,
                ToolName.MARK_AGENT_STATUS: _handle_mark_agent_status,
                ToolName.MARK_AGENT_UNAVAILABLE: _handle_mark_agent_status,
            }

            try:
                tool_name = ToolName(name)
            except ValueError as exc:
                raise ValueError(f"Unknown tool: {name}") from exc
            handler = tool_handlers.get(tool_name)
            if not handler:
                raise ValueError(f"Unknown tool: {name}")
            return await handler()

    async def start(self) -> None:
        """Start MCP server on Unix socket."""
        socket_path_str = os.path.expandvars(MCP_SOCKET_PATH)
        socket_path = Path(socket_path_str)

        # Remove existing socket file if present
        if socket_path.exists():
            socket_path.unlink()

        logger.info("MCP server listening on socket: %s", socket_path)

        # Create Unix socket server
        server = await asyncio.start_unix_server(
            self._handle_socket_connection,
            path=str(socket_path),
            backlog=MCP_SOCKET_BACKLOG,
        )
        self._server = server

        # Make socket accessible (owner only)
        socket_path.chmod(0o600)

        try:
            async with server:
                await server.serve_forever()
        finally:
            self._server = None

    async def stop(self) -> None:
        """Stop MCP server listener if running."""
        server = self._server
        if not server:
            return
        server.close()
        await server.wait_closed()
        self._server = None

        if not self._connection_tasks:
            return

        for task in list(self._connection_tasks):
            task.cancel()
        done, pending = await asyncio.wait(
            self._connection_tasks,
            timeout=MCP_CONNECTION_SHUTDOWN_TIMEOUT_S,
        )
        if pending:
            logger.warning(
                "Timed out stopping %d MCP connection task(s)",
                len(pending),
            )
        self._connection_tasks.difference_update(done)

    async def health_snapshot(self, socket_path: Path) -> MCPHealthSnapshot:
        """Return a health snapshot for MCP server diagnostics."""
        server = self._server
        server_present = server is not None
        is_serving = bool(server_present and server and server.is_serving())
        socket_exists = socket_path.exists()
        last_accept_age = None
        if self._last_accept_at is not None:
            last_accept_age = max(0.0, asyncio.get_running_loop().time() - self._last_accept_at)
        return MCPHealthSnapshot(
            server_present=server_present,
            is_serving=is_serving,
            socket_exists=socket_exists,
            active_connections=self._active_connections,
            last_accept_age_s=last_accept_age,
        )

    async def _handle_socket_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle a single MCP client connection over Unix socket."""
        logger.debug("New MCP client connected")
        task = asyncio.current_task()
        if task:
            self._track_connection_task(task)
        try:
            first_message: JSONRPCMessage | None = None
            if MCP_HANDSHAKE_TIMEOUT_S > 0:
                try:
                    first_line = await asyncio.wait_for(reader.readline(), timeout=MCP_HANDSHAKE_TIMEOUT_S)
                except asyncio.TimeoutError:
                    logger.debug("MCP client handshake timed out")
                    return

                if not first_line:
                    return

                try:
                    first_message = JSONRPCMessage.model_validate_json(first_line.decode("utf-8"))
                except Exception as exc:
                    logger.warning("MCP client sent invalid JSON: %s", exc)
                    return

            # Create FRESH server instance for this connection
            # This ensures clean state (no stale initialization)
            server = Server("teleclaude")
            self._setup_tools(server)

            # Create memory streams like stdio_server does
            read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]
            read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
            write_stream: MemoryObjectSendStream[SessionMessage]
            write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

            read_stream_writer, read_stream = cast(
                tuple[
                    MemoryObjectSendStream[SessionMessage | Exception],
                    MemoryObjectReceiveStream[SessionMessage | Exception],
                ],
                anyio.create_memory_object_stream(0),
            )
            write_stream, write_stream_reader = cast(
                tuple[
                    MemoryObjectSendStream[SessionMessage],
                    MemoryObjectReceiveStream[SessionMessage],
                ],
                anyio.create_memory_object_stream(0),
            )

            async def socket_reader() -> None:
                """Read from socket and parse JSON-RPC messages."""
                try:
                    async with read_stream_writer:
                        if first_message is not None:
                            await read_stream_writer.send(SessionMessage(first_message))
                        while True:
                            line = await reader.readline()
                            if not line:
                                break
                            try:
                                message = JSONRPCMessage.model_validate_json(line.decode("utf-8"))
                                dump = message.model_dump()
                                method = dump.get("method")
                                if method != McpMethod.NOTIFICATIONS_INITIALIZED.value:
                                    logger.trace(
                                        "MCP reader received: method=%s id=%s",
                                        method,
                                        dump.get("id"),
                                    )
                                await read_stream_writer.send(SessionMessage(message))

                                # Emit tools/list_changed after handshake if tools changed
                                if (
                                    method == McpMethod.NOTIFICATIONS_INITIALIZED.value
                                    and self._should_emit_tools_changed()
                                ):
                                    notification = '{"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}\n'
                                    writer.write(notification.encode("utf-8"))
                                    await writer.drain()
                                    logger.info("Emitted notifications/tools/list_changed to reconnecting client")
                            except Exception as exc:
                                await read_stream_writer.send(exc)
                except anyio.ClosedResourceError:
                    pass

            async def socket_writer() -> None:
                """Write JSON-RPC messages to socket."""
                try:
                    async with write_stream_reader:
                        async for session_message in write_stream_reader:
                            json_str = session_message.message.model_dump_json(by_alias=True, exclude_none=True)
                            writer.write((json_str + "\n").encode("utf-8"))
                            await writer.drain()
                except anyio.ClosedResourceError:
                    pass

            # Run socket I/O and MCP server concurrently
            async with anyio.create_task_group() as tg:
                tg.start_soon(socket_reader)
                tg.start_soon(socket_writer)
                try:
                    await server.run(
                        read_stream,
                        write_stream,
                        server.create_initialization_options(
                            notification_options=NotificationOptions(tools_changed=True)
                        ),
                    )
                except (
                    anyio.ClosedResourceError,
                    anyio.EndOfStream,
                    ConnectionResetError,
                    BrokenPipeError,
                ):
                    logger.debug("MCP client disconnected (stream closed)")
                except Exception as e:
                    if _is_client_disconnect_exception(e):
                        logger.debug("MCP client disconnected (task group closed)")
                    else:
                        logger.warning("MCP server session ended with error: %s", e)

        except Exception:
            logger.exception("Error handling MCP connection")
        finally:
            writer.close()
            await writer.wait_closed()
            logger.debug("MCP client disconnected")
