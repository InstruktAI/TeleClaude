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
from teleclaude.memory import curation, extraction_handling
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
    """The scope a conversation session or an identity defines, with what is already in it."""

    model_config = ConfigDict(frozen=True)

    session_id: str | None
    person: str
    registered: bool
    namespace: str
    desk: bool
    home: str | None
    read_point: datetime | None
    memories: list[CurationMemory]
    prospects: list[CurationMemory]


class CurationAddress(BaseModel):
    """Where a curation request is addressed: a conversation session, or an identity (and desk) with its extraction."""

    model_config = ConfigDict(frozen=True)

    session_id: str | None = None
    identity: str | None = None
    desk: str | None = None
    extraction: str | None = None


class CurationTextRequest(CurationAddress):
    """A curation request that carries a statement."""

    type: ObservationType
    text: str


class CurationUpdateRequest(CurationAddress):
    """A request to replace the statement of one current memory."""

    id: int
    text: str


class CurationRetireRequest(CurationAddress):
    """A request to retire one current memory."""

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


class ExtractionMessage(BaseModel):
    """One conversational message of an extraction's stretch."""

    model_config = ConfigDict(frozen=True)

    key: str
    timestamp: str | None
    role: str
    text: str


class ExtractionReadResponse(BaseModel):
    """An extraction with the conversation material it covers, its coverage, scope and what it already yielded."""

    model_config = ConfigDict(frozen=True)

    id: str
    status: str
    reason: str | None
    identity: str
    desk: str | None
    source_session_id: str
    from_key: str | None
    through_key: str | None
    message_count: int
    covered_at: str | None
    ready: bool
    complete: bool
    missing_sources: list[str]
    messages: list[ExtractionMessage]
    prospects: list[CurationMemory]


class ExtractionFailRequest(BaseModel):
    """The reason an extraction could not be finished."""

    model_config = ConfigDict(frozen=True)

    reason: str


class ExtractionSettledResponse(BaseModel):
    """An extraction after it was completed or failed."""

    model_config = ConfigDict(frozen=True)

    id: str
    status: str


_ADDRESS_REFUSAL = "Address a curation request by --session, or by --identity (and --desk) with its --extraction."
_BAD_REQUEST_STATUS = 400


async def _require_procedure_agent(caller: CallerIdentity) -> None:
    """Refuse every caller that is not a procedure agent under the system principal, from the daemon's own records."""
    if not caller.session_id or not await is_procedure_agent_session(caller.session_id):
        raise HTTPException(status_code=_FORBIDDEN_STATUS, detail=_CURATION_REFUSAL)


def _curation_memory(row: db_models.MemoryObservation) -> CurationMemory:
    return CurationMemory(id=row.id or 0, type=row.type, text=row.narrative or "", created_at=row.created_at)


def _refused(exc: curation.CurationRefusedError) -> HTTPException:
    return HTTPException(status_code=exc.http_status_code, detail=str(exc))


def _session_form(address: CurationAddress) -> bool:
    """Whether a request is session-addressed; a request that is neither form is refused."""
    by_session = address.session_id is not None
    by_extraction = address.identity is not None and address.extraction is not None
    if by_session == by_extraction or (by_session and (address.identity or address.extraction or address.desk)):
        raise HTTPException(status_code=_BAD_REQUEST_STATUS, detail=_ADDRESS_REFUSAL)
    return by_session


@router.get("/curation/scope")
async def curation_scope(
    session_id: str | None = None,
    identity: str | None = None,
    desk: str | None = None,
    caller: CallerIdentity = Depends(carried_caller),
) -> CurationScopeResponse:
    """List the scope a conversation session defines, or the scope an identity (and desk) names."""
    await _require_procedure_agent(caller)
    if (session_id is None) == (identity is None) or (session_id is not None and desk is not None):
        raise HTTPException(status_code=_BAD_REQUEST_STATUS, detail=_ADDRESS_REFUSAL)
    try:
        listing = (
            await curation.list_scope(session_id)
            if session_id is not None
            else await curation.list_identity_scope(identity or "", desk)
        )
    except curation.CurationRefusedError as exc:
        raise _refused(exc) from exc
    scope = listing.scope
    return CurationScopeResponse(
        session_id=session_id,
        person=scope.person.identity_key,
        registered=scope.person.registered,
        namespace=scope.namespace,
        desk=scope.is_desk,
        home=scope.desk_home.namespace if scope.desk_home is not None else None,
        read_point=listing.target.read_point,
        memories=[_curation_memory(row) for row in listing.memories],
        prospects=[_curation_memory(row) for row in listing.prospects],
    )


@router.post("/curation/add")
async def curation_add(
    req: CurationTextRequest, caller: CallerIdentity = Depends(carried_caller)
) -> SaveObservationResponse:
    """Add a memory about the session's person, or the extraction's."""
    await _require_procedure_agent(caller)
    try:
        if _session_form(req):
            result = await curation.add_memory(req.session_id or "", req.type, req.text)
        else:
            result = await curation.add_extraction_memory(
                req.identity or "", req.desk, req.extraction or "", req.type, req.text
            )
    except curation.CurationRefusedError as exc:
        raise _refused(exc) from exc
    return SaveObservationResponse(id=result.id, title=result.title, project=result.project)


