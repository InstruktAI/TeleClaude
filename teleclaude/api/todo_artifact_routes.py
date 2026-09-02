"""Todo artifact REST endpoints (todos.db backed).

Read, write, remove, list, and diff todo artifacts. Split from
``todo_routes`` so each module stays focused; both routers mount under the
same ``/todos`` prefix.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.api.auth import (
    CallerIdentity,
    clearance_todos_artifacts_diff,
    clearance_todos_artifacts_remove,
    clearance_todos_artifacts_write,
)
from teleclaude.api.todo_artifact_authority import (
    refuse_non_prepare_writer,
    resolved_write_principal,
)
from teleclaude.api.todo_routes import (
    _DRIFT_TRACKED_ARTIFACT_NAMES,
    _default_cwd,
    _get_todos_db_from_cwd,
    _sync_artifact_provenance_state,
)
from teleclaude.api.todo_update_support import require_slug_in_todo
from teleclaude.constants import (
    ARTIFACT_INPUT,
    ARTIFACT_NAMES_RETIRED,
    ARTIFACT_NAMES_WRITABLE,
    PREPARE_ARTIFACT_NAMES,
)
from teleclaude.core.next_machine.provenance import clear_artifact_provenance
from teleclaude.core.next_machine.review_evidence import REVIEW_EVIDENCE_ARTIFACTS
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.todos_db import HolderWriteRefused

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)

router = APIRouter(prefix="/todos", tags=["todos"])

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_PARAMETER_NAMES = ("old", "new")
_MALFORMED_DIGEST_DETAIL = (
    "Invalid {0} digest: expected 64 lowercase hexadecimal characters; received {1!r} (length {2})."
)


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


class _ArtifactListResponse(BaseModel):
    """Response from artifact list."""

    model_config = ConfigDict(frozen=True)
    slug: str
    artifacts: list[str]


class _ArtifactDiffResponse(BaseModel):
    """Response from artifact diff."""

    model_config = ConfigDict(frozen=True)
    slug: str
    name: str
    old_digest: str
    new_digest: str
    diff: str


async def _clear_artifact_provenance_state(todos_db: TodosDb, slug: str, artifact_name: str) -> None:
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        return
    writer = StateWriter(raw_state)
    clear_artifact_provenance(writer, slug, artifact_name)
    await writer.commit(todos_db, slug)


async def _refuse_holder_mutation(todos_db: TodosDb, slug: str) -> None:
    """Raise a 409 if ``slug`` is a structural holder; its artifacts are frozen evidence."""
    if await todos_db.is_holder(slug):
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
    request_id = str(uuid.uuid4())
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    await require_slug_in_todo(todos_db, slug)
    await _refuse_holder_mutation(todos_db, slug)
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
    _identity: CallerIdentity = Depends(clearance_todos_artifacts_remove),
) -> _ArtifactRemoveResponse:
    """Remove a todo artifact and its version history."""
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    if name == ARTIFACT_INPUT:
        raise HTTPException(status_code=400, detail="input artifact cannot be removed")
    await require_slug_in_todo(todos_db, slug)
    await _refuse_holder_mutation(todos_db, slug)

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
    for parameter, digest in zip(_DIGEST_PARAMETER_NAMES, (old, new), strict=True):
        if not _DIGEST_RE.fullmatch(digest):
            raise HTTPException(
                status_code=422,
                detail=_MALFORMED_DIGEST_DETAIL.format(parameter, digest, len(digest)),
            )
    effective_cwd = cwd or _default_cwd()
    todos_db = await _get_todos_db_from_cwd(effective_cwd)
    try:
        diff = await todos_db.artifacts_diff(slug, name, old, new)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _ArtifactDiffResponse(slug=slug, name=name, old_digest=old, new_digest=new, diff=diff)
