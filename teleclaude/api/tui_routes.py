"""TUI-facing aggregate bootstrap endpoint."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from instrukt_ai_logging import get_logger

from teleclaude.api import (
    agents_routes,
    chiptunes_routes,
    computers_routes,
    jobs_routes,
    projects_routes,
    sessions_routes,
    settings_routes,
)
from teleclaude.api.auth import CallerIdentity, _is_tool_denied, verify_caller
from teleclaude.api.sessions_routes import ListSessionsQuery
from teleclaude.api_models import (
    AgentAvailabilityDTO,
    ChiptunesStatusDTO,
    ComputerDTO,
    JobDTO,
    ProjectWithTodosDTO,
    SessionDTO,
    SettingsDTO,
    TuiBootstrapDataDTO,
    TuiBootstrapDTO,
    TuiBootstrapErrorDTO,
    TuiBootstrapPillar,
)

if TYPE_CHECKING:
    from teleclaude.core.cache import DaemonCache

logger = get_logger(__name__)

router = APIRouter(prefix="/tui", tags=["tui"])

_CACHE: dict[str, DaemonCache | None] = {"value": None}
_DEFAULT_PILLARS: tuple[TuiBootstrapPillar, ...] = (
    "computers",
    "projects",
    "sessions",
    "availability",
    "jobs",
    "settings",
    "chiptunes",
)
_PILLAR_TOOL_NAMES: dict[TuiBootstrapPillar, str] = {
    "computers": "telec computers list",
    "projects": "telec projects list",
    "sessions": "telec sessions list",
    "availability": "telec agents availability",
    "jobs": "telec sessions list",
    "settings": "telec sessions list",
    "chiptunes": "telec sessions list",
}


def configure(cache: DaemonCache | None) -> None:
    """Wire cache; called from APIServer."""
    _CACHE["value"] = cache


def _parse_pillars(raw_pillars: str | None) -> list[TuiBootstrapPillar]:
    """Parse comma-separated pillar query value."""
    if not raw_pillars:
        return list(_DEFAULT_PILLARS)

    allowed = set(_DEFAULT_PILLARS)
    pillars: list[TuiBootstrapPillar] = []
    for value in raw_pillars.split(","):
        pillar = value.strip()
        if not pillar:
            continue
        if pillar not in allowed:
            raise HTTPException(status_code=400, detail=f"unknown TUI bootstrap pillar: {pillar}")
        if pillar not in pillars:
            pillars.append(pillar)  # type: ignore[arg-type]
    return pillars or list(_DEFAULT_PILLARS)


def _require_pillar_clearance(pillar: TuiBootstrapPillar, identity: CallerIdentity) -> None:
    """Raise when the caller is not allowed to read a bootstrap pillar."""
    tool_name = _PILLAR_TOOL_NAMES[pillar]
    if _is_tool_denied(tool_name, identity):
        role_desc = identity.system_role or identity.human_role or "unauthorized"
        raise HTTPException(
            status_code=403,
            detail=f"role '{role_desc}' is not permitted to call {tool_name}",
        )


async def _load_computers(*, identity: CallerIdentity) -> list[ComputerDTO]:
    """Load computer pillar through existing route behavior."""
    return await computers_routes.list_computers(_identity=identity)


async def _load_projects_with_todos(
    *,
    identity: CallerIdentity,
    include_removed: bool = False,
) -> list[ProjectWithTodosDTO]:
    """Load projects plus cached todos through one server-side pillar."""
    projects = await projects_routes.list_projects(_identity=identity)
    cache = _CACHE["value"]
    todo_map = {}
    if cache:
        todo_map = {
            (entry.computer, entry.project_path): entry.todos
            for entry in cache.get_todo_entries(include_removed=include_removed)
        }

    return [
        ProjectWithTodosDTO(
            computer=project.computer,
            name=project.name,
            path=project.path,
            description=project.description,
            todos=todo_map.get((project.computer, project.path), []),
        )
        for project in projects
    ]


async def _load_sessions(*, request: Request, identity: CallerIdentity) -> list[SessionDTO]:
    """Load session pillar through existing route behavior."""
    return await sessions_routes.list_sessions(
        request,
        query=ListSessionsQuery(),
        _identity=identity,
    )


async def _load_availability(*, identity: CallerIdentity) -> dict[str, AgentAvailabilityDTO]:
    """Load agent availability pillar through existing route behavior."""
    return await agents_routes.get_agent_availability(_identity=identity)


async def _load_jobs() -> list[JobDTO]:
    """Load scheduled jobs pillar."""
    return await jobs_routes.list_jobs()


async def _load_settings() -> SettingsDTO:
    """Load runtime settings pillar."""
    return await settings_routes.get_settings()


async def _load_chiptunes() -> ChiptunesStatusDTO:
    """Load chiptunes status pillar."""
    return await chiptunes_routes.chiptunes_status()


def _error_from_exception(pillar: TuiBootstrapPillar, error: Exception) -> TuiBootstrapErrorDTO:
    """Normalize a pillar exception into an API DTO."""
    message = str(error.detail) if isinstance(error, HTTPException) else str(error)
    return TuiBootstrapErrorDTO(pillar=pillar, message=message or type(error).__name__, retryable=True)


def _is_retryable_pillar_error(error: HTTPException) -> bool:
    """Return True when a route-level HTTP error represents a transient pillar failure."""
    return error.status_code >= 500


def _assign_result(data: TuiBootstrapDataDTO, pillar: TuiBootstrapPillar, value: object) -> TuiBootstrapDataDTO:
    """Return data with one successful pillar assigned."""
    match pillar:
        case "computers":
            return data.model_copy(update={"computers": value})
        case "projects":
            return data.model_copy(update={"projects_with_todos": value})
        case "sessions":
            return data.model_copy(update={"sessions": value})
        case "availability":
            return data.model_copy(update={"availability": value})
        case "jobs":
            return data.model_copy(update={"jobs": value})
        case "settings":
            return data.model_copy(update={"settings": value})
        case "chiptunes":
            return data.model_copy(update={"chiptunes": value})


def _build_loader(
    pillar: TuiBootstrapPillar,
    *,
    request: Request,
    identity: CallerIdentity,
    include_removed: bool = False,
) -> Callable[[], Awaitable[Any]]:
    """Return the async loader for a bootstrap pillar."""
    match pillar:
        case "computers":
            return lambda: _load_computers(identity=identity)
        case "projects":
            return lambda: _load_projects_with_todos(identity=identity, include_removed=include_removed)
        case "sessions":
            return lambda: _load_sessions(request=request, identity=identity)
        case "availability":
            return lambda: _load_availability(identity=identity)
        case "jobs":
            return _load_jobs
        case "settings":
            return _load_settings
        case "chiptunes":
            return _load_chiptunes


async def _load_pillar(
    pillar: TuiBootstrapPillar,
    *,
    request: Request,
    identity: CallerIdentity,
    include_removed: bool = False,
) -> tuple[TuiBootstrapPillar, object | Exception]:
    """Load one pillar, converting expected service failures into pillar errors."""
    _require_pillar_clearance(pillar, identity)
    loader = _build_loader(pillar, request=request, identity=identity, include_removed=include_removed)
    try:
        return pillar, await loader()
    except HTTPException as exc:
        if not _is_retryable_pillar_error(exc):
            raise
        return pillar, exc


@router.get("/bootstrap")
async def get_tui_bootstrap(
    request: Request,
    pillars: str | None = Query(None),
    include_removed: bool = Query(False),
    identity: CallerIdentity = Depends(verify_caller),
) -> TuiBootstrapDTO:
    """Return initial TUI state with per-pillar partial-success semantics."""
    requested = _parse_pillars(pillars)
    results = await asyncio.gather(
        *[
            _load_pillar(pillar, request=request, identity=identity, include_removed=include_removed)
            for pillar in requested
        ]
    )

    data = TuiBootstrapDataDTO()
    errors: list[TuiBootstrapErrorDTO] = []
    for pillar, result in results:
        if isinstance(result, Exception):
            logger.debug("TUI bootstrap pillar failed", pillar=pillar, error=str(result))
            errors.append(_error_from_exception(pillar, result))
            continue
        data = _assign_result(data, pillar, result)

    return TuiBootstrapDTO(requested=requested, data=data, errors=errors)
