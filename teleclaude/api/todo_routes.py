"""Todo/workflow REST endpoints for the telec CLI tool subcommands.

Exposes the next-machine state machine functions (prepare, work) and roadmap
mutation operations as REST endpoints with dual-factor caller identity
enforcement. Verdict, DOR, grounding, and finalize stamps flow through
``/stamp/{slug}``. Operator phase overrides flow through
``/mark-phase/{slug}`` and write the authoritative ``prepare_phase`` or
``work_phase`` field directly.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.api.auth import (
    CallerIdentity,
    clearance_todos_create,
    clearance_todos_integrate,
    clearance_todos_prepare,
    clearance_todos_set_deps,
    clearance_todos_work,
)
from teleclaude.api_models import OperationStatusDTO, TodoDumpRequest
from teleclaude.config import config
from teleclaude.core.next_machine.core import (
    _BUILD_VERDICT_PHASE,
    _BUILD_VERDICT_VALUES,
    _PREPARE_VERDICT_PHASES,
    _PREPARE_VERDICT_VALUES,
)
from teleclaude.core.next_machine.dep_graph import detect_circular_dependency
from teleclaude.core.next_machine.slug_resolution import resolve_canonical_project_root
from teleclaude.core.operations import get_operations_service
from teleclaude.core.operations.service import SerializedOperation
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.producer import emit_event
from teleclaude.types.state_value import StateValue

if TYPE_CHECKING:
    from teleclaude.core.next_machine.state_mutation import StateWriter
    from teleclaude.core.todos_db import TodosDb
    from teleclaude.core.todos_db._show import ShowPayload
    from teleclaude.types.state_value import StateValue

logger = get_logger(__name__)

router = APIRouter(prefix="/todos", tags=["todos"])

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


# ── Response models ─────────────────────────────────────────────────────────


class _SlugStatusResponse(BaseModel):
    """Standard ok response with slug."""

    model_config = ConfigDict(frozen=True)
    status: str
    slug: str


class _ArtifactReadResponse(BaseModel):
    """Response from artifact read."""

    model_config = ConfigDict(frozen=True)
    slug: str
    name: str
    content: str


class _ArtifactWriteResponse(BaseModel):
    """Response from artifact write."""

    model_config = ConfigDict(frozen=True)
    status: str
    slug: str
    name: str


class _SplitResponse(BaseModel):
    """Response from todo split."""

    model_config = ConfigDict(frozen=True)
    status: str
    slug: str
    children: str


class _StampResponse(BaseModel):
    """Response from todo stamp."""

    model_config = ConfigDict(frozen=True)
    status: str
    slug: str
    stamp_type: str


def _default_cwd() -> str:
    return str(config.computer.default_working_dir)


@router.post("/create", status_code=202, response_model=OperationStatusDTO, response_model_exclude_none=True)
async def todo_create(  # pyright: ignore
    slug: Annotated[str | None, Body()] = None,
    cwd: Annotated[str | None, Body()] = None,
    client_request_id: Annotated[str | None, Body()] = None,
    _identity: CallerIdentity = Depends(clearance_todos_create),
) -> SerializedOperation:
    """Run the creative lifecycle state machine.

    Submits a durable receipt-backed operation for the creative workflow.
    Returns immediately with a receipt for polling.
    """
    effective_cwd = cwd or _default_cwd()
    operations = get_operations_service()
    return await operations.submit_todo_create(
        slug=slug,
        cwd=effective_cwd,
        caller_session_id=_identity.session_id,
        client_request_id=client_request_id,
    )


@router.post("/prepare", status_code=202, response_model=OperationStatusDTO, response_model_exclude_none=True)
async def todo_prepare(  # pyright: ignore
    slug: Annotated[str | None, Body()] = None,
    cwd: Annotated[str | None, Body()] = None,
    client_request_id: Annotated[str | None, Body()] = None,
    _identity: CallerIdentity = Depends(clearance_todos_prepare),
) -> SerializedOperation:
    """Run the Phase A (prepare) state machine.

    Submits a durable receipt-backed operation for the prepare workflow.
    Returns immediately with a receipt for polling.
    """
    effective_cwd = cwd or _default_cwd()
    operations = get_operations_service()
    return await operations.submit_todo_prepare(
        slug=slug,
        cwd=effective_cwd,
        caller_session_id=_identity.session_id,
        client_request_id=client_request_id,
    )


@router.post("/work", status_code=202, response_model=OperationStatusDTO, response_model_exclude_none=True)
async def todo_work(  # pyright: ignore
    slug: Annotated[str | None, Body()] = None,
    cwd: Annotated[str | None, Body()] = None,
    client_request_id: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(clearance_todos_work),
) -> SerializedOperation:
    """Run the Phase B (work) state machine.

    Submits a durable receipt-backed operation for the build/review/fix cycle.
    Uses the caller's session_id for tracking and preserves that identity
    across the async boundary for finalize ownership. Requires clearance to
    invoke the work workflow (typically restricted to orchestrators).
    """
    if not cwd:
        raise HTTPException(status_code=400, detail="cwd required: working directory not provided")
    operations = get_operations_service()
    return await operations.submit_todo_work(
        slug=slug,
        cwd=cwd,
        caller_session_id=identity.session_id,
        client_request_id=client_request_id,
    )


@router.post("/integrate", status_code=202, response_model=OperationStatusDTO, response_model_exclude_none=True)
async def todo_integrate(  # pyright: ignore
    slug: Annotated[str | None, Body()] = None,
    cwd: Annotated[str | None, Body()] = None,
    client_request_id: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(clearance_todos_integrate),
) -> SerializedOperation:
    """Run the integration state machine.

    Submits a durable receipt-backed integration operation that preserves
    the caller's session_id for lease ownership checks inside the background
    runner. Requires integrator clearance.
    """
    if not cwd:
        raise HTTPException(status_code=400, detail="cwd required: working directory not provided")
    operations = get_operations_service()
    return await operations.submit_todo_integrate(
        slug=slug,
        cwd=cwd,
        caller_session_id=identity.session_id,
        client_request_id=client_request_id,
    )


@router.post("/set-deps")
async def todo_set_deps(  # pyright: ignore
    slug: Annotated[str, Body()],
    after: Annotated[list[str], Body()],
    cwd: Annotated[str | None, Body()] = None,
    _identity: CallerIdentity = Depends(clearance_todos_set_deps),
) -> dict[str, str]:
    """Set dependencies for a work item in the roadmap.

    Replaces all existing dependencies for the slug with the given list.
    Pass after=[] to clear all dependencies. Validates slugs and checks for
    circular dependencies. Requires clearance to modify roadmap dependencies.
    """
    if not cwd:
        raise HTTPException(status_code=400, detail="cwd required: working directory not provided")

    if not _SLUG_RE.match(slug):
        raise HTTPException(
            status_code=400,
            detail=f"invalid slug '{slug}': must be lowercase alphanumeric with hyphens only",
        )
    for dep in after:
        if not _SLUG_RE.match(dep):
            raise HTTPException(
                status_code=400,
                detail=f"invalid dependency '{dep}': must be lowercase alphanumeric with hyphens only",
            )
    if slug in after:
        raise HTTPException(status_code=400, detail=f"slug '{slug}' cannot depend on itself")

    todos_db = await _get_todos_db_from_cwd(cwd)

    if not await todos_db.slug_in_roadmap(slug):
        raise HTTPException(status_code=404, detail=f"slug '{slug}' not found in roadmap")
    for dep in after:
        if not await todos_db.slug_in_roadmap(dep):
            raise HTTPException(status_code=404, detail=f"dependency '{dep}' not found in roadmap")

    deps = await todos_db.load_deps()
    cycle = detect_circular_dependency(deps, slug, after)
    if cycle:
        cycle_str = " -> ".join(cycle)
        raise HTTPException(status_code=409, detail=f"circular dependency detected: {cycle_str}")

    await todos_db.set_deps(slug, after=after)

    msg = f"dependencies set for '{slug}': {', '.join(after)}" if after else f"dependencies cleared for '{slug}'"
    return {"result": f"OK: {msg}"}


# ---------------------------------------------------------------------------
# Artifact and stamp endpoints (todos.db backed)
# ---------------------------------------------------------------------------


async def _get_todos_db_from_cwd(cwd: str) -> TodosDb:
    """Resolve the todos DB for the given project cwd."""
    from teleclaude.core.todos_db import get_todos_db  # pylint: disable=import-outside-toplevel

    project_root = resolve_canonical_project_root(cwd)
    return await get_todos_db(project_root)


@router.get("/artifacts/{slug}/{name}")
async def read_artifact(
    slug: str,
    name: str,
    cwd: str | None = None,
) -> _ArtifactReadResponse:
    """Read a todo artifact by slug and name."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    content = await todos_db.read_artifact(slug, name)
    return _ArtifactReadResponse(slug=slug, name=name, content=content)


