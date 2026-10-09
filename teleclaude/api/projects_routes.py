"""Project listing endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import (
    CallerIdentity,
    caller_for_role_resolution,
    carried_caller,
    require_clearance_at_caller_person,
)
from teleclaude.api_models import AddProjectRequest, ProjectDTO, TodoDTO
from teleclaude.config.machine import config
from teleclaude.config.project_subject_init import adopt_project_subject
from teleclaude.config_subjects import ConfigSubjectKind
from teleclaude.core import command_handlers
from teleclaude.core.configuration_clearance import (
    ConfigurationOperation,
    ConfigurationTarget,
    decide,
    standing_for_caller,
)
from teleclaude.core.events import ProjectRefreshTrigger
from teleclaude.core.models import ProjectInfo
from teleclaude.identity_reach import resolve_reach
from teleclaude.project_setup.init_flow import ProjectIdentityConflict, ProjectInitializationTrigger
from teleclaude.services.project_catalog import get_project_catalog_service

if TYPE_CHECKING:
    from teleclaude.core.cache import DaemonCache

logger = get_logger(__name__)

_PROJECT_ADOPT_COMMAND = "telec config project adopt"
_PROJECT_ADOPTION_REFUSED = "project adoption refused — required standing: {required_standing} ({reason})"
_PROJECT_PATH_REQUIRED = "project path must be an absolute path"
_PROJECT_PATH_FILE = "project path names a file"
_PROJECT_PATH_CREATE_FAILED = "project folder could not be created"
_PROJECT_REFRESH_UNAVAILABLE = "project refresh is not configured"
_PROJECT_ADOPTION_FAILED = "project adoption failed: {reason}"
_PROJECT_ADOPTION_INTERNAL_FAILED = "project adoption failed"
_PROJECT_ENTRY_MISSING = "adopted project is missing from the refreshed registry"
_PROJECT_CREATE_LOG = "Unable to remove request-created project folders after adoption failure"
_PROJECT_ADOPTION_LOG = "Project adoption failed"

_CACHE: dict[str, DaemonCache | None] = {"value": None}
ProjectRefresh = Callable[[ProjectRefreshTrigger], Awaitable[None]]
_REFRESH: dict[str, ProjectRefresh | None] = {"value": None}

router = APIRouter()


def configure(cache: DaemonCache | None, refresh_local_projects: ProjectRefresh | None = None) -> None:
    """Wire cache; called from APIServer."""
    _CACHE["value"] = cache
    if refresh_local_projects is not None:
        _REFRESH["value"] = refresh_local_projects


def _dto_from_project(project: ProjectInfo, computer_name: str) -> ProjectDTO:
    """Convert a project record into the public DTO."""
    return ProjectDTO(
        computer=computer_name,
        name=project.name,
        path=str(project.path or ""),
        description=project.description,
        subject=project.subject,
        owner=project.owner,
    )


def _build_todos_snapshot(projects: list[ProjectInfo]) -> dict[str, list[TodoDTO]]:
    """Build a cacheable todo snapshot keyed by project path."""
    todos_by_project: dict[str, list[TodoDTO]] = {}
    for project in projects:
        if project.path and project.todos:
            todos_by_project[project.path] = project.todos
    return todos_by_project


@router.get("/projects")
async def list_projects(
    computer: str | None = None,
    _identity: CallerIdentity = Depends(carried_caller),
) -> list[ProjectDTO]:
    """List projects (local + cached remote projects).

    Serves local projects from cache when available (warmed on startup,
    kept fresh by OS-managed todo watcher notifications). Falls back to
    filesystem on cache miss.
    """
    try:
        computer_name = config.computer.name
        reach = resolve_reach(caller_for_role_resolution(_identity))
        cache = _CACHE["value"]
        include_local = computer is None or computer in ("local", computer_name)
        include_remote = cache is not None and (computer is None or not include_local)
        result: list[ProjectDTO] = []

        if include_local:
            cached_local: list[ProjectInfo] | None = None

            if cache:
                cached_local_raw = cache.get_projects(computer_name)
                if cached_local_raw:
                    cached_local = [
                        project for project in cached_local_raw if (project.computer or "") == computer_name
                    ]

            if cached_local is None:
                logger.info("GET /projects: cache MISS, reading filesystem")
                raw_projects = await command_handlers.list_projects_with_todos()
                if cache:
                    cache.apply_projects_snapshot(computer_name, raw_projects)
                    todos_by_project = _build_todos_snapshot(raw_projects)
                    if todos_by_project:
                        cache.apply_todos_snapshot(computer_name, todos_by_project)
                cached_local = raw_projects

            result.extend(
                _dto_from_project(project, computer_name)
                for project in cached_local
                if reach.admits(project.subject, project.owner, None)
            )

        if include_remote and cache:
            for project in cache.get_projects(computer):
                comp_name = str(project.computer or "")
                if comp_name == computer_name:
                    continue
                if reach.admits(project.subject, project.owner, None):
                    result.append(_dto_from_project(project, comp_name))

        return result
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("list_projects failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list projects: {exc}") from exc


def _remove_created_directories(directories: list[Path]) -> None:
    """Remove directories created for a failed request, but only while empty."""
    for directory in reversed(directories):
        try:
            directory.rmdir()
        except OSError as exc:
            logger.info(_PROJECT_CREATE_LOG, path=str(directory), error=str(exc))


@router.post("/projects", response_model=ProjectDTO)
async def add_project(
    request: AddProjectRequest,
    identity: CallerIdentity = Depends(require_clearance_at_caller_person(_PROJECT_ADOPT_COMMAND)),
) -> ProjectDTO:
    """Adopt one folder through the same published operation as the CLI.

    The verb band is the dependency; the target decision runs here, before the route makes any folder
    or reads any declaration. A system principal, including the daemon, carries no person standing and
    is refused.
    """
    clearance = decide(
        standing_for_caller(caller_for_role_resolution(identity)),
        ConfigurationTarget(
            kind=ConfigSubjectKind.PROJECT,
            instance=None,
            operation=ConfigurationOperation.ADOPT,
            sections=frozenset(),
        ),
    )
    if not clearance.allowed:
        raise HTTPException(
            status_code=403,
            detail=_PROJECT_ADOPTION_REFUSED.format(
                required_standing=clearance.required_standing.value, reason=clearance.reason
            ),
        )
    requested_path = Path(request.path).expanduser()
    if not requested_path.is_absolute():
        raise HTTPException(status_code=400, detail=_PROJECT_PATH_REQUIRED)
    try:
        project_root = requested_path.resolve()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=_PROJECT_PATH_REQUIRED) from exc

    if project_root.exists() and not project_root.is_dir():
        raise HTTPException(status_code=400, detail=_PROJECT_PATH_FILE)

    created_directories: list[Path] = []
    if not project_root.exists():
        ancestor = project_root
        while not ancestor.exists():
            created_directories.append(ancestor)
            if ancestor.parent == ancestor:
                break
            ancestor = ancestor.parent
        try:
            project_root.mkdir(parents=True)
        except FileExistsError as exc:
            if project_root.is_dir():
                created_directories.clear()
            else:
                raise HTTPException(status_code=400, detail=_PROJECT_PATH_FILE) from exc
        except OSError as exc:
            raise HTTPException(status_code=400, detail=_PROJECT_PATH_CREATE_FAILED) from exc

    try:
        await asyncio.to_thread(
            adopt_project_subject,
            project_root,
            trigger=ProjectInitializationTrigger.DAEMON,
        )
    except ProjectIdentityConflict as exc:
        _remove_created_directories(created_directories)
        raise HTTPException(status_code=409, detail=_PROJECT_ADOPTION_FAILED.format(reason=str(exc))) from exc
    except (OSError, ValueError) as exc:
        _remove_created_directories(created_directories)
        raise HTTPException(status_code=400, detail=_PROJECT_ADOPTION_FAILED.format(reason=str(exc))) from exc
    except Exception as exc:
        _remove_created_directories(created_directories)
        logger.error(_PROJECT_ADOPTION_LOG, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=_PROJECT_ADOPTION_INTERNAL_FAILED) from exc

    refresh_local_projects = _REFRESH["value"]
    if refresh_local_projects is None:
        raise HTTPException(status_code=503, detail=_PROJECT_REFRESH_UNAVAILABLE)
    await refresh_local_projects(ProjectRefreshTrigger.ADOPTION)

    catalog = get_project_catalog_service()
    entry = next((candidate for candidate in catalog.list_entries() if candidate.root == project_root), None)
    if entry is None:
        raise HTTPException(status_code=500, detail=_PROJECT_ENTRY_MISSING)
    return ProjectDTO(
        computer=config.computer.name,
        name=entry.display_name,
        path=str(entry.root),
        description=entry.description,
    )
