"""Central cache for remote data with TTL management and change notifications.

Provides instant reads for API endpoints and emits change events when data updates.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Generic, TypeVar

from instrukt_ai_logging import get_logger

from teleclaude.constants import CACHE_KEY_SEPARATOR, LOCAL_COMPUTER
from teleclaude.core.models import ComputerInfo, ProjectInfo, SessionSnapshot, TodoInfo

logger = get_logger(__name__)

T = TypeVar("T")


class CachedItem(Generic[T]):
    """Wrapper for cached items with timestamp tracking."""

    def __init__(self, data: T, cached_at: datetime | None = None) -> None:
        """Initialize cached item.

        Args:
            data: The cached data
            cached_at: Timestamp when data was cached (defaults to now)
        """
        self.data = data
        self.cached_at = cached_at or datetime.now(timezone.utc)

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

        age = (datetime.now(timezone.utc) - self.cached_at).total_seconds()
        return age > ttl_seconds


@dataclass(frozen=True)
class TodoCacheEntry:
    """Cached todos with context for filtering."""

    computer: str
    project_path: str
    todos: list[TodoInfo]
    is_stale: bool


class DaemonCache:
    """Central cache for remote data with TTL management.

    Data categories:
    - Computers: From heartbeats, TTL=60s
    - Projects: Pull once on access, TTL=5min
    - Sessions: Pull once + event updates, TTL=infinite
    - Todos: Pull once on access, TTL=5min
    """

    def __init__(self) -> None:
        """Initialize empty cache."""
        # Computer cache: key = computer name
        self._computers: dict[str, CachedItem[ComputerInfo]] = {}

        # Project cache: key = f"{computer}:{path}"
        self._projects: dict[str, CachedItem[ProjectInfo]] = {}

        # Session cache: key = session_id
        self._sessions: dict[str, CachedItem[SessionSnapshot]] = {}

        # Todo cache: key = f"{computer}:{project_path}"
        self._todos: dict[str, CachedItem[list[TodoInfo]]] = {}

        # Snapshot fingerprints + versions (per computer)
        self._projects_digest: dict[str, str] = {}
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

    # ==================== TTL Management ====================

    def is_stale(self, key: str, ttl_seconds: int) -> bool:
        """Check if a cached item is stale.

        Args:
            key: Cache key
            ttl_seconds: Time-to-live in seconds (0=always stale, <0=never stale)

        Returns:
            True if item is stale or missing, False otherwise
        """
        # Check each cache dictionary explicitly
        if key in self._computers:
            return self._computers[key].is_stale(ttl_seconds)
        if key in self._projects:
            return self._projects[key].is_stale(ttl_seconds)
        if key in self._sessions:
            return self._sessions[key].is_stale(ttl_seconds)
        if key in self._todos:
            return self._todos[key].is_stale(ttl_seconds)

        # Not found = stale
        return True

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

    # ==================== Data Access ====================

    def get_computers(self) -> list[ComputerInfo]:
        """Get all cached computers (auto-expires stale entries).

        Returns:
            List of computer info objects
        """
        # Filter to non-stale computers (TTL=60s)
        computers = []
        for key, cached in list(self._computers.items()):
            if cached.is_stale(60):
                self._computers.pop(key)  # Auto-expire
                logger.debug("Auto-expired stale computer: %s", key)
            else:
                computers.append(cached.data)
        return computers

    def get_projects(self, computer: str | None = None, *, include_stale: bool = False) -> list[ProjectInfo]:
        """Get cached projects, optionally filtered by computer.

        Args:
            computer: Optional computer name to filter by
            include_stale: When True, include stale entries (caller may trigger refresh)

        Returns:
            List of project info objects
        """
        projects: list[ProjectInfo] = []
        for key, cached in self._projects.items():
            # Filter by computer if specified
            if computer and not key.startswith(f"{computer}:"):
                continue

            # Filter out stale projects (TTL=5min) unless explicitly included
            if cached.is_stale(300) and not include_stale:
                continue

            # Include computer name derived from key for optimistic rendering
            comp_name = key.split(CACHE_KEY_SEPARATOR, 1)[0] if CACHE_KEY_SEPARATOR in key else ""
            project = cached.data
            project.computer = comp_name
            projects.append(project)

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
        from teleclaude.config import config

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

    def get_todos(self, computer: str, project_path: str, *, include_stale: bool = False) -> list[TodoInfo]:
        """Get cached todos for a project.

        Args:
            computer: Computer name
            project_path: Project path

        Returns:
            List of todo info objects (empty if not cached or stale unless include_stale)
        """
        key = f"{computer}:{project_path}"
        cached = self._todos.get(key)

        if not cached:
            return []
        if cached.is_stale(300) and not include_stale:  # TTL=5min
            return []

        return cached.data

    def get_todo_entries(
        self,
        *,
        computer: str | None = None,
        project_path: str | None = None,
        include_stale: bool = False,
    ) -> list[TodoCacheEntry]:
        """Get cached todos with context, optionally filtered.

        Args:
            computer: Optional computer name to filter by
            project_path: Optional project path to filter by
            include_stale: When True, include stale entries

        Returns:
            List of todo cache entries with context
        """
        entries: list[TodoCacheEntry] = []
        for key, cached in self._todos.items():
            comp_name, path = key.split(CACHE_KEY_SEPARATOR, 1) if CACHE_KEY_SEPARATOR in key else ("", key)
            if computer and comp_name != computer:
                continue
            if project_path and path != project_path:
                continue
            is_stale = cached.is_stale(300)
            if is_stale and not include_stale:
                continue
            entries.append(
                TodoCacheEntry(
                    computer=comp_name,
                    project_path=path,
                    todos=cached.data,
                    is_stale=is_stale,
                )
            )
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
            existing.cached_at = datetime.now(timezone.utc)
            return

        self._computers[name] = CachedItem(computer)
        self._computers_digest[name] = digest
        logger.debug("Updated computer cache: %s", name)
        self._notify("computer_updated", computer)

    def update_session(
        self,
        session: SessionSnapshot,
    ) -> None:
        """Update session info in cache.

        Args:
            session: Session snapshot object
        """
        session_id = session.session_id
        is_new = session_id not in self._sessions
        self._sessions[session_id] = CachedItem(session)
        logger.debug(
            "Updated session cache: %s (computer=%s, new=%s, title=%s)",
            session_id[:8],
            session.computer,
            is_new,
            session.title,
        )
        # Notify cache subscribers (state changes only).
        # Activity events (user input, tool use, agent output) flow through AgentActivityEvent.
        event = "session_started" if is_new else "session_updated"
        self._notify(event, session)

    def remove_session(self, session_id: str) -> None:
        """Remove session from cache.

        Args:
            session_id: Session ID to remove
        """
        if session_id in self._sessions:
            self._sessions.pop(session_id)
            logger.debug("Removed session from cache: %s", session_id[:8])
            self._notify("session_closed", {"session_id": session_id})

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
        todos: list[TodoInfo],
        *,
        event_name: str = "todos_updated",
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
        self._notify(event_name, {"computer": computer, "project_path": project_path, "todos": todos})

    async def refresh_local_todos(self, computer: str, project_path: str, event_hint: str) -> None:
        """Re-read todos from disk for a local project and update cache.

        Args:
            computer: Computer name
            project_path: Project path
            event_hint: Granular event name (todo_created/todo_updated/todo_removed)
        """
        from teleclaude.core import command_handlers

        todos = await command_handlers.list_todos(project_path)
        self.set_todos(computer, project_path, todos, event_name=event_hint)

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

    def apply_todos_snapshot(self, computer: str, todos_by_project: dict[str, list[TodoInfo]]) -> bool:
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

    def _computer_fingerprint(self, computer: ComputerInfo) -> str:
        payload = json.dumps(computer.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _todos_fingerprint(self, todos_by_project: dict[str, list[TodoInfo]]) -> str:
        def _todo_key(todo: TodoInfo) -> str:
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
                            str(todo.dor_score) if todo.dor_score is not None else "",
                            todo.deferrals_status or "",
                            str(todo.findings_count),
                            ",".join(todo.files),
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
        import asyncio

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
