"""List the local projects and their todos for the daemon's callers."""

import asyncio
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.api_models import TodoDTO
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.core.degradation import DegradedComponent, get_degradations
from teleclaude.core.models import ProjectInfo
from teleclaude.core.todo import assemble_todo_from_db, recently_delivered_cutoff
from teleclaude.core.workflow_store.store_refusal import STORE_REFUSALS, describe_store_refusal
from teleclaude.events.envelope import EventHomeMarker
from teleclaude.project_root import is_project_checkout
from teleclaude.services.project_catalog import get_project_catalog_service

logger = get_logger(__name__)


async def list_projects() -> list[ProjectInfo]:
    """List every present session-placement entry in registry order.

    Ephemeral request/response - no DB session required.

    Returns:
        List of project info objects.
    """
    catalog = get_project_catalog_service()
    catalog.refresh()
    return [
        ProjectInfo(
            name=entry.display_name,
            description=entry.description,
            path=str(entry.root),
            subject=(
                SubjectRef(ConfigSubjectKind(entry.kind.value), entry.identity).to_token()
                if entry.identity is not None
                else EventHomeMarker.UNKNOWN.value
            ),
            owner=entry.owner,
        )
        for entry in catalog.list_entries()
    ]


async def list_projects_with_todos() -> list[ProjectInfo]:
    """List projects with their todos included (local only)."""
    raw_projects = await list_projects()
    projects_with_todos: list[ProjectInfo] = []

    for project in raw_projects:
        todos: list[TodoDTO] = []
        if project.path and is_project_checkout(project.path):
            todos = await _list_project_todos_isolated(project.path)

        project.todos = todos
        projects_with_todos.append(project)

    return projects_with_todos


async def _list_project_todos_isolated(project_path: str) -> list[TodoDTO]:
    """List one project's todos; its store failing degrades that project alone and lists it without todos.

    Each project's workflow store is an independent unit of the listing, so one project's refusal never
    withholds the other projects from the callers that list them (startup, the API, peers, reconcilers).
    A failure is logged when it starts or changes, not on every listing that meets it again.
    """
    degradations = get_degradations()
    try:
        todos = await list_todos(project_path)
    except STORE_REFUSALS as refused:
        door = describe_store_refusal(refused, Path(project_path))
        if degradations.mark(DegradedComponent.WORKFLOW_STORE, door, subject=project_path):
            logger.error(
                "Project workflow store refused; the project is listed without todos",
                project_root=project_path,
                reason=str(refused),
                door=door,
            )
        return []
    except Exception as exc:
        if degradations.mark(DegradedComponent.WORKFLOW_STORE, str(exc), subject=project_path):
            logger.error(
                "Project workflow store failed; the project is listed without todos",
                project_root=project_path,
                reason=str(exc),
                exc_info=True,
            )
        return []
    if degradations.clear(DegradedComponent.WORKFLOW_STORE, subject=project_path):
        logger.info("Project workflow store serves again", project_root=project_path)
    return todos


async def list_todos(project_path: str) -> list[TodoDTO]:
    """List todos for a project.

    Runs the synchronous todo assembly on a worker so store resolution cannot
    block the daemon event loop. Ephemeral request/response - no DB session
    required.

    Args:
        project_path: Absolute path to project directory

    Returns:
        List of todo objects.
    """
    return await asyncio.to_thread(
        assemble_todo_from_db,
        project_path,
        include_icebox=True,
        include_delivered=True,
        delivered_since=recently_delivered_cutoff(),
        include_removed=True,
    )