@router.post("/artifacts/{slug}/{name}")
async def write_artifact(
    slug: str,
    name: str,
    content: Annotated[str, Body()],
    cwd: Annotated[str | None, Body()] = None,
    updated_by: Annotated[str | None, Body()] = None,
) -> _ArtifactWriteResponse:
    """Write (create or update) a todo artifact."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    if not await todos_db.slug_in_roadmap(slug):
        raise HTTPException(status_code=404, detail=f"slug '{slug}' not found in roadmap")
    await todos_db.write_artifact(slug, name, content, updated_by=updated_by)
    return _ArtifactWriteResponse(status="ok", slug=slug, name=name)


class _ArtifactListResponse(BaseModel):
    """Response from artifact list."""

    model_config = ConfigDict(frozen=True)
    slug: str
    artifacts: list[str]


@router.get("/artifacts/{slug}")
async def list_artifacts(
    slug: str,
    cwd: str | None = None,
) -> _ArtifactListResponse:
    """List artifact names for a slug."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    names = await todos_db.list_artifacts(slug)
    return _ArtifactListResponse(slug=slug, artifacts=names)


@router.post("/dump")
async def todo_dump(request: TodoDumpRequest) -> _SlugStatusResponse:
    """Create a todo: state + artifact + roadmap entry in todos.db.

    Kind variants (see TodoDumpRequest for the full contract):
      - None (default): writes an "input" artifact; enters the normal prepare lifecycle.
      - "bug": writes a "bug" artifact; stamps DOR/grounding/verdicts via
        apply_prepared_state so derive_prepare_phase resolves to PREPARED immediately.
      - "prepped": writes the content as an "implementation-plan" artifact; stamps
        all prepare primitives so the todo is immediately ready for build.
    """
    from teleclaude.core.next_machine._types import default_state  # pylint: disable=import-outside-toplevel

    slug = request.slug
    try:
        effective_cwd = request.cwd or _default_cwd()
        todos_db = await _get_todos_db_from_cwd(effective_cwd)

        existing = await todos_db.read_state(slug)
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"Todo '{slug}' already exists")

        state = default_state()
        if request.kind == "bug":
            state["kind"] = "bug"
        elif request.kind == "prepped":
            state["kind"] = "prepped"

        async with todos_db._session() as session:  # pylint: disable=protected-access
            async with session.begin():
                await todos_db.add_to_roadmap(slug, after=request.after if request.after else None, session=session)
                await todos_db.write_state(slug, state, session=session)

                if request.kind == "bug":
                    await todos_db.write_artifact(slug, "bug", request.content, session=session)
                elif request.kind == "prepped":
                    plan_content = f"# {slug} — Implementation Plan\n\n{request.content}\n"
                    await todos_db.write_artifact(slug, "implementation-plan", plan_content, session=session)
                else:
                    input_content = f"# {slug} — Input\n\n{request.content}\n"
                    await todos_db.write_artifact(slug, "input", input_content, session=session)

        todos_db._on_mutation()  # pylint: disable=protected-access

        if request.kind in ("prepped", "bug"):
            # Stamp DOR, grounding baseline, plan_review=approve, and
            # requirements_review=skipped so derive_prepare_phase resolves to PREPARED.
            from teleclaude.core.next_machine.state_io import (  # pylint: disable=import-outside-toplevel
                apply_prepared_state,
            )

            apply_prepared_state(effective_cwd, slug)
            todos_db._on_mutation()  # pylint: disable=protected-access

        return _SlugStatusResponse(status="ok", slug=slug)
    except HTTPException:
        raise
    except Exception:
        logger.error("todo_dump failed for slug=%s", slug, exc_info=True)
        raise


