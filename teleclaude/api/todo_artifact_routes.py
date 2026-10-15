"""Todo artifact REST endpoints (todos.db backed).

Read, write, remove, and list todo artifacts. Split from
``todo_routes`` so each module stays focused; both routers mount under the
same ``/todos`` prefix.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.api.todo_artifact_authority import (
    IntentBodyRefused,
    intent_body_mutation,
    refuse_foreign_claim,
    refuse_non_prepare_writer,
    resolved_write_principal,
    session_ancestry,
)
from teleclaude.api.todo_routes import (
    _DRIFT_TRACKED_ARTIFACT_NAMES,
    _default_cwd,
    _get_workflow_store_from_cwd,
    _sync_artifact_provenance_state,
)
from teleclaude.api.todo_update_support import require_slug_in_todo
from teleclaude.constants import (
    ARTIFACT_DESIGN_SPEC,
    ARTIFACT_INPUT,
    ARTIFACT_NAMES_RETIRED,
    ARTIFACT_NAMES_WRITABLE,
    PREPARE_ARTIFACT_NAMES,
)
from teleclaude.core.next_machine.provenance import clear_artifact_provenance
from teleclaude.core.next_machine.review_evidence import REVIEW_EVIDENCE_ARTIFACTS
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.todos_db import HolderWriteRefused, malformed_digest_detail
from teleclaude.core.workflow_machine.creative import CreativeCapability, CreativeRefused
from teleclaude.core.workflow_machine.creative_commit import creative_facts, episode_mutation
from teleclaude.core.workflow_machine.phase_reading import in_task_lane as task_lane_of
from teleclaude.project_root import resolve_project_root
from teleclaude.types.todos import TodoState

if TYPE_CHECKING:
    from teleclaude.core.workflow_store.store import WorkflowStore

logger = get_logger(__name__)

router = APIRouter(prefix="/todos", tags=["todos"])

# ── Response models ─────────────────────────────────────────────────────────


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


class _ArtifactListEntry(BaseModel):
    """One artifact name with the distinct writers recorded across its versions."""

    model_config = ConfigDict(frozen=True)
    name: str
    writers: list[str]


class _ArtifactListResponse(BaseModel):
    """Response from artifact list."""

    model_config = ConfigDict(frozen=True)
    slug: str
    artifacts: list[_ArtifactListEntry]


async def _clear_artifact_provenance_state(todos_db: WorkflowStore, slug: str, artifact_name: str) -> None:
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        return
    writer = StateWriter(raw_state)
    clear_artifact_provenance(writer, slug, artifact_name)
    await writer.commit(todos_db, slug)


async def _refuse_holder_mutation(todos_db: WorkflowStore, slug: str) -> None:
    """Raise a 409 if ``slug`` is a structural holder; its artifacts are frozen evidence."""
    if await todos_db.is_structural_group_holder(slug):
        raise HTTPException(
            status_code=409,
            detail=(
                f"todo '{slug}' is a structural holder with grouped children; it carries no todo_state, "
                "and its artifacts are frozen read-only evidence — write to its children instead"
            ),
        )


@router.get("/artifacts/{slug}/{name}")
async def read_artifact(
    slug: str,
    name: str,
    cwd: str | None = None,
    _identity: CallerIdentity = Depends(carried_caller),
) -> _ArtifactReadResponse:
    """Read a todo artifact by slug and name."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_workflow_store_from_cwd(effective_cwd)
    content = await todos_db.read_artifact(slug, name, include_removed=True)
    return _ArtifactReadResponse(slug=slug, name=name, content=content)


