"""Shared daemon-backed project actions for TUI views."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

from instrukt_ai_logging import get_logger

from teleclaude.api_models import ProjectDTO
from teleclaude.cli.api_client import APIError

_PROJECT_ADD_WORKER_GROUP = "project-add"
_PROJECT_ADD_SUCCESS_TEMPLATE = "Project '{name}' added"
_PROJECT_ADD_FAILURE_EVENT = "tui.project_add_failed"

logger = get_logger(__name__)


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

    def present_work_feedback(self, message: str | None, operation_id: str | None = None) -> None: ...

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
        if exc.work_feedback is not None:
            app.present_work_feedback(exc.work_feedback)
        else:
            logger.error(_PROJECT_ADD_FAILURE_EVENT, path=result.path, error=repr(exc), exc_info=True)
        return False
    except Exception as exc:
        logger.error(_PROJECT_ADD_FAILURE_EVENT, path=result.path, error=repr(exc), exc_info=True)
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
