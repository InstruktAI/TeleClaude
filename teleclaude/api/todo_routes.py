"""Todo/workflow REST endpoints for the telec CLI tool subcommands.

Exposes the next-machine state machine functions (prepare, work) and todo
mutation operations as REST endpoints with dual-factor caller identity
enforcement. Todo stamping — worker verdicts and human gate approvals alike —
is one daemon-side mutation via ``POST /todos/stamp``.
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
    clearance_todos_artifacts_write,
    clearance_todos_create,
    clearance_todos_integrate,
    clearance_todos_prepare,
    clearance_todos_reactivate,
    clearance_todos_remove,
    clearance_todos_update,
    clearance_todos_work,
    optional_caller_identity,
)
from teleclaude.api.kind_mapper import map_v1_kind_to_canonical
from teleclaude.api.todo_artifact_authority import (
    optional_capture_principal,
    refuse_non_prepare_writer,
    resolved_write_principal,
)
from teleclaude.api.todo_create_support import seed_plan_drafting, seed_task_plan_authorization
from teleclaude.api.todo_dependency_validation import validate_requested_dependencies
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
    PREPARE_ARTIFACT_NAMES,
    TodoStatus,
)
from teleclaude.core.dates import normalize_task_schedule
from teleclaude.core.next_machine.dep_graph import detect_circular_dependency
from teleclaude.core.next_machine.kind_migration import (
    KindMigrationRequiresForce,
    KindMigrationResult,
    migrate_todo_kind,
)
from teleclaude.core.next_machine.lifecycle import adopt_prepare_handoff_phase
from teleclaude.core.next_machine.provenance import clear_artifact_provenance, sync_artifact_provenance
from teleclaude.core.next_machine.state_io import initial_todo_state_for_kind
from teleclaude.core.next_machine.state_mutation import StateMutationError, StateWriter
from teleclaude.core.operations import get_operations_service
from teleclaude.core.operations.service import SerializedOperation
from teleclaude.core.todos_db import HolderTransitionRefused, HolderWriteRefused, get_todos_db
from teleclaude.core.todos_db._show import assemble_show_payload
from teleclaude.core.todos_db._todo_soft_delete import ReactivateRefused
from teleclaude.events.envelope import EventLevel
from teleclaude.events.producer import emit_event
from teleclaude.project_root import resolve_state_root
from teleclaude.snippet_validation import snippet_body_digest
from teleclaude.types.lifecycle import WORK_LIFECYCLE_PHASES
from teleclaude.types.todo_kind import ALL_DUMP_KINDS, TODO_KIND_CHANGE, TODO_KIND_TASK
from teleclaude.types.todos import HoldAuditSource

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb
    from teleclaude.core.todos_db._show import ShowPayload

logger = get_logger(__name__)

router = APIRouter(prefix="/todos", tags=["todos"])

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
_CREATE_HOLD_REASON = "todo create --hold"
_DRIFT_TRACKED_ARTIFACT_NAMES = {
    ARTIFACT_INPUT,
    ARTIFACT_PRD,
    ARTIFACT_REQUIREMENTS,
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_TASK_PLAN,
}


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


class _TodoUpdateResponse(BaseModel):
    """Response from synchronous todo update legs."""

    model_config = ConfigDict(frozen=True)
    status: str
    slug: str
    kind: str | None = None
    lifecycle_phase: str | None = None
    after: list[str] | None = None
    hold: bool | None = None
    warnings: list[str]
    folded_artifact: str | None = None


def _validate_update_request(
    *,
    new_slug: str | None,
    after: list[str] | None,
    kind: str | None,
    hold: bool,
    release: bool,
    schedule: str | None,
) -> None:
    """Validate the todo update facade's patch shape."""
    if new_slug is None and after is None and kind is None and schedule is None and not hold and not release:
        raise HTTPException(
            status_code=400, detail="at least one of new_slug, after, kind, schedule, hold, or release is required"
        )
    if hold and release:
        raise HTTPException(status_code=400, detail="hold and release are mutually exclusive")


def _normalize_schedule_request(schedule: str | None) -> str | None:
    if schedule is None:
        return None
    try:
        return normalize_task_schedule(schedule)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


