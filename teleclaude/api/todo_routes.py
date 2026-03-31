"""Todo/workflow REST endpoints for the telec CLI tool subcommands.

Exposes the next-machine state machine functions (prepare, work)
and roadmap mutation operations (mark-phase, set-deps) as REST endpoints
with dual-factor caller identity enforcement.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.api.auth import (
    CallerIdentity,
    clearance_todos_create,
    clearance_todos_integrate,
    clearance_todos_mark_phase,
    clearance_todos_prepare,
    clearance_todos_set_deps,
    clearance_todos_work,
)
from teleclaude.api_models import OperationStatusDTO
from teleclaude.config import config
from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine.core import (
    _PREPARE_ARTIFACT_PHASES,
    _PREPARE_PHASE_VALUES,
    _PREPARE_VERDICT_PHASES,
    _PREPARE_VERDICT_VALUES,
    detect_circular_dependency,
    has_uncommitted_changes,
    load_roadmap,
    load_roadmap_deps,
    save_roadmap,
)
from teleclaude.core.next_machine.slug_resolution import resolve_canonical_project_root
from teleclaude.core.next_machine.state_io import mark_phase, stamp_artifact, stamp_verdict
from teleclaude.core.operations import get_operations_service
from teleclaude.core.operations.service import SerializedOperation

if TYPE_CHECKING:
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


_BUILD_TERMINAL_STATES = frozenset(
    {"build_complete", "review_pending", "review_approved", "finalize_ready", "finalize_handed_off"}
)


def _resolve_worktree_cwd(cwd: str, slug: str, force: bool) -> str:
    """Resolve effective cwd for worktree-scoped operations."""
    project_root = resolve_canonical_project_root(cwd)
    worktree_path = Path(project_root) / WORKTREE_DIR / slug
    if worktree_path.exists():
        return str(worktree_path)
    if force:
        return cwd
    raise HTTPException(status_code=404, detail=f"worktree not found at {worktree_path}")


def _auto_commit_state(effective_cwd: str, slug: str, label: str) -> None:
    """Auto-commit state.yaml to keep the worktree clean."""
    from teleclaude.git import Repo  # pylint: disable=import-outside-toplevel

    repo = Repo(effective_cwd)
    if repo.git.diff("HEAD", "--", f"todos/{slug}/state.yaml").strip():
        repo.git.add("--", f"todos/{slug}/state.yaml")
        # --no-verify: state.yaml is pure machine-generated data, not subject to test/lint
        # gates. Pre-commit hooks running code checks on a bookkeeping commit would be
        # slow, irrelevant, and would fail in environments where the test suite requires
        # a running daemon.
        repo.git.commit("-m", f"chore(todo): {slug} {label}", "--no-verify", "--only", "--", f"todos/{slug}/state.yaml")


@router.post("/mark-phase")
async def todo_mark_phase(  # pyright: ignore  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    slug: Annotated[str, Body()],
    phase: Annotated[str | None, Body()] = None,
    status: Annotated[str | None, Body()] = None,
    target: Annotated[str | None, Body()] = None,
    cwd: Annotated[str | None, Body()] = None,
    _identity: CallerIdentity = Depends(clearance_todos_mark_phase),
    force: Annotated[bool, Body()] = False,
) -> dict[str, str]:
    """Mark a work phase as complete/approved in state.yaml.

    Supports both the new `target` param (direct state name) and the legacy
    `phase`/`status` pair. When `target` is provided, it takes precedence.
    """
    if not cwd:
        raise HTTPException(status_code=400, detail="cwd required: working directory not provided")

    _todos_db: TodosDb | None = None

    async def _ensure_db() -> TodosDb:
        nonlocal _todos_db
        if _todos_db is None:
            _todos_db = await _get_todos_db_from_cwd(cwd)
        return _todos_db

    # New target-based path
    if target:
        # Work-phase targets that need worktree resolution
        effective_cwd = _resolve_worktree_cwd(cwd, slug, force) if target in _BUILD_TERMINAL_STATES else cwd

        # Uncommitted-changes guard for build terminal states
        if not force and target in ("build_complete",):
            if has_uncommitted_changes(cwd, slug):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"worktree {WORKTREE_DIR}/{slug} has uncommitted changes"
                        " — commit them before marking phase complete"
                    ),
                )

        try:
            updated_state = mark_phase(effective_cwd, slug, target)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        await (await _ensure_db()).write_state(slug, updated_state)
        logger.info("mark_phase synced to todos.db: slug=%s target=%s", slug, target)

        try:
            _auto_commit_state(effective_cwd, slug, target)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("auto_commit_state failed slug=%s cwd=%s target=%s err=%s", slug, effective_cwd, target, exc)
            return {
                "result": f"PARTIAL: {slug} state updated - target: {target} (state written, commit failed: {exc})",
                "state": str(updated_state),
            }
        return {"result": f"OK: {slug} state updated - target: {target}", "state": str(updated_state)}

    # Legacy phase/status path — map to target
    if not phase or not status:
        raise HTTPException(status_code=400, detail="either 'target' or both 'phase' and 'status' are required")

    # Prepare sub-phases: verdict-based, operate on main repo
    if phase in _PREPARE_VERDICT_PHASES:
        if status not in _PREPARE_VERDICT_VALUES:
            raise HTTPException(
                status_code=400,
                detail=f"invalid verdict '{status}': must be one of {', '.join(_PREPARE_VERDICT_VALUES)}",
            )
        updated_state = stamp_verdict(cwd, slug, phase, status)
        await (await _ensure_db()).write_state(slug, updated_state)
        logger.info("stamp_verdict synced to todos.db: slug=%s phase=%s verdict=%s", slug, phase, status)
        return {"result": f"OK: {slug} state updated - {phase}.verdict: {status}", "state": str(updated_state)}

    # Artifact stamp phases
    if phase in _PREPARE_ARTIFACT_PHASES:
        updated_state = stamp_artifact(cwd, slug, phase)
        await (await _ensure_db()).write_state(slug, updated_state)
        logger.info("stamp_artifact synced to todos.db: slug=%s artifact=%s", slug, phase)
        return {
            "result": f"OK: {slug} state updated - artifacts.{phase}.produced_at stamped",
            "state": str(updated_state),
        }

    # Direct prepare_phase advancement
    if phase == "prepare":
        if status not in _PREPARE_PHASE_VALUES:
            raise HTTPException(
                status_code=400,
                detail=f"invalid prepare status '{status}': must be one of {', '.join(_PREPARE_PHASE_VALUES)}",
            )
        resolved_target = status
        updated_state = mark_phase(cwd, slug, resolved_target)
        await (await _ensure_db()).write_state(slug, updated_state)
        logger.info("mark_phase synced to todos.db: slug=%s prepare_phase=%s", slug, status)
        return {"result": f"OK: {slug} state updated - prepare_phase: {status}", "state": str(updated_state)}

    # Work phases: build/review — map to target name
    if phase not in ("build", "review"):
        all_phases = ("build", "review", "prepare", *_PREPARE_VERDICT_PHASES, *_PREPARE_ARTIFACT_PHASES)
        raise HTTPException(status_code=400, detail=f"invalid phase '{phase}': must be one of {', '.join(all_phases)}")

    resolved_target = f"{phase}_{status}"
    effective_cwd = _resolve_worktree_cwd(cwd, slug, force)

    # Uncommitted-changes guard
    build_terminal = ("complete", "approved")
    if not force and phase == "build" and status in build_terminal:
        if has_uncommitted_changes(cwd, slug):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"worktree {WORKTREE_DIR}/{slug} has uncommitted changes"
                    " — commit them before marking phase complete"
                ),
            )

    try:
        updated_state = mark_phase(effective_cwd, slug, resolved_target)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await (await _ensure_db()).write_state(slug, updated_state)
    logger.info("mark_phase synced to todos.db: slug=%s phase=%s status=%s", slug, phase, status)

    try:
        _auto_commit_state(effective_cwd, slug, f"{phase}={status}")
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(
            "auto_commit_state failed slug=%s cwd=%s phase=%s status=%s err=%s", slug, effective_cwd, phase, status, exc
        )
        return {
            "result": f"PARTIAL: {slug} state updated - {phase}: {status} (state written, commit failed: {exc})",
            "state": str(updated_state),
        }
    return {"result": f"OK: {slug} state updated - {phase}: {status}", "state": str(updated_state)}


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

    entries = load_roadmap(cwd)
    if not entries:
        raise HTTPException(status_code=404, detail="todos/roadmap.yaml not found")

    roadmap_slugs = {e.slug for e in entries}
    if slug not in roadmap_slugs:
        raise HTTPException(status_code=404, detail=f"slug '{slug}' not found in roadmap.yaml")
    for dep in after:
        if dep not in roadmap_slugs:
            raise HTTPException(status_code=404, detail=f"dependency '{dep}' not found in roadmap.yaml")

    deps = load_roadmap_deps(cwd)
    cycle = detect_circular_dependency(deps, slug, after)
    if cycle:
        cycle_str = " -> ".join(cycle)
        raise HTTPException(status_code=409, detail=f"circular dependency detected: {cycle_str}")

    for entry in entries:
        if entry.slug == slug:
            entry.after = after
            break

    save_roadmap(cwd, entries)

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
async def todo_dump(
    slug: Annotated[str, Body()],
    content: Annotated[str, Body()],
    after: Annotated[list[str] | None, Body()] = None,
    kind: Annotated[str | None, Body()] = None,
    cwd: Annotated[str | None, Body()] = None,
) -> _SlugStatusResponse:
    """Create a todo: state + artifact + roadmap entry in todos.db.

    When kind="bug", sets state.kind and writes a "bug" artifact instead of "input".
    """
    from teleclaude.core.next_machine._types import default_state  # pylint: disable=import-outside-toplevel

    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)

    existing = await todos_db.read_state(slug)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Todo '{slug}' already exists")

    state = default_state()
    if kind == "bug":
        state["kind"] = "bug"

    await todos_db.write_state(slug, state)

    if kind == "bug":
        await todos_db.write_artifact(slug, "bug", content)
    else:
        input_content = f"# {slug} — Input\n\n{content}\n"
        await todos_db.write_artifact(slug, "input", input_content)

    await todos_db.add_to_roadmap(slug, after=after if after else None)

    return _SlugStatusResponse(status="ok", slug=slug)


@router.post("/split")
async def todo_split(
    slug: Annotated[str, Body()],
    children: Annotated[list[str], Body()],
    cwd: Annotated[str | None, Body()] = None,
) -> _SplitResponse:
    """Split a todo into children: create child state + roadmap entries, update parent breakdown."""
    from teleclaude.core.next_machine._types import default_state  # pylint: disable=import-outside-toplevel

    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)

    # Verify parent exists
    parent_state = await todos_db.read_state(slug)
    if parent_state is None:
        raise HTTPException(status_code=404, detail=f"Parent todo '{slug}' not found")

    # Create children
    for child_slug in children:
        existing = await todos_db.read_state(child_slug)
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"Child todo '{child_slug}' already exists")
        await todos_db.write_state(child_slug, default_state())
        # Copy parent input to child
        parent_input = await todos_db.read_artifact(slug, "input")
        if parent_input:
            await todos_db.write_artifact(child_slug, "input", parent_input)
        await todos_db.add_to_roadmap(child_slug, group_slug=slug)

    # Update parent breakdown
    parent_state["breakdown"] = {"assessed": True, "todos": list(children)}  # type: ignore[dict-item]
    await todos_db.write_state(slug, parent_state)

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

    # Delete from DB
    await todos_db.delete_state(slug)
    await todos_db.delete_artifacts(slug)
    await todos_db.remove_from_roadmap(slug)
    await todos_db.clean_dep_references(slug)

    # Clean up worktree and branch (filesystem/git cleanup stays — these are code branches)
    cleanup_delivered_slug(effective_cwd, slug)

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


@router.post("/stamp/{slug}")
async def stamp(  # pylint: disable=too-many-locals,too-many-branches
    slug: str,
    stamp_type: Annotated[str, Body()],
    value: Annotated[str, Body()],
    cwd: Annotated[str | None, Body()] = None,
) -> _StampResponse:
    """Stamp a verdict, DOR, build, or grounding value into todo state."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    state = await todos_db.read_state(slug)
    if state is None:
        raise HTTPException(status_code=404, detail=f"no state found for slug '{slug}'")

    if stamp_type == "verdict":
        # Determine which review sub-phase from current state
        current = str(state.get("current", ""))
        phase_map = {
            "requirements_review": "requirements_review",
            "test_spec_review": "test_spec_review",
            "plan_review": "plan_review",
        }
        review_phase = phase_map.get(current)
        if not review_phase:
            raise HTTPException(
                status_code=409,
                detail=f"current state '{current}' is not a review phase",
            )
        review_dict = state.get(review_phase)
        if not isinstance(review_dict, dict):
            review_dict = {}
        review_dict["verdict"] = value
        state[review_phase] = review_dict
    elif stamp_type == "build":
        state["current"] = f"build_{value}"
    elif stamp_type == "grounding":
        grounding = state.get("grounding")
        if not isinstance(grounding, dict):
            grounding = {}
        grounding["valid"] = value == "valid"
        state["grounding"] = grounding
    elif stamp_type == "dor":
        # value format: "score:9,status:pass" or plain status like "pass"
        dor = state.get("dor")
        if not isinstance(dor, dict):
            dor = {}
        # Parse compound format: "score:9,status:pass"
        if "," in value and ":" in value:
            for part in value.split(","):
                k, _, v = part.partition(":")
                k, v = k.strip(), v.strip()
                if k == "score":
                    dor["score"] = int(v)
                elif k == "status":
                    dor["status"] = v
        else:
            dor["status"] = value
        state["dor"] = dor
    else:
        raise HTTPException(status_code=400, detail=f"unknown stamp type: {stamp_type}")

    await todos_db.write_state(slug, state)
    return _StampResponse(status="ok", slug=slug, stamp_type=stamp_type)


@router.get("/{slug}/show")
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
