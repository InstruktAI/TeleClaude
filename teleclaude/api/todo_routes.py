"""Todo/workflow REST endpoints for the telec CLI tool subcommands.

Exposes the next-machine state machine functions (prepare, work) and todo
mutation operations as REST endpoints with dual-factor caller identity
enforcement. Todo stamping — worker verdicts and human gate approvals alike —
is one daemon-side mutation via ``POST /todos/stamp``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict, Field

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.api.driver_start_guard import admission_caller_for
from teleclaude.api.todo_artifact_authority import (
    refuse_todo_update_outside_claiming_group,
    resolve_creation_lineage,
)
from teleclaude.api.todo_update_support import TASK_ERROR_RELEASE_REFUSAL as TASK_ERROR_RELEASE_REFUSAL
from teleclaude.api.todo_update_support import (
    apply_dependency_update,
    apply_group_membership_update,
    apply_hold_update,
    apply_unclaim_update,
    normalize_hold_reason,
    normalize_schedule_request,
    require_slug_in_todo,
    resolve_current_group_slug,
    should_emit_route_update,
    validate_kind_for_update,
    validate_update_request,
)
from teleclaude.api.work_feedback import DeclaredWorkRefusal
from teleclaude.api.working_copy_request import working_copy_request_deadline
from teleclaude.api_models import TodoDumpRequest
from teleclaude.api_models_operations import OperationStatusDTO
from teleclaude.config.machine import config
from teleclaude.constants import (
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_INPUT,
    ARTIFACT_TASK_PLAN,
    SLUG_NOT_FOUND_DETAIL,
)
from teleclaude.core.db import db as runtime_db
from teleclaude.core.human_involvement import (
    HumanInvolvementReasonInvalid,
    HumanInvolvementSurface,
    resolve_human_involvement,
)
from teleclaude.core.next_machine.driver_admission import (
    DriverAdmissionRequest,
    DriverReleaseRequest,
    StartRequest,
    admit_relayed_start,
    release_relayed_claim,
)
from teleclaude.core.next_machine.kind_migration import (
    KindMigrationRequiresForce,
    KindMigrationResult,
    migrate_todo_kind,
)
from teleclaude.core.next_machine.runtime.sessions import OwnSessionAnswer, own_session_answer
from teleclaude.core.next_machine.session_hold import emit_todo_updated
from teleclaude.core.next_machine.state_io import initial_todo_state_for_kind
from teleclaude.core.next_machine.state_mutation import StateMutationError, StateWriter
from teleclaude.core.next_machine.todo_creation import (
    NewTodo,
)
from teleclaude.core.operations.service import SerializedOperation, get_operations_service
from teleclaude.core.operations.todo_filing import FilingSeed, TodoFiling
from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root
from teleclaude.core.todos_db._exceptions import (
    AdmissionUnavailable,
    ClaimConflict,
    DriverStartBusy,
    OperationFailure,
)
from teleclaude.core.todos_db._todo_soft_delete import ReactivateRefused
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.slug import validate_slug
from teleclaude.types.creation_record import EntryPoint
from teleclaude.types.lifecycle import WORK_LIFECYCLE_PHASES
from teleclaude.types.todo_kind import TodoKind
from teleclaude.types.todos import HoldAuditSource

if TYPE_CHECKING:
    from teleclaude.core.workflow_store.store import WorkflowStore

logger = get_logger(__name__)

router = APIRouter(prefix="/todos", tags=["todos"], dependencies=[Depends(working_copy_request_deadline)])

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
_CLAIMED_HOLD_WARNING = (
    "Hold affects future dispatch only; claimed session {session_id} keeps running. "
    "Contact it with `telec sessions send {session_id} <message>`."
)
_TODO_UPDATE_EVENT_SOURCE = "api.todo.update"
_REACTIVATE_NO_MATCH_DETAIL_TEMPLATE = "No soft-removed entry found for slug '{slug}'"
_REACTIVATE_AMBIGUOUS_DETAIL_TEMPLATE = (
    "Ambiguous slug '{slug}': multiple removed rows exist ({details}). Restore by id instead."
)


# ── Response models ─────────────────────────────────────────────────────────


class _SlugStatusResponse(BaseModel):
    """Standard ok response with slug."""

    model_config = ConfigDict(frozen=True)
    status: str
    slug: str
    warnings: list[str] = Field(default_factory=list)


async def _resolve_human_involved(request: TodoDumpRequest, identity: CallerIdentity) -> bool:
    """Derive one creation-record boolean without propagating prior action state."""
    if identity.entry_point is not EntryPoint.AGENT:
        return identity.entry_point in {EntryPoint.TUI, EntryPoint.CLI}
    declaration_requested = request.human_involved or request.human_involvement_reason is not None
    if not declaration_requested:
        return False
    try:
        resolution = await resolve_human_involvement(
            session_id=identity.session_id,
            reason=request.human_involvement_reason,
            session_store=runtime_db,
            surface=HumanInvolvementSurface.TODO_CREATION,
        )
    except HumanInvolvementReasonInvalid as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{exc}; rerun without --human-involved if the filing is not human-involved.",
        ) from exc
    return resolution.involved


class _TodoUpdateResponse(BaseModel):
    """Response from synchronous todo update legs."""

    model_config = ConfigDict(frozen=True)
    status: str
    slug: str
    group: str | None = None
    kind: str | None = None
    lifecycle_phase: str | None = None
    after: list[str] | None = None
    hold: bool | None = None
    unclaim: str | None = None
    warnings: list[str]
    folded_artifact: str | None = None


def _claimed_hold_warnings(*, hold_value: bool | None, active_runner: object) -> list[str]:
    if hold_value is not True or not isinstance(active_runner, str) or not active_runner:
        return []
    return [_CLAIMED_HOLD_WARNING.format(session_id=active_runner)]


def _default_cwd() -> str:
    try:
        return str(resolve_project_root(config.computer.default_working_dir))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/create", status_code=202, response_model=OperationStatusDTO, response_model_exclude_none=True)
async def todo_create(  # pyright: ignore
    slug: Annotated[str | None, Body()] = None,
    cwd: Annotated[str | None, Body()] = None,
    client_request_id: Annotated[str | None, Body()] = None,
    _identity: CallerIdentity = Depends(carried_caller),
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
    _identity: CallerIdentity = Depends(carried_caller),
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
    identity: CallerIdentity = Depends(carried_caller),
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
    abandon: Annotated[bool, Body()] = False,
    identity: CallerIdentity = Depends(carried_caller),
) -> SerializedOperation:
    """Run the integration state machine.

    Submits a durable receipt-backed integration operation that preserves
    the caller's session_id for lease ownership checks inside the background
    runner. Requires integrator clearance. ``abandon`` parks an ungroundable
    CONTENT_GATE_BLOCKED candidate or a held clean uncommitted attempt,
    resetting only the integration worktree to its frozen pre-merge SHA.
    """
    if not cwd:
        raise HTTPException(status_code=400, detail="cwd required: working directory not provided")
    operations = get_operations_service()
    return await operations.submit_todo_integrate(
        slug=slug,
        cwd=cwd,
        caller_session_id=identity.session_id,
        client_request_id=client_request_id,
        abandon=abandon,
    )


@router.post("/update", response_model=None)
async def todo_update(  # pyright: ignore
    slug: Annotated[str, Body()],
    new_slug: Annotated[str | None, Body()] = None,
    group: Annotated[str | None, Body()] = None,
    after: Annotated[list[str] | None, Body()] = None,
    schedule: Annotated[str | None, Body()] = None,
    kind: Annotated[str | None, Body()] = None,
    hold: Annotated[bool, Body()] = False,
    reason: Annotated[str | None, Body()] = None,
    release: Annotated[bool, Body()] = False,
    unclaim: Annotated[bool, Body()] = False,
    force: Annotated[bool, Body()] = False,
    cwd: Annotated[str | None, Body()] = None,
    client_request_id: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> SerializedOperation | _TodoUpdateResponse:
    """Update a todo slug, group, dependencies, or kind through one mutation facade."""
    if not cwd:
        raise HTTPException(status_code=400, detail="cwd required: working directory not provided")
    normalized_hold_reason = validate_update_request(
        new_slug=new_slug,
        group=group,
        after=after,
        kind=kind,
        schedule=schedule,
        hold=hold,
        reason=reason,
        release=release,
        unclaim=unclaim,
    )

    _validate_slug_for_update(slug, field_name="slug")
    if new_slug is not None:
        _validate_slug_for_update(new_slug, field_name="new_slug")
    group_present = group is not None
    normalized_group = group.strip() if group is not None else None
    if normalized_group == "":
        normalized_group = None
    if normalized_group is not None:
        _validate_slug_for_update(normalized_group, field_name="group")
    validate_kind_for_update(kind)

    requested_after = after
    normalized_schedule = normalize_schedule_request(schedule)
    if requested_after is not None:
        for dep in requested_after:
            _validate_slug_for_update(dep, field_name="dependency")
        if slug in requested_after:
            raise HTTPException(status_code=400, detail=f"slug '{slug}' cannot depend on itself")

    warnings: list[str] = []
    migration_result: KindMigrationResult | None = None
    todos_db = await _get_workflow_store_from_cwd(cwd)

    await require_slug_in_todo(todos_db, slug)
    await refuse_todo_update_outside_claiming_group(todos_db, identity, slug)
    raw_state = await todos_db.read_state(slug)
    current_kind = raw_state.get("kind") if isinstance(raw_state, dict) else None
    active_runner = raw_state.get("active_runner") if isinstance(raw_state, dict) else None
    schedule_kind = kind if kind is not None else current_kind
    if schedule is not None and schedule_kind != TodoKind.TASK:
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

    if group_present:
        await apply_group_membership_update(
            todos_db,
            slug=slug,
            group_slug=normalized_group,
            requested_after=requested_after,
            cwd=cwd,
            identity=identity,
        )

    if kind is not None:
        try:
            migration_result = await migrate_todo_kind(todos_db, slug, target_kind=kind, force=force)
        except KindMigrationRequiresForce as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StateMutationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        warnings.extend(migration_result["warnings"])

    warnings.extend(
        await apply_dependency_update(
            todos_db,
            slug=slug,
            requested_after=requested_after,
            group_present=group_present,
        )
    )
    if schedule is not None:
        await todos_db.set_schedule(slug, schedule=normalized_schedule)

    hold_value = await apply_hold_update(
        todos_db,
        slug,
        hold=hold,
        reason=normalized_hold_reason,
        release=release,
        caller_session_id=identity.session_id,
    )
    warnings.extend(_claimed_hold_warnings(hold_value=hold_value, active_runner=active_runner))
    unclaim_summary = await apply_unclaim_update(
        runtime_db,
        slug=slug,
        cwd=cwd,
        unclaim=unclaim,
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

    if should_emit_route_update(
        group_present=group_present,
        kind=kind,
        requested_after=requested_after,
        schedule=schedule,
        hold_value=hold_value,
        unclaim_summary=unclaim_summary,
    ):
        await emit_todo_updated(
            slug=slug,
            project_root=str(resolve_project_root(cwd)),
            source=_TODO_UPDATE_EVENT_SOURCE,
        )

    group_result = await resolve_current_group_slug(todos_db, slug)
    logger.info(
        "todo update route completed",
        slug=slug,
        group=group_result,
        kind=migration_result["kind"] if migration_result else None,
        lifecycle_phase=migration_result["lifecycle_phase"] if migration_result else None,
        orphaned_artifacts=migration_result["orphaned_artifacts"] if migration_result else None,
        after=requested_after,
        cwd=cwd,
    )
    return _TodoUpdateResponse(
        status="ok",
        slug=slug,
        group=group_result,
        kind=migration_result["kind"] if migration_result else None,
        lifecycle_phase=migration_result["lifecycle_phase"] if migration_result else None,
        after=requested_after,
        hold=hold_value,
        unclaim=unclaim_summary,
        warnings=warnings,
        folded_artifact=migration_result.get("folded_artifact") if migration_result else None,
    )


def _validate_slug_for_update(slug: str, *, field_name: str) -> None:
    if not _SLUG_RE.match(slug):
        raise HTTPException(
            status_code=400,
            detail=f"invalid {field_name} '{slug}': must be lowercase alphanumeric with hyphens only",
        )


def _validate_slug_for_create(slug: str, *, field_name: str) -> None:
    try:
        validate_slug(slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid {field_name} '{slug}': {exc}") from exc


async def _todo_build_started(todos_db: WorkflowStore, slug: str) -> bool:
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        raise HTTPException(status_code=404, detail=SLUG_NOT_FOUND_DETAIL.format(slug=slug))
    writer = StateWriter(raw_state)
    phase = writer.state.lifecycle_phase
    if writer.state.build_start_base_sha:
        return True
    return phase in {work_phase.value for work_phase in WORK_LIFECYCLE_PHASES}


# ---------------------------------------------------------------------------
# Shared todos.db helpers (artifact routes import these; see todo_artifact_routes)
# ---------------------------------------------------------------------------


async def _get_workflow_store_from_cwd(cwd: str) -> WorkflowStore:
    """Resolve the todos DB for the given project cwd.

    Raises a 400 (not the caller-observed 404 'slug not found') when ``cwd``
    does not resolve to a real project checkout, instead of silently reading
    or materializing a stray store at the unresolved path.
    """
    try:
        project_root = resolve_project_root(cwd)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await get_workflow_store(project_root)


@router.post("/dump", status_code=202, response_model=OperationStatusDTO, response_model_exclude_none=True)
async def todo_content_create(
    request: TodoDumpRequest,
    identity: CallerIdentity | None = Depends(carried_caller),
) -> SerializedOperation:
    """File a todo: answer the request checks, then accept the filing with a receipt.

    The filing itself (documentation evidence, state + artifact + todo entry, seeding, the todo-created
    event) runs after the response as a receipt-backed operation in its project's acceptance order.

    Kind selects the entry point (see TodoDumpRequest):
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
        _validate_slug_for_create(slug, field_name="slug")
        for dep_slug in request.after or []:
            _validate_slug_for_create(dep_slug, field_name="after")
        if request.group is not None:
            _validate_slug_for_create(request.group, field_name="group")

        effective_cwd = request.cwd or _default_cwd()
        todos_db = await _get_workflow_store_from_cwd(effective_cwd)

        conflicting_status = await todos_db.find_live_slug_conflict(slug)
        if conflicting_status is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Todo '{slug}' already exists (status={conflicting_status})",
            )

        if not request.content.strip():
            raise HTTPException(status_code=400, detail="content must not be empty or whitespace-only")

        normalized_schedule = normalize_schedule_request(request.schedule)
        if request.schedule is not None and request.kind != TodoKind.TASK:
            raise HTTPException(status_code=400, detail="schedule is valid only for kind='task'")
        if normalized_schedule is not None and request.after:
            raise HTTPException(status_code=400, detail="schedule and dependencies are mutually exclusive")
        if request.plan and request.kind not in {TodoKind.CHANGE, TodoKind.TASK}:
            raise HTTPException(
                status_code=400,
                detail="--plan is valid only with --kind change or --kind task",
            )
        if request.hold and request.icebox:
            raise HTTPException(
                status_code=400,
                detail="hold and icebox are mutually exclusive",
            )
        normalized_hold_reason = normalize_hold_reason(hold=request.hold, reason=request.reason)
        try:
            lineage = resolve_creation_lineage(identity)
        except HTTPException:
            logger.warning(
                "creation lineage refused",
                slug=slug,
                entry_point=identity.entry_point.value if identity is not None and identity.entry_point else None,
                role=identity.role if identity is not None else None,
            )
            raise
        # resolve_creation_lineage above raises unless identity resolved, so
        # identity is provably non-None here.
        assert identity is not None
        caller_entry_point = identity.entry_point
        human_involved = await _resolve_human_involved(request, identity)
        entry_point = EntryPoint.SPLIT if request.group else caller_entry_point
        creation_context = request.group if entry_point == EntryPoint.SPLIT else None

        state = initial_todo_state_for_kind(request.kind)
        if request.hold:
            assert normalized_hold_reason is not None
            state["hold"] = True
            state["hold_audit"] = {
                "source": HoldAuditSource.CREATION.value,
                "set_at": datetime.now(UTC).isoformat(),
                "set_by_session_id": lineage.encode(),
                "reason": normalized_hold_reason,
            }
        pickup_requested = not request.icebox and not request.hold

        if request.plan:
            is_task_plan = request.kind == TodoKind.TASK
            written_artifact_name = ARTIFACT_TASK_PLAN if is_task_plan else ARTIFACT_IMPLEMENTATION_PLAN
            written_artifact_body = (
                f"# {slug} — Task Plan\n\n{request.content}\n"
                if is_task_plan
                else f"# {slug} — Implementation Plan\n\n{request.content}\n"
            )
        else:
            written_artifact_name = ARTIFACT_INPUT
            written_artifact_body = f"# {slug} — Input\n\n{request.content}\n"
        new_todo = NewTodo(
            slug=slug,
            kind=request.kind,
            state=state,
            lineage=lineage,
            entry_point=entry_point,
            human_involved=human_involved,
            cwd=effective_cwd,
            artifact_name=written_artifact_name,
            artifact_body=written_artifact_body,
            session_id=identity.session_id,
            after=request.after if request.after else None,
            schedule=normalized_schedule,
            group=request.group,
            icebox=request.icebox,
            context=creation_context,
        )
        if request.plan:
            seed = FilingSeed.TASK_PLAN if request.kind == TodoKind.TASK else FilingSeed.IMPLEMENTATION_PLAN
        else:
            seed = FilingSeed.NONE
        return await get_operations_service().submit_todo_filing(
            filing=TodoFiling.of(new_todo, seed=seed, pickup_requested=pickup_requested),
            project_root=str(resolve_project_root(effective_cwd)),
            caller_session_id=identity.session_id,
            client_request_id=request.client_request_id,
        )
    except HTTPException:
        raise
    except Exception:
        logger.error("todo filing refused", slug=slug, exc_info=True)
        raise


