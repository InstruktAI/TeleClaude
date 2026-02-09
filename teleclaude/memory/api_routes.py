"""FastAPI router for memory HTTP endpoints."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from teleclaude.memory.context import generate_context
from teleclaude.memory.search import MemorySearch
from teleclaude.memory.store import MemoryStore
from teleclaude.memory.types import ObservationInput, ObservationType

router = APIRouter(prefix="/api/memory", tags=["memory"])


class SaveObservationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    title: str | None = None
    project: str | None = None
    type: ObservationType = ObservationType.DISCOVERY
    concepts: list[str] | None = None
    facts: list[str] | None = None


class SaveObservationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    title: str
    project: str


class BatchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ids: list[int]
    project: str | None = None


@router.post("/save")
async def save_observation(req: SaveObservationRequest) -> SaveObservationResponse:
    """Save a memory observation."""
    inp = ObservationInput(
        text=req.text,
        title=req.title,
        project=req.project,
        type=req.type,
        concepts=req.concepts or [],
        facts=req.facts or [],
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
) -> list[dict]:
    """Search memory observations. Supports type filter for progressive disclosure."""
    search = MemorySearch()
    results = await search.search(query, project, limit, obs_type=type)
    return [asdict(r) for r in results]


@router.get("/timeline")
async def timeline(
    anchor: int,
    depth_before: int = Query(default=3, ge=0, le=20),
    depth_after: int = Query(default=3, ge=0, le=20),
    project: str | None = None,
) -> list[dict]:
    """Get observations around an anchor."""
    search = MemorySearch()
    results = await search.timeline(anchor, depth_before, depth_after, project)
    return [asdict(r) for r in results]


@router.post("/batch")
async def batch_fetch(body: BatchRequest) -> list[dict]:
    """Bulk fetch observations by IDs."""
    search = MemorySearch()
    results = await search.batch_fetch(body.ids, body.project)
    return [asdict(r) for r in results]


@router.get("/inject")
async def inject_context(projects: str) -> str:
    """Generate context for injection (replaces claude-mem /api/context/inject)."""
    project = projects.split(",")[0].strip()
    if not project:
        return ""
    return await generate_context(project)
