"""Identity-addressed todo lifecycle and artifact mutation routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.api import todo_artifact_routes, todo_routes, todo_stamp_routes
from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.api.todo_slug_routes import request_project_root
from teleclaude.api.todo_update_support import require_slug_found
from teleclaude.api.todo_write_admission import admit_item_write
from teleclaude.api.work_feedback import DeclaredWorkRefusal
from teleclaude.api.working_copy_request import working_copy_request_deadline
from teleclaude.api_models_operations import OperationStatusDTO
from teleclaude.constants import SLUG_NOT_IN_ICEBOX_DETAIL
from teleclaude.core.operations.service import SerializedOperation, get_operations_service
from teleclaude.core.todos_db._todo_soft_delete import TodoIdentityActionRefused, TodoIdentityNotFound
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.core.workflow_store.types import IdentityResolution as TodoIdentityResolution
from teleclaude.services.work.slug_actions import SlugActionOutcome, freeze_todo, unfreeze_todo

logger = get_logger(__name__)

router = APIRouter(
    prefix="/todos", tags=["todos"], dependencies=[Depends(working_copy_request_deadline), Depends(admit_item_write)]
)

_IDENTITY_ACTION_EVENT = "workflow.todo.identity_action"
_CWD_REQUIRED_DETAIL = "cwd required: working directory not provided"
_STATUS_OK = "ok"


class _IdentityAction(StrEnum):
    """Closed set of mutations addressable by a todo row identity."""

    PREPARE = "prepare"
    WORK = "work"
    REMOVE = "remove"
    FREEZE = "freeze"
    UNFREEZE = "unfreeze"
    HOLD = "hold"
    RELEASE = "release"
    STAMP = "stamp"
    ARTIFACT_WRITE = "artifact_write"
    ARTIFACT_REMOVE = "artifact_remove"


class _IdentityOutcome(StrEnum):
    """Closed set of outcomes recorded for one identity-addressed request."""

    PERFORMED = "performed"
    REFUSED = "refused"
    NOT_FOUND = "not_found"


def _log_identity_decision(
    *,
    action: _IdentityAction,
    todo_id: str,
    outcome: _IdentityOutcome,
    resolution: TodoIdentityResolution | None,
) -> None:
    logger.info(
        _IDENTITY_ACTION_EVENT,
        action=action.value,
        todo_id=todo_id,
        outcome=outcome.value,
        status=resolution.status.value if resolution is not None else None,
        slug=resolution.slug if resolution is not None else None,
    )


async def _resolve_identity(
    *,
    action: _IdentityAction,
    todo_id: str,
    cwd: str,
) -> tuple[WorkflowStore, TodoIdentityResolution]:
    try:
        todos_db = await todo_routes._get_workflow_store_from_cwd(cwd)
        resolution = await todos_db.resolve_live_slug_by_id(todo_id)
    except TodoIdentityActionRefused as exc:
        resolution = TodoIdentityResolution(slug=exc.slug, status=exc.status)
        _log_identity_decision(
            action=action,
            todo_id=todo_id,
            outcome=_IdentityOutcome.REFUSED,
            resolution=resolution,
        )
        detail = str(exc)
        raise DeclaredWorkRefusal(status_code=409, detail=detail, work_feedback=detail) from exc
    except TodoIdentityNotFound as exc:
        _log_identity_decision(
            action=action,
            todo_id=todo_id,
            outcome=_IdentityOutcome.NOT_FOUND,
            resolution=None,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        _log_identity_decision(
            action=action,
            todo_id=todo_id,
            outcome=_IdentityOutcome.REFUSED,
            resolution=None,
        )
        raise
    return todos_db, resolution


async def _perform_identity_action[ResultT](
    *,
    action: _IdentityAction,
    todo_id: str,
    cwd: str | None,
    perform: Callable[[TodoIdentityResolution, str], Awaitable[ResultT]],
    require_cwd: bool = False,
) -> ResultT:
    if require_cwd and not cwd:
        _log_identity_decision(
            action=action,
            todo_id=todo_id,
            outcome=_IdentityOutcome.REFUSED,
            resolution=None,
        )
        raise HTTPException(status_code=400, detail=_CWD_REQUIRED_DETAIL)

    effective_cwd = cwd or todo_routes._default_cwd()
    todos_db, resolution = await _resolve_identity(action=action, todo_id=todo_id, cwd=effective_cwd)
    try:
        with todos_db.identity_scope(resolution.slug, todo_id):
            result = await perform(resolution, effective_cwd)
    except HTTPException:
        try:
            current_resolution = await todos_db.resolve_live_slug_by_id(todo_id)
        except TodoIdentityActionRefused as refusal:
            current_resolution = TodoIdentityResolution(slug=refusal.slug, status=refusal.status)
            _log_identity_decision(
                action=action,
                todo_id=todo_id,
                outcome=_IdentityOutcome.REFUSED,
                resolution=current_resolution,
            )
            detail = str(refusal)
            raise DeclaredWorkRefusal(status_code=409, detail=detail, work_feedback=detail) from refusal
        except TodoIdentityNotFound as missing:
            _log_identity_decision(
                action=action,
                todo_id=todo_id,
                outcome=_IdentityOutcome.NOT_FOUND,
                resolution=None,
            )
            raise HTTPException(status_code=404, detail=str(missing)) from missing
        _log_identity_decision(
            action=action,
            todo_id=todo_id,
            outcome=_IdentityOutcome.REFUSED,
            resolution=current_resolution,
        )
        raise
    except Exception:
        _log_identity_decision(
            action=action,
            todo_id=todo_id,
            outcome=_IdentityOutcome.REFUSED,
            resolution=resolution,
        )
        raise

    _log_identity_decision(
        action=action,
        todo_id=todo_id,
        outcome=_IdentityOutcome.PERFORMED,
        resolution=resolution,
    )
    return result


@router.post(
    "/by-id/{todo_id}/prepare",
    status_code=202,
    response_model=OperationStatusDTO,
    response_model_exclude_none=True,
)
async def todo_prepare_by_id(
    todo_id: str,
    cwd: Annotated[str | None, Body()] = None,
    client_request_id: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> SerializedOperation:
    """Submit prepare for exactly the identified todo row."""
    return await _perform_identity_action(
        action=_IdentityAction.PREPARE,
        todo_id=todo_id,
        cwd=cwd,
        perform=lambda resolution, effective_cwd: get_operations_service().submit_todo_prepare(
            slug=resolution.slug,
            cwd=effective_cwd,
            caller_session_id=identity.session_id,
            client_request_id=client_request_id,
            addressed_todo_id=todo_id,
        ),
    )


@router.post(
    "/by-id/{todo_id}/work",
    status_code=202,
    response_model=OperationStatusDTO,
    response_model_exclude_none=True,
)
async def todo_work_by_id(
    todo_id: str,
    cwd: Annotated[str, Body()],
    client_request_id: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> SerializedOperation:
    """Submit work for exactly the identified todo row."""
    return await _perform_identity_action(
        action=_IdentityAction.WORK,
        todo_id=todo_id,
        cwd=cwd,
        require_cwd=True,
        perform=lambda resolution, effective_cwd: get_operations_service().submit_todo_work(
            slug=resolution.slug,
            cwd=effective_cwd,
            caller_session_id=identity.session_id,
            client_request_id=client_request_id,
            addressed_todo_id=todo_id,
        ),
    )


@router.post(
    "/by-id/{todo_id}/remove",
    status_code=202,
    response_model=OperationStatusDTO,
    response_model_exclude_none=True,
)
async def todo_remove_by_id(
    todo_id: str,
    cwd: Annotated[str | None, Body()] = None,
    client_request_id: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> SerializedOperation:
    """Submit removal for exactly the identified todo row."""
    return await _perform_identity_action(
        action=_IdentityAction.REMOVE,
        todo_id=todo_id,
        cwd=cwd,
        perform=lambda resolution, effective_cwd: get_operations_service().submit_todo_remove(
            slug=resolution.slug,
            cwd=effective_cwd,
            caller_session_id=identity.session_id,
            client_request_id=client_request_id,
            force=False,
            addressed_todo_id=todo_id,
        ),
    )


async def _freeze(resolution: TodoIdentityResolution, effective_cwd: str) -> todo_routes._SlugStatusResponse:
    result = await freeze_todo(request_project_root(effective_cwd), resolution.slug)
    require_slug_found(resolution.slug, found=result.outcome is not SlugActionOutcome.NOT_FOUND)
    return todo_routes._SlugStatusResponse(status=_STATUS_OK, slug=resolution.slug, warnings=result.warnings)


async def _unfreeze(resolution: TodoIdentityResolution, effective_cwd: str) -> todo_routes._SlugStatusResponse:
    result = await unfreeze_todo(request_project_root(effective_cwd), resolution.slug)
    if result.outcome is SlugActionOutcome.REFUSED:
        raise HTTPException(status_code=409, detail=result.detail)
    require_slug_found(
        resolution.slug,
        found=result.outcome is not SlugActionOutcome.NOT_FOUND,
        detail=SLUG_NOT_IN_ICEBOX_DETAIL,
    )
    return todo_routes._SlugStatusResponse(status=_STATUS_OK, slug=resolution.slug, warnings=result.warnings)


@router.post("/by-id/{todo_id}/freeze")
async def todo_freeze_by_id(
    todo_id: str,
    cwd: Annotated[str | None, Body(embed=True)] = None,
    _identity: CallerIdentity = Depends(carried_caller),
) -> todo_routes._SlugStatusResponse:
    """Freeze exactly the identified todo row."""
    return await _perform_identity_action(
        action=_IdentityAction.FREEZE,
        todo_id=todo_id,
        cwd=cwd,
        perform=_freeze,
    )


@router.post("/by-id/{todo_id}/unfreeze")
async def todo_unfreeze_by_id(
    todo_id: str,
    cwd: Annotated[str | None, Body(embed=True)] = None,
    _identity: CallerIdentity = Depends(carried_caller),
) -> todo_routes._SlugStatusResponse:
    """Unfreeze exactly the identified todo row."""
    return await _perform_identity_action(
        action=_IdentityAction.UNFREEZE,
        todo_id=todo_id,
        cwd=cwd,
        perform=_unfreeze,
    )


@router.post("/by-id/{todo_id}/hold")
async def todo_hold_by_id(
    todo_id: str,
    cwd: Annotated[str | None, Body()] = None,
    reason: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> todo_routes._TodoUpdateResponse | SerializedOperation:
    """Set a manual hold on exactly the identified todo row."""
    return await _perform_identity_action(
        action=_IdentityAction.HOLD,
        todo_id=todo_id,
        cwd=cwd,
        perform=lambda resolution, effective_cwd: todo_routes.todo_update(
            slug=resolution.slug,
            hold=True,
            reason=reason,
            cwd=effective_cwd,
            identity=identity,
        ),
    )


@router.post("/by-id/{todo_id}/release")
async def todo_release_by_id(
    todo_id: str,
    cwd: Annotated[str | None, Body(embed=True)] = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> todo_routes._TodoUpdateResponse | SerializedOperation:
    """Release a hold on exactly the identified todo row."""
    return await _perform_identity_action(
        action=_IdentityAction.RELEASE,
        todo_id=todo_id,
        cwd=cwd,
        perform=lambda resolution, effective_cwd: todo_routes.todo_update(
            slug=resolution.slug,
            release=True,
            cwd=effective_cwd,
            identity=identity,
        ),
    )


@router.post("/by-id/{todo_id}/stamp")
async def todo_stamp_by_id(
    todo_id: str,
    stamp_type: Annotated[str, Body()],
    background_tasks: BackgroundTasks,
    cwd: Annotated[str | None, Body()] = None,
    value: Annotated[str, Body()] = "",
    phase: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> todo_routes._SlugStatusResponse:
    """Apply a stamp to exactly the identified todo row."""
    return await _perform_identity_action(
        action=_IdentityAction.STAMP,
        todo_id=todo_id,
        cwd=cwd,
        perform=lambda resolution, effective_cwd: todo_stamp_routes.todo_stamp(
            slug=resolution.slug,
            stamp_type=stamp_type,
            cwd=effective_cwd,
            value=value,
            phase=phase,
            identity=identity,
            background_tasks=background_tasks,
        ),
    )


class _ArtifactByIdResponse(BaseModel):
    """The content of exactly the identified todo row's artifact."""

    model_config = ConfigDict(frozen=True)
    todo_id: str
    name: str
    content: str