@router.post("/remove", status_code=202, response_model=OperationStatusDTO, response_model_exclude_none=True)
async def todo_remove(  # pyright: ignore
    slug: Annotated[str, Body()],
    force: Annotated[bool, Body()] = False,
    cwd: Annotated[str | None, Body()] = None,
    client_request_id: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(carried_caller),
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
        force=force,
    )


@router.post("/switch-to-github", status_code=202, response_model=OperationStatusDTO, response_model_exclude_none=True)
async def todo_switch_to_github(
    cwd: Annotated[str | None, Body()] = None,
    client_request_id: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> SerializedOperation:
    """Submit the current project's one-way local-to-GitHub store migration."""
    operations = get_operations_service()
    return await operations.submit_todo_store_switch(
        cwd=cwd or _default_cwd(),
        caller_session_id=identity.session_id,
        client_request_id=client_request_id,
    )


class _DriverClaimResponse(BaseModel):
    """The master's answer to an admission or a release."""

    model_config = ConfigDict(frozen=True)
    admitted: bool = False
    cleared: bool = False


def _driver_refusal(failure: OperationFailure, status_code: int) -> DeclaredWorkRefusal:
    """The refusal a master answers a relayed admission or release with: the failure's own payload as the detail."""
    return DeclaredWorkRefusal(
        status_code=status_code,
        detail=dict(failure.to_error_payload()),
        work_feedback=failure.work_feedback or failure.summary(),
    )


@router.post("/driver-admission")
async def todo_driver_admission(
    body: DriverAdmissionRequest,
    identity: CallerIdentity = Depends(carried_caller),
) -> _DriverClaimResponse:
    """Admit a start of a GitHub-backed todo's driver on the master, recording its claim before its session exists.

    Answers 200 when admitted, 409 naming the holder and its computer (or the computers that did not
    answer for it) when the todo is held, 423 when another start of the todo is in progress, and 503 when
    this computer is not the unique live master or the start was not decided within its budget.
    """
    request = StartRequest(
        project_root=resolve_project_root(body.project_path),
        slug=body.slug,
        session_id=body.session_id,
        lane=body.lane,
        manually_started=body.manually_started,
        release_hold=body.release_hold,
        caller=admission_caller_for(identity),
    )
    try:
        await admit_relayed_start(request)
    except ClaimConflict as conflict:
        raise _driver_refusal(conflict, HTTPStatus.CONFLICT) from conflict
    except DriverStartBusy as busy:
        raise _driver_refusal(busy, HTTPStatus.LOCKED) from busy
    except AdmissionUnavailable as unavailable:
        raise _driver_refusal(unavailable, HTTPStatus.SERVICE_UNAVAILABLE) from unavailable
    return _DriverClaimResponse(admitted=True)


@router.post("/driver-release")
async def todo_driver_release(
    body: DriverReleaseRequest,
    _identity: CallerIdentity = Depends(carried_caller),
) -> _DriverClaimResponse:
    """Release a GitHub-backed todo's claim on the master, in the todo's section, while it still names the session."""
    try:
        cleared = await release_relayed_claim(resolve_project_root(body.project_path), body.slug, body.session_id)
    except DriverStartBusy as busy:
        raise _driver_refusal(busy, HTTPStatus.LOCKED) from busy
    except AdmissionUnavailable as unavailable:
        raise _driver_refusal(unavailable, HTTPStatus.SERVICE_UNAVAILABLE) from unavailable
    return _DriverClaimResponse(cleared=cleared)


class _SessionAnswerResponse(BaseModel):
    """This computer's answer about one session id, for one todo."""

    model_config = ConfigDict(frozen=True)
    answer: OwnSessionAnswer


@router.get("/session-answer")
async def todo_session_answer(
    project_path: str,
    slug: str,
    session_id: str,
    _identity: CallerIdentity = Depends(carried_caller),
) -> _SessionAnswerResponse:
    """Say whether a session this computer ran drives the todo, has ended, or was never run here.

    The master asks every known computer this when it judges a claim it cannot verify itself.
    The answer discloses only held, ended or not-own for a session id the asker already holds.
    """
    project_root = resolve_project_root(project_path)
    return _SessionAnswerResponse(answer=await own_session_answer(runtime_db, project_root, slug, session_id))


@router.post("/{slug}/reactivate")
async def todo_reactivate(
    slug: str,
    cwd: Annotated[str | None, Body(embed=True)] = None,
    _identity: CallerIdentity = Depends(carried_caller),
) -> _SlugStatusResponse:
    """Restore a soft-removed todo addressed by slug."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_workflow_store_from_cwd(effective_cwd)

    # Resolve slug to removed-row id (refuse if ambiguous)
    removed_entries = await todos_db.list_todo(include_removed=True, removed_only=True)
    matches = [r for r in removed_entries if r["slug"] == slug]

    if not matches:
        detail = _REACTIVATE_NO_MATCH_DETAIL_TEMPLATE.format(slug=slug)
        raise DeclaredWorkRefusal(status_code=404, detail=detail, work_feedback=detail)
    if len(matches) > 1:
        details = ", ".join(f"{m['id']} (removed {m.get('removed_at')})" for m in matches)
        detail = _REACTIVATE_AMBIGUOUS_DETAIL_TEMPLATE.format(slug=slug, details=details)
        raise DeclaredWorkRefusal(
            status_code=409,
            detail=detail,
            work_feedback=detail,
        )

    todo_id = matches[0]["id"]
    try:
        await todos_db.reactivate_removed(todo_id, cwd=effective_cwd)
    except ReactivateRefused as exc:
        if exc.work_feedback is not None:
            raise DeclaredWorkRefusal(
                status_code=400,
                detail=str(exc),
                work_feedback=exc.work_feedback,
            ) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _SlugStatusResponse(status="ok", slug=slug)


@router.post("/by-id/{todo_id}/reactivate")
async def todo_reactivate_by_id(
    todo_id: str,
    cwd: Annotated[str | None, Body(embed=True)] = None,
    _identity: CallerIdentity = Depends(carried_caller),
) -> _SlugStatusResponse:
    """Restore a soft-removed todo addressed by its durable row id."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_workflow_store_from_cwd(effective_cwd)
    try:
        slug = await todos_db.reactivate_removed(todo_id, cwd=effective_cwd)
    except ReactivateRefused as exc:
        if exc.work_feedback is not None:
            raise DeclaredWorkRefusal(
                status_code=400,
                detail=str(exc),
                work_feedback=exc.work_feedback,
            ) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _SlugStatusResponse(status="ok", slug=slug)