@router.post("/curation/update")
async def curation_update(
    req: CurationUpdateRequest, caller: CallerIdentity = Depends(carried_caller)
) -> CurationChangedResponse:
    """Replace the statement of one current memory in the session's or the extraction's scope."""
    await _require_procedure_agent(caller)
    try:
        if _session_form(req):
            await curation.update_memory(req.session_id or "", req.id, req.text)
        else:
            await curation.update_extraction_memory(
                req.identity or "", req.desk, req.extraction or "", req.id, req.text
            )
    except curation.CurationRefusedError as exc:
        raise _refused(exc) from exc
    return CurationChangedResponse(id=req.id)


@router.post("/curation/retire")
async def curation_retire(
    req: CurationRetireRequest, caller: CallerIdentity = Depends(carried_caller)
) -> CurationChangedResponse:
    """Retire one current memory in the session's or the extraction's scope."""
    await _require_procedure_agent(caller)
    try:
        if _session_form(req):
            await curation.retire_memory(req.session_id or "", req.id)
        else:
            await curation.retire_extraction_memory(req.identity or "", req.desk, req.extraction or "", req.id)
    except curation.CurationRefusedError as exc:
        raise _refused(exc) from exc
    return CurationChangedResponse(id=req.id)


@router.post("/curation/prospect")
async def curation_prospect(
    req: CurationTextRequest, caller: CallerIdentity = Depends(carried_caller)
) -> SaveObservationResponse:
    """Collect a business item from a desk conversation as a prospect."""
    await _require_procedure_agent(caller)
    by_session = req.session_id is not None
    by_extraction = req.desk is not None and req.extraction is not None and req.identity is None
    if by_session == by_extraction or (by_session and (req.desk or req.extraction or req.identity)):
        raise HTTPException(status_code=_BAD_REQUEST_STATUS, detail=_ADDRESS_REFUSAL)
    try:
        if by_session:
            result = await curation.record_prospect(req.session_id or "", req.type, req.text)
        else:
            result = await curation.record_extraction_prospect(req.desk or "", req.extraction or "", req.type, req.text)
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


@router.get("/curation/extraction/{extraction_id}")
async def curation_extraction_read(
    extraction_id: str, caller: CallerIdentity = Depends(carried_caller)
) -> ExtractionReadResponse:
    """Read an extraction: the conversation material it covers, its coverage, scope and what it already yielded."""
    await _require_procedure_agent(caller)
    try:
        reading = await extraction_handling.read_extraction(extraction_id)
    except curation.CurationRefusedError as exc:
        raise _refused(exc) from exc
    extraction = reading.extraction
    coverage = reading.coverage
    return ExtractionReadResponse(
        id=extraction.id,
        status=extraction.status,
        reason=extraction.reason,
        identity=extraction.identity_key,
        desk=extraction.desk,
        source_session_id=extraction.source_session_id,
        from_key=extraction.from_key,
        through_key=extraction.through_key,
        message_count=extraction.message_count,
        covered_at=coverage.covered_at if coverage is not None else None,
        ready=coverage.ready if coverage is not None else False,
        complete=not reading.missing_sources,
        missing_sources=reading.missing_sources,
        messages=[
            ExtractionMessage(key=message.key, timestamp=message.timestamp, role=message.role, text=message.text)
            for message in reading.messages
        ],
        prospects=[_curation_memory(row) for row in reading.prospects],
    )


@router.post("/curation/extraction/{extraction_id}/complete")
async def curation_extraction_complete(
    extraction_id: str, caller: CallerIdentity = Depends(carried_caller)
) -> ExtractionSettledResponse:
    """Declare an extraction's changes finished; its source's progress moves through its stretch."""
    await _require_procedure_agent(caller)
    try:
        extraction = await extraction_handling.complete(extraction_id)
    except curation.CurationRefusedError as exc:
        raise _refused(exc) from exc
    return ExtractionSettledResponse(id=extraction.id, status=extraction.status)


@router.post("/curation/extraction/{extraction_id}/fail")
async def curation_extraction_fail(
    extraction_id: str, req: ExtractionFailRequest, caller: CallerIdentity = Depends(carried_caller)
) -> ExtractionSettledResponse:
    """Report that an extraction could not be finished; its stretch stays eligible."""
    await _require_procedure_agent(caller)
    try:
        extraction = await extraction_handling.fail(extraction_id, req.reason)
    except curation.CurationRefusedError as exc:
        raise _refused(exc) from exc
    return ExtractionSettledResponse(id=extraction.id, status=extraction.status)


@router.delete("/{observation_id}")
async def delete_observation(observation_id: int) -> dict:  # type: ignore[type-arg]
    """Delete a memory observation by ID."""
    store = MemoryStore()
    deleted = await store.delete_observation(observation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Observation not found")
    return {"deleted": observation_id}
