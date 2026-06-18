"""The unified todo stamp surface.

One daemon-side mutation route for every stamp type — worker verdicts and human
gate approvals alike. Split from ``todo_routes`` so each module stays focused;
both routers mount under the same ``/todos`` prefix.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException

from teleclaude.api.auth import CallerIdentity, clearance_todos_update
from teleclaude.api.todo_routes import _SlugStatusResponse, _validate_slug_for_update
from teleclaude.core.next_machine.session_hold import notify_runner_of_gate_approval
from teleclaude.core.next_machine.stamps import apply_todo_stamp
from teleclaude.core.next_machine.state_mutation import StateMutationError
from teleclaude.git import GitCommandError

router = APIRouter(prefix="/todos", tags=["todos"])


def _human_gate_caller_stamp_id(identity: CallerIdentity) -> str:
    if identity.principal and identity.principal.startswith("human:"):
        return identity.principal
    if not identity.session_id and identity.email:
        return f"human:{identity.email}"
    if not identity.session_id and identity.human_role:
        return "human:terminal"
    raise HTTPException(status_code=403, detail="human principal required to approve todo gate")


@router.post("/stamp", response_model=_SlugStatusResponse)
async def todo_stamp(
    slug: Annotated[str, Body()],
    stamp_type: Annotated[str, Body()],
    cwd: Annotated[str | None, Body()] = None,
    value: Annotated[str, Body()] = "",
    phase: Annotated[str | None, Body()] = None,
    notify_runner: Annotated[bool, Body()] = False,
    identity: CallerIdentity = Depends(clearance_todos_update),
) -> _SlugStatusResponse:
    """Apply one todo stamp daemon-side, against the initialized session DB.

    The single stamp surface for every stamp type — worker verdicts and human
    gate approvals alike. Caller identity is taken from the verified request
    identity, never the body: a worker session stamps under its session id, a
    human terminal under its human principal. Running here rather than in the
    bare CLI is what gives the authority gate an initialized session DB.
    """
    if not cwd:
        raise HTTPException(status_code=400, detail="cwd required: working directory not provided")
    _validate_slug_for_update(slug, field_name="slug")
    # ``prd_approved`` is a human-only gate (UC-WFL-22): the caller must resolve to a
    # human principal, never an agent session. Every other stamp is a worker mutation
    # stamped under the verified session id (falling back to a human principal for a
    # human-driven terminal).
    if stamp_type == "prd_approved":
        caller_id = _human_gate_caller_stamp_id(identity)
    else:
        caller_id = identity.session_id or _human_gate_caller_stamp_id(identity)
    try:
        await apply_todo_stamp(
            cwd=cwd,
            slug=slug,
            stamp_type=stamp_type,
            value=value,
            phase=phase,
            caller_session_id=caller_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (StateMutationError, ValueError, GitCommandError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if notify_runner:
        await notify_runner_of_gate_approval(cwd, slug)
    return _SlugStatusResponse(status="ok", slug=slug)
