"""FastAPI router for memory HTTP endpoints."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict

from teleclaude.api.auth import (
    CallerIdentity,
    caller_for_role_resolution,
    carried_caller,
    principal_for_carried_caller,
)
from teleclaude.core import db_models
from teleclaude.core.identity import is_procedure_agent_session
from teleclaude.identity_reach import resolve_reach
from teleclaude.memory import curation
from teleclaude.memory.search import MemorySearch
from teleclaude.memory.store import DEFAULT_PROJECT, MemoryStore, resolve_observation_project_scope
from teleclaude.memory.types import ObservationInput, ObservationType

router = APIRouter(prefix="/api/memory", tags=["memory"])

_FORBIDDEN_STATUS = 403
_CURATION_REFUSAL = (
    "Memory curation is open only to an agent the platform started for a procedure. "
    "A memory agent is started by the end of a conversation session."
)


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


class CurationMemory(BaseModel):
    """One memory or prospect in a curation scope."""

    model_config = ConfigDict(frozen=True)

    id: int
    type: str
    text: str
    created_at: str


class CurationScopeResponse(BaseModel):
    """The scope a conversation session defines, with what is already in it."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    person: str
    registered: bool
    namespace: str
    desk: bool
    home: str | None
    read_point: datetime | None
    memories: list[CurationMemory]
    prospects: list[CurationMemory]


class CurationTextRequest(BaseModel):
    """A curation request that carries a statement for a conversation session's scope."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    type: ObservationType
    text: str


class CurationUpdateRequest(BaseModel):
    """A request to replace the statement of one current memory."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    id: int
    text: str


class CurationRetireRequest(BaseModel):
    """A request to retire one current memory."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    id: int


class CurationAdvanceRequest(BaseModel):
    """A request to advance a conversation session's read point."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    to: AwareDatetime


class CurationChangedResponse(BaseModel):
    """The memory an update or retirement changed."""

    model_config = ConfigDict(frozen=True)

    id: int


class CurationAdvanceResponse(BaseModel):
    """The read point after an advance."""

    model_config = ConfigDict(frozen=True)

    read_point: datetime | None


async def _require_procedure_agent(caller: CallerIdentity) -> None:
    """Refuse every caller that is not a procedure agent under the system principal, from the daemon's own records."""
    if not caller.session_id or not await is_procedure_agent_session(caller.session_id):
        raise HTTPException(status_code=_FORBIDDEN_STATUS, detail=_CURATION_REFUSAL)


def _curation_memory(row: db_models.MemoryObservation) -> CurationMemory:
    return CurationMemory(id=row.id or 0, type=row.type, text=row.narrative or "", created_at=row.created_at)


def _refused(exc: curation.CurationRefusedError) -> HTTPException:
    return HTTPException(status_code=exc.http_status_code, detail=str(exc))


@router.get("/curation/scope")
async def curation_scope(session_id: str, caller: CallerIdentity = Depends(carried_caller)) -> CurationScopeResponse:
    """List the scope a conversation session defines."""
    await _require_procedure_agent(caller)
    try:
        listing = await curation.list_scope(session_id)
    except curation.CurationRefusedError as exc:
        raise _refused(exc) from exc
    scope = listing.scope
    return CurationScopeResponse(
        session_id=scope.session_id,
        person=scope.person.identity_key,
        registered=scope.person.registered,
        namespace=scope.namespace,
        desk=scope.is_desk,
        home=scope.desk_home.namespace if scope.desk_home is not None else None,
        read_point=scope.read_point,
        memories=[_curation_memory(row) for row in listing.memories],
        prospects=[_curation_memory(row) for row in listing.prospects],
    )


@router.post("/curation/add")
async def curation_add(
    req: CurationTextRequest, caller: CallerIdentity = Depends(carried_caller)
) -> SaveObservationResponse:
    """Add a memory about the session's person."""
    await _require_procedure_agent(caller)
    try:
        result = await curation.add_memory(req.session_id, req.type, req.text)
    except curation.CurationRefusedError as exc:
        raise _refused(exc) from exc
    return SaveObservationResponse(id=result.id, title=result.title, project=result.project)


@router.post("/curation/update")
async def curation_update(
    req: CurationUpdateRequest, caller: CallerIdentity = Depends(carried_caller)
) -> CurationChangedResponse:
    """Replace the statement of one current memory in the session's scope."""
    await _require_procedure_agent(caller)
    try:
        await curation.update_memory(req.session_id, req.id, req.text)
    except curation.CurationRefusedError as exc:
        raise _refused(exc) from exc
    return CurationChangedResponse(id=req.id)


@router.post("/curation/retire")
async def curation_retire(
    req: CurationRetireRequest, caller: CallerIdentity = Depends(carried_caller)
) -> CurationChangedResponse:
    """Retire one current memory in the session's scope."""
    await _require_procedure_agent(caller)
    try:
        await curation.retire_memory(req.session_id, req.id)
    except curation.CurationRefusedError as exc:
        raise _refused(exc) from exc
    return CurationChangedResponse(id=req.id)


@router.post("/curation/prospect")
async def curation_prospect(
    req: CurationTextRequest, caller: CallerIdentity = Depends(carried_caller)
) -> SaveObservationResponse:
    """Collect a business item from a desk conversation as a prospect."""
    await _require_procedure_agent(caller)
    try:
        result = await curation.record_prospect(req.session_id, req.type, req.text)
    except curation.CurationRefusedError as exc:
        raise _refused(exc) from exc
    return SaveObservationResponse(id=result.id, title=result.title, project=result.project)


@router.post("/curation/advance")
async def curation_advance(
    req: CurationAdvanceRequest, caller: CallerIdentity = Depends(carried_caller)
) -> CurationAdvanceResponse:
    """Advance a conversation session's read point; it never moves backwards."""
    await _require_procedure_agent(caller)
    try:
        read_point = await curation.advance_read_point(req.session_id, req.to)
    except curation.CurationRefusedError as exc:
        raise _refused(exc) from exc
    return CurationAdvanceResponse(read_point=read_point)


@router.delete("/{observation_id}")
async def delete_observation(observation_id: int) -> dict:  # type: ignore[type-arg]
    """Delete a memory observation by ID."""
    store = MemoryStore()
    deleted = await store.delete_observation(observation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Observation not found")
    return {"deleted": observation_id}
