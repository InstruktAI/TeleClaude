"""The sealed act surface: one daemon-side route through which a session performs a lifecycle act.

The caller's session comes from the verified request identity, never the body; the roles and
authority the act is judged against are read from that session's record
(``local/projects/teleclaude/spec/feature/workflow/item-acts``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.api.sessions_actions_routes import run_pinned_session
from teleclaude.api_models import RunSessionRequest
from teleclaude.api_models_operations import OperationStatusDTO
from teleclaude.core.operations.service import SerializedOperation, get_operations_service
from teleclaude.core.operations.todo_stamp import StampSubmission
from teleclaude.core.workflow_machine.act_types import ActRefused, ActRequest
from teleclaude.core.workflow_machine.acts import perform_act
from teleclaude.core.workflow_machine.entry import EntryRefused, plan_child
from teleclaude.core.workflow_machine.helpers import HelperStartRefused, register_helper_start, settle_helper_start
from teleclaude.types.todo_act import TodoActApiRoute, TodoChildApiRoute, TodoStampApiRoute
from teleclaude.types.workflow_record import Act


class TodoActResponse(BaseModel):
    """The outcome of a performed act."""

    status: str
    act_key: str
    phase: str | None
    complete: bool
    finding_key: str


router = APIRouter(prefix="/todos", tags=["todos"])
_CWD_REQUIRED = "cwd required: working directory not provided"
_SESSION_REQUIRED = "a session is required to perform a lifecycle act"
_STATUS_OK = "ok"
_STATUS_REFUSED = 409
_STATUS_BAD_REQUEST = 400
_STATUS_FORBIDDEN = 403
_STATUS_ACCEPTED = 202
_STAMP_AS_OPERATION = "stamp runs the build gates and is submitted as an operation; use telec todo act <item> stamp"


@router.post(TodoActApiRoute.ROUTER_PATH)
async def todo_act(
    item: Annotated[str, Body()],
    act: Annotated[str, Body()],
    cwd: Annotated[str | None, Body()] = None,
    text: Annotated[str, Body()] = "",
    sha: Annotated[str, Body()] = "",
    revision: Annotated[str, Body()] = "",
    person: Annotated[str, Body()] = "",
    finding: Annotated[str, Body()] = "",
    wait: Annotated[str, Body()] = "",
    instruction: Annotated[str, Body()] = "",
    identity: CallerIdentity = Depends(carried_caller),
) -> TodoActResponse:
    """Perform one lifecycle act as the authenticated session."""
    if not cwd:
        raise HTTPException(status_code=_STATUS_BAD_REQUEST, detail=_CWD_REQUIRED)
    if not identity.session_id:
        raise HTTPException(status_code=_STATUS_FORBIDDEN, detail=_SESSION_REQUIRED)
    if act == Act.STAMP.value:
        raise HTTPException(status_code=_STATUS_BAD_REQUEST, detail=_STAMP_AS_OPERATION)
    try:
        request = ActRequest(
            project_root=cwd,
            item=item,
            act=Act(act),
            caller_session_id=identity.session_id,
            text=text,
            sha=sha,
            revision=revision,
            person=person,
            finding_key=finding,
            wait=wait,
            instruction=instruction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=_STATUS_BAD_REQUEST, detail=str(exc)) from exc
    try:
        result = await perform_act(request)
    except ActRefused as refusal:
        raise HTTPException(status_code=_STATUS_REFUSED, detail=str(refusal)) from refusal
    return TodoActResponse(
        status=_STATUS_OK,
        act_key=result.act_key,
        phase=result.phase.value if result.phase is not None else None,
        complete=result.complete,
        finding_key=result.finding_key,
    )


@router.post(
    TodoStampApiRoute.ROUTER_PATH,
    status_code=_STATUS_ACCEPTED,
    response_model=OperationStatusDTO,
    response_model_exclude_none=True,
)
async def todo_stamp(
    item: Annotated[str, Body()],
    sha: Annotated[str, Body()],
    cwd: Annotated[str | None, Body()] = None,
    text: Annotated[str, Body()] = "",
    client_request_id: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> SerializedOperation:
    """Submit a stamp as a receipt-backed operation; its outcome is delivered to the calling session."""
    if not cwd:
        raise HTTPException(status_code=_STATUS_BAD_REQUEST, detail=_CWD_REQUIRED)
    if not identity.session_id:
        raise HTTPException(status_code=_STATUS_FORBIDDEN, detail=_SESSION_REQUIRED)
    return await get_operations_service().submit_todo_stamp(
        StampSubmission(slug=item, cwd=cwd, sha=sha, text=text, client_request_id=client_request_id),
        identity.session_id,
    )


class TodoChildResponse(BaseModel):
    """The child session a holding driver started."""

    status: str
    session_id: str
    procedure: str


@router.post(TodoChildApiRoute.ROUTER_PATH)
async def todo_child(
    item: Annotated[str, Body()],
    cwd: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> TodoChildResponse:
    """Start the child the holding driver's declarations name, as a session in the driver's claiming group."""
    if not cwd:
        raise HTTPException(status_code=_STATUS_BAD_REQUEST, detail=_CWD_REQUIRED)
    if not identity.session_id:
        raise HTTPException(status_code=_STATUS_FORBIDDEN, detail=_SESSION_REQUIRED)
    try:
        plan = await plan_child(cwd, item, identity.session_id)
        start_key = await register_helper_start(cwd, item, identity.session_id)
    except (EntryRefused, HelperStartRefused) as refusal:
        raise HTTPException(status_code=_STATUS_REFUSED, detail=str(refusal)) from refusal
    try:
        created = await run_pinned_session(
            RunSessionRequest(command=plan.procedure_id, args=plan.arguments, project=cwd, subfolder=plan.subfolder),
            identity,
            plan.declarations,
        )
    except BaseException:
        await settle_helper_start(cwd, item, start_key, "")
        raise
    await settle_helper_start(cwd, item, start_key, str(created.session_id))
    return TodoChildResponse(status=_STATUS_OK, session_id=str(created.session_id), procedure=plan.procedure_id)