TASK_ERROR_RELEASE_REFUSAL = (
    "is held by a task error and cannot be bare-released. "
    "Recover with `telec todo stamp --task-outcome success` (delivers) "
    "or kill the run and start it manually."
)


async def _apply_hold_update(
    todos_db: TodosDb,
    slug: str,
    *,
    hold: bool,
    release: bool,
    caller_session_id: str | None,
) -> bool | None:
    """Apply a hold/release update and return the resulting hold value."""
    if not hold and not release:
        return None
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        raise HTTPException(status_code=404, detail=f"slug '{slug}' not found in todo list")
    writer = StateWriter(raw_state)
    if release and writer.state.hold_audit.source == HoldAuditSource.TASK_ERROR:
        raise HTTPException(status_code=409, detail=f"slug '{slug}' {TASK_ERROR_RELEASE_REFUSAL}")
    writer.state.hold = hold
    if hold:
        writer.state.hold_audit.source = HoldAuditSource.MANUAL
        writer.state.hold_audit.set_at = datetime.now(UTC).isoformat()
        writer.state.hold_audit.set_by_session_id = caller_session_id or ""
        writer.state.hold_audit.reason = "todo update"
    else:
        writer.state.hold_audit.source = HoldAuditSource.NONE
        writer.state.hold_audit.set_at = ""
        writer.state.hold_audit.set_by_session_id = ""
        writer.state.hold_audit.reason = ""
    await writer.commit(todos_db, slug)
    return writer.state.hold


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
    schedule: Annotated[str | None, Body()] = None,
    kind: Annotated[str | None, Body()] = None,
    hold: Annotated[bool, Body()] = False,
    release: Annotated[bool, Body()] = False,
    force: Annotated[bool, Body()] = False,
    cwd: Annotated[str | None, Body()] = None,
    client_request_id: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(clearance_todos_update),
) -> SerializedOperation | _TodoUpdateResponse:
    """Update a todo slug, dependencies, or kind through one mutation facade."""
    if not cwd:
        raise HTTPException(status_code=400, detail="cwd required: working directory not provided")
    _validate_update_request(new_slug=new_slug, after=after, kind=kind, schedule=schedule, hold=hold, release=release)

    _validate_slug_for_update(slug, field_name="slug")
    if new_slug is not None:
        _validate_slug_for_update(new_slug, field_name="new_slug")
    if kind is not None and kind not in ALL_DUMP_KINDS:
        raise HTTPException(status_code=400, detail=f"unknown todo kind: {kind!r}")

    requested_after = after
    normalized_schedule = _normalize_schedule_request(schedule)
    if requested_after is not None:
        for dep in requested_after:
            _validate_slug_for_update(dep, field_name="dependency")
        if slug in requested_after:
            raise HTTPException(status_code=400, detail=f"slug '{slug}' cannot depend on itself")

    warnings: list[str] = []
    migration_result: KindMigrationResult | None = None
    todos_db = await _get_todos_db_from_cwd(cwd)

    if not await todos_db.slug_in_todo(slug):
        raise HTTPException(status_code=404, detail=f"slug '{slug}' not found in todo list")
    raw_state = await todos_db.read_state(slug)
    current_kind = raw_state.get("kind") if isinstance(raw_state, dict) else None
    schedule_kind = kind if kind is not None else current_kind
    if schedule is not None and schedule_kind != TODO_KIND_TASK:
        raise HTTPException(status_code=400, detail="schedule is valid only for kind='task'")
    existing_schedule = await todos_db.get_schedule(slug)
    existing_deps = await todos_db.get_deps(slug)
    if normalized_schedule is not None and requested_after:
        raise HTTPException(status_code=400, detail="schedule and dependencies are mutually exclusive")
    if normalized_schedule is not None and requested_after is None and existing_deps:
        raise HTTPException(status_code=400, detail="clear dependencies before setting schedule")
    clearing_schedule = schedule is not None and normalized_schedule is None
    if requested_after and (normalized_schedule is not None or (existing_schedule and not clearing_schedule)):
        raise HTTPException(status_code=400, detail="clear schedule before setting dependencies")

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
        await validate_requested_dependencies(todos_db, slug, requested_after)

        deps = await todos_db.load_deps()
        cycle = detect_circular_dependency(deps, slug, requested_after)
        if cycle:
            cycle_str = " -> ".join(cycle)
            raise HTTPException(status_code=409, detail=f"circular dependency detected: {cycle_str}")

        await todos_db.set_deps(slug, after=requested_after)
    if schedule is not None:
        await todos_db.set_schedule(slug, schedule=normalized_schedule)

    hold_value = await _apply_hold_update(
        todos_db,
        slug,
        hold=hold,
        release=release,
        caller_session_id=identity.session_id,
    )

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

    await _emit_todo_updated(slug=slug, cwd=cwd)

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
        hold=hold_value,
        warnings=warnings,
        folded_artifact=migration_result.get("folded_artifact") if migration_result else None,
    )


