"""Bug reads and known-issue suppression ledger requests.

The suppression ledger belongs to the computer that runs the log bug hunter for
the project, so these requests are answered by the computer that holds the
project; the CLI's local path reads and writes the same ledger in place.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from teleclaude.api.auth import CallerIdentity, carried_caller, principal_for_carried_caller
from teleclaude.api.todo_routes import _default_cwd
from teleclaude.api_models import BugListEntryDTO
from teleclaude.project_root import resolve_project_root
from teleclaude.services.log_bug_hunter_suppressions import (
    Disposition,
    MatchMode,
    SuppressionDict,
    SuppressionLedgerError,
    active,
    append,
    load,
    new_suppression,
    remove,
    suppressions_path_for,
)
from teleclaude.services.project_catalog import get_project_catalog_service
from teleclaude.services.project_catalog.loaders import load_project_node
from teleclaude.services.work import get_work_service

router = APIRouter(prefix="/bugs", tags=["bugs"])

_UNKNOWN_PROJECT_DETAIL = "Unknown project '{name}'."
_UNLOADABLE_PROJECT_DETAIL = "No loadable teleclaude.yml under {root}; cannot resolve project for suppression."


class SuppressionRequest(BaseModel):
    """One suppression to register in a project's ledger."""

    model_config = ConfigDict(frozen=True)

    pattern: str
    reason: str
    match: MatchMode = MatchMode.SUBSTRING
    disposition: Disposition = Disposition.WONTFIX
    source_bug: str | None = None
    expires_at: datetime | None = None
    project: str | None = None
    cwd: str | None = None


class SuppressionRegistered(BaseModel):
    """The suppression a ledger registered."""

    model_config = ConfigDict(frozen=True)

    id: str
    project: str
    match: MatchMode
    pattern: str


class SuppressionListing(BaseModel):
    """A project's active suppressions."""

    model_config = ConfigDict(frozen=True)

    project: str
    suppressions: list[SuppressionDict]


class SuppressionRemoval(BaseModel):
    """Whether a ledger held the suppression asked to be removed."""

    model_config = ConfigDict(frozen=True)

    project: str
    removed: bool


def _project_slug(project: str | None, cwd: str | None) -> str:
    """The slug the project's suppression ledger is keyed on: the named project's, else the one `cwd` is in."""
    if project and Path(project).is_absolute():
        node = load_project_node(Path(project))
        if node is None:
            raise HTTPException(status_code=400, detail=_UNLOADABLE_PROJECT_DETAIL.format(root=project))
        return node.slug
    if project:
        requested = project.casefold()
        for node in get_project_catalog_service().list_projects():
            if requested in (node.slug.casefold(), node.name.casefold()):
                return node.slug
        raise HTTPException(status_code=404, detail=_UNKNOWN_PROJECT_DETAIL.format(name=project))
    try:
        root = resolve_project_root(cwd or _default_cwd())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    node = load_project_node(root)
    if node is None:
        raise HTTPException(status_code=400, detail=_UNLOADABLE_PROJECT_DETAIL.format(root=root))
    return node.slug


@router.get("", response_model_exclude_none=True)
async def list_bugs(
    cwd: str | None = None,
    _identity: CallerIdentity = Depends(carried_caller),
) -> list[BugListEntryDTO]:
    """List the project's active bug fixes with their lifecycle progress label."""
    try:
        project_root = resolve_project_root(cwd or _default_cwd())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await asyncio.to_thread(get_work_service(str(Path(project_root))).todo.bug_entries)


@router.post("/suppressions")
async def register_suppression(
    request: SuppressionRequest,
    identity: CallerIdentity = Depends(carried_caller),
) -> SuppressionRegistered:
    """Register a known-issue suppression so the log bug hunter stops re-filing a triaged signal."""
    slug = _project_slug(request.project, request.cwd)
    principal = principal_for_carried_caller(identity, required=True)
    assert principal is not None
    entry = new_suppression(
        pattern=request.pattern,
        match=request.match,
        disposition=request.disposition,
        reason=request.reason,
        source_bug=request.source_bug,
        created_by=principal,
        expires_at=request.expires_at,
    )
    try:
        append(suppressions_path_for(slug), entry)
    except SuppressionLedgerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SuppressionRegistered(id=entry.id, project=slug, match=entry.match, pattern=entry.pattern)


@router.get("/suppressions")
async def list_suppressions(
    project: str | None = None,
    cwd: str | None = None,
    _identity: CallerIdentity = Depends(carried_caller),
) -> SuppressionListing:
    """List the project's active known-issue suppressions."""
    slug = _project_slug(project, cwd)
    try:
        ledger = load(suppressions_path_for(slug))
    except SuppressionLedgerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    entries = active(ledger, datetime.now(UTC))
    return SuppressionListing(project=slug, suppressions=[entry.to_dict() for entry in entries])


@router.delete("/suppressions/{suppression_id}")
async def remove_suppression(
    suppression_id: str,
    project: str | None = None,
    cwd: str | None = None,
    _identity: CallerIdentity = Depends(carried_caller),
) -> SuppressionRemoval:
    """Remove a known-issue suppression so its signal is eligible for filing again."""
    slug = _project_slug(project, cwd)
    try:
        removed = remove(suppressions_path_for(slug), suppression_id)
    except SuppressionLedgerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SuppressionRemoval(project=slug, removed=removed)
