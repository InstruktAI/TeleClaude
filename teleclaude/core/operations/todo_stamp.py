"""Receipt-backed todo stamps: the submission identity and the execution of one persisted stamp.

A stamp runs the project's build gates, which can take many minutes, so the sealed act command
submits it as an operation: the caller receives a receipt at once, the daemon owns the running work
until it settles, and the outcome is delivered to the calling session
(``local/projects/teleclaude/spec/feature/workflow/work-review-cycle``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from teleclaude.core.db_models import Operation
from teleclaude.core.operations._kinds import OperationKind
from teleclaude.core.operations.todo_identity import todo_operation_context
from teleclaude.core.workflow_machine.act_types import ActRequest
from teleclaude.core.workflow_machine.acts import perform_act
from teleclaude.types.workflow_record import Act

STAMP_REATTACH_REFUSAL: Final = (
    "client request id {request_id} is already bound to a different stamp; refusing to reuse it"
)
STAMPED_TEMPLATE: Final = "Stamped {item} at {sha}: phase {phase}, {state}."
COMPLETE_STATE: Final = "complete"
IN_PROGRESS_STATE: Final = "effects still running; repeat the act to complete them"
NO_PHASE: Final = "unknown"
UNREACHABLE_STATUS: Final = 409


class StampPayload(BaseModel):
    """The persisted request of one stamp operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    slug: str
    cwd: str
    sha: str
    text: str


def _payload_of(operation: Operation) -> StampPayload:
    return StampPayload.model_validate_json(operation.payload_json)


@dataclass(frozen=True)
class StampSubmission:
    """What a stamp submission asks for."""

    slug: str
    cwd: str
    sha: str
    text: str
    client_request_id: str | None


def todo_stamp_submission(
    request: StampSubmission,
) -> tuple[str, Callable[[Operation], bool], Callable[[Operation], None]]:
    """The durable payload and the checks that keep a reattachment to the same stamp request."""
    payload = StampPayload(
        kind=OperationKind.TODO_STAMP, slug=request.slug, cwd=request.cwd, sha=request.sha, text=request.text
    )

    def same_request(operation: Operation) -> bool:
        existing = _payload_of(operation)
        return existing.sha == request.sha and existing.text == request.text

    def guard(operation: Operation) -> None:
        if not same_request(operation):
            raise HTTPException(
                status_code=UNREACHABLE_STATUS,
                detail=STAMP_REATTACH_REFUSAL.format(request_id=request.client_request_id or ""),
            )

    return payload.model_dump_json(), same_request, guard


async def run_todo_stamp_operation(operation: Operation) -> str:
    """Perform the persisted stamp as the session that submitted it and report where the item stands."""
    payload = _payload_of(operation)
    cwd, caller_session_id = todo_operation_context(operation)
    result = await perform_act(
        ActRequest(
            project_root=cwd,
            item=payload.slug,
            act=Act.STAMP,
            caller_session_id=caller_session_id,
            text=payload.text,
            sha=payload.sha,
        )
    )
    return STAMPED_TEMPLATE.format(
        item=payload.slug,
        sha=payload.sha,
        phase=result.phase.value if result.phase is not None else NO_PHASE,
        state=COMPLETE_STATE if result.complete else IN_PROGRESS_STATE,
    )


async def continue_task_run_in_place(operation: Operation) -> str:
    """In-place continuation for a caller already bound to the task slug.

    A task is normally executed by a dedicated ``/run-task`` worker the bridge dispatches; an operator
    START is unbound and takes that path. This fallback only fires when the caller session already
    drives the slug, so it returns the run-task continuation rather than the SDLC work machine.
    """
    slug = operation.slug or "<auto>"
    return (
        f"TASK_RUNNING: {slug} — execute the next firing from the current task-plan, "
        "record the result in the log, and stamp the firing's outcome: a success ends "
        "this session (delivered if one-shot, recorded and resting if recurring); an "
        "error stays alive as the human-inspection beacon."
    )
