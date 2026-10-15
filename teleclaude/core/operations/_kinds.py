"""Operation-kind vocabulary: the closed set of kinds, their outcome events, and the command types they back."""

from __future__ import annotations

from enum import StrEnum

from teleclaude.core.events import EventType
from teleclaude.types.commands import CommandType


class OperationKind(StrEnum):
    """The closed set of operation kinds a receipt-backed operation can carry."""

    TODO_WORK = "todo_work"
    TASK_RUN = "task_run"
    TODO_INTEGRATE = "todo_integrate"
    TODO_CREATE = "todo_create"
    TODO_PREPARE = "todo_prepare"
    TODO_STAMP = "todo_stamp"
    TODO_RENAME = "todo_rename"
    TODO_REMOVE = "todo_remove"
    SESSION_CLOSE = "session_close"
    AGENT_RESTART = "agent_restart"
    AGENT_HANDOFF = "agent_handoff"
    PROCEDURE_ACTIVATION = "procedure_activation"
    JOB_RUN = "job_run"


_OUTCOME_EVENTS: dict[OperationKind, tuple[EventType, EventType]] = {
    OperationKind.TODO_WORK: ("operation.todo_work.completed", "operation.todo_work.failed"),
    OperationKind.TASK_RUN: ("operation.task_run.completed", "operation.task_run.failed"),
    OperationKind.TODO_INTEGRATE: ("operation.todo_integrate.completed", "operation.todo_integrate.failed"),
    OperationKind.TODO_CREATE: ("operation.todo_create.completed", "operation.todo_create.failed"),
    OperationKind.TODO_PREPARE: ("operation.todo_prepare.completed", "operation.todo_prepare.failed"),
    OperationKind.TODO_STAMP: ("operation.todo_stamp.completed", "operation.todo_stamp.failed"),
    OperationKind.TODO_RENAME: ("operation.todo_rename.completed", "operation.todo_rename.failed"),
    OperationKind.TODO_REMOVE: ("operation.todo_remove.completed", "operation.todo_remove.failed"),
    OperationKind.SESSION_CLOSE: ("session.close.completed", "session.close.failed"),
    OperationKind.AGENT_RESTART: ("agent.restart.completed", "agent.restart.failed"),
    OperationKind.AGENT_HANDOFF: ("agent_runtime.handoff.completed", "agent_runtime.handoff.failed"),
    OperationKind.PROCEDURE_ACTIVATION: (
        "agent_runtime.procedure_activation.completed",
        "agent_runtime.procedure_activation.failed",
    ),
    OperationKind.JOB_RUN: ("operation.job_run.completed", "operation.job_run.failed"),
}
_COMMAND_TYPE_TO_OPERATION_KIND: dict[CommandType, OperationKind] = {
    CommandType.CLOSE_SESSION: OperationKind.SESSION_CLOSE,
    CommandType.RESTART_AGENT: OperationKind.AGENT_RESTART,
    CommandType.HANDOFF_AGENT: OperationKind.AGENT_HANDOFF,
    CommandType.ACTIVATE_PROCEDURE: OperationKind.PROCEDURE_ACTIVATION,
}


def outcome_events_for(kind: str) -> tuple[EventType, EventType] | None:
    """The success and failure events of a stored kind, or None for a kind that is no longer declared."""
    try:
        return _OUTCOME_EVENTS[OperationKind(kind)]
    except (ValueError, KeyError):
        return None


def all_outcome_events() -> tuple[EventType, ...]:
    """Return every outcome event — both members of every kind's success/failure pair.

    The published bridge subscribes to this rather than to ``_OUTCOME_EVENTS``
    directly, so a new kind's pair is picked up without the subscriber module
    knowing the map's shape.
    """
    return tuple(event for pair in _OUTCOME_EVENTS.values() for event in pair)
