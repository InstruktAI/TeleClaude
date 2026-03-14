"""WebSocket support mixin for APIServer."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from fastapi import WebSocket, WebSocketDisconnect
from instrukt_ai_logging import get_logger

from teleclaude.api_models import (
    ProjectDTO,
    ProjectsInitialDataDTO,
    ProjectsInitialEventDTO,
    ProjectWithTodosDTO,
    RefreshDataDTO,
    RefreshEventDTO,
    SessionClosedDataDTO,
    SessionClosedEventDTO,
    SessionDTO,
    SessionsInitialDataDTO,
    SessionsInitialEventDTO,
    SessionStartedEventDTO,
    SessionUpdatedEventDTO,
    TodoDTO,
)
from teleclaude.config import config
from teleclaude.core.models import JsonDict, JsonValue, SessionSnapshot
from teleclaude.transport.redis_transport import RedisTransport

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.task_registry import TaskRegistry
    from teleclaude.events.db import EventDB

from teleclaude.api.ws_constants import (
    API_WS_CONTROL_EVENTS,
    API_WS_CONTROL_SEND_TIMEOUT_S,
    API_WS_DEFAULT_SEND_TIMEOUT_S,
    API_WS_REPLACEABLE_EVENTS,
    API_WS_REPLACEABLE_SEND_TIMEOUT_S,
    _WsClientState,
)

logger = get_logger(__name__)


class _WebSocketMixin:  # pyright: ignore[reportUnusedClass]
    """WebSocket support methods extracted from APIServer."""

    if TYPE_CHECKING:
        client: AdapterClient
        task_registry: TaskRegistry | None
        _cache: DaemonCache | None
        _ws_clients: set[WebSocket]
        _client_subscriptions: dict[WebSocket, dict[str, set[str]]]
        _ws_client_states: dict[WebSocket, _WsClientState]
        _previous_interest: dict[str, set[str]]
        _refresh_debounce_task: asyncio.Task[object] | None
        _refresh_pending_payload: JsonDict | None

        @property
        def cache(self) -> DaemonCache | None: ...

        @property
        def _event_db(self) -> EventDB | None: ...

    async def _handle_websocket(self, websocket: WebSocket) -> None:
        """Handle WebSocket connection for push updates.

        Args:
            websocket: WebSocket connection
        """
        await websocket.accept()
        self._ws_clients.add(websocket)
        self._client_subscriptions[websocket] = {}
        self._ensure_ws_client_state(websocket)
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
                        if newly_added and len(self._ws_clients) == 1:
                            self._trigger_initial_refresh()

        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
        except Exception as e:
            if self._is_expected_ws_disconnect(e):
                logger.info("WebSocket connection closed: %s", e)
            else:
                logger.error("WebSocket error: %s", e, exc_info=True)
        finally:
            await self._drop_ws_client(websocket, reason="connection-end")

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
                    # Apply role-based visibility filtering using WS connection headers
                    email = websocket.headers.get("x-web-user-email")
                    role = websocket.headers.get("x-web-user-role")
                    if email and role != "admin":
                        if role == "member":
                            cached_sessions = [
                                s for s in cached_sessions if s.human_email == email or s.visibility == "shared"
                            ]
                        else:
                            cached_sessions = [s for s in cached_sessions if s.human_email == email]
                    sessions = [SessionDTO.from_core(s, computer=s.computer) for s in cached_sessions]
                    event = SessionsInitialEventDTO(data=SessionsInitialDataDTO(sessions=sessions, computer=computer))
                    await self._send_or_enqueue_payload(websocket, event.event, event.model_dump(exclude_none=True))
            elif data_type in ("preparation", "projects"):
                # Send current projects from cache for this computer
                if self.cache:
                    cached_projects = self.cache.get_projects(computer if computer != "local" else None)
                    projects: list[ProjectDTO | ProjectWithTodosDTO] = []
                    for proj in cached_projects:
                        comp = proj.computer or ""
                        if data_type == "preparation":
                            todos = self.cache.get_todos(comp or config.computer.name, proj.path)
                            roadmap_exists = Path(f"{proj.path}/todos/roadmap.yaml").exists()
                            projects.append(
                                ProjectWithTodosDTO(
                                    computer=comp,
                                    name=proj.name,
                                    path=proj.path,
                                    description=proj.description,
                                    has_roadmap=roadmap_exists,
                                    todos=[
                                        TodoDTO(
                                            slug=t.slug,
                                            status=t.status,
                                            description=t.description,
                                            computer=comp or config.computer.name,
                                            project_path=proj.path,
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
                                        for t in todos
                                    ],
                                )
                            )
                        else:
                            projects.append(
                                ProjectDTO(
                                    computer=comp,
                                    name=proj.name,
                                    path=proj.path,
                                    description=proj.description,
                                )
                            )

                    event = ProjectsInitialEventDTO(  # type: ignore[assignment]
                        event="projects_initial" if data_type == "projects" else "preparation_initial",
                        data=ProjectsInitialDataDTO(projects=projects, computer=computer),
                    )
                    await self._send_or_enqueue_payload(websocket, event.event, event.model_dump(exclude_none=True))
            elif data_type == "notifications":
                if self._event_db is not None:
                    rows = await self._event_db.list_notifications(limit=50)
                    await self._send_or_enqueue_payload(
                        websocket,
                        "notifications_initial",
                        {"type": "notifications_initial", "notifications": rows},  # type: ignore[dict-item]
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
        session_payload = self._build_session_cache_payload(event, data)
        if session_payload is not None:
            self._broadcast_payload(event, session_payload)
            return

        if event == "session_closed":
            self._broadcast_payload(event, self._build_session_closed_payload(event, data))
            return

        refresh_payload = self._build_refresh_payload(event, data)
        if refresh_payload is not None:
            self._schedule_refresh_broadcast(refresh_payload)
            return

        self._broadcast_payload(event, self._build_generic_payload(event, data))

    def _build_session_cache_payload(self, event: str, data: object) -> JsonDict | None:
        """Build DTO-backed payloads for session cache events when possible."""
        if event not in ("session_started", "session_updated"):
            return None
        session = self._extract_session_snapshot(data)
        if session is None:
            return None
        dto = SessionDTO.from_core(session, computer=session.computer)
        if event == "session_started":
            return SessionStartedEventDTO(event=event, data=dto).model_dump(exclude_none=True)
        return SessionUpdatedEventDTO(event=event, data=dto).model_dump(exclude_none=True)

    def _extract_session_snapshot(self, data: object) -> SessionSnapshot | None:
        """Extract a session snapshot from a cache notification payload."""
        if isinstance(data, SessionSnapshot):
            return data
        if not isinstance(data, dict):
            return None
        session = data.get("session")
        return session if isinstance(session, SessionSnapshot) else None

    def _build_session_closed_payload(self, event: str, data: object) -> JsonDict:
        """Build the session_closed websocket payload."""
        if isinstance(data, dict):
            return SessionClosedEventDTO(
                data=SessionClosedDataDTO(session_id=str(data.get("session_id", "")))
            ).model_dump(exclude_none=True)
        return self._build_generic_payload(event, data)

    def _build_refresh_payload(self, event: str, data: object) -> JsonDict | None:
        """Build coalesced refresh payloads for cache snapshot/update events."""
        if event not in {
            "computer_updated",
            "project_updated",
            "projects_updated",
            "todos_updated",
            "todo_created",
            "todo_updated",
            "todo_removed",
            "projects_snapshot",
            "todos_snapshot",
        }:
            return None

        computer, project_path = self._extract_refresh_targets(event, data)
        normalized_event = self._normalize_refresh_event(event)
        return RefreshEventDTO(
            event=normalized_event,
            data=RefreshDataDTO(computer=computer, project_path=project_path),
        ).model_dump(exclude_none=True)

    def _extract_refresh_targets(self, event: str, data: object) -> tuple[str | None, str | None]:
        """Resolve the affected computer/project identifiers for refresh events."""
        if isinstance(data, dict):
            computer = data.get("computer")
            project_path = data.get("project_path")
            return (
                computer if isinstance(computer, str) else None,
                project_path if isinstance(project_path, str) else None,
            )

        computer = self._get_optional_str_attr(data, "computer")
        project_path = self._get_optional_str_attr(data, "path")
        if event == "computer_updated" and computer is None:
            computer = self._get_optional_str_attr(data, "name")
        return computer, project_path

    def _normalize_refresh_event(
        self, event: str
    ) -> Literal[
        "computer_updated",
        "project_updated",
        "projects_updated",
        "todos_updated",
        "todo_created",
        "todo_updated",
        "todo_removed",
    ]:
        """Map snapshot-style cache events onto the WS refresh event contract."""
        if event == "projects_snapshot":
            return "projects_updated"
        if event == "todos_snapshot":
            return "todos_updated"
        return event  # type: ignore[return-value]

    def _build_generic_payload(self, event: str, data: object) -> JsonDict:
        """Fallback websocket payload for non-DTO events."""
        if hasattr(data, "to_dict"):
            return {"event": event, "data": cast(JsonValue, data.to_dict())}  # pyright: ignore[reportAttributeAccessIssue]
        return {"event": event, "data": cast(JsonValue, data)}

    def _get_optional_str_attr(self, obj: object, attr_name: str) -> str | None:
        """Read a string attribute when present on an arbitrary cache object."""
        if not hasattr(obj, attr_name):
            return None
        value = getattr(obj, attr_name)
        return value if isinstance(value, str) else None

    def _schedule_refresh_broadcast(self, payload: JsonDict) -> None:
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

    def _broadcast_payload(self, event: str, payload: JsonDict, *, targets: list[WebSocket] | None = None) -> None:
        """Send a WS payload to connected clients. If targets is given, only those clients receive it."""
        clients = targets if targets is not None else list(self._ws_clients)
        for ws in clients:
            self._enqueue_ws_payload(ws, event, payload)

    async def _close_ws(self, websocket: WebSocket) -> None:
        """Close a WebSocket connection safely with timeout."""
        try:
            await asyncio.wait_for(websocket.close(), timeout=1.0)
        except (TimeoutError, Exception):
            pass

    def _ensure_ws_client_state(self, websocket: WebSocket) -> _WsClientState:
        """Create sender state lazily for a websocket client."""
        state = self._ws_client_states.get(websocket)
        if state is None:
            state = _WsClientState(queue=asyncio.Queue())
            self._ws_client_states[websocket] = state
        if state.sender_task is None or state.sender_task.done():
            sender = self._ws_sender_loop(websocket, state)
            task_name = f"ws-sender-{id(websocket)}"
            if self.task_registry:
                state.sender_task = self.task_registry.spawn(sender, name=task_name)
            else:
                state.sender_task = asyncio.create_task(sender, name=task_name)
        return state

    def _enqueue_ws_payload(self, websocket: WebSocket, event: str, payload: JsonDict) -> None:
        """Queue a payload for serialized delivery to one websocket."""
        if websocket not in self._ws_clients:
            return
        state = self._ensure_ws_client_state(websocket)
        state.queue.put_nowait((event, payload))

    async def _send_or_enqueue_payload(self, websocket: WebSocket, event: str, payload: JsonDict) -> None:
        """Send directly for untracked sockets or enqueue for managed clients."""
        if websocket in self._ws_clients:
            self._enqueue_ws_payload(websocket, event, payload)
            return
        await self._send_ws_payload(websocket, event, payload)

    async def _ws_sender_loop(self, websocket: WebSocket, state: _WsClientState) -> None:
        """Serialize outbound writes for a websocket client."""
        while True:
            event, payload = await state.queue.get()
            try:
                delivered = await self._send_ws_payload(websocket, event, payload)
                if not delivered:
                    return
            finally:
                state.queue.task_done()

    async def _send_ws_payload(self, websocket: WebSocket, event: str, payload: JsonDict) -> bool:
        """Send one payload and normalize disconnect handling."""
        timeout = self._ws_send_timeout_seconds(event)
        try:
            if timeout is None:
                await websocket.send_json(payload)
            else:
                await asyncio.wait_for(websocket.send_json(payload), timeout=timeout)
            return True
        except TimeoutError:
            logger.warning(
                "WebSocket send timeout, removing client",
                extra={"event_type": event, "timeout_s": timeout},
            )
            await self._drop_ws_client(websocket, reason=f"send-timeout:{event}")
            return False
        except Exception as exc:
            if self._is_expected_ws_disconnect(exc):
                logger.info(
                    "WebSocket connection lost during send: %s",
                    exc,
                    extra={"event_type": event},
                )
                await self._drop_ws_client(websocket, reason=f"send-disconnect:{event}")
                return False
            logger.error(
                "Unexpected error sending WebSocket event '%s': %s",
                event,
                exc,
                exc_info=True,
                extra={"event_type": event, "payload_keys": list(payload.keys())},
            )
            await self._drop_ws_client(websocket, reason=f"send-error:{event}")
            raise

    def _ws_send_timeout_seconds(self, event: str) -> float | None:
        """Return the timeout budget for a websocket event.

        Control-plane state must not be dropped aggressively; low-value refresh and
        chiptunes updates can use a shorter budget.
        """
        if event in API_WS_CONTROL_EVENTS:
            return API_WS_CONTROL_SEND_TIMEOUT_S
        if event in API_WS_REPLACEABLE_EVENTS:
            return API_WS_REPLACEABLE_SEND_TIMEOUT_S
        return API_WS_DEFAULT_SEND_TIMEOUT_S

    def _is_expected_ws_disconnect(self, exc: BaseException) -> bool:
        """Classify disconnect-shaped transport errors that should not be treated as bugs."""
        seen: set[int] = set()
        current: BaseException | None = exc
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, (WebSocketDisconnect, OSError, ConnectionError)):
                return True
            name = current.__class__.__name__
            if name in {"ClientDisconnected", "ConnectionClosed", "ConnectionClosedError", "ConnectionClosedOK"}:
                return True
            if isinstance(current, RuntimeError) and "close message has been sent" in str(current):
                return True
            next_exc = current.__cause__ if current.__cause__ is not None else current.__context__
            current = next_exc
        return False

    async def _drop_ws_client(self, websocket: WebSocket, *, reason: str) -> None:
        """Remove sender/subscription state for one websocket client."""
        state = self._ws_client_states.pop(websocket, None)
        self._ws_clients.discard(websocket)
        self._client_subscriptions.pop(websocket, None)

        sender_task = state.sender_task if state is not None else None
        current_task = asyncio.current_task()
        if sender_task is not None and sender_task is not current_task and not sender_task.done():
            sender_task.cancel()
            try:
                await sender_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("WebSocket sender task ended with error during cleanup", exc_info=True)

        await self._close_ws(websocket)

        if self.cache and len(self._ws_clients) == 0:
            self._update_cache_interest()

        logger.debug("WebSocket client removed", extra={"client_id": id(websocket), "reason": reason})

    async def _notification_push(
        self,
        notification_id: int,
        event_type: str,
        level: int,
        was_created: bool,
        is_meaningful: bool,
    ) -> None:
        """Push a notification event to subscribed WebSocket clients."""
        if self._event_db is None:
            return
        row = await self._event_db.get_notification(notification_id)
        if row is None:
            return
        payload: dict[str, object] = {  # guard: loose-dict - WS payload
            "type": "notification_created" if was_created else "notification_updated",
            "event_type": event_type,
            "notification": row,
        }
        # Collect clients subscribed to the "notifications" topic; send only to them.
        # Using _broadcast_payload directly (not _schedule_refresh_broadcast) avoids the
        # 250ms debounce that would coalesce back-to-back notification payloads.
        subscribed: list[WebSocket] = []
        seen: set[int] = set()
        for ws, computer_subs in self._client_subscriptions.items():
            if id(ws) in seen:
                continue
            for data_types in computer_subs.values():
                if "notifications" in data_types:
                    subscribed.append(ws)
                    seen.add(id(ws))
                    break
        if subscribed:
            self._broadcast_payload("notification", payload, targets=subscribed)
