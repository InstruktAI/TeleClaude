"""The held standing of a ready item, for the todo projection.

``local/projects/teleclaude/spec/feature/workflow/item-lifecycle`` (The held standing is visible): the todo projection reports a
held ``ready`` item as ``ready`` at its commit, held by a session since a time, with the stated reasons. The reading
compares the item\'s stamp with the integration head, so a stamp the head has moved past does not read ``ready``. Only an
item that is held and stored ``ready`` (or admitted) is read, so the projection reads the remote for those alone.
"""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.core.next_machine.kinds import KIND_TASK
from teleclaude.core.workflow_machine.heads import HEAD_COMPARED_PHASES
from teleclaude.core.workflow_machine.lane import resolve_lane_sync
from teleclaude.core.workflow_machine.phase_reading import PhaseReading, read_phase
from teleclaude.core.workflow_machine.reasons import reason_notes
from teleclaude.core.workflow_machine.stamp import RemoteReadFailed, integration_head_sync
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.types.claim_change import workflow_record_of
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue
from teleclaude.types.todo_standing import TodoStandingDTO
from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import Act, Phase

logger = get_logger(__name__)

HEAD_UNREADABLE_LOG = "held standing read without the integration head"


def item_reading(
    store: WorkflowStore, project_path: str, slug: str, state: dict[str, StateValue]
) -> PhaseReading | None:
    """The machine\'s reading of a live item that is not a task, by the common resolver; None for any other item.

    The one reading the projection uses for the item\'s phase fields and for its standing, so a creative episode that
    reads ``design`` and a stamp the head moved past are seen by every consumer alike. The integration head is read
    only for the stored phases whose reading compares it, and for an admitted item; a head that cannot be read leaves
    the stamp as it is.
    """
    model = TodoState.model_validate(state)
    if model.kind == KIND_TASK or model.lifecycle_phase is LifecyclePhase.DELIVERED:
        return None
    head = ""
    if model.lifecycle_phase in HEAD_COMPARED_PHASES or model.workflow.admitted is not None:
        try:
            head = integration_head_sync(project_path, slug)
        except RemoteReadFailed:
            logger.warning(HEAD_UNREADABLE_LOG, slug=slug, project_path=project_path)
    return read_phase(model, resolve_lane_sync(store, project_path, slug, state, head))


def held_ready_standing(state: dict[str, StateValue], reading: PhaseReading | None) -> TodoStandingDTO | None:
    """The held standing of the item, or None when it is not a held item that reads ``ready``."""
    model = TodoState.model_validate(state)
    if reading is None or reading.phase is not Phase.READY or not model.active_runner:
        return None
    record = workflow_record_of(state)
    claims = [entry.at for entry in record.ledger if entry.act is Act.CLAIM]
    return TodoStandingDTO(
        phase=Phase.READY.value,
        ready_at_commit=reading.ready_sha,
        ready_since=reading.ready_at,
        held_by=model.active_runner,
        held_since=claims[-1] if claims else "",
        reasons=[note.text for note in reason_notes(record)],
    )
