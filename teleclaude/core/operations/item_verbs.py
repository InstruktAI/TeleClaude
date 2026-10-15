"""The manual prepare and work verbs for an item driven by the lifecycle machine.

``telec todo prepare`` and ``telec todo work`` are receipt-backed operations. For an item of the lifecycle machine,
the operation calls its entry verb and reports what the verb returned: the session of the driver it started, the
instruction for the holding driver, or the one cause it refused with
(``local/projects/teleclaude/spec/feature/workflow/item-acts``). A task, a structural holder or an item the machine
does not read keeps the path it had.
"""

from __future__ import annotations

from pathlib import Path

from teleclaude.core.db import db
from teleclaude.core.db_models import Operation, ProcedureEventDeliveryOutcome
from teleclaude.core.next_machine.kinds import KIND_TASK
from teleclaude.core.next_machine.runner_types import RunnerLane, RunnerSkipReason
from teleclaude.core.workflow_machine.entry import EntryRequest, EntryVerb, LaunchInProgress, enter
from teleclaude.core.workflow_machine.lane import resolve_lane
from teleclaude.core.workflow_machine.phase_reading import read_phase
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.events.envelope_facts import home_for_project_path
from teleclaude.events.schemas.sdlc import TodoDriverRequestData, TodoPreparationRequested, TodoWorkRequested
from teleclaude.types.todos import TodoState

_VERB_FOR_LANE = {RunnerLane.PREPARE: EntryVerb.PREPARE, RunnerLane.WORK: EntryVerb.WORK}
_REQUEST_EVENT_FOR_VERB = {
    EntryVerb.PREPARE: TodoPreparationRequested.type_name(),
    EntryVerb.WORK: TodoWorkRequested.type_name(),
}
_OWN_ACTIVATION_OUTCOMES = (ProcedureEventDeliveryOutcome.PENDING, ProcedureEventDeliveryOutcome.DELIVERED)
NO_RESERVATION = ""


async def own_reservation(caller_session_id: str, slug: str, verb: EntryVerb, project_root: str) -> str:
    """The reservation key of the driver request this session was started for on this item, or empty.

    The key is read from the activation the platform accepted for the calling session, never from anything the
    caller states: a driver names the request it was started for only by having been started for it. The request
    must be for this item of this project: the slug, the project path and the home of the event all match, so an
    item of the same name in another project never lends its key.
    """
    activations = await db.list_session_procedure_activations(
        session_id=caller_session_id, outcomes=_OWN_ACTIVATION_OUTCOMES
    )
    wanted = _REQUEST_EVENT_FOR_VERB[verb]
    root = Path(project_root).resolve()
    home = home_for_project_path(project_root)
    for activation in reversed(activations):
        event = ReceivedEvent.model_validate_json(activation.event_json)
        if event.type != wanted or event.home != home:
            continue
        data = TodoDriverRequestData.model_validate(event.data)
        if data.slug == slug and Path(data.project_path).resolve() == root:
            return data.reservation_key
    return NO_RESERVATION


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
    if (
        state.kind == KIND_TASK
        or read_phase(state, await resolve_lane(store, project_root, slug, raw, state)).phase is None
    ):
        return None
    try:
        result = await enter(
            EntryRequest(
                project_root=project_root,
                item=slug,
                verb=verb,
                caller_session_id=caller_session_id,
                reservation=await own_reservation(caller_session_id, slug, verb, project_root),
            )
        )
    except LaunchInProgress as pending:
        return str(pending)
    return result.text
