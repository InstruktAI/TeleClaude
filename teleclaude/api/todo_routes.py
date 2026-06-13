"""Todo/workflow REST endpoints for the telec CLI tool subcommands.

Exposes the next-machine state machine functions (prepare, work) and todo
mutation operations as REST endpoints with dual-factor caller identity
enforcement. Local todo stamping remains a CLI-local mutation.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.api.auth import (
    CallerIdentity,
    clearance_todos_artifacts_diff,
    clearance_todos_artifacts_remove,
    clearance_todos_create,
    clearance_todos_integrate,
    clearance_todos_prepare,
    clearance_todos_reactivate,
    clearance_todos_remove,
    clearance_todos_update,
    clearance_todos_work,
)
from teleclaude.api.kind_mapper import map_v1_kind_to_canonical
from teleclaude.api_models import OperationStatusDTO, TodoDumpRequest
from teleclaude.config import config
from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_INPUT,
    ARTIFACT_NAMES_RETIRED,
    ARTIFACT_NAMES_WRITABLE,
    ARTIFACT_PRD,
    ARTIFACT_REQUIREMENTS,
    ARTIFACT_TASK_PLAN,
)
from teleclaude.core.next_machine._types import StateValue, default_state
from teleclaude.core.next_machine.dep_graph import detect_circular_dependency
from teleclaude.core.next_machine.kind_migration import (
    KindMigrationRequiresForce,
    KindMigrationResult,
    migrate_todo_kind,
)
from teleclaude.core.next_machine.kinds import KIND_ENTRY_PHASE, canonical_kind
from teleclaude.core.next_machine.provenance import clear_artifact_provenance, sync_artifact_provenance
from teleclaude.core.next_machine.state_io import apply_prepared_state
from teleclaude.core.next_machine.state_mutation import StateMutationError, StateWriter
from teleclaude.core.operations import get_operations_service
from teleclaude.core.operations.service import SerializedOperation
from teleclaude.core.todos_db import HolderWriteRefused, get_todos_db
from teleclaude.core.todos_db._roadmap_soft_delete import ReactivateRefused
from teleclaude.core.todos_db._show import assemble_show_payload
from teleclaude.events.envelope import EventLevel
from teleclaude.events.producer import emit_event
from teleclaude.project_root import resolve_state_root
from teleclaude.snippet_validation import snippet_body_digest
from teleclaude.types.lifecycle import WORK_LIFECYCLE_PHASES, LifecyclePhase
from teleclaude.types.todo_kind import ALL_DUMP_KINDS, TODO_KIND_CHANGE, TODO_KIND_TASK

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb
    from teleclaude.core.todos_db._show import ShowPayload

logger = get_logger(__name__)

router = APIRouter(prefix="/todos", tags=["todos"])

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
_DRIFT_TRACKED_ARTIFACT_NAMES = {
    ARTIFACT_INPUT,
    ARTIFACT_PRD,
    ARTIFACT_REQUIREMENTS,
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_TASK_PLAN,
}


def _initial_todo_state_for_kind(kind: str | None) -> dict[str, StateValue]:
    """Return the initial persisted state for a newly created todo kind."""
    state = default_state()
    if kind is None:
        state["kind"] = None
        state.pop("lifecycle_phase", None)
        return state

    canonical = canonical_kind(kind)
    state["kind"] = canonical
    entry_phase = KIND_ENTRY_PHASE[canonical]
    if entry_phase in (LifecyclePhase.DIAGNOSE, LifecyclePhase.PREPARED):
        state["lifecycle_phase"] = entry_phase.value
    return state


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


class _ArtifactRemoveResponse(BaseModel):
    """Response from artifact removal."""

    model_config = ConfigDict(frozen=True)
    status: str
    slug: str
    name: str
    removed: bool
    versions_deleted: int


class _SplitResponse(BaseModel):
    """Response from todo split."""

    model_config = ConfigDict(frozen=True)
    status: str
    slug: str
    children: str


class _TodoUpdateResponse(BaseModel):
    """Response from synchronous todo update legs."""

    model_config = ConfigDict(frozen=True)
    status: str
    slug: str
    kind: str | None = None
    lifecycle_phase: str | None = None
    after: list[str] | None = None
    warnings: list[str]
    folded_artifact: str | None = None


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


@router.post("/update", response_model=None)
async def todo_update(  # pyright: ignore
    slug: Annotated[str, Body()],
    new_slug: Annotated[str | None, Body()] = None,
    after: Annotated[list[str] | None, Body()] = None,
    kind: Annotated[str | None, Body()] = None,
    force: Annotated[bool, Body()] = False,
    cwd: Annotated[str | None, Body()] = None,
    client_request_id: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(clearance_todos_update),
) -> SerializedOperation | _TodoUpdateResponse:
    """Update a todo slug, dependencies, or kind through one mutation facade."""
    if not cwd:
        raise HTTPException(status_code=400, detail="cwd required: working directory not provided")
    if new_slug is None and after is None and kind is None:
        raise HTTPException(status_code=400, detail="at least one of new_slug, after, or kind is required")

    _validate_slug_for_update(slug, field_name="slug")
    if new_slug is not None:
        _validate_slug_for_update(new_slug, field_name="new_slug")
    if kind is not None and kind not in ALL_DUMP_KINDS:
        raise HTTPException(status_code=400, detail=f"unknown todo kind: {kind!r}")

    requested_after = after
    if requested_after is not None:
        for dep in requested_after:
            _validate_slug_for_update(dep, field_name="dependency")
        if slug in requested_after:
            raise HTTPException(status_code=400, detail=f"slug '{slug}' cannot depend on itself")

    warnings: list[str] = []
    migration_result: KindMigrationResult | None = None
    todos_db = await _get_todos_db_from_cwd(cwd)

    if not await todos_db.slug_in_roadmap(slug):
        raise HTTPException(status_code=404, detail=f"slug '{slug}' not found in todo list")

    if (new_slug is not None or kind is not None) and await _todo_build_started(todos_db, slug):
        raise HTTPException(
            status_code=409, detail=f"slug and kind updates are refused after build starts for '{slug}'"
        )

    if kind is not None:
        try:
            migration_result = await migrate_todo_kind(todos_db, slug, target_kind=kind, force=force)
        except KindMigrationRequiresForce as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StateMutationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        warnings.extend(migration_result["warnings"])

    if requested_after is not None:
        for dep in requested_after:
            if not await todos_db.slug_in_roadmap(dep):
                raise HTTPException(status_code=404, detail=f"dependency '{dep}' not found in todo list")

        deps = await todos_db.load_deps()
        cycle = detect_circular_dependency(deps, slug, requested_after)
        if cycle:
            cycle_str = " -> ".join(cycle)
            raise HTTPException(status_code=409, detail=f"circular dependency detected: {cycle_str}")

        await todos_db.set_deps(slug, after=requested_after)

    if new_slug is not None:
        operations = get_operations_service()
        logger.info(
            "todo update route delegating rename",
            slug=slug,
            new_slug=new_slug,
            kind=migration_result["kind"] if migration_result else None,
            after=requested_after,
            cwd=cwd,
        )
        return await operations.submit_todo_rename(
            old_slug=slug,
            new_slug=new_slug,
            cwd=cwd,
            caller_session_id=identity.session_id,
            client_request_id=client_request_id,
        )

    logger.info(
        "todo update route completed",
        slug=slug,
        kind=migration_result["kind"] if migration_result else None,
        lifecycle_phase=migration_result["lifecycle_phase"] if migration_result else None,
        orphaned_artifacts=migration_result["orphaned_artifacts"] if migration_result else None,
        after=requested_after,
        cwd=cwd,
    )
    return _TodoUpdateResponse(
        status="ok",
        slug=slug,
        kind=migration_result["kind"] if migration_result else None,
        lifecycle_phase=migration_result["lifecycle_phase"] if migration_result else None,
        after=requested_after,
        warnings=warnings,
        folded_artifact=migration_result.get("folded_artifact") if migration_result else None,
    )


def _validate_slug_for_update(slug: str, *, field_name: str) -> None:
    if not _SLUG_RE.match(slug):
        raise HTTPException(
            status_code=400,
            detail=f"invalid {field_name} '{slug}': must be lowercase alphanumeric with hyphens only",
        )


async def _todo_build_started(todos_db: TodosDb, slug: str) -> bool:
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        raise HTTPException(status_code=404, detail=f"slug '{slug}' not found in todo list")
    writer = StateWriter(raw_state)
    phase = writer.state.lifecycle_phase
    if writer.state.build_start_base_sha:
        return True
    return phase in {work_phase.value for work_phase in WORK_LIFECYCLE_PHASES}


# ---------------------------------------------------------------------------
# Artifact endpoints (todos.db backed)
# ---------------------------------------------------------------------------


async def _get_todos_db_from_cwd(cwd: str) -> TodosDb:
    """Resolve the todos DB for the given project cwd."""
    project_root = resolve_state_root(cwd)
    return await get_todos_db(project_root)


async def _sync_artifact_provenance_state(
    todos_db: TodosDb, slug: str, artifact_name: str, *, repo_root: str, artifact_body: str
) -> None:
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        return
    writer = StateWriter(raw_state)
    await sync_artifact_provenance(
        todos_db,
        writer,
        slug,
        artifact_name,
        repo_root=repo_root,
        artifact_body=artifact_body,
        snippet_digest_fn=snippet_body_digest,
    )
    await writer.commit(todos_db, slug)


async def _clear_artifact_provenance_state(todos_db: TodosDb, slug: str, artifact_name: str) -> None:
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        return
    writer = StateWriter(raw_state)
    clear_artifact_provenance(writer, slug, artifact_name)
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
    codebase_sha_at_write: Annotated[str | None, Body()] = None,
    referenced_paths: Annotated[list[str] | None, Body()] = None,
) -> _ArtifactWriteResponse:
    """Write (create or update) a todo artifact."""
    if name not in ARTIFACT_NAMES_WRITABLE:
        if name in ARTIFACT_NAMES_RETIRED:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"artifact kind '{name}' is retired: no longer produced. "
                    "Reads and removes of pre-cutover todos remain supported; "
                    "writes are refused."
                ),
            )
        raise HTTPException(
            status_code=422,
            detail=f"unknown artifact kind '{name}'",
        )
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    effective_updated_by = updated_by or "api.todo.write_artifact"
    if not await todos_db.slug_in_roadmap(slug):
        raise HTTPException(status_code=404, detail=f"slug '{slug}' not found in todo list")
    if await todos_db.is_holder(slug):
        raise HTTPException(
            status_code=409,
            detail=(
                f"todo '{slug}' was split into children and is now a holder; it carries no "
                "artifacts or state — write to its children instead"
            ),
        )
    if name == ARTIFACT_INPUT and await todos_db.artifact_exists(slug, ARTIFACT_REQUIREMENTS):
        raise HTTPException(
            status_code=409,
            detail=f"input artifact for '{slug}' is frozen — requirements already exist",
        )
    try:
        await todos_db.write_artifact(slug, name, content, updated_by=effective_updated_by)
        _ = codebase_sha_at_write, referenced_paths
        if name in _DRIFT_TRACKED_ARTIFACT_NAMES:
            await _sync_artifact_provenance_state(
                todos_db,
                slug,
                name,
                repo_root=effective_cwd,
                artifact_body=content,
            )
    except HolderWriteRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logger.info(
        "todo artifact write route completed",
        slug=slug,
        artifact=name,
        updated_by=effective_updated_by,
        cwd=effective_cwd,
    )
    return _ArtifactWriteResponse(status="ok", slug=slug, name=name)


@router.delete("/artifacts/{slug}/{name}")
async def remove_artifact(
    slug: str,
    name: str,
    cwd: str | None = None,
    _identity: CallerIdentity = Depends(clearance_todos_artifacts_remove),
) -> _ArtifactRemoveResponse:
    """Remove a todo artifact and its version history."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    if name == ARTIFACT_INPUT:
        raise HTTPException(status_code=400, detail="input artifact cannot be removed")
    if not await todos_db.slug_in_roadmap(slug):
        raise HTTPException(status_code=404, detail=f"slug '{slug}' not found in todo list")

    try:
        result = await todos_db.delete_artifact(slug, name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if result["removed"]:
        await _clear_artifact_provenance_state(todos_db, slug, name)
        logger.info(
            "todo artifact remove route completed",
            slug=slug,
            artifact=name,
            versions_deleted=result["versions_deleted"],
            cwd=effective_cwd,
        )
    return _ArtifactRemoveResponse(
        status="ok",
        slug=slug,
        name=name,
        removed=result["removed"],
        versions_deleted=result["versions_deleted"],
    )


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
async def todo_content_create(request: TodoDumpRequest) -> _SlugStatusResponse:
    """Create a todo: state + artifact + todo entry in todos.db.

    Kind selects the entry point (see TodoDumpRequest):
      - omitted kind: content is the "input" artifact; enters analyzer assignment.
      - "feature" | "change": content is the "input" artifact; enters prepare
        (feature authors a PRD, change drafts a plan directly).
      - "bug": content is the "input" artifact; apply_prepared_state stamps the
        canonical lifecycle `prepared` so it enters the fix lane directly.
      - "task": content is the "input" artifact; enters prepared and is forced silent.
    ``silent`` suppresses dispatch (parking).
    """
    slug = request.slug
    try:
        effective_cwd = request.cwd or _default_cwd()
        todos_db = await _get_todos_db_from_cwd(effective_cwd)

        existing = await todos_db.read_state(slug)
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"Todo '{slug}' already exists")

        if not request.content.strip():
            raise HTTPException(status_code=400, detail="content must not be empty or whitespace-only")

        if request.plan and request.kind != TODO_KIND_CHANGE:
            raise HTTPException(
                status_code=400,
                detail="--plan supplies a complete implementation-plan and is only valid with --kind change",
            )

        state = _initial_todo_state_for_kind(request.kind)
        force_silent = request.kind == TODO_KIND_TASK
        pickup_requested = not (request.silent or force_silent)

        written_artifact_name = ""
        written_artifact_body = ""
        async with todos_db._session() as session:  # pylint: disable=protected-access
            async with session.begin():
                await todos_db.add_to_roadmap(slug, after=request.after if request.after else None, session=session)
                await todos_db.write_state(slug, state, session=session)

                if request.plan:
                    plan_content = f"# {slug} — Implementation Plan\n\n{request.content}\n"
                    written_artifact_name = ARTIFACT_IMPLEMENTATION_PLAN
                    written_artifact_body = plan_content
                    await todos_db.write_artifact(
                        slug,
                        ARTIFACT_IMPLEMENTATION_PLAN,
                        plan_content,
                        updated_by="api.todo.create.plan",
                        session=session,
                    )
                else:
                    input_content = f"# {slug} — Input\n\n{request.content}\n"
                    written_artifact_name = ARTIFACT_INPUT
                    written_artifact_body = input_content
                    await todos_db.write_artifact(
                        slug,
                        ARTIFACT_INPUT,
                        input_content,
                        updated_by="api.todo.create",
                        session=session,
                    )

        todos_db.on_committed("todo_updated")

        if written_artifact_name in _DRIFT_TRACKED_ARTIFACT_NAMES:
            await _sync_artifact_provenance_state(
                todos_db,
                slug,
                written_artifact_name,
                repo_root=effective_cwd,
                artifact_body=written_artifact_body,
            )

        if request.plan:
            # Stamp DOR, grounding baseline, and review approvals so a --plan
            # change (complete plan supplied) is immediately `prepared` and skips
            # the prepare phase.
            final_state = apply_prepared_state(effective_cwd, slug)
            state["lifecycle_phase"] = str(final_state.get("lifecycle_phase", state.get("lifecycle_phase", "draft")))
            todos_db.on_committed("todo_updated")

        lifecycle_phase = state.get("lifecycle_phase")
        event_lifecycle_phase = lifecycle_phase if isinstance(lifecycle_phase, str) else None
        await emit_event(
            event="workflow.todo.created",
            source="api.todo.create",
            level=EventLevel.WORKFLOW,
            domain="software-development",
            payload={
                "slug": slug,
                "kind": None if request.kind is None else map_v1_kind_to_canonical(request.kind),
                "creation_mode": "pickup" if pickup_requested else "silent",
                "pickup_requested": pickup_requested,
                "lifecycle_phase": event_lifecycle_phase,
                "created_at": datetime.now(UTC).isoformat(),
                "project_path": effective_cwd,
            },
        )

        logger.info(
            "todo creation completed",
            slug=slug,
            kind=request.kind,
            cwd=effective_cwd,
            artifact=ARTIFACT_IMPLEMENTATION_PLAN if request.plan else ARTIFACT_INPUT,
        )

        return _SlugStatusResponse(status="ok", slug=slug)
    except HTTPException:
        raise
    except Exception:
        logger.error("todo creation failed for slug=%s", slug, exc_info=True)
        raise


