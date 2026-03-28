"""Internal routes for OS-managed todo watcher notifications."""

from __future__ import annotations

import hmac
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core import command_handlers
from teleclaude.core.next_machine.prepare_events import invalidate_stale_preparations
from teleclaude.project_setup.todo_watcher_install import get_watcher_secret
from teleclaude.services.todo_watcher import is_dir_event_allowed, is_path_allowed

if TYPE_CHECKING:
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.models import TodoInfo

logger = get_logger(__name__)

_STATE: dict[str, DaemonCache | None] = {"cache": None}

router = APIRouter()


def configure(cache: DaemonCache | None) -> None:
    """Wire cache dependency from the API server."""
    _STATE["cache"] = cache


@router.post("/internal/watcher-notification")
async def handle_watcher_notification(request: Request) -> JSONResponse:
    """Accept a local watcher notification, validate it, and refresh cached todos."""
    if not _uses_unix_socket_transport(request):
        return JSONResponse(
            status_code=403,
            content={"detail": "watcher notifications require Unix socket transport"},
        )

    payload = await request.json()
    project_root = payload.get("project_root") if isinstance(payload, dict) else None
    changed_paths = payload.get("changed_paths") if isinstance(payload, dict) else None
    if not isinstance(project_root, str) or not isinstance(changed_paths, list):
        return JSONResponse(status_code=422, content={"detail": "invalid watcher payload"})

    received_secret = request.headers.get("X-Watcher-Secret", "")
    expected_secret = _get_watcher_secret(project_root)
    if not received_secret or not expected_secret or not hmac.compare_digest(received_secret, expected_secret):
        return JSONResponse(status_code=403, content={"detail": "invalid watcher credentials"})

    if not _project_is_trusted(project_root, _get_trusted_dirs()):
        return JSONResponse(status_code=403, content={"detail": "untrusted project root"})

    filtered_paths = _filter_changed_paths(changed_paths)
    if not filtered_paths:
        return JSONResponse(status_code=200, content={"status": "ignored"})

    await _invalidate_stale_preparations(project_root, filtered_paths)
    todos = await _recompute_todos(project_root, filtered_paths)
    digest_changed = _apply_snapshot_with_digest_check(project_root, todos)
    if digest_changed:
        _emit_change_event(project_root)

    return JSONResponse(status_code=200, content={"status": "ok"})


def _get_watcher_secret(project_root: str) -> str | None:
    """Load the persisted watcher secret for a project."""
    return get_watcher_secret(Path(project_root))


def _get_trusted_dirs() -> list[object]:
    """Return the configured trusted project directories."""
    return list(config.computer.get_all_trusted_dirs())


def _project_is_trusted(project_root: str, trusted_dirs: list[object]) -> bool:
    """Return True when the project root lives under a trusted directory."""
    project_path = _normalize_trusted_path(project_root)
    for trusted_dir in trusted_dirs:
        trusted_path_value = getattr(trusted_dir, "path", "")
        if not isinstance(trusted_path_value, str) or not trusted_path_value:
            continue
        trusted_path = _normalize_trusted_path(trusted_path_value)
        if project_path == trusted_path or project_path.startswith(f"{trusted_path}/"):
            return True
    return False


def _filter_changed_paths(changed_paths: list[object]) -> list[str]:
    """Re-apply the watcher allowlist on the daemon side."""
    filtered: list[str] = []
    for raw_path in changed_paths:
        if not isinstance(raw_path, str):
            continue
        if not (is_path_allowed(raw_path) or is_dir_event_allowed(raw_path)):
            continue
        if raw_path not in filtered:
            filtered.append(raw_path)
    return filtered


async def _invalidate_stale_preparations(project_root: str, changed_paths: list[str]) -> None:
    """Invalidate stale prepare state for affected todos."""
    invalidate_stale_preparations(project_root, changed_paths)


async def _recompute_todos(project_root: str, changed_paths: list[str]) -> list[TodoInfo]:
    """Recompute the affected project's todo snapshot once for the notification batch."""
    del changed_paths

    return await command_handlers.list_todos(project_root)


def _apply_snapshot_with_digest_check(project_root: str, todos: list[TodoInfo]) -> bool:
    """Update the cached todo snapshot only when the full snapshot digest changes."""
    cache = _STATE["cache"]
    if cache is None:
        return False

    computer_name = config.computer.name
    todos_by_project = {entry.project_path: entry.todos for entry in cache.get_todo_entries(computer=computer_name)}
    todos_by_project[project_root] = todos
    return cache.apply_todos_snapshot(computer_name, todos_by_project)


def _emit_change_event(project_root: str) -> None:
    """Hook for additional post-refresh side effects when the digest changes."""
    logger.debug("Todo watcher notification applied", extra={"project_root": project_root})


def _uses_unix_socket_transport(request: Request) -> bool:
    """Reject TCP/HTTP requests that hit the shared route table."""
    scope = getattr(request, "scope", None)
    return isinstance(scope, dict) and scope.get("client") is None


def _normalize_trusted_path(path: str) -> str:
    """Normalize paths for trust checks without touching the filesystem."""
    return str(Path(path)).replace("\\", "/").rstrip("/")
