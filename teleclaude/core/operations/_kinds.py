"""Operation-kind vocabulary: the closed set of kinds, their outcome events, and the command types they back."""

from __future__ import annotations

from teleclaude.core.events import EventType
from teleclaude.types.commands import CommandType

OPERATION_KIND_TODO_WORK = "todo_work"
OPERATION_KIND_TASK_RUN = "task_run"
OPERATION_KIND_TODO_INTEGRATE = "todo_integrate"
OPERATION_KIND_TODO_CREATE = "todo_create"
OPERATION_KIND_TODO_PREPARE = "todo_prepare"
OPERATION_KIND_TODO_RENAME = "todo_rename"
OPERATION_KIND_TODO_REMOVE = "todo_remove"
OPERATION_KIND_SESSION_CLOSE = "session_close"
OPERATION_KIND_AGENT_RESTART = "agent_restart"
OPERATION_KIND_AGENT_HANDOFF = "agent_handoff"
OPERATION_KIND_PROCEDURE_ACTIVATION = "procedure_activation"
_OUTCOME_EVENTS: dict[str, tuple[EventType, EventType]] = {
    OPERATION_KIND_TODO_WORK: ("operation.todo_work.completed", "operation.todo_work.failed"),
    OPERATION_KIND_TASK_RUN: ("operation.task_run.completed", "operation.task_run.failed"),
    OPERATION_KIND_TODO_INTEGRATE: ("operation.todo_integrate.completed", "operation.todo_integrate.failed"),
    OPERATION_KIND_TODO_CREATE: ("operation.todo_create.completed", "operation.todo_create.failed"),
    OPERATION_KIND_TODO_PREPARE: ("operation.todo_prepare.completed", "operation.todo_prepare.failed"),
    OPERATION_KIND_TODO_RENAME: ("operation.todo_rename.completed", "operation.todo_rename.failed"),
    OPERATION_KIND_TODO_REMOVE: ("operation.todo_remove.completed", "operation.todo_remove.failed"),
    OPERATION_KIND_SESSION_CLOSE: ("session.close.completed", "session.close.failed"),
    OPERATION_KIND_AGENT_RESTART: ("agent.restart.completed", "agent.restart.failed"),
    OPERATION_KIND_AGENT_HANDOFF: ("agent_runtime.handoff.completed", "agent_runtime.handoff.failed"),
    OPERATION_KIND_PROCEDURE_ACTIVATION: (
        "agent_runtime.procedure_activation.completed",
        "agent_runtime.procedure_activation.failed",
    ),
}
_COMMAND_TYPE_TO_OPERATION_KIND: dict[CommandType, str] = {
    CommandType.CLOSE_SESSION: OPERATION_KIND_SESSION_CLOSE,
    CommandType.RESTART_AGENT: OPERATION_KIND_AGENT_RESTART,
    CommandType.HANDOFF_AGENT: OPERATION_KIND_AGENT_HANDOFF,
    CommandType.ACTIVATE_PROCEDURE: OPERATION_KIND_PROCEDURE_ACTIVATION,
}


def all_outcome_events() -> tuple[EventType, ...]:
    """Return every outcome event — both members of every kind's success/failure pair.

    The published bridge subscribes to this rather than to ``_OUTCOME_EVENTS``
    directly, so a new kind's pair is picked up without the subscriber module
    knowing the map's shape.
    """
    return tuple(event for pair in _OUTCOME_EVENTS.values() for event in pair)