@router.post("/split")
async def todo_split(
    slug: Annotated[str, Body()],
    children: Annotated[list[str], Body()],
    cwd: Annotated[str | None, Body()] = None,
) -> _SplitResponse:
    """Split a todo into children and turn the parent into a stateless holder."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)

    if not await todos_db.slug_in_roadmap(slug):
        raise HTTPException(status_code=404, detail=f"Parent todo '{slug}' not found")

    parent_state = await todos_db.read_state(slug)
    raw_parent_kind = parent_state.get("kind") if parent_state is not None else None
    try:
        parent_kind = canonical_kind(raw_parent_kind if isinstance(raw_parent_kind, str) else None)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Parent todo '{slug}' has unresolvable kind: {raw_parent_kind!r}",
        ) from exc

    parent_input = await todos_db.read_artifact(slug, ARTIFACT_INPUT)
    child_state = _initial_todo_state_for_kind(parent_kind)

    async with todos_db._session() as session:  # pylint: disable=protected-access
        async with session.begin():
            for child_slug in children:
                if child_slug == slug:
                    raise HTTPException(status_code=409, detail=f"Child todo '{child_slug}' already exists")
                if await todos_db.slug_conflicts_non_removed(child_slug, session=session):
                    raise HTTPException(status_code=409, detail=f"Child todo '{child_slug}' already exists")
                await todos_db.add_to_roadmap(child_slug, group_slug=slug, session=session)
                await todos_db.write_state(child_slug, child_state, session=session)
                if parent_input:
                    await todos_db.write_artifact(
                        child_slug,
                        ARTIFACT_INPUT,
                        parent_input,
                        updated_by="api.todo.split.clone_input",
                        session=session,
                    )

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
    """Remove a todo: delete state, artifacts, todo entry, and clean up worktree.

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
        raise HTTPException(status_code=404, detail=f"Todo '{slug}' not found in todo list")
    return _SlugStatusResponse(status="ok", slug=slug)


