"""Slug-addressed todo reads and actions: list, show, freeze, unfreeze, and deliver.

These requests answer for the project the caller names, on the computer that
holds it. Every addressing form of an action runs the same workflow function.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.api.claim_block import claim_block_for
from teleclaude.api.person_display import with_person_chips_on_todos
from teleclaude.api.todo_routes import _default_cwd, _get_workflow_store_from_cwd
from teleclaude.api.working_copy_request import working_copy_request_deadline
from teleclaude.api_models import TodoDTO
from teleclaude.constants import SLUG_NOT_FOUND_DETAIL
from teleclaude.core.todos_db._show import ClaimBlock, TodoShowPayload, assemble_show_payload, payload_is_active_todo
from teleclaude.project_root import resolve_project_root
from teleclaude.services.work import get_work_service
from teleclaude.services.work.slug_actions import SlugActionResult, deliver_todo, freeze_todo, unfreeze_todo

logger = get_logger(__name__)

router = APIRouter(prefix="/todos", tags=["todos"], dependencies=[Depends(working_copy_request_deadline)])


def request_project_root(cwd: str | None) -> Path:
    """Resolve the project root a request names, or refuse it as a 400."""
    try:
        return resolve_project_root(cwd or _default_cwd())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model_exclude_none=True)
async def list_todos(
    cwd: str | None = None,
    delivered_since: str | None = None,
    _identity: CallerIdentity = Depends(carried_caller),
) -> list[TodoDTO]:
    """List every todo of the project with its status; callers section the list as they present it."""
    project_root = request_project_root(cwd)
    todos = await asyncio.to_thread(
        get_work_service(str(project_root)).todo.entries,
        include_icebox=True,
        include_delivered=True,
        include_removed=True,
        delivered_since=delivered_since or None,
    )
    return with_person_chips_on_todos(todos)


@router.get("/show/{slug}")
async def show_todo(
    slug: str,
    cwd: str | None = None,
    include_removed: Annotated[bool, Query()] = False,
    include_artifact_content: Annotated[bool, Query()] = False,
    identity: CallerIdentity = Depends(carried_caller),
) -> object:
    """Return the diagnostic state payload of one todo; an active todo's carries the ``claim`` block."""
    project_root = request_project_root(cwd)
    todos_db = await _get_workflow_store_from_cwd(str(project_root))
    payload = await assemble_show_payload(
        todos_db,
        slug,
        include_removed=include_removed,
        include_artifact_content=include_artifact_content,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail=SLUG_NOT_FOUND_DETAIL.format(slug=slug))
    if payload_is_active_todo(payload):
        cast(TodoShowPayload, payload)["claim"] = await claim_block_for(project_root, slug, identity)
    return payload


@router.get("/claim/{slug}")
async def claim_of_todo(
    slug: str,
    cwd: str | None = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> ClaimBlock:
    """Return who holds one active todo's lifecycle claim, as a driver start from this computer would find it."""
    project_root = request_project_root(cwd)
    payload = await assemble_show_payload(await _get_workflow_store_from_cwd(str(project_root)), slug)
    if payload is None or not payload_is_active_todo(payload):
        raise HTTPException(status_code=404, detail=SLUG_NOT_FOUND_DETAIL.format(slug=slug))
    return await claim_block_for(project_root, slug, identity)


@router.post("/{slug}/freeze")
async def freeze_by_slug(
    slug: str,
    cwd: Annotated[str | None, Body(embed=True)] = None,
    _identity: CallerIdentity = Depends(carried_caller),
) -> dict[str, object]:  # guard: loose-dict - JSON body of a route response
    """Move a todo to the icebox."""
    return (await freeze_todo(request_project_root(cwd), slug)).to_dict()


@router.post("/{slug}/unfreeze")
async def unfreeze_by_slug(
    slug: str,
    cwd: Annotated[str | None, Body(embed=True)] = None,
    _identity: CallerIdentity = Depends(carried_caller),
) -> dict[str, object]:  # guard: loose-dict - JSON body of a route response
    """Return an iceboxed todo to the active list."""
    return (await unfreeze_todo(request_project_root(cwd), slug)).to_dict()


@router.post("/{slug}/deliver")
async def deliver_by_slug(
    slug: str,
    cwd: Annotated[str | None, Body()] = None,
    commit: Annotated[str | None, Body()] = None,
    _identity: CallerIdentity = Depends(carried_caller),
) -> dict[str, object]:  # guard: loose-dict - JSON body of a route response
    """Mark a todo delivered and clean up what its delivery leaves behind."""
    result: SlugActionResult = await deliver_todo(request_project_root(cwd), slug, commit)
    return result.to_dict()
