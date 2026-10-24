"""Execution contract for receipt-backed GitHub workflow-store switches."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.core.db import Db
from teleclaude.core.db_models import Operation
from teleclaude.core.operations._kinds import OperationKind
from teleclaude.core.operations.todo_identity import todo_operation_context, todo_operation_submission
from teleclaude.core.workflow_store.github_switch import switch_project_to_github

if TYPE_CHECKING:
    from teleclaude.core.operations.service import OperationsService, SerializedOperation


async def submit_todo_store_switch(
    service: OperationsService,
    *,
    cwd: str,
    caller_session_id: str,
    client_request_id: str | None,
) -> SerializedOperation:
    """Submit one addressless project switch through the operation service."""
    payload_json, existing_match_ok, on_existing = todo_operation_submission(
        kind=OperationKind.TODO_STORE_SWITCH,
        slug=None,
        cwd=cwd,
        addressed_todo_id=None,
        client_request_id=client_request_id,
    )
    return await service._submit_operation(
        kind=OperationKind.TODO_STORE_SWITCH,
        caller_session_id=caller_session_id,
        cwd=cwd,
        slug=None,
        client_request_id=client_request_id,
        payload_json=payload_json,
        existing_match_ok=existing_match_ok,
        on_existing=on_existing,
    )


async def run_todo_store_switch_operation(db: Db, operation: Operation) -> str:
    """Run one project-scoped store switch and fail the receipt with its report if incomplete."""
    cwd, _caller_session_id = todo_operation_context(operation)
    report = await switch_project_to_github(db, cwd, operation.operation_id)
    result = report.render()
    if not report.complete:
        raise RuntimeError(result)
    return result
