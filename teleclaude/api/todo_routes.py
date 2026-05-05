"""Todo/workflow REST endpoints for the telec CLI tool subcommands.

Exposes the next-machine state machine functions (prepare, work) and roadmap
mutation operations as REST endpoints with dual-factor caller identity
enforcement. Local todo stamping and operator phase overrides are CLI-local
mutations, not API routes.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.api.auth import (
    CallerIdentity,
    clearance_todos_artifacts_diff,
    clearance_todos_create,
    clearance_todos_integrate,
    clearance_todos_prepare,
    clearance_todos_remove,
    clearance_todos_set_deps,
    clearance_todos_work,
)
from teleclaude.api_models import OperationStatusDTO, TodoDumpRequest
from teleclaude.config import config
from teleclaude.core.next_machine._types import default_state
from teleclaude.core.next_machine.dep_graph import detect_circular_dependency
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.next_machine.slug_resolution import resolve_canonical_project_root
from teleclaude.core.next_machine.state_io import apply_prepared_state
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.operations import get_operations_service
from teleclaude.core.operations.service import SerializedOperation
from teleclaude.core.todos_db import get_todos_db
from teleclaude.core.todos_db._show import assemble_show_payload
from teleclaude.types.todos import BreakdownState

if TYPE_CHECKING:
    from teleclaude.core.next_machine.state_mutation import StateWriter
    from teleclaude.core.todos_db import TodosDb
    from teleclaude.core.todos_db._show import ShowPayload

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
# Artifact endpoints (todos.db backed)
# ---------------------------------------------------------------------------


async def _get_todos_db_from_cwd(cwd: str) -> TodosDb:
    """Resolve the todos DB for the given project cwd."""
    project_root = resolve_canonical_project_root(cwd)
    return await get_todos_db(project_root)


async def _sync_artifact_digest_state(todos_db: TodosDb, slug: str, artifact_name: str) -> None:
    """Refresh only the artifact digest stored in todo state."""
    key = {
        "input": "input",
        "requirements": "requirements",
        "implementation-plan": "implementation_plan",
    }.get(artifact_name)
    if key is None:
        return
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        return
    writer = StateWriter(raw_state)
    entry = getattr(writer.state.artifacts, key, None)
    if entry is None:
        return
    entry.digest = await todos_db.artifact_digest(slug, artifact_name)
    await writer.commit(todos_db, slug)


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
    effective_updated_by = updated_by or "api.todo.write_artifact"
    if not await todos_db.slug_in_roadmap(slug):
        raise HTTPException(status_code=404, detail=f"slug '{slug}' not found in roadmap")
    if name == "input" and await todos_db.artifact_exists(slug, "requirements"):
        raise HTTPException(
            status_code=409,
            detail=f"input artifact for '{slug}' is frozen — requirements already exist",
        )
    await todos_db.write_artifact(slug, name, content, updated_by=effective_updated_by)
    if name in {"input", "requirements", "implementation-plan"}:
        await _sync_artifact_digest_state(todos_db, slug, name)
    logger.info(
        "todo artifact write route completed",
        slug=slug,
        artifact=name,
        updated_by=effective_updated_by,
        cwd=effective_cwd,
    )
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


class _ArtifactDiffResponse(BaseModel):
    """Response from artifact diff."""

    model_config = ConfigDict(frozen=True)
    slug: str
    name: str
    old_digest: str
    new_digest: str
    diff: str


@router.get("/artifacts/{slug}/{name}/diff")
async def diff_artifact(
    slug: str,
    name: str,
    old: str,
    new: str,
    cwd: str | None = None,
    _identity: CallerIdentity = Depends(clearance_todos_artifacts_diff),
) -> _ArtifactDiffResponse:
    """Return a unified diff between two artifact versions identified by digest."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    try:
        diff = await todos_db.artifacts_diff(slug, name, old, new)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _ArtifactDiffResponse(slug=slug, name=name, old_digest=old, new_digest=new, diff=diff)