@router.post("/artifacts/{slug}/{name}")
async def write_artifact(
    slug: str,
    name: str,
    content: Annotated[str, Body()],
    cwd: Annotated[str | None, Body()] = None,
    codebase_sha_at_write: Annotated[str | None, Body()] = None,
    referenced_paths: Annotated[list[str] | None, Body()] = None,
    identity: CallerIdentity = Depends(carried_caller),
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
    request_id = str(uuid.uuid4())
    try:
        project_root = str(resolve_project_root(effective_cwd))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    todos_db = await _get_workflow_store_from_cwd(project_root)
    await _refuse_holder_mutation(todos_db, slug)
    await require_slug_in_todo(todos_db, slug)
    raw_for_lane = await todos_db.read_state(slug) if name == ARTIFACT_INPUT else None
    in_task_lane = raw_for_lane is not None and task_lane_of(TodoState.model_validate(raw_for_lane))
    intent_body_write = name == ARTIFACT_INPUT and bool(identity.session_id)
    if not intent_body_write or in_task_lane:
        await refuse_foreign_claim(todos_db, identity, slug)
        if name in PREPARE_ARTIFACT_NAMES:
            await refuse_non_prepare_writer(identity, slug, name)
    effective_updated_by = resolved_write_principal(identity)
    try:
        if intent_body_write:
            await todos_db.write_artifact_with_state_change(
                slug,
                name,
                content,
                updated_by=effective_updated_by,
                mutate=intent_body_mutation(
                    slug, await session_ancestry(identity.session_id), expect_task=in_task_lane
                ),
            )
        elif name == ARTIFACT_DESIGN_SPEC:
            await todos_db.write_artifact_with_state_change(
                slug,
                name,
                content,
                updated_by=effective_updated_by,
                mutate=episode_mutation(
                    slug,
                    CreativeCapability.DESIGN_SPEC_WRITE,
                    identity.session_id or "",
                    facts=await creative_facts(todos_db, slug),
                ),
            )
        else:
            await todos_db.write_artifact(slug, name, content, updated_by=effective_updated_by)
        _ = codebase_sha_at_write, referenced_paths
        if name in _DRIFT_TRACKED_ARTIFACT_NAMES:
            await _sync_artifact_provenance_state(
                todos_db,
                slug,
                name,
                repo_root=project_root,
                artifact_body=content,
                prepared_session_id=identity.session_id,
            )
    except (HolderWriteRefused, CreativeRefused, IntentBodyRefused) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if name in {artifacts.report_artifact_name for artifacts in REVIEW_EVIDENCE_ARTIFACTS.values()}:
        logger.info(
            "workflow.review_report_written",
            slug=slug,
            artifact=name,
            digest=await todos_db.artifact_digest(slug, name),
            updated_by=effective_updated_by,
            request_id=request_id,
            outcome="stored",
        )
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
    _identity: CallerIdentity = Depends(carried_caller),
) -> _ArtifactRemoveResponse:
    """Remove a todo artifact and its version history."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_workflow_store_from_cwd(effective_cwd)
    await _refuse_holder_mutation(todos_db, slug)
    if name == ARTIFACT_INPUT:
        raise HTTPException(status_code=400, detail="input artifact cannot be removed")
    await require_slug_in_todo(todos_db, slug)

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


class _ArtifactDiffResponse(BaseModel):
    """Response from artifact diff."""

    model_config = ConfigDict(frozen=True)
    slug: str
    name: str
    diff: str


@router.get("/artifacts/{slug}/{name}/diff")
async def diff_artifact(
    slug: str,
    name: str,
    old_digest: str,
    new_digest: str,
    cwd: str | None = None,
    _identity: CallerIdentity = Depends(carried_caller),
) -> _ArtifactDiffResponse:
    """Show a unified diff between two versions of a todo artifact."""
    malformed_detail = malformed_digest_detail(old_digest, new_digest)
    if malformed_detail is not None:
        raise HTTPException(status_code=422, detail=malformed_detail)
    todos_db = await _get_workflow_store_from_cwd(cwd or _default_cwd())
    try:
        diff = await todos_db.artifacts_diff(slug, name, old_digest, new_digest, include_removed=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _ArtifactDiffResponse(slug=slug, name=name, diff=diff)


@router.get("/artifacts/{slug}")
async def list_artifacts(
    slug: str,
    cwd: str | None = None,
    _identity: CallerIdentity = Depends(carried_caller),
) -> _ArtifactListResponse:
    """List artifact names for a slug, with each artifact's distinct writers."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_workflow_store_from_cwd(effective_cwd)
    rows = await todos_db.list_artifacts_with_writers(slug, include_removed=True)
    entries = [_ArtifactListEntry(name=row["name"], writers=row["writers"]) for row in rows]
    return _ArtifactListResponse(slug=slug, artifacts=entries)