@router.post("/split")
async def todo_split(
    slug: Annotated[str, Body()],
    children: Annotated[list[str], Body()],
    cwd: Annotated[str | None, Body()] = None,
) -> _SplitResponse:
    """Split a todo into children: create child state + roadmap entries, update parent breakdown."""
    from teleclaude.core.next_machine._types import default_state  # pylint: disable=import-outside-toplevel
    from teleclaude.core.next_machine.state_mutation import StateWriter  # pylint: disable=import-outside-toplevel
    from teleclaude.types.todos import BreakdownState  # pylint: disable=import-outside-toplevel

    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)

    # Verify parent exists and route the parent mutation through the validated
    # StateWriter boundary so the breakdown update is type-checked before the
    # transaction commits. Child state creation below is bootstrap of a fresh
    # record — not mutation of existing persisted state — and stays on the raw
    # default_state() path.
    parent_state = await todos_db.read_state(slug)
    if parent_state is None:
        raise HTTPException(status_code=404, detail=f"Parent todo '{slug}' not found")

    parent_input = await todos_db.read_artifact(slug, "input")
    parent_writer = StateWriter(parent_state)
    parent_writer.state.breakdown = BreakdownState(assessed=True, todos=list(children))

    async with todos_db._session() as session:  # pylint: disable=protected-access
        async with session.begin():
            for child_slug in children:
                existing = await todos_db.read_state(child_slug)
                if existing is not None:
                    raise HTTPException(status_code=409, detail=f"Child todo '{child_slug}' already exists")
                await todos_db.add_to_roadmap(child_slug, group_slug=slug, session=session)
                await todos_db.write_state(child_slug, default_state(), session=session)
                if parent_input:
                    await todos_db.write_artifact(child_slug, "input", parent_input, session=session)

            await parent_writer.commit(todos_db, slug, session=session)

    todos_db._on_mutation()  # pylint: disable=protected-access

    return _SplitResponse(status="ok", slug=slug, children=",".join(children))


