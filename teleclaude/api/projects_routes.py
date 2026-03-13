from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CLEARANCE_PROJECTS_LIST, CallerIdentity
from teleclaude.api_models import ProjectDTO
from teleclaude.config import config
from teleclaude.core import command_handlers
from teleclaude.core.models import ProjectInfo, TodoInfo

if TYPE_CHECKING:
    from teleclaude.core.cache import DaemonCache

logger = get_logger(__name__)

_cache: DaemonCache | None = None

router = APIRouter()


def configure(cache: DaemonCache | None) -> None:
    """Wire cache; called from APIServer."""
    global _cache
    _cache = cache


@router.get("/projects")
async def list_projects(
    computer: str | None = None,
    identity: CallerIdentity = Depends(CLEARANCE_PROJECTS_LIST),
) -> list[ProjectDTO]:
    """List projects (local + cached remote projects).

    Serves local projects from cache when available (warmed on startup,
    kept fresh by TodoWatcher). Falls back to filesystem on cache miss.
    """
    try:
        computer_name = config.computer.name
        result: list[ProjectDTO] = []

        # Try cache first for local projects
        cached_local: list[ProjectInfo] | None = None
        if _cache:
            cached_local_raw = _cache.get_projects(computer_name)
            if cached_local_raw:
                cached_local = [p for p in cached_local_raw if (p.computer or "") == computer_name]

        if cached_local:
            # Cache hit — serve from cache
            for p in cached_local:
                result.append(
                    ProjectDTO(
                        computer=computer_name,
                        name=p.name,
                        path=p.path or "",
                        description=p.description,
                    )
                )
        else:
            # Cache miss — fall back to filesystem
            logger.info("GET /projects: cache MISS, reading filesystem")
            raw_projects = await command_handlers.list_projects_with_todos()
            if _cache:
                _cache.apply_projects_snapshot(computer_name, raw_projects)
                todos_by_project: dict[str, list[TodoInfo]] = {}
                for p in raw_projects:
                    if p.path and p.todos:
                        todos_by_project[p.path] = p.todos
                if todos_by_project:
                    _cache.apply_todos_snapshot(computer_name, todos_by_project)

            for p in raw_projects:
                result.append(
                    ProjectDTO(
                        computer=computer_name,
                        name=p.name,
                        path=p.path,
                        description=p.description,
                    )
                )

        # Add cached REMOTE projects from cache (skip local to avoid duplicates)
        if _cache:
            cached_projects = _cache.get_projects(computer)
            for proj in cached_projects:
                comp_name = str(proj.computer or "")
                if comp_name == computer_name:
                    continue
                proj_path = str(proj.path or "")
                result.append(
                    ProjectDTO(
                        computer=comp_name,
                        name=proj.name,
                        path=proj_path,
                        description=proj.description,
                    )
                )

        return result
    except Exception as e:
        logger.error("list_projects failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list projects: {e}") from e
