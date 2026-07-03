"""Central cache for remote data with TTL management and change notifications.

Provides instant reads for API endpoints and emits change events when data updates.
"""

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.api_models import TodoDTO
from teleclaude.config import config
from teleclaude.constants import CACHE_KEY_SEPARATOR, LOCAL_COMPUTER, CacheEvent, TodoStatus
from teleclaude.core import command_handlers
from teleclaude.core.models import ComputerInfo, ProjectInfo, SessionSnapshot
from teleclaude.core.reconciliation import FleetCapabilityEntry
from teleclaude.transport.cluster_publisher import ClusterPublisher

logger = get_logger(__name__)


class CachedItem[T]:
    """Wrapper for cached items with timestamp tracking."""

    def __init__(self, data: T, cached_at: datetime | None = None) -> None:
        """Initialize cached item.

        Args:
            data: The cached data
            cached_at: Timestamp when data was cached (defaults to now)
        """
        self.data = data
        self.cached_at = cached_at or datetime.now(UTC)

    def is_stale(self, ttl_seconds: int) -> bool:
        """Check if cached item has exceeded its TTL.

        Args:
            ttl_seconds: Time-to-live in seconds

        Returns:
            True if item is older than TTL, False otherwise
        """
        if ttl_seconds == 0:
            return True  # TTL of 0 means always stale (always refresh)
        if ttl_seconds < 0:
            return False  # Negative TTL means infinite (never stale)

        age = (datetime.now(UTC) - self.cached_at).total_seconds()
        return age > ttl_seconds


@dataclass(frozen=True)
class TodoCacheEntry:
    """Cached todos with context for filtering."""

    computer: str
    project_path: str
    todos: list[TodoDTO]


class TodoCacheNotificationPayload(TypedDict, total=False):
    """Payload emitted when cached todos change."""

    computer: str
    project_path: str
    todos: list[TodoDTO]
    old_slug: str
    new_slug: str
    renamed_at: str
    renamed_by_principal: str
    surfaces_moved: list[str]


def _merge_todo_event_data(
    payload: TodoCacheNotificationPayload,
    event_data: Mapping[str, object] | None,
) -> None:
    if event_data is None:
        return

    old_slug = event_data.get("old_slug")
    if isinstance(old_slug, str):
        payload["old_slug"] = old_slug
    new_slug = event_data.get("new_slug")
    if isinstance(new_slug, str):
        payload["new_slug"] = new_slug
    renamed_at = event_data.get("renamed_at")
    if isinstance(renamed_at, str):
        payload["renamed_at"] = renamed_at
    renamed_by_principal = event_data.get("renamed_by_principal")
    if isinstance(renamed_by_principal, str):
        payload["renamed_by_principal"] = renamed_by_principal
    surfaces_moved = event_data.get("surfaces_moved")
    if isinstance(surfaces_moved, list):
        parsed_surfaces = [surface for surface in surfaces_moved if isinstance(surface, str)]
        if len(parsed_surfaces) == len(surfaces_moved):
            payload["surfaces_moved"] = parsed_surfaces


