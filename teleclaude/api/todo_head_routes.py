"""The publish report surface: how the sealed commit tells the platform what it pushed.

A session about to push one explicit commit registers an intent, then completes it with the push's own
result (``local/projects/teleclaude/spec/feature/workflow/work-review-cycle``). Only the holder and a
builder in its claiming group may report.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.core.workflow_machine.heads import (
    IntentRefused,
    IntentRequest,
    complete_publish_intent,
    register_publish_intent,
)
from teleclaude.types.todo_head import TodoHeadApiRoute, TodoIntentReceipt

router = APIRouter(prefix="/todos", tags=["todos"])
_CWD_REQUIRED = "cwd required: working directory not provided"
_SESSION_REQUIRED = "a session is required to report a publish"
_STATUS_OK = "ok"
_STATUS_REFUSED = 409
_STATUS_BAD_REQUEST = 400
_STATUS_FORBIDDEN = 403


class TodoCompletionResponse(BaseModel):
    """The completed intent."""

    status: str


@router.post(TodoHeadApiRoute.INTENT_ROUTER_PATH)
async def todo_publish_intent(
    item: Annotated[str, Body()],
    sha: Annotated[str, Body()],
    expected_tip: Annotated[str, Body()] = "",
    cwd: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> TodoIntentReceipt:
    """Register the intent to push one commit as a swap of the item's integration ref."""
    if not cwd:
        raise HTTPException(status_code=_STATUS_BAD_REQUEST, detail=_CWD_REQUIRED)
    if not identity.session_id:
        raise HTTPException(status_code=_STATUS_FORBIDDEN, detail=_SESSION_REQUIRED)
    try:
        key = await register_publish_intent(
            IntentRequest(
                project_root=cwd, item=item, sha=sha, expected_tip=expected_tip, caller_session_id=identity.session_id
            )
        )
    except IntentRefused as refusal:
        raise HTTPException(status_code=_STATUS_REFUSED, detail=str(refusal)) from refusal
    return TodoIntentReceipt(status=_STATUS_OK, key=key)


@router.post(TodoHeadApiRoute.COMPLETION_ROUTER_PATH)
async def todo_publish_complete(
    item: Annotated[str, Body()],
    key: Annotated[str, Body()],
    swapped: Annotated[bool, Body()],
    cwd: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> TodoCompletionResponse:
    """Complete a registered intent with the push's own result."""
    if not cwd:
        raise HTTPException(status_code=_STATUS_BAD_REQUEST, detail=_CWD_REQUIRED)
    if not identity.session_id:
        raise HTTPException(status_code=_STATUS_FORBIDDEN, detail=_SESSION_REQUIRED)
    try:
        await complete_publish_intent(cwd, item, key, identity.session_id, swapped)
    except IntentRefused as refusal:
        raise HTTPException(status_code=_STATUS_REFUSED, detail=str(refusal)) from refusal
    return TodoCompletionResponse(status=_STATUS_OK)