@router.post("/remove")
async def todo_remove(
    slug: Annotated[str, Body()],
    cwd: Annotated[str | None, Body()] = None,
) -> _SlugStatusResponse:
    """Remove a todo: delete state, artifacts, and roadmap entry from todos.db.

    Also cleans up worktree and branch if they exist.
    """
    from teleclaude.core.next_machine.delivery import cleanup_delivered_slug  # pylint: disable=import-outside-toplevel

    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)

    async with todos_db._session() as session:  # pylint: disable=protected-access
        async with session.begin():
            await todos_db.delete_state(slug, session=session)
            await todos_db.delete_artifacts(slug, session=session)
            await todos_db.remove_from_roadmap(slug, session=session)
            await todos_db.clean_dep_references(slug, session=session)

    todos_db._on_mutation()  # pylint: disable=protected-access

    # Clean up worktree and branch (filesystem/git cleanup stays — these are code branches)
    await asyncio.to_thread(cleanup_delivered_slug, effective_cwd, slug)

    return _SlugStatusResponse(status="ok", slug=slug)


@router.post("/freeze/{slug}")
async def todo_freeze(
    slug: str,
    cwd: Annotated[str | None, Body(embed=True)] = None,
) -> _SlugStatusResponse:
    """Move a todo to icebox."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    if not await todos_db.freeze(slug):
        raise HTTPException(status_code=404, detail=f"Todo '{slug}' not found in roadmap")
    return _SlugStatusResponse(status="ok", slug=slug)


@router.post("/unfreeze/{slug}")
async def todo_unfreeze(
    slug: str,
    cwd: Annotated[str | None, Body(embed=True)] = None,
) -> _SlugStatusResponse:
    """Restore a todo from icebox to active roadmap."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    if not await todos_db.unfreeze(slug):
        raise HTTPException(status_code=404, detail=f"Todo '{slug}' not found in icebox")
    return _SlugStatusResponse(status="ok", slug=slug)


