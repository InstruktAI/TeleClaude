"""The acts only the previous machine knew, refused for an item this machine drives.

``local/projects/teleclaude/spec/feature/workflow/item-lifecycle`` (UC-IL12) is the contract: a verb that applies an approval, return or handoff
act that only the previous machine knew is refused, naming the item's phase and the act that replaces it, and no phase moves. The creative gate
stamps and the task stamps belong to lanes that stay, and a todo of kind task or a delivered item is not driven by this machine.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from teleclaude.core.workflow_machine.lane import resolve_lane
from teleclaude.core.workflow_machine.phase_reading import read_phase
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import Act, Phase


class PreviousStamp(StrEnum):
    """The stamp types the previous machine owned and this machine replaces by an act."""

    VERDICT = "verdict"
    FINALIZE_READY = "finalize_ready"
    DEFERRALS_PROCESSED = "deferrals_processed"
    REQUIREMENTS_READY = "requirements_ready"
    PLAN_READY = "plan_ready"
    PRD_APPROVED = "prd_approved"
    DIAGNOSIS_SETTLED = "diagnosis_settled"
    DIAGNOSIS_UNRESOLVED = "diagnosis_unresolved"
    ARCHITECTURE_SKIPPED = "architecture_skipped"
    DRIFT_REVIEWED = "drift_reviewed"
    BUILD_COMPLETE = "build_complete"
    KICKBACK = "kickback"


RETURN_TO_WORK: Final = "return_to_work"
CREATE_CAPABILITY: Final = "create"

_REPLACING_ACT: Final[dict[str, str | None]] = {
    PreviousStamp.VERDICT: Act.FINDING.value,
    PreviousStamp.FINALIZE_READY: Act.STAMP.value,
    PreviousStamp.DEFERRALS_PROCESSED: CREATE_CAPABILITY,
    PreviousStamp.REQUIREMENTS_READY: Act.PREPARED.value,
    PreviousStamp.PLAN_READY: Act.PREPARED.value,
    PreviousStamp.PRD_APPROVED: None,
    PreviousStamp.DIAGNOSIS_SETTLED: Act.PREPARED.value,
    PreviousStamp.DIAGNOSIS_UNRESOLVED: Act.WAITING.value,
    PreviousStamp.ARCHITECTURE_SKIPPED: Act.PREPARED.value,
    PreviousStamp.DRIFT_REVIEWED: Act.PREPARED.value,
    PreviousStamp.BUILD_COMPLETE: Act.STAMP.value,
    PreviousStamp.KICKBACK: Act.KICKBACK.value,
    RETURN_TO_WORK: Act.KICKBACK.value,
}
_PERFORMER: Final[dict[str, str]] = {
    Act.PREPARED.value: "the holding driver",
    Act.WAITING.value: "the holding driver",
    Act.STAMP.value: "the holding driver",
    Act.KICKBACK.value: "the holding driver",
    Act.FINDING.value: "the holding driver",
    Act.DECISION.value: "the session of the waited-on person",
    CREATE_CAPABILITY: "any session with todo write",
}
REFUSAL_TEMPLATE: Final = "{verb} is refused: {item} is in {phase}. Door: {door}.{replacement}"
REPLACEMENT_TEMPLATE: Final = " The act that replaces it is {act}, performed by {performer}."
DOOR_HELD: Final = "the holding session {holder}"
DOOR_HELD_KICKBACK: Final = "the holding session {holder}, whose `telec todo act {item} kickback` returns the item"
DOOR_START: Final = "the driver start in progress, and the session it is starting; it was requested by {requester}"
DOOR_ADMITTED: Final = (
    "the integrator's admission at {sha}; the integrator delivers or parks it, and a parked item is then reachable "
    "by the ready or work row"
)
DOOR_WAITING: Final = (
    "{person}'s decision (`telec todo act {item} decision`), which starts the waited phase's driver; from work, "
    "that driver may kick back"
)
DOOR_READY: Final = "`telec todo work {item} --reason <text>`"
DOOR_WORK: Final = "`telec todo work {item}`, whose driver may kick back"
DOOR_PREPARATION: Final = "none needed: the item is in preparation, which `telec todo prepare {item}` drives"
DOOR_DESIGN: Final = (
    "the creative lane, `telec todo design {item}`; the item reaches preparation when its design completes"
)
UNKNOWN_REQUESTER: Final = "the lifecycle runner or a person at a terminal"
NOT_DRIVEN_PHASES: Final = frozenset({Phase.DELIVERED})


class PreviousActRefused(Exception):
    """A verb that only the previous machine knew was refused for an item this machine drives; nothing was written."""


def door_for(state: TodoState, phase: Phase, item: str) -> str:
    """The door the first matching row of the contract's table names for the item's state."""
    holder = state.active_runner
    if holder:
        template = DOOR_HELD_KICKBACK if phase in (Phase.WORK, Phase.READY) else DOOR_HELD
        return template.format(holder=holder, item=item)
    launch = state.workflow.launch
    if launch is not None:
        return DOOR_START.format(requester=launch.requested_by or UNKNOWN_REQUESTER)
    admitted = state.workflow.admitted
    if admitted is not None:
        return DOOR_ADMITTED.format(sha=admitted.sha[:8])
    waiting = state.workflow.waiting
    if phase is Phase.WAITING and waiting is not None:
        return DOOR_WAITING.format(person=waiting.person, item=item)
    doors = {
        Phase.READY: DOOR_READY,
        Phase.WORK: DOOR_WORK,
        Phase.PREPARED: DOOR_WORK,
        Phase.PREPARATION: DOOR_PREPARATION,
        Phase.DESIGN: DOOR_DESIGN,
    }
    return doors.get(phase, DOOR_PREPARATION).format(item=item)


async def refuse_previous_machine_act(project_root: str, slug: str, verb: str) -> None:
    """Raise ``PreviousActRefused`` when ``verb`` is an act of the previous machine and the item is one this machine reads.

    Any other verb, an item of the task lane, a delivered item and an item with no stored state pass through unchanged.
    The refusal names the item's phase as the machine reads it and the door the contract's table gives for its state;
    where an act of this machine replaces the retired one it names that act and its performer.
    """
    if verb not in _REPLACING_ACT:
        return
    replacing = _REPLACING_ACT[verb]
    store = await get_workflow_store(project_root)
    raw = await store.read_state(slug)
    if raw is None:
        return
    state = TodoState.model_validate(raw)
    reading = read_phase(state, await resolve_lane(store, project_root, slug, raw, state))
    if reading.phase is None or reading.phase in NOT_DRIVEN_PHASES:
        return
    replacement = (
        REPLACEMENT_TEMPLATE.format(act=replacing, performer=_PERFORMER[replacing]) if replacing is not None else ""
    )
    raise PreviousActRefused(
        REFUSAL_TEMPLATE.format(
            verb=verb,
            item=slug,
            phase=reading.phase.value,
            door=door_for(state, reading.phase, slug),
            replacement=replacement,
        )
    )
