"""The held standing of a ready item, for the todo projection.

``local/projects/teleclaude/spec/feature/workflow/item-lifecycle`` (The held standing is visible): the todo projection reports a
held ``ready`` item as ``ready`` at its commit, held by a session since a time, with the stated reasons. The reading
compares the item\'s stamp with the integration head, so a stamp the head has moved past does not read ``ready``. Only an
item that is held and stored ``ready`` (or admitted) is read, so the projection reads the remote for those alone.
"""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.core.workflow_machine.phase_reading import LaneFacts, read_phase
from teleclaude.core.workflow_machine.reasons import reason_notes
from teleclaude.core.workflow_machine.stamp import RemoteReadFailed, integration_head_sync
from teleclaude.types.claim_change import workflow_record_of
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue
from teleclaude.types.todo_standing import TodoStandingDTO
from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import Act, Phase

logger = get_logger(__name__)

HEAD_UNREADABLE_LOG = "held standing read without the integration head"


def held_ready_standing(project_path: str, slug: str, state: dict[str, StateValue]) -> TodoStandingDTO | None:
    """The held standing of the item, or None when it is not a held item that reads ``ready``."""
    model = TodoState.model_validate(state)
    if not model.active_runner:
        return None
    if model.lifecycle_phase is not LifecyclePhase.READY and model.workflow.admitted is None:
        return None
    head = ""
    unreadable = False
    try:
        head = integration_head_sync(project_path, slug)
    except RemoteReadFailed:
        unreadable = True
        logger.warning(HEAD_UNREADABLE_LOG, slug=slug, project_path=project_path)
    reading = read_phase(
        model,
        LaneFacts(creative_incomplete=False, integration_head=head, artifact_digests=(), head_unreadable=unreadable),
    )
    if reading.phase is not Phase.READY:
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
