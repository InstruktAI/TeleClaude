"""FastAPI router for memory HTTP endpoints."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from teleclaude.api.auth import (
    CallerIdentity,
    caller_for_role_resolution,
    carried_caller,
    principal_for_carried_caller,
)
from teleclaude.identity_reach import resolve_reach
from teleclaude.memory.search import MemorySearch
from teleclaude.memory.store import DEFAULT_PROJECT, MemoryStore, resolve_observation_project_scope
from teleclaude.memory.types import ObservationInput, ObservationType

router = APIRouter(prefix="/api/memory", tags=["memory"])


class SaveObservationRequest(BaseModel):
    """Request body for saving a memory observation."""

    model_config = ConfigDict(frozen=True)

    text: str
    title: str | None = None
    project: str | None = None
    type: ObservationType = ObservationType.DISCOVERY
    concepts: list[str] | None = None
    facts: list[str] | None = None
    identity_key: str | None = None


class SaveObservationResponse(BaseModel):
    """Response body after saving a memory observation."""

    model_config = ConfigDict(frozen=True)

    id: int
    title: str
    project: str


@router.post("/save")
async def save_observation(
    req: SaveObservationRequest,
    caller: CallerIdentity = Depends(carried_caller),
) -> SaveObservationResponse:
    """Save a memory observation."""
    principal = principal_for_carried_caller(caller, required=True)
    project = req.project or DEFAULT_PROJECT
    subject, subject_owner = resolve_observation_project_scope(project)
    inp = ObservationInput(
        text=req.text,
        title=req.title,
        project=project,
        type=req.type,
        concepts=req.concepts or [],
        facts=req.facts or [],
        identity_key=req.identity_key,
        subject=subject,
        subject_owner=subject_owner,
        principal=principal,
    )
    store = MemoryStore()
    result = await store.save_observation(inp)
    return SaveObservationResponse(id=result.id, title=result.title, project=result.project)


@router.get("/search")
async def search_memory(
    query: str,
    limit: int = Query(default=20, ge=1, le=100),
    project: str | None = None,
    type: ObservationType | None = Query(
        default=None, description="Filter by observation type for progressive disclosure"
    ),
    identity_key: str | None = None,
    caller: CallerIdentity = Depends(carried_caller),
) -> list[dict]:  # type: ignore[type-arg]
    """Search memory observations. Supports type and identity_key filters."""
    principal_for_carried_caller(caller, required=True)
    reach = resolve_reach(caller_for_role_resolution(caller))
    search = MemorySearch()
    results = await search.search(query, reach, project, limit, obs_type=type, identity_key=identity_key)
    return [asdict(r) for r in results]


@router.get("/timeline")
async def timeline(
    anchor: int,
    depth_before: int = Query(default=3, ge=0, le=20),
    depth_after: int = Query(default=3, ge=0, le=20),
    project: str | None = None,
    caller: CallerIdentity = Depends(carried_caller),
) -> list[dict]:  # type: ignore[type-arg]
    """Get observations around an anchor."""
    principal_for_carried_caller(caller, required=True)
    reach = resolve_reach(caller_for_role_resolution(caller))
    search = MemorySearch()
    results = await search.timeline(anchor, reach, depth_before, depth_after, project)
    return [asdict(r) for r in results]


@router.delete("/{observation_id}")
async def delete_observation(observation_id: int) -> dict:  # type: ignore[type-arg]
    """Delete a memory observation by ID."""
    store = MemoryStore()
    deleted = await store.delete_observation(observation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Observation not found")
    return {"deleted": observation_id}
