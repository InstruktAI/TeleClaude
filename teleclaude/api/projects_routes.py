"""Project listing endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, clearance_projects_list
from teleclaude.api_models import ProjectDTO
from teleclaude.config import config
from teleclaude.core import command_handlers
from teleclaude.core.models import ProjectInfo, TodoInfo

if TYPE_CHECKING:
    from teleclaude.core.cache import DaemonCache

logger = get_logger(__name__)

_CACHE: dict[str, DaemonCache | None] = {"value": None}

router = APIRouter()


def configure(cache: DaemonCache | None) -> None:
    """Wire cache; called from APIServer."""
    _CACHE["value"] = cache


def _dto_from_project(project: ProjectInfo, computer_name: str) -> ProjectDTO:
    """Convert a project record into the public DTO."""
    return ProjectDTO(
        computer=computer_name,
        name=project.name,
        path=str(project.path or ""),
        description=project.description,
    )


def _build_todos_snapshot(projects: list[ProjectInfo]) -> dict[str, list[TodoInfo]]:
    """Build a cacheable todo snapshot keyed by project path."""
    todos_by_project: dict[str, list[TodoInfo]] = {}
    for project in projects:
        if project.path and project.todos:
            todos_by_project[project.path] = project.todos
    return todos_by_project


@router.get("/projects")
async def list_projects(
    computer: str | None = None,
    _identity: CallerIdentity = Depends(clearance_projects_list),
) -> list[ProjectDTO]:
    """List projects (local + cached remote projects).

    Serves local projects from cache when available (warmed on startup,
    kept fresh by TodoWatcher). Falls back to filesystem on cache miss.
    """
    try:
        computer_name = config.computer.name
        cache = _CACHE["value"]
        cached_local: list[ProjectInfo] | None = None

        if cache:
            cached_local_raw = cache.get_projects(computer_name)
            if cached_local_raw:
                cached_local = [project for project in cached_local_raw if (project.computer or "") == computer_name]

        if cached_local is None:
            logger.info("GET /projects: cache MISS, reading filesystem")
            raw_projects = await command_handlers.list_projects_with_todos()
            if cache:
                cache.apply_projects_snapshot(computer_name, raw_projects)
                todos_by_project = _build_todos_snapshot(raw_projects)
                if todos_by_project:
                    cache.apply_todos_snapshot(computer_name, todos_by_project)
            cached_local = raw_projects

        result = [_dto_from_project(project, computer_name) for project in cached_local]

        if cache:
            for project in cache.get_projects(computer):
                comp_name = str(project.computer or "")
                if comp_name == computer_name:
                    continue
                result.append(_dto_from_project(project, comp_name))

        return result
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("list_projects failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list projects: {exc}") from exc