def _apply_grounding_stamp(writer: StateWriter, value: str) -> None:
    """Apply a `grounding` stamp through the typed grounding lifecycle.

    ``value == "valid"`` clears any recorded invalidation; any other value
    forces a stamped invalidation so downstream prepare machinery re-runs.
    Both branches route through :class:`GroundingManager` so the stamp path
    shares one contract with the rest of the grounding lifecycle.
    """
    from teleclaude.core.next_machine.state_mutation import (  # pylint: disable=import-outside-toplevel
        GroundingManager,
    )

    grounding_manager = GroundingManager(writer)
    if value == "valid":
        grounding_manager.clear_invalidation()
    else:
        grounding_manager.invalidate(reason="stamped_invalid", changed_paths=[])


def _apply_dor_stamp(writer: StateWriter, value: str) -> None:
    """Apply a `dor` stamp, parsing either a compound score/status or a bare status."""
    from teleclaude.types.todos import DorState  # pylint: disable=import-outside-toplevel

    dor_model = writer.state.dor or DorState()
    if "," in value and ":" in value:
        for part in value.split(","):
            k, _, v = part.partition(":")
            k, v = k.strip(), v.strip()
            if k == "score":
                dor_model.score = int(v)
            elif k == "status":
                dor_model.status = v
    else:
        dor_model.status = value
    writer.state.dor = dor_model


_ALL_VERDICT_PHASES = (*_PREPARE_VERDICT_PHASES, _BUILD_VERDICT_PHASE)


