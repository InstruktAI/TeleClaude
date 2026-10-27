"""The one write that records a driver's claim on a todo."""

from __future__ import annotations

from teleclaude.core.next_machine.runner_types import RunnerLane
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.todos import HoldAuditState


async def set_active_runner(
    todos_db: WorkflowStore,
    slug: str,
    session_id: str,
    *,
    lane: RunnerLane,
    manually_started: bool,
    release_hold: bool,
) -> bool:
    """Write the driver link and its manual marker as one guarded mutation.

    ``active_runner`` and ``manually_started`` are always written together so a
    todo never carries a driver link without its origin marker. ``release_hold``
    is the caller-owned intent to clear a stored hold: true only for a fresh
    claim/start of a held unclaimed todo, false for a live owner's continuation.

    Returns whether the claim was recorded: ``False`` when the todo has no live state to record it on.
    """
    state = await todos_db.read_state(slug)
    if state is None:
        return False
    writer = StateWriter(state)
    writer.state.active_runner = session_id
    writer.state.manually_started = manually_started
    if release_hold:
        writer.state.hold = False
        writer.state.hold_audit = HoldAuditState()
    if lane is RunnerLane.TASK_RUN:
        writer.state.lifecycle_phase = LifecyclePhase.TASK_RUNNING
    await writer.commit(todos_db, slug)
    return True