@router.post("/unfreeze/{slug}")
async def todo_unfreeze(
    slug: str,
    cwd: Annotated[str | None, Body(embed=True)] = None,
) -> _SlugStatusResponse:
    """Restore a todo from icebox to active todo list."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    if not await todos_db.unfreeze(slug):
        raise HTTPException(status_code=404, detail=f"Todo '{slug}' not found in icebox")
    return _SlugStatusResponse(status="ok", slug=slug)


@router.get("/{slug}/show", response_model=None)
async def todo_show(
    slug: str,
    cwd: str | None = None,
    include_removed: bool = False,
    include_artifact_content: bool = False,
) -> ShowPayload:
    """Return full show payload for a slug."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    payload = await assemble_show_payload(
        todos_db, slug, include_removed=include_removed, include_artifact_content=include_artifact_content
    )
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Todo '{slug}' not found")
    return payload


@router.post("/{slug}/reactivate")
async def todo_reactivate(
    slug: str,
    cwd: Annotated[str | None, Body(embed=True)] = None,
    _identity: CallerIdentity = Depends(clearance_todos_reactivate),
) -> _SlugStatusResponse:
    """Restore a soft-removed todo addressed by slug."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)

    # Resolve slug to removed-row id (refuse if ambiguous)
    removed_entries = await todos_db.list_roadmap(include_removed=True, removed_only=True)
    matches = [r for r in removed_entries if r["slug"] == slug]

    if not matches:
        raise HTTPException(status_code=404, detail=f"No soft-removed entry found for slug '{slug}'")
    if len(matches) > 1:
        details = ", ".join(f"{m['id']} (removed {m.get('removed_at')})" for m in matches)
        raise HTTPException(
            status_code=409,
            detail=f"Ambiguous slug '{slug}': multiple removed rows exist ({details}). Restore by id instead.",
        )

    roadmap_id = matches[0]["id"]
    try:
        await todos_db.reactivate_removed(roadmap_id)
    except ReactivateRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _SlugStatusResponse(status="ok", slug=slug)


@router.post("/by-id/{roadmap_id}/reactivate")
async def todo_reactivate_by_id(
    roadmap_id: str,
    cwd: Annotated[str | None, Body(embed=True)] = None,
    _identity: CallerIdentity = Depends(clearance_todos_reactivate),
) -> _SlugStatusResponse:
    """Restore a soft-removed todo addressed by its durable row id."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    try:
        slug = await todos_db.reactivate_removed(roadmap_id)
    except ReactivateRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _SlugStatusResponse(status="ok", slug=slug)
