"""Execution contract for receipt-backed repairs of a project's GitHub board."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.config.machine import config
from teleclaude.core.db_models import Operation
from teleclaude.core.operations._kinds import OperationKind
from teleclaude.core.operations.todo_identity import todo_operation_context, todo_operation_submission
from teleclaude.core.workflow_store.github_board_setup import BoardRepairOutcome
from teleclaude.core.workflow_store.github_store import repair_github_board

if TYPE_CHECKING:
    from teleclaude.core.operations.service import OperationsService, SerializedOperation

_REPAIRED = "The board shows every item as the workflow record reflects."
_INCOMPLETE = "The board could not be fully repaired."
_SETUP_OWED = "Board setup: {}"
_ITEM_UNWRITTEN = "{}: {}"
_LINE_BREAK = "\n"


async def submit_todo_board_repair(
    service: OperationsService,
    *,
    cwd: str,
    caller_session_id: str,
    client_request_id: str | None,
) -> SerializedOperation:
    """Submit one addressless board repair through the operation service."""
    payload_json, existing_match_ok, on_existing = todo_operation_submission(
        kind=OperationKind.TODO_BOARD_REPAIR,
        slug=None,
        cwd=cwd,
        addressed_todo_id=None,
        client_request_id=client_request_id,
    )
    return await service._submit_operation(
        kind=OperationKind.TODO_BOARD_REPAIR,
        caller_session_id=caller_session_id,
        cwd=cwd,
        slug=None,
        client_request_id=client_request_id,
        payload_json=payload_json,
        existing_match_ok=existing_match_ok,
        on_existing=on_existing,
    )


async def run_todo_board_repair_operation(operation: Operation) -> str:
    """Repair the project's board and fail the receipt with the report when anything could not be written."""
    cwd, _caller_session_id = todo_operation_context(operation)
    outcome = await repair_github_board(cwd, computer=config.computer.name)
    report = render_board_repair(outcome)
    if not outcome.complete:
        raise RuntimeError(report)
    return report


def render_board_repair(outcome: BoardRepairOutcome) -> str:
    """Render what a repair wrote, or what it could not write and why."""
    if outcome.complete:
        return _REPAIRED
    lines = [_INCOMPLETE]
    if outcome.setup.cause is not None:
        lines.append(_SETUP_OWED.format(outcome.setup.cause))
    lines.extend(_ITEM_UNWRITTEN.format(slug, reason) for slug, reason in outcome.unwritten)
    return _LINE_BREAK.join(lines)
