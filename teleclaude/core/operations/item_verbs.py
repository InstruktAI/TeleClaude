"""The manual prepare and work verbs for an item driven by the lifecycle machine.

``telec todo prepare`` and ``telec todo work`` are receipt-backed operations. For an item of the lifecycle machine,
the operation calls its entry verb and reports what the verb returned: the session of the driver it started, the
instruction for the holding driver, or the one cause it refused with
(``local/projects/teleclaude/spec/feature/workflow/item-acts``). A task, a structural holder or an item the machine
does not read keeps the path it had.
"""

from __future__ import annotations

from teleclaude.core.db_models import Operation
from teleclaude.core.next_machine.create import creative_incomplete
from teleclaude.core.next_machine.kinds import KIND_TASK
from teleclaude.core.next_machine.runner_types import RunnerLane, RunnerSkipReason
from teleclaude.core.workflow_machine.entry import EntryRequest, EntryVerb, LaunchInProgress, enter
from teleclaude.core.workflow_machine.heads import reading_head
from teleclaude.core.workflow_machine.phase_reading import read_phase
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.types.todos import TodoState

_VERB_FOR_LANE = {RunnerLane.PREPARE: EntryVerb.PREPARE, RunnerLane.WORK: EntryVerb.WORK}


def format_manual_lifecycle_reason(reason: RunnerSkipReason | str | None) -> str:
    """The skip reason of a manual start as text."""
    return reason.value if isinstance(reason, RunnerSkipReason) else str(reason)


async def run_item_verb(
    operation: Operation, lane: RunnerLane, caller_session_id: str, project_root: str, store: WorkflowStore
) -> str | None:
    """Run the entry verb of the lane for the operation's item; None when the item is not the machine's.

    A refusal propagates and fails the operation with its one cause; a start still in progress reports so and is
    attached to by repeating the verb.
    """
    verb = _VERB_FOR_LANE.get(lane)
    slug = operation.slug
    if verb is None or slug is None:
        return None
    raw = await store.read_state(slug)
    if raw is None:
        return None
    state = TodoState.model_validate(raw)
    head = await reading_head(project_root, slug, state)
    creative = await creative_incomplete(store, project_root, slug, raw)
    if state.kind == KIND_TASK or read_phase(state, integration_head=head, creative_incomplete=creative).phase is None:
        return None
    try:
        result = await enter(
            EntryRequest(project_root=project_root, item=slug, verb=verb, caller_session_id=caller_session_id)
        )
    except LaunchInProgress as pending:
        return str(pending)
    return result.text