@router.get("/by-id/{todo_id}/artifacts/{name}")
async def read_artifact_by_id(
    todo_id: str,
    name: str,
    cwd: str | None = None,
    _identity: CallerIdentity = Depends(carried_caller),
) -> _ArtifactByIdResponse:
    """Read an artifact of exactly the identified todo row, including a retained row."""
    todos_db = await todo_routes._get_workflow_store_from_cwd(cwd or todo_routes._default_cwd())
    content = await todos_db.read_artifact_by_id(todo_id, name)
    return _ArtifactByIdResponse(todo_id=todo_id, name=name, content=content)


@router.post("/by-id/{todo_id}/artifacts/{name}")
async def write_artifact_by_id(
    todo_id: str,
    name: str,
    content: Annotated[str, Body()],
    cwd: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> todo_artifact_routes._ArtifactWriteResponse:
    """Write an artifact to exactly the identified todo row."""
    return await _perform_identity_action(
        action=_IdentityAction.ARTIFACT_WRITE,
        todo_id=todo_id,
        cwd=cwd,
        perform=lambda resolution, effective_cwd: todo_artifact_routes.write_artifact(
            slug=resolution.slug,
            name=name,
            content=content,
            cwd=effective_cwd,
            identity=identity,
        ),
    )


@router.delete("/by-id/{todo_id}/artifacts/{name}")
async def remove_artifact_by_id(
    todo_id: str,
    name: str,
    cwd: str | None = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> todo_artifact_routes._ArtifactRemoveResponse:
    """Remove an artifact from exactly the identified todo row."""
    return await _perform_identity_action(
        action=_IdentityAction.ARTIFACT_REMOVE,
        todo_id=todo_id,
        cwd=cwd,
        perform=lambda resolution, effective_cwd: todo_artifact_routes.remove_artifact(
            slug=resolution.slug,
            name=name,
            cwd=effective_cwd,
            _identity=identity,
        ),
    )