class DaemonCache:
    """Central cache for remote data with TTL management.

    Data categories:
    - Computers: From heartbeats, TTL=60s
    - Projects: Pull once on access, TTL=5min
    - Sessions: Pull once + event updates, TTL=infinite
    - Todos: Pull once on access, TTL=5min
    """

    def __init__(self, on_stale_read: Callable[[str, str], None] | None = None) -> None:
        """Initialize empty cache.

        Args:
            on_stale_read: Optional callback invoked when a read returns stale cached data.
                Signature: (resource_type: str, computer: str) where resource_type is
                "projects" or "todos". Exceptions are suppressed and logged.
        """
        self._on_stale_read = on_stale_read

        # Computer cache: key = computer name
        self._computers: dict[str, CachedItem[ComputerInfo]] = {}

        # Project cache: key = f"{computer}:{path}"
        self._projects: dict[str, CachedItem[ProjectInfo]] = {}

        # Session cache: key = session_id
        self._sessions: dict[str, CachedItem[SessionSnapshot]] = {}

        # Todo cache: key = f"{computer}:{project_path}"
        self._todos: dict[str, CachedItem[list[TodoDTO]]] = {}

        # Snapshot fingerprints + versions (per computer)
        self._projects_digest: dict[str, str] = {}
        self._sessions_digest: dict[str, str] = {}
        self._todos_digest: dict[str, str] = {}
        self._projects_version: dict[str, int] = {}
        self._todos_version: dict[str, int] = {}
        self._computers_digest: dict[str, str] = {}

        # Change subscribers: callbacks notified when cache updates
        self._subscribers: set[Callable[[str, object], None]] = set()

        # Interest tracking: per-computer interest in data types
        # Structure: {data_type: {computer1, computer2, ...}}
        # Examples: {"sessions": {"raspi", "macbook"}, "projects": {"raspi"}}
        self._interest: dict[str, set[str]] = {}

        # Cluster publisher (cross-computer events). Attached after RedisTransport
        # is wired; None during single-computer and test contexts.
        self._cluster_publisher: ClusterPublisher | None = None

    def attach_cluster_publisher(self, publisher: ClusterPublisher) -> None:
        """Wire the cross-computer publisher into the cache.

        Called from the daemon once the Redis transport is available. After
        attachment, mutating writers fire-and-forget ``cluster.*`` events so
        peers can materialize the same state into their local caches.
        """
        self._cluster_publisher = publisher
        logger.info("Cluster publisher attached to DaemonCache")

    @property
    def cluster_publisher(self) -> ClusterPublisher | None:
        """Return the attached cross-computer publisher, when cluster mode is active."""
        return self._cluster_publisher

    def _publish_cluster(
        self,
        channel: str,
        payload: dict[str, object],  # guard: loose-dict - event payload
        *,
        feature_id: str | None = None,
    ) -> None:
        """Schedule a fire-and-forget publish to a ``cluster.*`` channel.

        No-op when no publisher is attached (single-computer / test contexts).
        When a publisher IS attached but no event loop is running, the cache
        write is committed and the publish is dropped — but it logs a WARN
        with channel context so the loss is observable rather than silent.
        In production the daemon always runs cache writers from async
        contexts, so this branch should be unreachable; if it ever fires the
        warning surfaces an invariant violation worth investigating.
        """
        publisher = self._cluster_publisher
        if publisher is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "Cluster publish dropped: no running event loop",
                channel=channel,
                origin=publisher.origin,
            )
            return
        loop.create_task(publisher.publish(channel, payload, feature_id=feature_id))

    def _signal_stale_read(self, resource_type: str, computer: str) -> None:
        """Signal a stale read to the callback, suppressing any exceptions.

        Args:
            resource_type: "projects" or "todos"
            computer: Computer name where stale data was read
        """
        if self._on_stale_read is None:
            return
        try:
            self._on_stale_read(resource_type, computer)
        except Exception as e:
            logger.error("on_stale_read callback failed: %s", e, exc_info=True)

    # ==================== TTL Management ====================

    def invalidate(self, key: str) -> None:
        """Remove a specific item from cache.

        Args:
            key: Cache key to invalidate
        """
        # Remove from all caches
        self._computers.pop(key, None)
        self._projects.pop(key, None)
        self._sessions.pop(key, None)
        self._todos.pop(key, None)
        logger.debug("Invalidated cache key: %s", key)

    def invalidate_all(self) -> None:
        """Clear all cached data."""
        self._computers.clear()
        self._projects.clear()
        self._sessions.clear()
        self._todos.clear()
        logger.info("Cleared all cache data")

    def publish_workflow_change(
        self,
        scope: str,
        *,
        computer: str,
        project_path: str | None = None,
    ) -> None:
        """Invalidate caches and notify subscribers about a v2 workflow event.

        Used by the v2 ``workflow.*`` Redis bridge to keep the v1 daemon's view
        coherent without doing field-level cache surgery. The bridge classifies
        the channel; this method translates the classification into the right
        cache eviction + the right subscriber notification so the existing
        WebSocket refresh pipeline can fan it out.

        Args:
            scope: One of ``"todos"``, ``"artifacts"``, ``"roadmap"``. Todos
                and artifacts both invalidate the per-project todos cache and
                fire ``todos_updated``; roadmap invalidates the project digest
                and fires ``projects_updated``.
            computer: Computer name whose caches should be invalidated.
            project_path: Project path required for todo/artifact scopes; the
                call is a no-op if missing for those scopes.
        """
        if scope in ("todos", "artifacts"):
            if not project_path:
                logger.debug("publish_workflow_change(%s) skipped: project_path missing", scope)
                return
            key = f"{computer}:{project_path}"
            self._todos.pop(key, None)
            self._todos_digest.pop(computer, None)
            self._notify(
                "todos_updated",
                {"computer": computer, "project_path": project_path},
            )
            return
        if scope == "roadmap":
            self._projects_digest.pop(computer, None)
            self._notify("projects_updated", {"computer": computer})
            return
        logger.warning("publish_workflow_change: unknown scope=%s", scope)

    # ==================== Data Access ====================

    def get_computers(self) -> list[ComputerInfo]:
        """Get all cached computers, including stale ones.

        Computers are refreshed via heartbeats (push model); the read path
        must not mutate state or filter entries based on TTL.

        Returns:
            List of all cached computer info objects
        """
        return [cached.data for cached in self._computers.values()]

    def get_fleet_capability_entries(self) -> list[FleetCapabilityEntry]:
        """Return cached heartbeat capability entries with their advertisement time."""
        return [
            FleetCapabilityEntry(
                computer=cached.data.name,
                version=cached.data.version,
                channel=cached.data.channel,
                capability_set=frozenset(cached.data.capability_set),
                last_advertised_at=cached.cached_at,
            )
            for cached in self._computers.values()
        ]

    def get_projects(self, computer: str | None = None) -> list[ProjectInfo]:
        """Get cached projects, optionally filtered by computer.

        Always returns all cached entries regardless of TTL. Stale reads trigger
        the on_stale_read callback once per unique computer per call.

        Args:
            computer: Optional computer name to filter by

        Returns:
            List of project info objects
        """
        projects: list[ProjectInfo] = []
        stale_computers: set[str] = set()
        for key, cached in self._projects.items():
            # Filter by computer if specified
            if computer and not key.startswith(f"{computer}:"):
                continue

            # Include computer name derived from key for optimistic rendering
            comp_name = key.split(CACHE_KEY_SEPARATOR, 1)[0] if CACHE_KEY_SEPARATOR in key else ""
            project = cached.data
            project.computer = comp_name
            projects.append(project)

            if cached.is_stale(300) and comp_name not in stale_computers:
                stale_computers.add(comp_name)

        for comp_name in stale_computers:
            self._signal_stale_read("projects", comp_name)

        return projects

    def get_projects_digest(self, computer: str) -> str | None:
        """Get the stored projects digest for a computer."""
        return self._projects_digest.get(computer)

    def get_sessions(self, computer: str | None = None) -> list[SessionSnapshot]:
        """Get cached sessions, optionally filtered by computer.

        Handles 'local' alias and exact computer name matching.

        Args:
            computer: Optional computer name or 'local' alias to filter by

        Returns:
            List of session snapshot objects
        """
        local_name = config.computer.name
        sessions = []

        for cached in self._sessions.values():
            session = cached.data
            session_computer = local_name if session.computer == LOCAL_COMPUTER else session.computer
            # Filter by computer if specified
            if computer is not None:
                # Handle 'local' alias convention
                if computer == LOCAL_COMPUTER:
                    if session_computer != local_name:
                        continue
                # Handle specific computer name (can be local or remote)
                elif session_computer != computer:
                    continue

            sessions.append(session)
        return sessions

    def get_todos(self, computer: str, project_path: str, include_removed: bool = False) -> list[TodoDTO]:
        """Get cached todos for a project.

        Always returns cached data regardless of TTL. Stale reads trigger the
        on_stale_read callback.

        Args:
            computer: Computer name
            project_path: Project path
            include_removed: Whether to include soft-removed todos

        Returns:
            List of todo info objects (empty if not cached)
        """
        key = f"{computer}:{project_path}"
        cached = self._todos.get(key)

        if not cached:
            return []

        if cached.is_stale(300):
            self._signal_stale_read("todos", computer)

        todos = cached.data
        if not include_removed:
            todos = [t for t in todos if t.status != TodoStatus.REMOVED.value]

        return todos

    def get_todo_entries(
        self,
        *,
        computer: str | None = None,
        project_path: str | None = None,
        include_removed: bool = False,
    ) -> list[TodoCacheEntry]:
        """Get cached todos with context, optionally filtered.

        Always returns all matching entries regardless of TTL. Stale reads trigger
        the on_stale_read callback once per unique computer per call.

        Args:
            computer: Optional computer name to filter by
            project_path: Optional project path to filter by
            include_removed: Whether to include soft-removed todos

        Returns:
            List of todo cache entries with context
        """
        entries: list[TodoCacheEntry] = []
        stale_computers: set[str] = set()
        for key, cached in self._todos.items():
            comp_name, path = key.split(CACHE_KEY_SEPARATOR, 1) if CACHE_KEY_SEPARATOR in key else ("", key)
            if computer and comp_name != computer:
                continue
            if project_path and path != project_path:
                continue

            todos = cached.data
            if not include_removed:
                todos = [t for t in todos if t.status != TodoStatus.REMOVED.value]

            entries.append(
                TodoCacheEntry(
                    computer=comp_name,
                    project_path=path,
                    todos=todos,
                )
            )
            if cached.is_stale(300) and comp_name not in stale_computers:
                stale_computers.add(comp_name)

        for comp_name in stale_computers:
            self._signal_stale_read("todos", comp_name)

        return entries

    # ==================== Data Updates ====================

    def update_computer(self, computer: ComputerInfo) -> None:
        """Update computer info in cache.

        Args:
            computer: Computer info object
        """
        name = computer.name
        digest = self._computer_fingerprint(computer)
        existing = self._computers.get(name)
        if existing and self._computers_digest.get(name) == digest:
            # Refresh timestamp without spamming change notifications.
            existing.data = computer
            existing.cached_at = datetime.now(UTC)
            return

        self._computers[name] = CachedItem(computer)
        self._computers_digest[name] = digest
        logger.debug("Updated computer cache: %s", name)
        self._notify("computer_updated", computer)

    def update_session(
        self,
        session: SessionSnapshot,
        *,
        from_cluster: bool = False,
    ) -> None:
        """Update session info in cache.

        Args:
            session: Session snapshot object
            from_cluster: Internal flag — set by the cluster bridge when
                materializing a remote event. Suppresses the re-publish that
                would otherwise loop the event back through Redis.
        """
        session_id = session.session_id
        is_new = session_id not in self._sessions
        self._sessions[session_id] = CachedItem(session)
        logger.debug(
            "Updated session cache: %s (computer=%s, new=%s, title=%s)",
            session_id,
            session.computer,
            is_new,
            session.title,
        )
        # Notify cache subscribers (state changes only).
        # Activity events (user input, tool use, agent output) flow through AgentActivityEvent.
        event = CacheEvent.SESSION_STARTED.value if is_new else CacheEvent.SESSION_UPDATED.value
        self._notify(event, session)
        if not from_cluster:
            channel = "cluster.session.created" if is_new else "cluster.session.updated"
            self._publish_cluster(channel, session.to_dict())

    def remove_session(self, session_id: str, *, from_cluster: bool = False) -> None:
        """Remove session from cache.

        Args:
            session_id: Session ID to remove
            from_cluster: Internal flag set by the cluster bridge to suppress
                re-publish (see :meth:`update_session`).
        """
        if session_id in self._sessions:
            self._sessions.pop(session_id)
            logger.debug("Removed session from cache: %s", session_id)
            self._notify("session_closed", {"session_id": session_id})
            if not from_cluster:
                self._publish_cluster("cluster.session.closed", {"session_id": session_id})

    def set_projects(self, computer: str, projects: list[ProjectInfo]) -> None:
        """Set projects for a computer.

        Args:
            computer: Computer name
            projects: List of project info objects
        """
        # Store each project with key = f"{computer}:{path}"
        for project in projects:
            path = project.path
            key = f"{computer}:{path}"
            project.computer = computer
            self._projects[key] = CachedItem(project)

        logger.debug("Updated projects cache for %s: %d projects", computer, len(projects))
        self._notify("projects_updated", {"computer": computer, "projects": projects})

    def set_todos(
        self,
        computer: str,
        project_path: str,
        todos: list[TodoDTO],
        *,
        event_name: str = "todos_updated",
        event_data: Mapping[str, object] | None = None,
    ) -> None:
        """Set todos for a project.

        Args:
            computer: Computer name
            project_path: Project path
            todos: List of todo info objects
            event_name: Cache event to emit (default: todos_updated)
        """
        key = f"{computer}:{project_path}"
        self._todos[key] = CachedItem(todos)
        logger.debug("Updated todos cache for %s: %d todos (event=%s)", key, len(todos), event_name)
        payload: TodoCacheNotificationPayload = {"computer": computer, "project_path": project_path, "todos": todos}
        _merge_todo_event_data(payload, event_data)
        self._notify(event_name, payload)

    async def refresh_local_todos(
        self,
        computer: str,
        project_path: str,
        event_hint: str,
        event_data: Mapping[str, object] | None = None,
    ) -> None:
        """Re-read todos from disk for a local project and update cache.

        Args:
            computer: Computer name
            project_path: Project path
            event_hint: Granular event name (todo_created/todo_updated/todo_removed)
        """
        todos = await command_handlers.list_todos(project_path)
        self.set_todos(computer, project_path, todos, event_name=event_hint, event_data=event_data)

    def apply_sessions_snapshot(
        self,
        computer: str,
        sessions: list[SessionSnapshot],
        *,
        from_cluster: bool = False,
    ) -> bool:
        """Apply a full sessions snapshot for a remote computer with reconciliation.

        The pull response from a peer lists that peer's local sessions
        authoritatively, so this replaces the cached set for ``computer``:
        cached sessions for that computer absent from the snapshot are removed
        (closed/ended sessions disappear even when their live
        ``cluster.session.closed`` event was missed), and the rest are upserted.
        ``from_cluster`` suppresses the re-publish that ``update_session`` /
        ``remove_session`` would otherwise emit, matching the bootstrap pull.

        Only call this for a remote computer; local sessions are authoritative
        from the database, not from a snapshot.
        """
        digest = self._sessions_fingerprint(sessions)
        if self._sessions_digest.get(computer) == digest:
            return False

        snapshot_ids = {session.session_id for session in sessions}
        for session_id in list(self._sessions.keys()):
            cached = self._sessions.get(session_id)
            if cached is None or cached.data.computer != computer:
                continue
            if session_id not in snapshot_ids:
                self.remove_session(session_id, from_cluster=from_cluster)

        for session in sessions:
            session.computer = computer
            self.update_session(session, from_cluster=from_cluster)

        self._sessions_digest[computer] = digest
        return True

    def apply_projects_snapshot(self, computer: str, projects: list[ProjectInfo]) -> bool:
        """Apply a full projects snapshot for a computer with change detection."""
        digest = self._projects_fingerprint(projects)
        if self._projects_digest.get(computer) == digest:
            return False

        # Remove existing projects for this computer that aren't in the snapshot
        snapshot_paths = {project.path for project in projects}
        for key in list(self._projects.keys()):
            if not key.startswith(f"{computer}:"):
                continue
            path = key.split(":", 1)[1]
            if path not in snapshot_paths:
                self._projects.pop(key, None)

        # Upsert snapshot projects
        for project in projects:
            key = f"{computer}:{project.path}"
            project.computer = computer
            self._projects[key] = CachedItem(project)

        self._projects_digest[computer] = digest
        self._projects_version[computer] = self._projects_version.get(computer, 0) + 1
        self._notify(
            "projects_snapshot",
            {"computer": computer, "version": self._projects_version[computer]},
        )
        return True

    def apply_todos_snapshot(self, computer: str, todos_by_project: dict[str, list[TodoDTO]]) -> bool:
        """Apply a full todos snapshot for a computer with change detection."""
        digest = self._todos_fingerprint(todos_by_project)
        if self._todos_digest.get(computer) == digest:
            return False

        snapshot_paths = set(todos_by_project.keys())
        for key in list(self._todos.keys()):
            if not key.startswith(f"{computer}:"):
                continue
            path = key.split(":", 1)[1]
            if path not in snapshot_paths:
                self._todos.pop(key, None)

        for project_path, todos in todos_by_project.items():
            key = f"{computer}:{project_path}"
            self._todos[key] = CachedItem(todos)

        self._todos_digest[computer] = digest
        self._todos_version[computer] = self._todos_version.get(computer, 0) + 1
        self._notify(
            "todos_snapshot",
            {"computer": computer, "version": self._todos_version[computer]},
        )
        return True

    def _projects_fingerprint(self, projects: list[ProjectInfo]) -> str:
        def _project_key(project: ProjectInfo) -> str:
            return project.path

        parts: list[str] = []
        for project in sorted(projects, key=_project_key):
            parts.append(
                "|".join(
                    [
                        project.path,
                        project.name,
                        project.description or "",
                    ]
                )
            )
        joined = "\n".join(parts)
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    def _sessions_fingerprint(self, sessions: list[SessionSnapshot]) -> str:
        parts = [
            json.dumps(session.to_dict(), sort_keys=True, default=str)
            for session in sorted(sessions, key=lambda session: session.session_id)
        ]
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

    def _computer_fingerprint(self, computer: ComputerInfo) -> str:
        payload = json.dumps(computer.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _todos_fingerprint(self, todos_by_project: dict[str, list[TodoDTO]]) -> str:
        def _todo_key(todo: TodoDTO) -> str:
            return todo.slug

        parts: list[str] = []
        for project_path in sorted(todos_by_project.keys()):
            todos = todos_by_project[project_path]
            for todo in sorted(todos, key=_todo_key):
                parts.append(
                    "|".join(
                        [
                            project_path,
                            todo.slug,
                            todo.status,
                            todo.description or "",
                            "1" if todo.has_requirements else "0",
                            "1" if todo.has_impl_plan else "0",
                            todo.build_status or "",
                            todo.review_status or "",
                            todo.deferrals_status or "",
                            ",".join(todo.files),
                            str(todo.version_total),
                            todo.lifecycle_phase or "",
                            todo.integration_phase or "",
                            todo.finalize_status or "",
                            "1" if todo.hold else "0",
                            "1" if todo.held else "0",
                            todo.hold_source or "",
                            todo.active_runner or "",
                            todo.prepare_review_verdict or "",
                        ]
                    )
                )
        joined = "\n".join(parts)
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    # ==================== Interest Management ====================

    def set_interest(self, data_type: str, computer: str) -> None:
        """Register interest in a data type for a specific computer.

        Args:
            data_type: Type of data (e.g., "sessions", "projects", "todos")
            computer: Computer name to track interest for
        """
        if data_type not in self._interest:
            self._interest[data_type] = set()
        self._interest[data_type].add(computer)
        logger.debug("Registered interest: %s for computer %s", data_type, computer)

    def has_interest(self, data_type: str, computer: str) -> bool:
        """Check if cache has interest in data type for specific computer.

        Args:
            data_type: Type of data to check
            computer: Computer name to check

        Returns:
            True if interest is active for this computer, False otherwise
        """
        return computer in self._interest.get(data_type, set())

    def remove_interest(self, data_type: str, computer: str) -> None:
        """Remove interest in a data type for a specific computer.

        Args:
            data_type: Type of data (e.g., "sessions", "projects", "todos")
            computer: Computer name to remove interest for
        """
        if data_type in self._interest:
            self._interest[data_type].discard(computer)
            # Clean up empty sets
            if not self._interest[data_type]:
                del self._interest[data_type]
            logger.debug("Removed interest: %s for computer %s", data_type, computer)

    def get_interested_computers(self, data_type: str) -> list[str]:
        """Get all computers with interest in a data type.

        Args:
            data_type: Type of data to check

        Returns:
            List of computer names with interest in this data type
        """
        return list(self._interest.get(data_type, set()))

    # ==================== Change Notifications ====================

    def subscribe(self, callback: Callable[[str, object], None]) -> None:
        """Subscribe to cache change notifications.

        Args:
            callback: Function to call on cache changes (event, data)
        """
        self._subscribers.add(callback)
        logger.debug("Added cache subscriber: %s", callback.__name__)

    def unsubscribe(self, callback: Callable[[str, object], None]) -> None:
        """Unsubscribe from cache change notifications.

        Args:
            callback: Function to remove from subscribers
        """
        self._subscribers.discard(callback)
        logger.debug("Removed cache subscriber: %s", callback.__name__)

    def _notify(self, event: str, data: object) -> None:
        """Notify all subscribers of a cache change without blocking the caller.

        Dispatches each callback via call_soon so the current coroutine
        is not held up by slow or numerous subscribers.

        Args:
            event: Event type (e.g., "session_updated", "computer_updated")
            data: Event data
        """
        if not self._subscribers:
            return
        logger.debug("Cache notification: event=%s, subscribers=%d", event, len(self._subscribers))
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop (e.g. during tests) — call synchronously
            for callback in self._subscribers:
                try:
                    callback(event, data)
                except Exception as e:
                    logger.error("Cache subscriber callback failed: %s", e, exc_info=True)
            return

        for callback in self._subscribers:

            def _safe_call(cb: Callable[[str, object], None] = callback) -> None:
                try:
                    cb(event, data)
                except Exception as e:
                    logger.error("Cache subscriber callback failed: %s", e, exc_info=True)

            loop.call_soon(_safe_call)
