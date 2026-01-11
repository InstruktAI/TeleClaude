"""Central cache for remote data with TTL management and change notifications.

Provides instant reads for REST endpoints and emits change events when data updates.
"""

from datetime import datetime, timezone
from typing import Callable, Generic, TypeVar

from instrukt_ai_logging import get_logger

from teleclaude.core.command_handlers import ProjectInfo, TodoInfo
from teleclaude.mcp.types import ComputerInfo, SessionInfo

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
        self._sessions: dict[str, CachedItem[SessionInfo]] = {}

        # Todo cache: key = f"{computer}:{project_path}"
        self._todos: dict[str, CachedItem[list[TodoInfo]]] = {}

        # Change subscribers: callbacks notified when cache updates
        self._subscribers: set[Callable[[str, object], None]] = set()

        # Interest tracking: which views TUI has subscribed to
        # Examples: "sessions", "preparation"
        self._interest: set[str] = set()

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
            List of computer info dicts
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

    def get_projects(self, computer: str | None = None) -> list[ProjectInfo]:
        """Get cached projects, optionally filtered by computer.

        Args:
            computer: Optional computer name to filter by

        Returns:
            List of project info dicts
        """
        projects = []
        for key, cached in self._projects.items():
            # Filter by computer if specified
            if computer and not key.startswith(f"{computer}:"):
                continue

            # Filter out stale projects (TTL=5min)
            if cached.is_stale(300):
                continue

            projects.append(cached.data)
        return projects

    def get_sessions(self, computer: str | None = None) -> list[SessionInfo]:
        """Get cached sessions, optionally filtered by computer.

        Args:
            computer: Optional computer name to filter by

        Returns:
            List of session info dicts
        """
        sessions = []
        for cached in self._sessions.values():
            session = cached.data
            # Filter by computer if specified
            if computer and session.get("computer") != computer:
                continue
            sessions.append(session)
        return sessions

    def get_todos(self, computer: str, project_path: str) -> list[TodoInfo]:
        """Get cached todos for a project.

        Args:
            computer: Computer name
            project_path: Project path

        Returns:
            List of todo info dicts (empty if not cached or stale)
        """
        key = f"{computer}:{project_path}"
        cached = self._todos.get(key)

        if not cached or cached.is_stale(300):  # TTL=5min
            return []

        return cached.data

    # ==================== Data Updates ====================

    def update_computer(self, computer: ComputerInfo) -> None:
        """Update computer info in cache.

        Args:
            computer: Computer info dict
        """
        name = computer["name"]
        self._computers[name] = CachedItem(computer)
        logger.debug("Updated computer cache: %s", name)
        self._notify("computer_updated", computer)

    def update_session(self, session: SessionInfo) -> None:
        """Update session info in cache.

        Args:
            session: Session info dict
        """
        session_id = session["session_id"]
        self._sessions[session_id] = CachedItem(session)
        logger.debug("Updated session cache: %s", session_id[:8])
        self._notify("session_updated", session)

    def remove_session(self, session_id: str) -> None:
        """Remove session from cache.

        Args:
            session_id: Session ID to remove
        """
        if session_id in self._sessions:
            self._sessions.pop(session_id)
            logger.debug("Removed session from cache: %s", session_id[:8])
            self._notify("session_removed", {"session_id": session_id})

    def set_projects(self, computer: str, projects: list[ProjectInfo]) -> None:
        """Set projects for a computer.

        Args:
            computer: Computer name
            projects: List of project info dicts
        """
        # Store each project with key = f"{computer}:{path}"
        for project in projects:
            path = project["path"]
            key = f"{computer}:{path}"
            self._projects[key] = CachedItem(project)

        logger.debug("Updated projects cache for %s: %d projects", computer, len(projects))
        self._notify("projects_updated", {"computer": computer, "projects": projects})

    def set_todos(self, computer: str, project_path: str, todos: list[TodoInfo]) -> None:
        """Set todos for a project.

        Args:
            computer: Computer name
            project_path: Project path
            todos: List of todo info dicts
        """
        key = f"{computer}:{project_path}"
        self._todos[key] = CachedItem(todos)
        logger.debug("Updated todos cache for %s: %d todos", key, len(todos))
        self._notify("todos_updated", {"computer": computer, "project_path": project_path, "todos": todos})

    # ==================== Interest Management ====================

    def set_interest(self, interests: set[str]) -> None:
        """Set client interest (replaces existing interest).

        Args:
            interests: Set of interest strings (e.g., {"sessions", "preparation"})
        """
        self._interest = interests.copy()  # Copy to prevent external mutation
        logger.debug("Updated cache interest: %s", interests)

    def get_interest(self) -> set[str]:
        """Get current client interest.

        Returns:
            Set of interest strings
        """
        return self._interest.copy()

    def has_interest(self, interest: str) -> bool:
        """Check if cache has specific interest.

        Args:
            interest: Interest string to check

        Returns:
            True if interest is active, False otherwise
        """
        return interest in self._interest

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
        """Notify all subscribers of a cache change.

        Args:
            event: Event type (e.g., "session_updated", "computer_updated")
            data: Event data
        """
        logger.debug("Cache notification: event=%s, subscribers=%d", event, len(self._subscribers))
        for callback in self._subscribers:
            try:
                callback(event, data)
            except Exception as e:
                logger.error("Cache subscriber callback failed: %s", e, exc_info=True)
