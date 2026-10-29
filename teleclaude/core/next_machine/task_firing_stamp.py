"""The task firing-start stamp: one timed line per firing, appended to the todo's ``log``."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from teleclaude.config.machine import config
from teleclaude.constants import ARTIFACT_LOG
from teleclaude.core.dates import ensure_utc
from teleclaude.core.next_machine.kinds import KIND_TASK
from teleclaude.core.next_machine.state_mutation import StateMutationError, StateWriter
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import Event, TodoEventKind

if TYPE_CHECKING:
    from teleclaude.core.workflow_store.store import WorkflowStore


def firing_start_directive(slug: str) -> str:
    """The first act of every task firing, as directive text for a session that runs one in place."""
    return f"first stamp this firing's start with `telec todo stamp {slug} --task-firing-started`"


async def apply_task_firing_started_stamp(
    todos_db: WorkflowStore,
    writer: StateWriter,
    slug: str,
    *,
    caller_session_id: str,
    started_at: datetime,
) -> dict[str, StateValue]:
    """Record the start of a task firing as one timed line at the end of the ``log``.

    The running session stamps its own start as its first act; ``started_at`` is the
    system-clock instant the composing dispatch captures for that stamp, rendered in
    ``computer.timezone``. The audit
    event commits first and names the stamping session; a repeat from that session
    finds it and writes nothing, so a session's firing carries at most one line.
    """
    if writer.state.kind != KIND_TASK:
        raise StateMutationError("cannot stamp task_firing_started: todo is not kind='task'")
    if any(
        event.kind == TodoEventKind.TASK_FIRING_STARTED and event.actor == caller_session_id
        for event in writer.state.events
    ):
        return writer.to_dict()

    zone_name = config.computer.timezone
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise StateMutationError(f"computer.timezone {zone_name!r} is not a resolvable IANA zone") from exc
    line = ensure_utc(started_at).astimezone(zone).strftime("[%H:%M:%S-%d/%m] execution")

    writer.state.events.append(
        Event(at=started_at.isoformat(), actor=caller_session_id, kind=TodoEventKind.TASK_FIRING_STARTED)
    )
    committed = await writer.commit(todos_db, slug)

    existing_log = await todos_db.read_artifact(slug, ARTIFACT_LOG)
    body = f"{existing_log.rstrip()}\n\n{line}\n" if existing_log.strip() else f"{line}\n"
    await todos_db.write_artifact(slug, ARTIFACT_LOG, body, updated_by=caller_session_id)
    return committed