async def _emit_todo_updated(*, slug: str, cwd: str) -> None:
    project_root = str(resolve_state_root(cwd))
    try:
        await emit_event(
            event="workflow.todo.updated",
            source="api.todo.update",
            level=EventLevel.WORKFLOW,
            domain="software-development",
            payload={
                "slug": slug,
                "updated_at": datetime.now(UTC).isoformat(),
                "project_path": project_root,
            },
        )
    except RuntimeError:
        logger.info("workflow.todo.updated not emitted: event producer unavailable", slug=slug)


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
    if artifact_name == ARTIFACT_TASK_PLAN:
        writer.state.lifecycle_phase = adopt_prepare_handoff_phase(writer.state).value
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
    codebase_sha_at_write: Annotated[str | None, Body()] = None,
    referenced_paths: Annotated[list[str] | None, Body()] = None,
    identity: CallerIdentity = Depends(clearance_todos_artifacts_write),
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
    if not await todos_db.slug_in_todo(slug):
        raise HTTPException(status_code=404, detail=f"slug '{slug}' not found in todo list")
    if await todos_db.is_holder(slug):
        raise HTTPException(
            status_code=409,
            detail=(
                f"todo '{slug}' is a structural holder with grouped children; it carries no "
                "artifacts or state — write to its children instead"
            ),
        )
    if name in PREPARE_ARTIFACT_NAMES:
        await refuse_non_prepare_writer(identity, slug, name)
    effective_updated_by = resolved_write_principal(identity)
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
    if not await todos_db.slug_in_todo(slug):
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
async def todo_content_create(
    request: TodoDumpRequest,
    identity: CallerIdentity | None = Depends(optional_caller_identity),
) -> _SlugStatusResponse:
    """Create a todo: state + artifact + todo entry in todos.db.

    Kind selects the entry point (see TodoDumpRequest):
      - omitted kind: content is the "input" artifact; enters analyzer assignment.
      - "feature" | "change": content is the "input" artifact; enters prepare
        (feature authors a PRD, change drafts a plan directly).
      - "change" with ``--plan``: content seeds the "implementation-plan"
        artifact, marked `seeded`, and enters `plan_drafting` — a full
        plan-draft pass grounds and reviews it before `prepared`.
      - "bug": content is the "input" artifact; enters the diagnose-then-plan
        prepare flow.
      - "task": content is the "input" artifact; enters task-plan drafting unless --plan supplies
        the pre-authorized task-plan.
    ``icebox`` creates the todo parked in the icebox (no prepare auto-spawn).
    ``hold`` creates an active todo with the dispatch brake set
    (``hold_audit.source=creation``) so the lifecycle router and runner skip it
    until it is released — the hidden specialist control for live-human prepare
    orchestration; mutually exclusive with ``icebox``.
    ``group`` attaches the new todo as a child of the named parent slug,
    making the parent a structural holder via the existing derivation.
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

        normalized_schedule = _normalize_schedule_request(request.schedule)
        if request.schedule is not None and request.kind != TODO_KIND_TASK:
            raise HTTPException(status_code=400, detail="schedule is valid only for kind='task'")
        if normalized_schedule is not None and request.after:
            raise HTTPException(status_code=400, detail="schedule and dependencies are mutually exclusive")
        if request.plan and request.kind not in {TODO_KIND_CHANGE, TODO_KIND_TASK}:
            raise HTTPException(
                status_code=400,
                detail="--plan is valid only with --kind change or --kind task",
            )
        if request.hold and request.icebox:
            raise HTTPException(
                status_code=400,
                detail="hold and icebox are mutually exclusive",
            )
        created_by_principal = optional_capture_principal(identity)
        state = initial_todo_state_for_kind(request.kind)
        if request.hold:
            state["hold"] = True
            state["hold_audit"] = {
                "source": HoldAuditSource.CREATION.value,
                "set_at": datetime.now(UTC).isoformat(),
                "set_by_session_id": created_by_principal or "",
                "reason": _CREATE_HOLD_REASON,
            }
        pickup_requested = not request.icebox and not request.hold

        written_artifact_name = ""
        written_artifact_body = ""
        async with todos_db._session() as session:  # pylint: disable=protected-access
            async with session.begin():
                await todos_db.add_to_todo(
                    slug,
                    after=request.after if request.after else None,
                    schedule=normalized_schedule,
                    group_slug=request.group,
                    status=TodoStatus.ICEBOX if request.icebox else TodoStatus.ACTIVE,
                    created_by_principal=created_by_principal,
                    session=session,
                )
                await todos_db.write_state(slug, state, session=session)

                if request.plan:
                    is_task_plan = request.kind == TODO_KIND_TASK
                    plan_content = (
                        f"# {slug} — Task Plan\n\n{request.content}\n"
                        if is_task_plan
                        else f"# {slug} — Implementation Plan\n\n{request.content}\n"
                    )
                    written_artifact_name = ARTIFACT_TASK_PLAN if is_task_plan else ARTIFACT_IMPLEMENTATION_PLAN
                    written_artifact_body = plan_content
                    await todos_db.write_artifact(
                        slug,
                        written_artifact_name,
                        plan_content,
                        updated_by="api.todo.create.task-plan" if is_task_plan else "api.todo.create.plan",
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

        if request.plan and request.kind == TODO_KIND_CHANGE:
            # Seed the supplied plan as a plan-drafting basis (see
            # seed_plan_drafting); it must run after the seeding write's
            # provenance sync above, which would otherwise clear the seed.
            state["lifecycle_phase"] = await seed_plan_drafting(todos_db, slug, repo_root=effective_cwd)
            todos_db.on_committed("todo_updated")
        elif request.plan and request.kind == TODO_KIND_TASK:
            state["lifecycle_phase"] = await seed_task_plan_authorization(
                todos_db,
                slug,
                caller_session_id=created_by_principal or "system:todo-create-plan",
            )
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
                "created_by_principal": created_by_principal,
            },
        )

        logger.info(
            "todo creation completed",
            slug=slug,
            kind=request.kind,
            cwd=effective_cwd,
            artifact=written_artifact_name,
        )

        return _SlugStatusResponse(status="ok", slug=slug)
    except HTTPException:
        raise
    except HolderTransitionRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        logger.error("todo creation failed", slug=slug, exc_info=True)
        raise


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
    removed_entries = await todos_db.list_todo(include_removed=True, removed_only=True)
    matches = [r for r in removed_entries if r["slug"] == slug]

    if not matches:
        raise HTTPException(status_code=404, detail=f"No soft-removed entry found for slug '{slug}'")
    if len(matches) > 1:
        details = ", ".join(f"{m['id']} (removed {m.get('removed_at')})" for m in matches)
        raise HTTPException(
            status_code=409,
            detail=f"Ambiguous slug '{slug}': multiple removed rows exist ({details}). Restore by id instead.",
        )

    todo_id = matches[0]["id"]
    try:
        await todos_db.reactivate_removed(todo_id)
    except ReactivateRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _SlugStatusResponse(status="ok", slug=slug)


@router.post("/by-id/{todo_id}/reactivate")
async def todo_reactivate_by_id(
    todo_id: str,
    cwd: Annotated[str | None, Body(embed=True)] = None,
    _identity: CallerIdentity = Depends(clearance_todos_reactivate),
) -> _SlugStatusResponse:
    """Restore a soft-removed todo addressed by its durable row id."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    try:
        slug = await todos_db.reactivate_removed(todo_id)
    except ReactivateRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _SlugStatusResponse(status="ok", slug=slug)
