"""Shared daemon-backed project actions for TUI views."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

from teleclaude.api_models import ProjectDTO
from teleclaude.cli.api_client import APIError

_PROJECT_ADD_WORKER_GROUP = "project-add"
_PROJECT_ADD_SUCCESS_TEMPLATE = "Project '{name}' added"
_ERROR_SEVERITY = "error"


class NewProjectResultLike(Protocol):
    """Path returned by the new-project modal."""

    path: str


class ProjectAPI(Protocol):
    """Daemon operation exposed to the project views."""

    async def add_project(self, path: str) -> ProjectDTO: ...


class ProjectNotifier(Protocol):
    """Minimal application surface needed by project actions."""

    api: ProjectAPI

    def notify(self, message: str, *, severity: str = "information") -> None: ...

    def notify_text(self, message: str, *, severity: str = "information") -> None: ...

    def run_worker(
        self,
        work: Awaitable[object],
        *,
        group: str,
        exclusive: bool,
    ) -> object: ...


async def save_new_project(app: ProjectNotifier, result: NewProjectResultLike) -> bool:
    """Adopt the selected folder through the daemon and report its outcome."""
    try:
        project = await app.api.add_project(result.path)
    except APIError as exc:
        app.notify_text(exc.detail, severity=_ERROR_SEVERITY)
        return False
    except Exception as exc:
        app.notify_text(str(exc), severity=_ERROR_SEVERITY)
        return False

    app.notify(_PROJECT_ADD_SUCCESS_TEMPLATE.format(name=project.name))
    return True


def start_new_project_save(app: ProjectNotifier, result: NewProjectResultLike) -> None:
    """Schedule adoption without blocking the Textual event loop."""
    app.run_worker(
        save_new_project(app, result),
        group=_PROJECT_ADD_WORKER_GROUP,
        exclusive=True,
    )