@router.post("/dump")
async def todo_dump(request: TodoDumpRequest) -> _SlugStatusResponse:
    """Create a todo: state + artifact + roadmap entry in todos.db.

    Kind variants (see TodoDumpRequest for the full contract):
      - None (default): writes an "input" artifact; enters the normal prepare lifecycle.
      - "bug": writes a "bug" artifact; stamps DOR/grounding/verdicts via
        apply_prepared_state so the canonical lifecycle is immediately `prepared`.
      - "draft": writes an "input" artifact with kind="draft" and lifecycle_phase="draft"; bypasses lifecycle.
      - "prepped": writes the content as an "implementation-plan" artifact; stamps
        all prepare primitives so the todo is immediately ready for build.
    """
    slug = request.slug
    try:
        effective_cwd = request.cwd or _default_cwd()
        todos_db = await _get_todos_db_from_cwd(effective_cwd)

        existing = await todos_db.read_state(slug)
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"Todo '{slug}' already exists")

        state = default_state()
        if request.kind in ("bug", "draft", "prepped"):
            state["kind"] = request.kind
        if request.kind == "draft":
            state["lifecycle_phase"] = LifecyclePhase.DRAFT.value

        async with todos_db._session() as session:  # pylint: disable=protected-access
            async with session.begin():
                await todos_db.add_to_roadmap(slug, after=request.after if request.after else None, session=session)
                await todos_db.write_state(slug, state, session=session)

                if request.kind == "bug":
                    await todos_db.write_artifact(
                        slug,
                        "bug",
                        request.content,
                        updated_by="api.todo.dump.bug",
                        session=session,
                    )
                elif request.kind == "prepped":
                    plan_content = f"# {slug} — Implementation Plan\n\n{request.content}\n"
                    await todos_db.write_artifact(
                        slug,
                        "implementation-plan",
                        plan_content,
                        updated_by="api.todo.dump.prepped",
                        session=session,
                    )
                else:
                    input_content = f"# {slug} — Input\n\n{request.content}\n"
                    await todos_db.write_artifact(
                        slug,
                        "input",
                        input_content,
                        updated_by="api.todo.dump",
                        session=session,
                    )

        todos_db.on_committed("todo_updated")

        if request.kind == "prepped":
            await _sync_artifact_digest_state(todos_db, slug, "implementation-plan")
        elif request.kind != "bug":
            await _sync_artifact_digest_state(todos_db, slug, "input")

        if request.kind in ("prepped", "bug"):
            # Stamp DOR, grounding baseline, and review approvals so the
            # canonical lifecycle is immediately `prepared`.
            apply_prepared_state(effective_cwd, slug)
            todos_db.on_committed("todo_updated")

        logger.info(
            "todo dump completed",
            slug=slug,
            kind=request.kind or "todo",
            cwd=effective_cwd,
            artifact="implementation-plan"
            if request.kind == "prepped"
            else ("bug" if request.kind == "bug" else "input"),
        )

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
                    await todos_db.write_artifact(
                        child_slug,
                        "input",
                        parent_input,
                        updated_by="api.todo.split.clone_input",
                        session=session,
                    )

            await parent_writer.commit(todos_db, slug, session=session)

    todos_db.on_committed("todo_updated")
    logger.info(
        "todo split completed",
        slug=slug,
        child_count=len(children),
        cwd=effective_cwd,
    )

    return _SplitResponse(status="ok", slug=slug, children=",".join(children))


@router.post("/remove", status_code=202, response_model=OperationStatusDTO, response_model_exclude_none=True)
async def todo_remove(  # pyright: ignore
    slug: Annotated[str, Body()],
    cwd: Annotated[str | None, Body()] = None,
    client_request_id: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(clearance_todos_remove),
) -> SerializedOperation:
    """Remove a todo: delete state, artifacts, roadmap entry, and clean up worktree.

    Submits a durable receipt-backed remove operation. Returns immediately
    with a receipt for polling.
    """
    effective_cwd = cwd or _default_cwd()
    operations = get_operations_service()
    return await operations.submit_todo_remove(
        slug=slug,
        cwd=effective_cwd,
        caller_session_id=identity.session_id,
        client_request_id=client_request_id,
    )


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


@router.get("/{slug}/show", response_model=None)
async def todo_show(
    slug: str,
    cwd: str | None = None,
) -> ShowPayload:
    """Return full show payload for a slug."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    payload = await assemble_show_payload(todos_db, slug)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Todo '{slug}' not found")
    return payload
