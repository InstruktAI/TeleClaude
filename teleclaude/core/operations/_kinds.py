"""Operation vocabulary: kinds, outcome-event types, and the command types they back."""

from __future__ import annotations

from enum import StrEnum

from teleclaude.types.commands import CommandType


class OperationKind(StrEnum):
    """The closed set of operation kinds a receipt-backed operation can carry."""

    TODO_WORK = "todo_work"
    TASK_RUN = "task_run"
    TODO_INTEGRATE = "todo_integrate"
    TODO_CREATE = "todo_create"
    TODO_PREPARE = "todo_prepare"
    TODO_RENAME = "todo_rename"
    TODO_REMOVE = "todo_remove"
    TODO_STORE_SWITCH = "todo_store_switch"
    TODO_FILING = "todo_filing"
    SESSION_CLOSE = "session_close"
    AGENT_RESTART = "agent_restart"
    AGENT_HANDOFF = "agent_handoff"
    PROCEDURE_ACTIVATION = "procedure_activation"
    JOB_RUN = "job_run"


class OperationSucceededEvent(StrEnum):
    """The closed set of success events emitted by receipt-backed operations."""

    TODO_WORK = "operation.todo_work.completed"
    TASK_RUN = "operation.task_run.completed"
    TODO_INTEGRATE = "operation.todo_integrate.completed"
    TODO_CREATE = "operation.todo_create.completed"
    TODO_PREPARE = "operation.todo_prepare.completed"
    TODO_RENAME = "operation.todo_rename.completed"
    TODO_REMOVE = "operation.todo_remove.completed"
    TODO_STORE_SWITCH = "operation.todo_store_switch.completed"
    TODO_FILING = "operation.todo_filing.completed"
    SESSION_CLOSE = "session.close.completed"
    AGENT_RESTART = "agent.restart.completed"
    AGENT_HANDOFF = "agent_runtime.handoff.completed"
    PROCEDURE_ACTIVATION = "agent_runtime.procedure_activation.completed"
    JOB_RUN = "operation.job_run.completed"


class OperationFailedEvent(StrEnum):
    """The closed set of failure events emitted by receipt-backed operations."""

    TODO_WORK = "operation.todo_work.failed"
    TASK_RUN = "operation.task_run.failed"
    TODO_INTEGRATE = "operation.todo_integrate.failed"
    TODO_CREATE = "operation.todo_create.failed"
    TODO_PREPARE = "operation.todo_prepare.failed"
    TODO_RENAME = "operation.todo_rename.failed"
    TODO_REMOVE = "operation.todo_remove.failed"
    TODO_STORE_SWITCH = "operation.todo_store_switch.failed"
    TODO_FILING = "operation.todo_filing.failed"
    SESSION_CLOSE = "session.close.failed"
    AGENT_RESTART = "agent.restart.failed"
    AGENT_HANDOFF = "agent_runtime.handoff.failed"
    PROCEDURE_ACTIVATION = "agent_runtime.procedure_activation.failed"
    JOB_RUN = "operation.job_run.failed"


_OUTCOME_EVENTS: dict[OperationKind, tuple[OperationSucceededEvent, OperationFailedEvent]] = {
    OperationKind.TODO_WORK: (OperationSucceededEvent.TODO_WORK, OperationFailedEvent.TODO_WORK),
    OperationKind.TASK_RUN: (OperationSucceededEvent.TASK_RUN, OperationFailedEvent.TASK_RUN),
    OperationKind.TODO_INTEGRATE: (OperationSucceededEvent.TODO_INTEGRATE, OperationFailedEvent.TODO_INTEGRATE),
    OperationKind.TODO_CREATE: (OperationSucceededEvent.TODO_CREATE, OperationFailedEvent.TODO_CREATE),
    OperationKind.TODO_PREPARE: (OperationSucceededEvent.TODO_PREPARE, OperationFailedEvent.TODO_PREPARE),
    OperationKind.TODO_RENAME: (OperationSucceededEvent.TODO_RENAME, OperationFailedEvent.TODO_RENAME),
    OperationKind.TODO_REMOVE: (OperationSucceededEvent.TODO_REMOVE, OperationFailedEvent.TODO_REMOVE),
    OperationKind.TODO_STORE_SWITCH: (
        OperationSucceededEvent.TODO_STORE_SWITCH,
        OperationFailedEvent.TODO_STORE_SWITCH,
    ),
    OperationKind.TODO_FILING: (OperationSucceededEvent.TODO_FILING, OperationFailedEvent.TODO_FILING),
    OperationKind.SESSION_CLOSE: (OperationSucceededEvent.SESSION_CLOSE, OperationFailedEvent.SESSION_CLOSE),
    OperationKind.AGENT_RESTART: (OperationSucceededEvent.AGENT_RESTART, OperationFailedEvent.AGENT_RESTART),
    OperationKind.AGENT_HANDOFF: (OperationSucceededEvent.AGENT_HANDOFF, OperationFailedEvent.AGENT_HANDOFF),
    OperationKind.PROCEDURE_ACTIVATION: (
        OperationSucceededEvent.PROCEDURE_ACTIVATION,
        OperationFailedEvent.PROCEDURE_ACTIVATION,
    ),
    OperationKind.JOB_RUN: (OperationSucceededEvent.JOB_RUN, OperationFailedEvent.JOB_RUN),
}
_COMMAND_TYPE_TO_OPERATION_KIND: dict[CommandType, OperationKind] = {
    CommandType.CLOSE_SESSION: OperationKind.SESSION_CLOSE,
    CommandType.RESTART_AGENT: OperationKind.AGENT_RESTART,
    CommandType.HANDOFF_AGENT: OperationKind.AGENT_HANDOFF,
    CommandType.ACTIVATE_PROCEDURE: OperationKind.PROCEDURE_ACTIVATION,
}


def outcome_events_for(kind: str) -> tuple[OperationSucceededEvent, OperationFailedEvent] | None:
    """The success and failure events of a stored kind, or None for a kind that is no longer declared."""
    try:
        return _OUTCOME_EVENTS[OperationKind(kind)]
    except (ValueError, KeyError):
        return None


def kind_for_outcome_event(event_name: str) -> tuple[OperationKind, bool] | None:
    """Return the owning kind and success flag for one declared outcome event."""
    for kind, (success_event, failure_event) in _OUTCOME_EVENTS.items():
        if event_name == success_event:
            return kind, True
        if event_name == failure_event:
            return kind, False
    return None
