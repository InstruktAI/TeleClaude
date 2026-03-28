"""Shared path filtering helpers for the OS-managed todo watcher."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from threading import Lock, Timer
from typing import TypedDict

import httpx
from instrukt_ai_logging import get_logger
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from teleclaude.constants import API_SOCKET_PATH

_TEMP_SUFFIXES = (".swp", ".swx", ".bak", ".tmp", "~")
_ALLOWED_FILE_SUFFIXES = (".md", ".yaml")

logger = get_logger(__name__)


class WatcherNotificationPayload(TypedDict):
    """Serialized watcher notification sent from the watcher service to the daemon."""

    project_root: str
    changed_paths: list[str]


@dataclass(frozen=True)
class WatcherNotification:
    """Debounced watcher payload delivered to the notification callback."""

    project_root: str
    changed_paths: list[str]


NotificationCallback = Callable[[WatcherNotification], Awaitable[None] | None]


class TodoWatcherProcess:
    """Observe a single project root and batch matching filesystem changes."""

    recursive = True

    def __init__(self, project_root: str, debounce_seconds: float = 1.0) -> None:
        self.project_root = project_root
        self.debounce_seconds = debounce_seconds
        self.on_notification: NotificationCallback | None = None
        self._observer = Observer()
        self._pending_paths: list[str] = []
        self._flush_timer: Timer | None = None
        self._lock = Lock()

    def handle_fs_event(
        self,
        path: str,
        *,
        event_type: str,
        dest_path: str | None = None,
        is_directory: bool = False,
    ) -> None:
        """Normalize a watchdog event and queue any matching paths."""
        matched_paths: list[str] = []
        if event_type == "moved" and dest_path is not None:
            src_path = normalize_path(self.project_root, path)
            dest_normalized_path = normalize_path(self.project_root, dest_path)
            matched_paths = evaluate_move_event(src_path, dest_normalized_path)
        else:
            normalized_path = normalize_path(self.project_root, path)
            if not normalized_path:
                return
            if is_directory:
                if is_dir_event_allowed(normalized_path):
                    matched_paths.append(normalized_path)
            elif is_path_allowed(normalized_path) or is_dir_event_allowed(normalized_path):
                matched_paths.append(normalized_path)

        if not matched_paths:
            return

        with self._lock:
            self._pending_paths.extend(matched_paths)
            if self._flush_timer is not None:
                self._flush_timer.cancel()
            self._flush_timer = Timer(self.debounce_seconds, self._flush_pending_paths)
            self._flush_timer.daemon = True
            self._flush_timer.start()

    def run(self) -> None:
        """Start the watchdog observer loop until interrupted."""
        self._observer.schedule(_TodoWatcherEventHandler(self), self.project_root, recursive=self.recursive)
        self._observer.start()
        logger.info("todo watcher started", project_root=self.project_root)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("todo watcher interrupted", project_root=self.project_root)
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the observer and cancel any pending debounce timer."""
        with self._lock:
            if self._flush_timer is not None:
                self._flush_timer.cancel()
                self._flush_timer = None
        self._observer.stop()
        self._observer.join(timeout=2.0)

    def _flush_pending_paths(self) -> None:
        with self._lock:
            changed_paths = list(dict.fromkeys(self._pending_paths))
            self._pending_paths.clear()
            self._flush_timer = None

        if not changed_paths or self.on_notification is None:
            return

        notification = WatcherNotification(
            project_root=self.project_root,
            changed_paths=changed_paths,
        )
        result = self.on_notification(notification)
        if inspect.isawaitable(result):
            asyncio.run(_run_notification(result))


async def post_watcher_notification(
    project_root: str,
    changed_paths: list[str],
    watcher_secret: str,
    *,
    socket_path: str = API_SOCKET_PATH,
) -> None:
    """POST a watcher notification to the daemon over the Unix socket API."""
    transport = httpx.AsyncHTTPTransport(uds=socket_path)
    payload = build_notification_payload(project_root, changed_paths)
    headers = {"X-Watcher-Secret": watcher_secret}
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost", timeout=5.0) as client:
        response = await client.post("/internal/watcher-notification", json=payload, headers=headers)
        response.raise_for_status()


def normalize_path(project_root: str, absolute_path: str) -> str:
    """Normalize a filesystem path to a project-relative POSIX path."""
    normalized_root = _normalize_project_root(project_root)
    normalized_path = _normalize_posix_path(absolute_path)
    if not normalized_path:
        return ""
    if not normalized_root:
        return normalized_path.lstrip("/")
    if normalized_path == normalized_root:
        return ""
    root_prefix = f"{normalized_root}/"
    if normalized_path.startswith(root_prefix):
        return normalized_path[len(root_prefix) :]
    return normalized_path.lstrip("/")