@router.post("/stamp/{slug}")
async def stamp(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-branches,too-many-locals
    slug: str,
    stamp_type: Annotated[str, Body()],
    value: Annotated[str, Body()] = "",
    phase: Annotated[str | None, Body()] = None,
    cwd: Annotated[str | None, Body()] = None,
) -> _StampResponse:
    """Stamp a verdict, DOR, grounding, specs-built, or finalize-ready value.

    Verdict stamps require an explicit ``phase`` body field — derivation-based
    state no longer tracks a persistent ``current`` pointer. Accepted phases
    are the three prepare review keys and ``build_review`` for the work lane.
    """
    from teleclaude.core.next_machine.state_io import (  # pylint: disable=import-outside-toplevel
        stamp_finalize_ready,
        stamp_verdict,
    )
    from teleclaude.core.next_machine.state_mutation import (  # pylint: disable=import-outside-toplevel
        StateMutationError,
        StateWriter,
    )

    effective_cwd = cwd or _default_cwd()

    if stamp_type == "verdict":
        if not phase:
            raise HTTPException(status_code=400, detail="verdict stamp requires explicit 'phase' body field")
        if phase not in _ALL_VERDICT_PHASES:
            raise HTTPException(
                status_code=400,
                detail=f"invalid verdict phase '{phase}': must be one of {', '.join(_ALL_VERDICT_PHASES)}",
            )
        allowed_values = _BUILD_VERDICT_VALUES if phase == _BUILD_VERDICT_PHASE else _PREPARE_VERDICT_VALUES
        if value not in allowed_values:
            raise HTTPException(
                status_code=400,
                detail=f"invalid verdict '{value}' for phase '{phase}': must be one of {', '.join(allowed_values)}",
            )
        try:
            await asyncio.to_thread(stamp_verdict, effective_cwd, slug, phase, value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _StampResponse(status="ok", slug=slug, stamp_type=stamp_type)

    if stamp_type == "finalize_ready":
        try:
            state = await asyncio.to_thread(stamp_finalize_ready, effective_cwd, slug)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        finalize_raw = state.get("finalize")
        finalize: dict[str, StateValue] = finalize_raw if isinstance(finalize_raw, dict) else {}
        sha = str(finalize.get("sha", ""))
        worker_session_id = str(finalize.get("worker_session_id", ""))
        await emit_event(
            event="domain.software-development.planning.todo_finalize_ready",
            source=f"finalizer/{worker_session_id or 'unknown'}",
            level=EventLevel.WORKFLOW,
            domain="software-development",
            visibility=EventVisibility.LOCAL,
            entity=slug,
            description=f"Finalize ready for {slug} (sha {sha[:8]})",
            payload={
                "slug": slug,
                "branch": slug,
                "sha": sha,
                "worker_session_id": worker_session_id,
            },
        )
        return _StampResponse(status="ok", slug=slug, stamp_type=stamp_type)

    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        raise HTTPException(status_code=404, detail=f"no state found for slug '{slug}'")

    try:
        writer = StateWriter(raw_state)
        if stamp_type == "grounding":
            _apply_grounding_stamp(writer, value)
        elif stamp_type == "dor":
            _apply_dor_stamp(writer, value)
        elif stamp_type == "specs_built":
            from datetime import UTC  # pylint: disable=import-outside-toplevel
            from datetime import datetime as _dt  # pylint: disable=import-outside-toplevel

            writer.state.artifacts.test_specs.produced_at = _dt.now(UTC).isoformat()
            writer.state.artifacts.test_specs.stale = False
        else:
            raise HTTPException(status_code=400, detail=f"unknown stamp type: {stamp_type}")
        await writer.commit(todos_db, slug)
    except StateMutationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _StampResponse(status="ok", slug=slug, stamp_type=stamp_type)


@router.post("/mark-phase/{slug}", response_model=None)
async def mark_phase(
    slug: str,
    phase: Annotated[str, Body()],
    cwd: Annotated[str | None, Body()] = None,
) -> dict[str, StateValue]:
    """Write the authoritative ``prepare_phase`` or ``work_phase`` field.

    The operator-override escape hatch. Dispatches on enum membership: values
    in :class:`PreparePhase` write ``prepare_phase``; values in :class:`WorkPhase`
    write ``work_phase``. Unknown values yield a 400 with both enums' valid
    values listed so callers can self-correct without a separate round-trip.

    Returns the full updated state payload so the caller can read the new
    authoritative field in the same round trip and drive subsequent decisions
    from the persisted state, not a metadata echo.
    """
    from teleclaude.core.next_machine._types import (  # pylint: disable=import-outside-toplevel
        PreparePhase,
        WorkPhase,
    )
    from teleclaude.core.next_machine.state_io import (  # pylint: disable=import-outside-toplevel
        read_phase_state,
        write_phase_state,
    )

    effective_cwd = cwd or _default_cwd()
    prepare_values = {p.value for p in PreparePhase}
    work_values = {p.value for p in WorkPhase}

    if phase in prepare_values:
        field = "prepare_phase"
    elif phase in work_values:
        field = "work_phase"
    else:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown phase value '{phase}': "
                f"prepare_phase accepts {sorted(prepare_values)}; "
                f"work_phase accepts {sorted(work_values)}"
            ),
        )

    def _apply() -> dict[str, StateValue]:
        state = dict(read_phase_state(effective_cwd, slug))
        state[field] = phase
        write_phase_state(effective_cwd, slug, state)
        return state

    return await asyncio.to_thread(_apply)


@router.get("/{slug}/show", response_model=None)
async def todo_show(
    slug: str,
    cwd: str | None = None,
) -> ShowPayload:
    """Return full show payload for a slug."""
    from teleclaude.core.todos_db._show import assemble_show_payload  # pylint: disable=import-outside-toplevel

    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    payload = await assemble_show_payload(todos_db, slug)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Todo '{slug}' not found")
    return payload
