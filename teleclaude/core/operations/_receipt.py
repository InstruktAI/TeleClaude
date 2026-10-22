"""How a receipt tells its caller where its operation lives and how to read it."""

from typing import TypedDict

from teleclaude.config.machine import config
from teleclaude.core.todos_db._exceptions import OperationErrorPayload

_RECOVERY_COMMAND_TEMPLATE = "telec operations get {operation_id} --computer {computer}"


def recovery_command(operation_id: str) -> str:
    """The command that reads an operation, addressed to the computer that owns its row."""
    return _RECOVERY_COMMAND_TEMPLATE.format(operation_id=operation_id, computer=config.computer.name)


class SerializedOperation(TypedDict, total=False):
    operation_id: str
    kind: str
    state: str
    poll_after_ms: int
    status_path: str
    recovery_command: str
    slug: str
    success_event: str
    failure_event: str
    computer: str
    progress_phase: str
    progress_decision: str
    progress_reason: str
    result: str
    error: str
    work_feedback: str
    error_payload: OperationErrorPayload
    client_request_id: str