def is_path_allowed(path: str) -> bool:
    """Return True when a relative file path is relevant for todo updates."""
    normalized_path = _normalize_relative_path(path)
    if not normalized_path or _is_noise_path(normalized_path):
        return False

    parts = normalized_path.split("/")
    allowed = False
    if len(parts) == 2 and parts[0] == "todos":
        allowed = parts[1].endswith(".yaml")
    elif len(parts) == 3 and parts[0] == "todos":
        if parts[1] == "_icebox":
            allowed = parts[2] == "icebox.yaml"
        else:
            allowed = parts[2].endswith(_ALLOWED_FILE_SUFFIXES)
    elif len(parts) == 4 and parts[0] == "todos" and parts[1] == "_icebox":
        allowed = parts[3].endswith(_ALLOWED_FILE_SUFFIXES)
    elif len(parts) == 5 and parts[0] == "trees" and parts[2] == "todos":
        allowed = parts[4].endswith(_ALLOWED_FILE_SUFFIXES)

    return allowed


def is_dir_event_allowed(path: str) -> bool:
    """Return True when a relative directory path changes todo resolution."""
    normalized_path = _normalize_relative_path(path)
    if not normalized_path or _is_noise_path(normalized_path):
        return False

    parts = normalized_path.split("/")
    if len(parts) == 2 and parts[0] == "todos":
        return parts[1] != "_icebox"
    if len(parts) == 3 and parts[0] == "todos" and parts[1] == "_icebox":
        return True
    if len(parts) == 2 and parts[0] == "trees":
        return True
    return len(parts) == 4 and parts[0] == "trees" and parts[2] == "todos"


def evaluate_move_event(src: str, dst: str) -> list[str]:
    """Evaluate both sides of a move event against the shared allowlist."""
    matches: list[str] = []
    for candidate in (_normalize_relative_path(src), _normalize_relative_path(dst)):
        if not candidate:
            continue
        if is_path_allowed(candidate) or is_dir_event_allowed(candidate):
            if candidate not in matches:
                matches.append(candidate)
    return matches


def build_notification_payload(project_root: str, changed_paths: list[str]) -> WatcherNotificationPayload:
    """Build the watcher notification body."""
    return {
        "project_root": project_root,
        "changed_paths": list(changed_paths),
    }


def _normalize_project_root(project_root: str) -> str:
    """Normalize a project root to a comparable POSIX string."""
    return _normalize_posix_path(project_root).rstrip("/")


def _normalize_relative_path(path: str) -> str:
    """Normalize a potentially relative path to a clean POSIX form."""
    normalized = _normalize_posix_path(path)
    return normalized.lstrip("/")


def _normalize_posix_path(path: str) -> str:
    """Convert path separators to POSIX form without touching the filesystem."""
    raw_parts = PurePosixPath(path.replace("\\", "/")).parts
    if not raw_parts:
        return ""

    normalized_parts = [part for part in raw_parts if part not in ("", ".")]
    if not normalized_parts:
        return ""
    if normalized_parts[0] == "/":
        return "/" + "/".join(normalized_parts[1:])
    return "/".join(normalized_parts)


def _is_noise_path(path: str) -> bool:
    """Reject hidden paths and editor artifacts before allowlist matching."""
    parts = path.split("/")
    if any(part.startswith(".") for part in parts):
        return True
    name = parts[-1]
    return name.endswith(_TEMP_SUFFIXES)


class _TodoWatcherEventHandler(FileSystemEventHandler):
    """Bridge watchdog callbacks into TodoWatcherProcess batching."""

    def __init__(self, watcher: TodoWatcherProcess) -> None:
        super().__init__()
        self._watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        src_path = _coerce_event_path(event.src_path)
        if src_path is None:
            return
        self._watcher.handle_fs_event(src_path, event_type="created", is_directory=event.is_directory)

    def on_modified(self, event: FileSystemEvent) -> None:
        src_path = _coerce_event_path(event.src_path)
        if src_path is None:
            return
        self._watcher.handle_fs_event(src_path, event_type="modified", is_directory=event.is_directory)

    def on_deleted(self, event: FileSystemEvent) -> None:
        src_path = _coerce_event_path(event.src_path)
        if src_path is None:
            return
        self._watcher.handle_fs_event(src_path, event_type="deleted", is_directory=event.is_directory)

    def on_moved(self, event: FileSystemEvent) -> None:
        src_path = _coerce_event_path(event.src_path)
        dest_path = _coerce_event_path(getattr(event, "dest_path", None))
        if src_path is None:
            return
        self._watcher.handle_fs_event(
            src_path,
            event_type="moved",
            dest_path=dest_path,
            is_directory=event.is_directory,
        )


async def _run_notification(result: Awaitable[None]) -> None:
    """Await a notification callback inside a fresh event loop."""
    await result


def _coerce_event_path(path: object) -> str | None:
    """Convert watchdog path values to strings when possible."""
    return path if isinstance(path, str) else None


__all__ = [
    "NotificationCallback",
    "TodoWatcherProcess",
    "WatcherNotification",
    "WatcherNotificationPayload",
    "build_notification_payload",
    "evaluate_move_event",
    "is_dir_event_allowed",
    "is_path_allowed",
    "normalize_path",
    "post_watcher_notification",
]
