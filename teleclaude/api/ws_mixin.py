"""WebSocket support mixin for APIServer."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import TYPE_CHECKING, Literal, cast

from fastapi import WebSocket, WebSocketDisconnect
from instrukt_ai_logging import get_logger

from teleclaude.api.person_display import ownership_surface, with_person_chips_on_todos
from teleclaude.api.session_view_models import project_session_dtos
from teleclaude.api.ws_constants import (
    API_WS_CONTROL_EVENTS,
    API_WS_CONTROL_SEND_TIMEOUT_S,
    API_WS_DEFAULT_SEND_TIMEOUT_S,
    API_WS_REPLACEABLE_EVENTS,
    API_WS_REPLACEABLE_SEND_TIMEOUT_S,
    _WsClientState,
)
from teleclaude.api.ws_options import WsProjectionOptionError, WsProjectionOptions, WsStream, parse_ws_streams
from teleclaude.api_models import (
    ProjectDTO,
    ProjectsInitialDataDTO,
    ProjectsInitialEventDTO,
    ProjectWithTodosDTO,
    RefreshDataDTO,
    RefreshEventDTO,
    SessionClosedDataDTO,
    SessionClosedEventDTO,
    SessionsInitialDataDTO,
    SessionsInitialEventDTO,
    SessionStartedEventDTO,
    SessionUpdatedEventDTO,
)
from teleclaude.caller_identity import CliCaller
from teleclaude.config.machine import config
from teleclaude.constants import CacheEvent
from teleclaude.core.cache import ComputerUpdatedNotification
from teleclaude.core.models import JsonDict, JsonValue, SessionSnapshot
from teleclaude.core.models._adapter import session_is_unattended
from teleclaude.core.session_listing import listed_by_default, snapshot_reached_by_reach
from teleclaude.core.session_status import SessionLifecycleStatus
from teleclaude.identity_reach import Reach, ReachCache, ReachResolutionError

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)

_REACH_RESOLUTION_FAILURE_CLOSE_REASON = "identity reach resolution failed"
_SNAPSHOT_FAILURE_CLOSE_REASON = "initial state could not be projected"
_WEBSOCKET_INTERNAL_ERROR_CODE = 1011
_REACH_RESOLUTION_CLOSE_FAILED = "Failed to close a websocket after reach resolution failed"
_SNAPSHOT_FAILED_LOG = "Failed to project initial state for stream %s"
_CONNECTED_LOG = "WebSocket client connected"
_FRAME_PARSE_FAILED_LOG = "WebSocket frame could not be parsed; reading the next frame"
_LEGACY_FRAME_IGNORED_LOG = "Ignoring subscription frame on a connection that declared its options"
_LEGACY_FRAME_INVALID_LOG = "Invalid subscribe format: %s"
_LEGACY_FRAME_TYPE_INVALID_LOG = "Subscribe type is not usable: %s"
_LEGACY_FRAME_TYPES_INVALID = "types missing/invalid"
_REFRESH_DATA_FIELD = "data"
_REFRESH_EVENT_FIELD = "event"
_REFRESH_COMPUTER_FIELD = "computer"
_REFRESH_PROJECT_PATH_FIELD = "project_path"
_REFRESH_SUBJECT_FIELD = "subject"
_REFRESH_OWNER_FIELD = "owner"
_REFRESH_PROJECTS_UPDATED_EVENT = "projects_updated"
_REFRESH_COMPUTER_UPDATED_EVENT = "computer_updated"
_REFRESH_PUSH_EVENT = "refresh"
_SUBSCRIBE_FIELD = "subscribe"
_SUBSCRIBE_TYPES_FIELD = "types"
_SUBSCRIBE_INCLUDE_REMOVED_FIELD = "include_removed"
_LOCAL_COMPUTER_NAME = "local"
_PROJECT_STREAM_EVENTS: dict[WsStream, Literal["projects_initial", "preparation_initial"]] = {
    WsStream.PROJECTS: "projects_initial",
    WsStream.PREPARATION: "preparation_initial",
}
_TODO_REFRESH_EVENTS = frozenset(
    {
        CacheEvent.TODOS_UPDATED.value,
        CacheEvent.TODO_CREATED.value,
        CacheEvent.TODO_UPDATED.value,
        CacheEvent.TODO_RENAMED.value,
        CacheEvent.TODO_REMOVED.value,
        CacheEvent.TODOS_SNAPSHOT.value,
    }
)
_STREAM_INIT_ORDER = (WsStream.SESSIONS, WsStream.PROJECTS, WsStream.PREPARATION, WsStream.TODOS)
_SESSION_CHANGE_EVENTS = frozenset({CacheEvent.SESSION_STARTED.value, CacheEvent.SESSION_UPDATED.value})


def _session_is_open(session: SessionSnapshot) -> bool:
    """Whether a cached session is open: any lifecycle status short of closed."""
    return session.closed_at is None and session.status != SessionLifecycleStatus.CLOSED


class _WebSocketMixin:  # pyright: ignore[reportUnusedClass]
    """WebSocket support methods extracted from APIServer."""

    if TYPE_CHECKING:
        client: AdapterClient
        task_registry: TaskRegistry | None
        _cache: DaemonCache | None
        _ws_clients: set[WebSocket]
        _ws_viewers: dict[WebSocket, CliCaller]
        _ws_caller_session_ids: dict[WebSocket, str | None]
        _ws_reach_caches: dict[WebSocket, ReachCache]
        _ws_sent_session_ids: dict[WebSocket, set[str]]
        _ws_client_states: dict[WebSocket, _WsClientState]
        _refresh_debounce_task: asyncio.Task[object] | None
        _refresh_pending_payloads: dict[WebSocket, JsonDict]

        @property
        def cache(self) -> DaemonCache | None:
            """Expose the daemon cache for websocket helpers."""
            raise NotImplementedError

    async def _handle_websocket(
        self,
        websocket: WebSocket,
        viewer: CliCaller,
        caller_session_id: str | None = None,
        options: WsProjectionOptions | None = None,
    ) -> None:
        """Handle WebSocket connection for push updates.

        Args:
            websocket: WebSocket connection
            viewer: Caller identity the connection reads as
            caller_session_id: Session that opened the connection, when one did
            options: Projection options the connection declared; None marks a
                legacy client that selects its streams with subscription frames
        """
        await websocket.accept()
        self._ws_clients.add(websocket)
        self._ws_viewers[websocket] = viewer
        self._ws_caller_session_ids[websocket] = caller_session_id
        self._ws_reach_caches[websocket] = ReachCache(
            viewer,
            on_invalidate=lambda: self._schedule_reach_resync(websocket),
        )
        self._ws_sent_session_ids[websocket] = set()
        state = self._ensure_ws_client_state(websocket)
        logger.info(_CONNECTED_LOG)

        try:
            if options is None:
                state.legacy = True
            else:
                state.include_removed = options.include_removed
                await self._initialize_ws_streams(websocket, options.streams)

            while True:
                # Receive messages from client
                message = await websocket.receive_text()
                try:
                    data_raw: object = json.loads(message)
                except Exception:
                    logger.exception(_FRAME_PARSE_FAILED_LOG)
                    continue

                # Type guard: ensure data is a dict
                if not isinstance(data_raw, dict):
                    logger.warning("WebSocket received non-dict message: %s", type(data_raw))
                    continue

                data: dict[str, object] = data_raw  # guard: loose-dict - WebSocket message

                if _SUBSCRIBE_FIELD in data:
                    await self._apply_legacy_subscribe_frame(websocket, data[_SUBSCRIBE_FIELD])

        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
        except Exception as e:
            if self._is_expected_ws_disconnect(e):
                logger.info("WebSocket connection closed: %s", e)
            else:
                logger.error("WebSocket error: %s", e, exc_info=True)
        finally:
            await self._drop_ws_client(websocket, reason="connection-end")

    async def _apply_legacy_subscribe_frame(self, websocket: WebSocket, subscribe_data: object) -> None:
        """Apply an old-style subscription frame as projection options for a legacy connection.

        A frame's types select streams and its include-removed flag sets that
        option; its computer field is ignored. The first frame that selects a
        stream fixes the flag. Later frames only add streams not yet selected and
        never re-send an initialized stream's snapshot.
        """
        state = self._ws_client_states.get(websocket)
        if state is None or not state.legacy:
            logger.debug(_LEGACY_FRAME_IGNORED_LOG)
            return
        frame = self._legacy_frame_options(subscribe_data)
        if frame is None:
            return
        streams, include_removed = frame
        if not state.streams:
            state.include_removed = include_removed
        await self._initialize_ws_streams(websocket, streams)

    @staticmethod
    def _legacy_frame_options(subscribe_data: object) -> tuple[frozenset[WsStream], bool] | None:
        """Resolve a legacy subscription frame into streams and the include-removed flag."""
        if isinstance(subscribe_data, str):
            try:
                return parse_ws_streams([subscribe_data]), False
            except WsProjectionOptionError as exc:
                logger.warning(_LEGACY_FRAME_INVALID_LOG, exc)
                return None
        if not isinstance(subscribe_data, dict):
            logger.warning(_LEGACY_FRAME_INVALID_LOG, type(subscribe_data))
            return None
        types_raw = subscribe_data.get(_SUBSCRIBE_TYPES_FIELD)
        if not isinstance(types_raw, list):
            logger.warning(_LEGACY_FRAME_INVALID_LOG, _LEGACY_FRAME_TYPES_INVALID)
            return None
        streams: set[WsStream] = set()
        for type_raw in types_raw:
            if not isinstance(type_raw, str):
                logger.warning(_LEGACY_FRAME_TYPE_INVALID_LOG, type(type_raw))
                continue
            try:
                streams.update(parse_ws_streams([type_raw]))
            except WsProjectionOptionError as exc:
                logger.warning(_LEGACY_FRAME_TYPE_INVALID_LOG, exc)
        return frozenset(streams), bool(subscribe_data.get(_SUBSCRIBE_INCLUDE_REMOVED_FIELD, False))

    async def _initialize_ws_streams(self, websocket: WebSocket, requested: Iterable[WsStream]) -> None:
        """Queue the initial state of each requested stream not yet initialized.

        A stream receives subsequent changes only once its initial state is
        queued, so the snapshot always precedes the changes on the connection's
        serialized sender. Nothing suspends between capturing a snapshot and
        marking its stream initialized.
        """
        state = self._ws_client_states.get(websocket)
        if state is None:
            return
        wanted = frozenset(requested)
        for stream in _STREAM_INIT_ORDER:
            if stream not in wanted or stream in state.streams:
                continue
            if not await self._send_stream_snapshot(websocket, stream, state.include_removed):
                return
            state.streams.add(stream)

    async def _send_stream_snapshot(self, websocket: WebSocket, stream: WsStream, include_removed: bool) -> bool:
        """Queue one stream's initial state; close the connection and return False when it cannot be projected."""
        try:
            if stream is WsStream.SESSIONS:
                self._queue_session_snapshot(websocket)
            elif stream in _PROJECT_STREAM_EVENTS:
                self._queue_projects_snapshot(websocket, stream, include_removed)
        except ReachResolutionError as exc:
            await self._close_ws_for_reach_failure(websocket, str(exc))
            return False
        except Exception:
            logger.error(_SNAPSHOT_FAILED_LOG, stream, exc_info=True)
            await self._drop_ws_client(websocket, reason=_SNAPSHOT_FAILURE_CLOSE_REASON)
            return False
        return True

    def _queue_session_snapshot(self, websocket: WebSocket) -> None:
        """Queue the viewer's complete eligible session snapshot, unpartitioned by computer.

        Eligibility composes the owners: open lifecycle status, the default
        listing's attended-session rule, and the viewer's identity reach.
        """
        cache = self.cache
        reach_cache = self._ws_reach_caches.get(websocket)
        if cache is None or reach_cache is None:
            return
        reach = reach_cache.get()
        open_sessions = [session for session in cache.get_sessions() if _session_is_open(session)]
        visible = [
            session
            for session in listed_by_default(open_sessions, all_sessions=False, session_ids=None)
            if self._viewer_can_read_session(reach, session)
        ]
        self._ws_sent_session_ids.setdefault(websocket, set()).update(session.session_id for session in visible)
        sessions = project_session_dtos(
            visible,
            serving_computer=config.computer.name,
            computer_registry=cache.get_computers(),
        )
        event = SessionsInitialEventDTO(data=SessionsInitialDataDTO(sessions=sessions, ownership=ownership_surface()))
        self._enqueue_ws_payload(websocket, event.event, event.model_dump(exclude_none=True))

    def _queue_projects_snapshot(self, websocket: WebSocket, stream: WsStream, include_removed: bool) -> None:
        """Queue every cached computer's reach-admitted projects, with todos for the preparation stream."""
        cache = self.cache
        reach_cache = self._ws_reach_caches.get(websocket)
        if cache is None or reach_cache is None:
            return
        reach = reach_cache.get()
        projects: list[ProjectDTO | ProjectWithTodosDTO] = []
        for proj in cache.get_projects(None):
            if not reach.admits(proj.subject, proj.owner, None):
                continue
            comp = proj.computer or ""
            if stream is WsStream.PREPARATION:
                todos = cache.get_todos(comp or config.computer.name, proj.path, include_removed=include_removed)
                projects.append(
                    ProjectWithTodosDTO(
                        computer=comp,
                        name=proj.name,
                        path=proj.path,
                        description=proj.description,
                        subject=proj.subject,
                        owner=proj.owner,
                        has_todo=False,
                        todos=with_person_chips_on_todos(
                            t.model_copy(
                                update={
                                    _REFRESH_COMPUTER_FIELD: comp or config.computer.name,
                                    _REFRESH_PROJECT_PATH_FIELD: proj.path,
                                }
                            )
                            for t in todos
                        ),
                    )
                )
            else:
                projects.append(
                    ProjectDTO(
                        computer=comp,
                        name=proj.name,
                        path=proj.path,
                        description=proj.description,
                        subject=proj.subject,
                        owner=proj.owner,
                    )
                )

        event = ProjectsInitialEventDTO(
            event=_PROJECT_STREAM_EVENTS[stream],
            data=ProjectsInitialDataDTO(
                projects=projects, computer=_LOCAL_COMPUTER_NAME, ownership=ownership_surface()
            ),
        )
        self._enqueue_ws_payload(websocket, event.event, event.model_dump(exclude_none=True))

    def _schedule_reach_resync(self, websocket: WebSocket) -> None:
        """Queue a fresh session snapshot after a live viewer's reach changes."""
        if websocket in self._ws_clients:
            pending_refresh = self._refresh_pending_payloads.get(websocket)
            refresh_data = pending_refresh.get(_REFRESH_DATA_FIELD) if pending_refresh is not None else None
            if isinstance(refresh_data, dict) and refresh_data.get(_REFRESH_PROJECT_PATH_FIELD) is not None:
                self._refresh_pending_payloads.pop(websocket, None)
            asyncio.create_task(self._resync_ws_reach(websocket))

    async def _resync_ws_reach(self, websocket: WebSocket) -> None:
        """Rebuild every initialized stream of one connection from current reach.

        The delivered-session record is kept: a session the new snapshot omits was
        still shown to this connection, so its explicit closure stays deliverable.
        """
        state = self._ws_client_states.get(websocket)
        if state is None:
            return
        for stream in _STREAM_INIT_ORDER:
            if stream not in state.streams:
                continue
            if not await self._send_stream_snapshot(websocket, stream, state.include_removed):
                return

    async def _send_session_snapshots(self, targets: Iterable[WebSocket]) -> None:
        """Queue a fresh complete session snapshot to each connection that selected the session stream."""
        for websocket in targets:
            state = self._ws_client_states.get(websocket)
            if state is None or WsStream.SESSIONS not in state.streams:
                continue
            await self._send_stream_snapshot(websocket, WsStream.SESSIONS, state.include_removed)

    async def _close_ws_for_reach_failure(self, websocket: WebSocket, reason: str) -> None:
        """Close a connection whose visibility decision could not be resolved."""
        try:
            await websocket.close(code=_WEBSOCKET_INTERNAL_ERROR_CODE, reason=reason)
        except Exception:
            logger.warning(_REACH_RESOLUTION_CLOSE_FAILED, exc_info=True)
        finally:
            await self._drop_ws_client(websocket, reason=_REACH_RESOLUTION_FAILURE_CLOSE_REASON)

    @staticmethod
    def _viewer_can_read_session(reach: Reach, session: SessionSnapshot) -> bool:
        return snapshot_reached_by_reach(reach, session)

    def _session_event_targets(self, session: SessionSnapshot) -> list[WebSocket]:
        """Select initialized session-stream viewers who can read this session at send time.

        An unattended procedure agent is shown to no viewer: it is a presentation
        fact beside reach, so the reach check below is untouched. The source
        computer of the session takes no part in selection.
        """
        if session_is_unattended(session):
            return []
        targets: list[WebSocket] = []
        for websocket, state in self._ws_client_states.items():
            if websocket not in self._ws_clients or WsStream.SESSIONS not in state.streams:
                continue
            viewer = self._ws_viewers.get(websocket)
            reach_cache = self._ws_reach_caches.get(websocket)
            if viewer is None or reach_cache is None:
                continue
            try:
                if not self._viewer_can_read_session(reach_cache.get(), session):
                    continue
            except ReachResolutionError as exc:
                asyncio.create_task(self._close_ws_for_reach_failure(websocket, str(exc)))
                continue
            self._ws_sent_session_ids.setdefault(websocket, set()).add(session.session_id)
            targets.append(websocket)
        return targets

    def _subject_event_targets(
        self,
        subject: str,
        owner: str,
        *,
        caller_session_id: str | None = None,
    ) -> list[WebSocket]:
        """Select viewers whose reach admits a subject or own operation."""
        targets: list[WebSocket] = []
        for websocket in self._ws_clients:
            viewer = self._ws_viewers.get(websocket)
            reach_cache = self._ws_reach_caches.get(websocket)
            if viewer is None or reach_cache is None:
                continue
            if caller_session_id is not None and self._ws_caller_session_ids.get(websocket) == caller_session_id:
                targets.append(websocket)
                continue
            try:
                if reach_cache.get().admits(subject, owner, None):
                    targets.append(websocket)
            except ReachResolutionError as exc:
                asyncio.create_task(self._close_ws_for_reach_failure(websocket, str(exc)))
        return targets

    def _on_cache_change(self, event: str, data: object) -> None:
        """Handle cache change notifications and push to WebSocket clients.

        Args:
            event: Event type (e.g., "session_updated", "computer_updated")
            data: Event data
        """
        if event in _SESSION_CHANGE_EVENTS:
            self._deliver_session_change(event, data)
            return

        if event == "session_closed":
            session_id = str(data.get("session_id", "")) if isinstance(data, dict) else ""
            targets = [
                websocket
                for websocket, sent_ids in self._ws_sent_session_ids.items()
                if session_id and session_id in sent_ids
            ]
            for websocket in targets:
                self._ws_sent_session_ids[websocket].discard(session_id)
            if targets:
                self._broadcast_payload(event, self._build_session_closed_payload(event, data), targets=targets)
            return

        if event == CacheEvent.COMPUTER_UPDATED.value and isinstance(data, ComputerUpdatedNotification):
            if data.attachment_inputs_changed:
                self._reproject_computer_sessions(data.computer_name)

        refresh_payload = self._build_refresh_payload(event, data)
        if refresh_payload is not None:
            targets = self._refresh_targets(event, data)
            if targets:
                self._schedule_refresh_broadcast(refresh_payload, targets=targets)
            return

        self._broadcast_payload(event, self._build_generic_payload(event, data))

    def _deliver_session_change(self, event: str, data: object) -> None:
        """Deliver a session change as the session's current cached row.

        Cache notifications are dispatched after the change that raised them, so
        the notified payload may be older than the cache. The row is re-read here:
        a session that left the cache since is not delivered, and its closure
        notice owns that outcome.
        """
        notified = self._extract_session_snapshot(data)
        cache = self.cache
        if notified is None or cache is None:
            return
        session = cache.get_session(notified.session_id)
        if session is None:
            return
        targets = self._session_event_targets(session)
        if targets:
            self._broadcast_payload(event, self._build_session_cache_payload(event, session), targets=targets)

    def _reproject_computer_sessions(self, computer_name: str) -> None:
        """Send current attachment projections for sessions owned by one peer."""
        cache = self.cache
        if cache is None:
            return
        for session in cache.get_sessions():
            if session.computer == computer_name:
                self._deliver_session_change(CacheEvent.SESSION_UPDATED.value, session)

    def _build_session_cache_payload(self, event: str, session: SessionSnapshot) -> JsonDict:
        """Build the DTO-backed payload for a session started or updated event."""
        cache = self.cache
        computer_registry = cache.get_computers() if cache is not None else []
        dto = project_session_dtos(
            [session],
            serving_computer=config.computer.name,
            computer_registry=computer_registry,
        )[0]
        if event == CacheEvent.SESSION_STARTED.value:
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
            "todo_renamed",
        }:
            return None

        computer, project_path = self._extract_refresh_targets(event, data)
        normalized_event = self._normalize_refresh_event(event)
        return RefreshEventDTO(
            event=normalized_event,
            data=RefreshDataDTO(computer=computer, project_path=project_path),
        ).model_dump(exclude_none=True)

    def _refresh_targets(self, event: str, data: object) -> list[WebSocket]:
        """Select initialized viewers of the notice's streams and apply reach before a path is delivered.

        Todo change notices also reach the todos stream; project and computer notices do not.
        """
        _, project_path = self._extract_refresh_targets(event, data)
        if isinstance(data, dict):
            subject_raw = data.get(_REFRESH_SUBJECT_FIELD)
            owner_raw = data.get(_REFRESH_OWNER_FIELD)
        else:
            subject_raw = self._get_optional_str_attr(data, _REFRESH_SUBJECT_FIELD)
            owner_raw = self._get_optional_str_attr(data, _REFRESH_OWNER_FIELD)
        subject = subject_raw if isinstance(subject_raw, str) else None
        owner = owner_raw if isinstance(owner_raw, str) else None
        entry_update = project_path is not None and event != _REFRESH_COMPUTER_UPDATED_EVENT
        notice_streams = _PROJECT_STREAM_EVENTS.keys() | ({WsStream.TODOS} if event in _TODO_REFRESH_EVENTS else set())
        targets: list[WebSocket] = []
        for websocket, state in self._ws_client_states.items():
            if websocket not in self._ws_clients or not state.streams & notice_streams:
                continue
            if entry_update:
                reach_cache = self._ws_reach_caches.get(websocket)
                if reach_cache is None:
                    continue
                try:
                    if not reach_cache.get().admits(subject, owner, None):
                        continue
                except ReachResolutionError as exc:
                    asyncio.create_task(self._close_ws_for_reach_failure(websocket, str(exc)))
                    continue
            targets.append(websocket)
        return targets

    def _extract_refresh_targets(self, event: str, data: object) -> tuple[str | None, str | None]:
        """Resolve the affected computer/project identifiers for refresh events."""
        if isinstance(data, ComputerUpdatedNotification):
            return data.computer_name, None
        if isinstance(data, dict):
            computer = data.get("computer")
            project_path = data.get("project_path")
            return (
                computer if isinstance(computer, str) else None,
                project_path if isinstance(project_path, str) else None,
            )

        computer = self._get_optional_str_attr(data, "computer")
        project_path = self._get_optional_str_attr(data, "path")
        if event == _REFRESH_COMPUTER_UPDATED_EVENT and computer is None:
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
        if event == "todo_renamed":
            return "todo_updated"
        return event  # type: ignore[return-value]

    def _build_generic_payload(self, event: str, data: object) -> JsonDict:
        """Fallback websocket payload for non-DTO events."""
        to_dict = getattr(data, "to_dict", None)
        if callable(to_dict):
            return {
                "event": event,
                "data": cast(JsonValue, to_dict()),
            }
        return {"event": event, "data": cast(JsonValue, data)}

    def _get_optional_str_attr(self, obj: object, attr_name: str) -> str | None:
        """Read a string attribute when present on an arbitrary cache object."""
        if not hasattr(obj, attr_name):
            return None
        value = getattr(obj, attr_name)
        return value if isinstance(value, str) else None

    def _schedule_refresh_broadcast(self, payload: JsonDict, *, targets: list[WebSocket]) -> None:
        """Coalesce refresh events independently for each subscribed connection."""
        event = payload.get(_REFRESH_EVENT_FIELD)
        data = payload.get(_REFRESH_DATA_FIELD)
        if not isinstance(event, str) or not isinstance(data, dict):
            return
        for websocket in targets:
            self._refresh_pending_payloads[websocket] = self._merge_refresh_payloads(
                self._refresh_pending_payloads.get(websocket),
                payload,
            )
        if self._refresh_debounce_task and not self._refresh_debounce_task.done():
            return

        async def _debounced() -> None:
            await asyncio.sleep(0.25)
            pending, self._refresh_pending_payloads = self._refresh_pending_payloads, {}
            self._refresh_debounce_task = None
            for websocket, pending_payload in pending.items():
                self._broadcast_payload(_REFRESH_PUSH_EVENT, pending_payload, targets=[websocket])

        if not self._refresh_pending_payloads:
            return

        if self.task_registry:
            self._refresh_debounce_task = self.task_registry.spawn(_debounced(), name="ws-broadcast-refresh")
        else:
            self._refresh_debounce_task = asyncio.create_task(_debounced(), name="ws-broadcast-refresh")

    @staticmethod
    def _merge_refresh_payloads(
        previous: JsonDict | None,
        current: JsonDict,
    ) -> JsonDict:
        """Merge refreshes into a pathless refetch when their targets differ."""
        if previous is None:
            return current
        previous_data = previous.get(_REFRESH_DATA_FIELD)
        current_data = current.get(_REFRESH_DATA_FIELD)
        if not isinstance(previous_data, dict) or not isinstance(current_data, dict):
            return current
        previous_event = previous.get(_REFRESH_EVENT_FIELD)
        current_event = current.get(_REFRESH_EVENT_FIELD)
        event = current_event if previous_event == current_event else _REFRESH_PROJECTS_UPDATED_EVENT
        if previous_event == _REFRESH_COMPUTER_UPDATED_EVENT or current_event == _REFRESH_COMPUTER_UPDATED_EVENT:
            event = _REFRESH_COMPUTER_UPDATED_EVENT
        previous_computer = previous_data.get(_REFRESH_COMPUTER_FIELD)
        current_computer = current_data.get(_REFRESH_COMPUTER_FIELD)
        computer = previous_computer if previous_computer == current_computer else None
        previous_path = previous_data.get(_REFRESH_PROJECT_PATH_FIELD)
        current_path = current_data.get(_REFRESH_PROJECT_PATH_FIELD)
        project_path = previous_path if previous_path == current_path else None
        return RefreshEventDTO(
            event=event,  # type: ignore[arg-type]
            data=RefreshDataDTO(computer=computer, project_path=project_path),
        ).model_dump(exclude_none=True)

    def _broadcast_payload(self, event: str, payload: JsonDict, *, targets: list[WebSocket] | None = None) -> None:
        """Send a WS payload to connected clients. If targets is given, only those clients receive it."""
        clients = targets if targets is not None else list(self._ws_clients)
        for ws in clients:
            self._enqueue_ws_payload(ws, event, payload)

    async def _close_ws(self, websocket: WebSocket) -> None:
        """Close a WebSocket connection safely with timeout."""
        try:
            await asyncio.wait_for(websocket.close(), timeout=1.0)
        except TimeoutError:
            pass
        except Exception:
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
            if isinstance(current, WebSocketDisconnect | OSError | ConnectionError):
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
        """Remove sender and projection state for one websocket client."""
        state = self._ws_client_states.pop(websocket, None)
        self._ws_clients.discard(websocket)
        self._ws_viewers.pop(websocket, None)
        self._ws_caller_session_ids.pop(websocket, None)
        reach_cache = self._ws_reach_caches.pop(websocket, None)
        if reach_cache is not None:
            reach_cache.close()
        self._ws_sent_session_ids.pop(websocket, None)

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

        logger.debug("WebSocket client removed", extra={"client_id": id(websocket), "reason": reason})
